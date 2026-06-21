from __future__ import annotations

import logging
import os
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import requests

import place_weather
import route_analysis
from place_registry import place_definition


logger = logging.getLogger(__name__)

BIGQUERY_SCOPE = "https://www.googleapis.com/auth/bigquery"
BIGQUERY_PROJECT_ENV_VARS = ("PREDSEA_BIGQUERY_PROJECT", "GOOGLE_CLOUD_PROJECT")
BIGQUERY_DATASET_ENV_VARS = ("PREDSEA_BIGQUERY_DATASET", "BQ_DATASET")
BIGQUERY_EVIDENCE_TABLE_ENV_VARS = ("PREDSEA_BIGQUERY_EVIDENCE_TABLE", "BQ_TABLE_EVIDENCE")
BIGQUERY_CLIMATOLOGY_TABLE_ENV_VARS = ("PREDSEA_BIGQUERY_CLIMATOLOGY_TABLE", "BQ_TABLE_CLIMATOLOGY")
BIGQUERY_LOCATION_ENV_VARS = ("PREDSEA_BIGQUERY_LOCATION", "BQ_LOCATION")
AEMET_TIMEOUT_SECONDS = int(os.environ.get("PREDSEA_AEMET_TIMEOUT_SECONDS", "30"))

BALEARIC_ZONE_IDS = {
    "07",
    "BALEARES",
    "BALEAR",
    "MEDITERRANEO OCCIDENTAL",
    "MED_W",
}

ROLLING_VARIABLES = {
    "wave_height": {"label": "Wave height", "unit": "m", "severe_abs": 3.0},
    "wave_height_max": {"label": "Max wave height", "unit": "m", "severe_abs": 4.0},
    "swell_1_height": {"label": "Swell height", "unit": "m", "severe_abs": 2.5},
    "wind_speed": {"label": "Wind speed", "unit": "m/s", "severe_abs": 15.0},
    "current_speed": {"label": "Current speed", "unit": "m/s", "severe_abs": 1.0},
    "wave_period_peak": {"label": "Wave period", "unit": "s", "severe_abs": 12.0},
}

CLIMATOLOGICAL_VARIABLES = {
    "air_temperature": {"label": "Air temperature", "unit": "C", "severe_abs": None},
    "water_temperature": {"label": "Water temperature", "unit": "C", "severe_abs": None},
    "sea_level": {"label": "Sea level", "unit": "m", "severe_abs": None},
    "salinity": {"label": "Salinity", "unit": "PSU", "severe_abs": None},
    "sea_level_pressure": {"label": "Sea pressure", "unit": "hPa", "severe_abs": None},
}

SEVERITY_ORDER = {"severe": 0, "moderate": 1, "info": 2}


def build_warnings_response(
    *,
    route: str | None = None,
    place: str | None = None,
    date: str | None = None,
    z_threshold: float = 1.5,
    lookback_hours: int = 240,
    min_window_hours: int = 240,
    min_sample_count: int = 10,
    include_aemet: bool = True,
    include_anomaly: bool = True,
):
    generated_at_utc = datetime.now(timezone.utc).isoformat()
    scope_terms = build_scope_terms(route=route, place=place)
    warnings = []
    sources_available = []

    if include_anomaly:
        rolling_warnings, rolling_available = compute_rolling_anomaly_warnings(
            scope_terms,
            z_threshold=z_threshold,
            lookback_hours=lookback_hours,
            min_window_hours=min_window_hours,
            min_sample_count=min_sample_count,
            generated_at_utc=generated_at_utc,
            route=route,
            place=place,
        )
        climatological_warnings, climatology_available = compute_climatological_anomaly_warnings(
            scope_terms,
            z_threshold=z_threshold,
            generated_at_utc=generated_at_utc,
            route=route,
            place=place,
        )
        warnings.extend(rolling_warnings)
        warnings.extend(climatological_warnings)
        if rolling_available or climatology_available:
            sources_available.append("predsea_anomaly")

    if include_aemet:
        aemet_warnings, aemet_available = fetch_aemet_warnings(
            generated_at_utc=generated_at_utc,
            route=route,
            place=place,
        )
        warnings.extend(aemet_warnings)
        if aemet_available:
            sources_available.append("aemet_official")

    warnings = dedupe_and_sort_warnings(warnings)
    summary = warnings_summary(warnings)
    summary["sources_available"] = sources_available

    if not warnings and not sources_available:
        stance = "Warning sources temporarily unavailable. Check conditions manually."
    elif summary["severe"]:
        severe_variables = ", ".join(_unique_warning_variables(warnings, severity="severe"))
        stance = f"SEVERE conditions detected ({severe_variables}). Review warnings before departure."
    elif summary["moderate"]:
        moderate_variables = ", ".join(_unique_warning_variables(warnings, severity="moderate"))
        stance = f"Moderate anomalies detected ({moderate_variables}). Monitor conditions closely."
    elif not warnings:
        stance = "No active warnings. Conditions appear within normal parameters."
    else:
        stance = "Minor informational alerts active. No immediate action required."

    return {
        "generated_at_utc": generated_at_utc,
        "context": {
            "route": route,
            "place": place,
            "date": date,
            "lookback_hours": lookback_hours,
            "min_window_hours": min_window_hours,
            "min_sample_count": min_sample_count,
            "z_threshold": z_threshold,
        },
        "summary": summary,
        "operational_stance": stance,
        "warnings": warnings,
        "sources_available": sources_available,
    }


def build_scope_terms(*, route=None, place=None):
    terms = []
    if route:
        try:
            route_def = route_analysis.load_route(route)
        except Exception:
            route_def = None
        if route_def:
            terms.extend(
                [
                    route,
                    route_def.get("id"),
                    route_def.get("name"),
                    (route_def.get("origin") or {}).get("name"),
                    (route_def.get("destination") or {}).get("name"),
                ]
            )
            for point in route_def.get("sample_points") or []:
                terms.append(point.get("name"))
    if place:
        try:
            place_def = place_definition(place)
        except Exception:
            place_def = None
        if place_def:
            terms.extend(
                [
                    place,
                    place_def.get("name"),
                    place_def.get("parent_place_id"),
                ]
            )
            terms.extend(place_def.get("aliases") or [])
    normalized = []
    seen = set()
    for term in terms:
        if term is None:
            continue
        text = str(term).strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(text)
    return normalized


def compute_rolling_anomaly_warnings(
    scope_terms,
    *,
    z_threshold,
    lookback_hours,
    min_window_hours,
    min_sample_count,
    generated_at_utc,
    route=None,
    place=None,
):
    project_id = resolve_env(*BIGQUERY_PROJECT_ENV_VARS)
    dataset_id = resolve_env(*BIGQUERY_DATASET_ENV_VARS, default="predsea_validation")
    table_id = resolve_env(*BIGQUERY_EVIDENCE_TABLE_ENV_VARS, default="evidence_rows")
    location = resolve_env(*BIGQUERY_LOCATION_ENV_VARS, default="europe-west1")
    if not project_id or not dataset_id or not table_id:
        return [], False
    station_clause = build_station_clause(scope_terms)
    rolling_variable_list = ", ".join(f"'{variable}'" for variable in sorted(ROLLING_VARIABLES))
    sql = f"""
WITH window_stats AS (
  SELECT
    variable, station_id, station_name, latitude, longitude,
    AVG(value) AS window_mean,
    STDDEV(value) AS window_stddev,
    COUNT(*) AS sample_count,
    MIN(sample_time_utc) AS earliest_sample,
    MAX(sample_time_utc) AS latest_sample_time,
    TIMESTAMP_DIFF(MAX(sample_time_utc), MIN(sample_time_utc), HOUR) AS window_hours_actual
  FROM `{project_id}.{dataset_id}.{table_id}`
  WHERE record_type = 'observation'
    AND variable IN ({rolling_variable_list})
    AND ingested_at_utc >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {int(lookback_hours)} HOUR)
    AND value IS NOT NULL
    {station_clause}
  GROUP BY variable, station_id, station_name, latitude, longitude
  HAVING COUNT(*) >= {int(min_sample_count)}
     AND TIMESTAMP_DIFF(MAX(sample_time_utc), MIN(sample_time_utc), HOUR) >= {int(min_window_hours)}
),
latest_obs AS (
  SELECT
    e.variable, e.station_id, e.station_name, e.latitude, e.longitude,
    e.value AS current_value, e.units,
    e.sample_time_utc, e.observed_at_utc, e.freshness_status,
    w.window_mean, w.window_stddev, w.sample_count, w.window_hours_actual,
    SAFE_DIVIDE(e.value - w.window_mean, w.window_stddev) AS z_score
  FROM `{project_id}.{dataset_id}.{table_id}` e
  JOIN window_stats w
    ON e.variable = w.variable AND e.station_id = w.station_id
  WHERE e.record_type = 'observation'
    AND e.sample_time_utc = w.latest_sample_time
)
SELECT *, 'rolling' AS baseline_type
FROM latest_obs
WHERE ABS(z_score) >= {float(z_threshold)}
ORDER BY ABS(z_score) DESC
LIMIT 200
"""
    try:
        rows = run_bigquery_query(sql, project_id=project_id, location=location)
    except Exception as error:
        logger.warning("Rolling anomaly query failed: %s", error)
        return [], False
    warnings = [rolling_warning_from_row(row, generated_at_utc=generated_at_utc, route=route, place=place) for row in rows]
    return [warning for warning in warnings if warning], True


def compute_climatological_anomaly_warnings(
    scope_terms,
    *,
    z_threshold,
    generated_at_utc,
    route=None,
    place=None,
):
    project_id = resolve_env(*BIGQUERY_PROJECT_ENV_VARS)
    dataset_id = resolve_env(*BIGQUERY_DATASET_ENV_VARS, default="predsea_validation")
    table_id = resolve_env(*BIGQUERY_EVIDENCE_TABLE_ENV_VARS, default="evidence_rows")
    clim_table = resolve_env(*BIGQUERY_CLIMATOLOGY_TABLE_ENV_VARS, default="climatology_baseline")
    location = resolve_env(*BIGQUERY_LOCATION_ENV_VARS, default="europe-west1")
    if not project_id or not dataset_id or not table_id:
        return [], False
    station_clause = build_station_clause(scope_terms)
    clim_variable_list = ", ".join(f"'{variable}'" for variable in sorted(CLIMATOLOGICAL_VARIABLES))
    sql = f"""
WITH latest_obs AS (
  SELECT
    variable, station_id, station_name, latitude, longitude,
    value AS current_value, units,
    sample_time_utc, observed_at_utc, freshness_status,
    EXTRACT(MONTH FROM sample_time_utc) AS obs_month,
    EXTRACT(HOUR FROM sample_time_utc) AS obs_hour
  FROM `{project_id}.{dataset_id}.{table_id}`
  WHERE record_type = 'observation'
    AND variable IN ({clim_variable_list})
    AND value IS NOT NULL
    AND ingested_at_utc >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 6 HOUR)
    {station_clause}
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY variable, station_id
    ORDER BY sample_time_utc DESC
  ) = 1
),
scored AS (
  SELECT
    o.*,
    c.clim_mean,
    c.clim_stddev,
    c.sample_count,
    c.history_years,
    SAFE_DIVIDE(o.current_value - c.clim_mean, c.clim_stddev) AS z_score
  FROM latest_obs o
  JOIN `{project_id}.{dataset_id}.{clim_table}` c
    ON o.station_id = c.station_id
   AND o.variable = c.variable
   AND o.obs_month = c.month
   AND o.obs_hour = c.hour_utc
  WHERE c.sample_count >= 30
    AND c.history_years >= 3
)
SELECT *, 'climatological' AS baseline_type
FROM scored
WHERE ABS(z_score) >= {float(z_threshold)}
ORDER BY ABS(z_score) DESC
LIMIT 200
"""
    try:
        rows = run_bigquery_query(sql, project_id=project_id, location=location)
    except Exception as error:
        logger.warning("Climatological anomaly query failed: %s", error)
        return [], False
    warnings = [climatological_warning_from_row(row, generated_at_utc=generated_at_utc, route=route, place=place) for row in rows]
    return [warning for warning in warnings if warning], True


def fetch_aemet_warnings(*, generated_at_utc, route=None, place=None):
    api_key = os.environ.get("AEMET_API_KEY")
    if not api_key:
        return [], False
    headers = {"api_key": api_key, "Accept": "application/json"}
    base_url = "https://opendata.aemet.es/opendata/api/avisos_cap/ultimoelaborado/area/esp"
    try:
        response = requests.get(base_url, headers=headers, timeout=AEMET_TIMEOUT_SECONDS)
        response.raise_for_status()
        first = response.json()
        data_url = first.get("datos")
        if not data_url:
            raise RuntimeError("AEMET response missing 'datos' URL")
        response = requests.get(data_url, headers=headers, timeout=AEMET_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()
    except Exception as error:
        logger.warning("AEMET warnings fetch failed: %s", error)
        return [], False

    alerts = flatten_aemet_payload(payload)
    warnings = []
    for alert in alerts:
        alert_warnings = aemet_warning_from_alert(alert, generated_at_utc=generated_at_utc, route=route, place=place)
        if alert_warnings:
            warnings.extend(alert_warnings)
    return warnings, True


def flatten_aemet_payload(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("avisos", "warnings", "data", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
        info = payload.get("info")
        if isinstance(info, list):
            return [payload]
    return []


def aemet_warning_from_alert(alert, *, generated_at_utc, route=None, place=None):
    if not isinstance(alert, dict):
        return None
    infos = alert.get("info") or []
    if not isinstance(infos, list):
        infos = [infos]
    warnings = []
    now = parse_utc_timestamp(generated_at_utc) or datetime.now(timezone.utc)
    for info in infos:
        if not isinstance(info, dict):
            continue
        area_desc = area_description(info)
        if not area_matches_balearics(area_desc):
            continue
        expires = parse_utc_timestamp(info.get("expires") or info.get("effective") or info.get("end"))
        if expires and expires <= now:
            continue
        severity = aemet_severity_to_predsea(info.get("severity") or alert.get("severity"))
        event = info.get("event") or info.get("headline") or "AEMET warning"
        variable = aemet_event_to_variable(event)
        warnings.append(
            {
                "source": "aemet_official",
                "severity": severity,
                "variable": variable,
                "label": info.get("headline") or event,
                "description": info.get("description") or info.get("headline") or event,
                "value": None,
                "unit": None,
                "z_score": None,
                "baseline_type": None,
                "station_id": None,
                "station_name": None,
                "latitude": None,
                "longitude": None,
                "issued_at_utc": generated_at_utc,
                "valid_from_utc": info.get("onset") or alert.get("sent"),
                "valid_to_utc": info.get("expires"),
                "route": route,
                "aemet_event": event,
                "aemet_area": area_desc,
                "extra": {
                    "severity_raw": info.get("severity") or alert.get("severity"),
                    "headline": info.get("headline"),
                    "description": info.get("description"),
                },
            }
        )
    return warnings


def rolling_warning_from_row(row, *, generated_at_utc, route=None, place=None):
    variable = row.get("variable")
    meta = ROLLING_VARIABLES.get(variable)
    if not meta:
        return None
    value = as_float(row.get("current_value"))
    z_score = as_float(row.get("z_score"))
    if value is None or z_score is None:
        return None
    severe_abs = meta.get("severe_abs")
    if severe_abs is not None and abs(value) >= severe_abs:
        severity = "severe"
    elif abs(z_score) >= 2.5:
        severity = "severe"
    elif abs(z_score) >= 1.5:
        severity = "moderate"
    else:
        severity = "info"
    station_name = row.get("station_name")
    baseline_mean = as_float(row.get("window_mean"))
    baseline_stddev = as_float(row.get("window_stddev"))
    direction = "above" if z_score >= 0 else "below"
    description = (
        f"{station_name or row.get('station_id')}: {meta['label']} is {direction} baseline "
        f"at {value:.2f} {meta['unit']} (z={z_score:.2f})."
    )
    if severe_abs is not None and abs(value) >= severe_abs:
        description = (
            f"{station_name or row.get('station_id')}: {meta['label']} reached {value:.2f} {meta['unit']}, "
            f"above the severe threshold of {severe_abs:.2f} {meta['unit']}."
        )
    return {
        "source": "predsea_anomaly",
        "severity": severity,
        "variable": variable,
        "label": f"{meta['label']} anomaly",
        "description": description,
        "value": value,
        "unit": meta["unit"],
        "z_score": z_score,
        "baseline_type": "rolling",
        "station_id": row.get("station_id"),
        "station_name": station_name,
        "latitude": as_float(row.get("latitude")),
        "longitude": as_float(row.get("longitude")),
        "issued_at_utc": generated_at_utc,
        "valid_from_utc": row.get("sample_time_utc"),
        "valid_to_utc": None,
        "route": route,
        "aemet_event": None,
        "aemet_area": None,
        "extra": {
            "baseline_mean": baseline_mean,
            "baseline_stddev": baseline_stddev,
            "baseline_type": "rolling",
            "sample_count": int_value(row.get("sample_count")),
            "window_hours_actual": int_value(row.get("window_hours_actual")),
            "min_window_hours": 240,
            "min_sample_count": 10,
            "lookback_hours": 240,
            "freshness_status": row.get("freshness_status"),
        },
    }


def climatological_warning_from_row(row, *, generated_at_utc, route=None, place=None):
    variable = row.get("variable")
    meta = CLIMATOLOGICAL_VARIABLES.get(variable)
    if not meta:
        return None
    value = as_float(row.get("current_value"))
    z_score = as_float(row.get("z_score"))
    if value is None or z_score is None:
        return None
    severity = "severe" if abs(z_score) >= 2.5 else "moderate" if abs(z_score) >= 1.5 else "info"
    station_name = row.get("station_name")
    direction = "above" if z_score >= 0 else "below"
    description = (
        f"{station_name or row.get('station_id')}: {meta['label']} is {direction} the climatological "
        f"baseline at {value:.2f} {meta['unit']} (z={z_score:.2f})."
    )
    return {
        "source": "predsea_anomaly",
        "severity": severity,
        "variable": variable,
        "label": f"{meta['label']} anomaly",
        "description": description,
        "value": value,
        "unit": meta["unit"],
        "z_score": z_score,
        "baseline_type": "climatological",
        "station_id": row.get("station_id"),
        "station_name": station_name,
        "latitude": as_float(row.get("latitude")),
        "longitude": as_float(row.get("longitude")),
        "issued_at_utc": generated_at_utc,
        "valid_from_utc": row.get("sample_time_utc"),
        "valid_to_utc": None,
        "route": route,
        "aemet_event": None,
        "aemet_area": None,
        "extra": {
            "baseline_mean": as_float(row.get("clim_mean")),
            "baseline_stddev": as_float(row.get("clim_stddev")),
            "baseline_type": "climatological",
            "clim_month": int_value(row.get("obs_month")),
            "clim_hour_utc": int_value(row.get("obs_hour")),
            "sample_count": int_value(row.get("sample_count")),
            "history_years": int_value(row.get("history_years")),
            "freshness_status": row.get("freshness_status"),
        },
    }


def dedupe_and_sort_warnings(warnings):
    selected = {}
    for warning in warnings:
        if not warning:
            continue
        key = dedupe_key(warning)
        existing = selected.get(key)
        if existing is None:
            selected[key] = warning
            continue
        if warning.get("baseline_type") == "climatological" and existing.get("baseline_type") != "climatological":
            selected[key] = warning
            continue
        if existing.get("baseline_type") == "climatological" and warning.get("baseline_type") != "climatological":
            continue
        if SEVERITY_ORDER[warning["severity"]] < SEVERITY_ORDER[existing["severity"]]:
            selected[key] = warning
    return sorted(
        selected.values(),
        key=lambda warning: (
            SEVERITY_ORDER.get(warning.get("severity"), 99),
            0 if warning.get("source") == "aemet_official" else 1,
            warning.get("station_name") or warning.get("station_id") or warning.get("label") or "",
        ),
    )


def warnings_summary(warnings):
    summary = {
        "total": len(warnings),
        "severe": 0,
        "moderate": 0,
        "info": 0,
        "aemet_official": 0,
        "predsea_anomaly": 0,
    }
    for warning in warnings:
        severity = warning.get("severity")
        source = warning.get("source")
        if severity in summary:
            summary[severity] += 1
        if source in summary:
            summary[source] += 1
    return summary


def aemet_severity_to_predsea(severity):
    text = str(severity or "").strip().lower()
    if text in {"extreme", "severe"}:
        return "severe"
    if text == "moderate":
        return "moderate"
    return "info"


def aemet_event_to_variable(event):
    text = str(event or "").lower()
    if "viento" in text or "wind" in text:
        return "wind_speed"
    if "oleaje" in text or "wave" in text or "marejada" in text:
        return "wave_height"
    if "lluvia" in text or "rain" in text:
        return "precipitation"
    if "temperatura" in text:
        return "air_temperature"
    if "presión" in text or "pressure" in text:
        return "sea_level_pressure"
    if "nivel" in text or "sea level" in text:
        return "sea_level"
    return None


def area_description(info):
    area = info.get("area") if isinstance(info, dict) else None
    if isinstance(area, dict):
        return area.get("areaDesc") or area.get("description") or area.get("name")
    return None


def area_matches_balearics(area_desc):
    text = str(area_desc or "").upper()
    if not text:
        return False
    return any(zone in text for zone in BALEARIC_ZONE_IDS)


def build_station_clause(scope_terms):
    if not scope_terms:
        return ""
    predicates = []
    for term in scope_terms:
        normalized = sql_literal(term.lower())
        predicates.extend(
            [
                f"LOWER(COALESCE(station_id, '')) = {normalized}",
                f"LOWER(COALESCE(station_name, '')) LIKE '%' || {normalized} || '%'",
                f"LOWER(COALESCE(source_label, '')) LIKE '%' || {normalized} || '%'",
                f"LOWER(COALESCE(source_system, '')) LIKE '%' || {normalized} || '%'",
            ]
        )
    return "AND (" + " OR ".join(predicates) + ")"


def resolve_env(*names, default=None):
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return default


def sql_literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def query_bigquery(sql, *, project_id, location=None):
    try:
        import google.auth
        from google.auth.transport.requests import AuthorizedSession
    except Exception as error:
        raise RuntimeError(f"BigQuery auth helpers unavailable: {error}") from error

    creds, default_project = google.auth.default(scopes=[BIGQUERY_SCOPE])
    project = project_id or default_project
    if not project:
        raise RuntimeError("BigQuery project is unavailable")
    session = AuthorizedSession(creds)
    query_url = f"https://bigquery.googleapis.com/bigquery/v2/projects/{project}/queries"
    payload = {
        "query": sql,
        "useLegacySql": False,
        "timeoutMs": 30000,
        "maxResults": 200,
    }
    if location:
        payload["location"] = location
    response = session.post(query_url, json=payload)
    response.raise_for_status()
    body = response.json()
    if not body.get("jobComplete", True):
        job_id = (body.get("jobReference") or {}).get("jobId")
        if not job_id:
            return []
        get_url = f"https://bigquery.googleapis.com/bigquery/v2/projects/{project}/queries/{job_id}"
        for _ in range(30):
            time.sleep(1)
            response = session.get(get_url, params={"location": location} if location else None)
            response.raise_for_status()
            body = response.json()
            if body.get("jobComplete", True):
                break
    if body.get("errors"):
        raise RuntimeError(body["errors"][0].get("message") or "BigQuery query failed")
    return bigquery_rows(body)


def bigquery_rows(body):
    schema = (body.get("schema") or {}).get("fields") or []
    rows = []
    for row in body.get("rows") or []:
        values = row.get("f") or []
        record = {}
        for field, value in zip(schema, values):
            record[field["name"]] = bigquery_value(value.get("v"))
        rows.append(record)
    return rows


def bigquery_value(value):
    if isinstance(value, dict) and "v" in value:
        value = value["v"]
    if isinstance(value, list):
        return [bigquery_value(item) for item in value]
    return value


def as_float(value):
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def int_value(value):
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except Exception:
        return None


def dedupe_key(warning):
    if warning.get("source") == "aemet_official":
        return (
            warning.get("source"),
            warning.get("aemet_event"),
            warning.get("aemet_area"),
            warning.get("valid_from_utc"),
            warning.get("valid_to_utc"),
        )
    return (
        warning.get("source"),
        warning.get("station_id"),
        warning.get("variable"),
        warning.get("valid_from_utc"),
    )


def _unique_warning_variables(warnings, severity):
    variables = []
    seen = set()
    for warning in warnings:
        if warning.get("severity") != severity:
            continue
        variable = warning.get("variable") or warning.get("aemet_event") or warning.get("label")
        if not variable:
            continue
        if variable in seen:
            continue
        seen.add(variable)
        variables.append(variable)
    return variables[:5]
