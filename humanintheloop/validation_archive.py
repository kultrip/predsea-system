import json
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = "predsea.validation.v1"

OBSERVATION_VARIABLES = {
    "sea_level_m": ("sea_level", "m"),
    "depth_m": ("depth", "m"),
    "wave_height_m": ("wave_height", "m"),
    "wave_from_direction_deg": ("wave_direction", "degree"),
    "wave_direction_deg": ("wave_direction", "degree"),
    "hs_m": ("wave_height", "m"),
    "hmax_m": ("wave_height_max", "m"),
    "wind_speed_mps": ("wind_speed", "m/s"),
    "wind_direction_deg": ("wind_direction", "degree"),
    "temperature_c": ("air_temperature", "celsius"),
    "water_temp_c": ("water_temperature", "celsius"),
    "water_temperature_c": ("water_temperature", "celsius"),
    "water_temp": ("water_temperature", "celsius"),
    "salinity_psu": ("salinity", "psu"),
    "sea_level_pressure_hpa": ("sea_level_pressure", "hPa"),
    "air_pressure_hpa": ("air_pressure", "hPa"),
    "current_speed_mps": ("current_speed", "m/s"),
    "current_direction_deg": ("current_direction", "degree"),
}

COMPASS_DEGREES = {
    "N": 0.0,
    "NNE": 22.5,
    "NE": 45.0,
    "ENE": 67.5,
    "E": 90.0,
    "ESE": 112.5,
    "SE": 135.0,
    "SSE": 157.5,
    "S": 180.0,
    "SSW": 202.5,
    "SW": 225.0,
    "WSW": 247.5,
    "W": 270.0,
    "WNW": 292.5,
    "NW": 315.0,
    "NNW": 337.5,
}

FORECAST_VARIABLES = {
    "wave_m": ("wave_height", "m"),
    "wave_direction_deg": ("wave_direction", "degree"),
    "current_mps": ("current_speed", "m/s"),
    "current_direction_deg": ("current_direction", "degree"),
    "swell_1_height_m": ("swell_1_height", "m"),
    "swell_1_direction_deg": ("swell_1_direction", "degree"),
    "swell_2_height_m": ("swell_2_height", "m"),
    "swell_2_direction_deg": ("swell_2_direction", "degree"),
    "wind_wave_height_m": ("wind_wave_height", "m"),
    "wind_wave_direction_deg": ("wind_wave_direction", "degree"),
}


def write_validation_archive(
    run_dir,
    run_date,
    run_id,
    routes,
    snapshots_by_route,
    observations,
    output_root,
):
    validation_dir = Path(run_dir) / "validation"
    validation_dir.mkdir(parents=True, exist_ok=True)

    observation_rows = build_observation_rows(observations, run_date, run_id)
    forecast_rows = build_forecast_rows(snapshots_by_route, routes, run_date, run_id)
    historical_forecast_rows = load_historical_forecast_rows(output_root)
    matched_rows = match_observations_to_forecasts(
        observation_rows,
        historical_forecast_rows + forecast_rows,
    )
    summary = build_validation_summary(run_date, run_id, observation_rows, forecast_rows, matched_rows)

    write_jsonl(validation_dir / "observation_samples.jsonl", observation_rows)
    write_jsonl(validation_dir / "forecast_index.jsonl", forecast_rows)
    write_jsonl(validation_dir / "matched_validation.jsonl", matched_rows)
    (validation_dir / "validation_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def build_observation_rows(observations, run_date, run_id):
    rows = []
    collected_at_utc = current_timestamp_utc()
    for station_id, record in sorted((observations or {}).items()):
        if not isinstance(record, dict):
            continue
        sample_time = normalize_timestamp(
            record.get("sample_time_utc") or record.get("last_sample_utc") or record.get("observed_at_utc")
        )
        observed_at = normalize_timestamp(
            record.get("observed_at_utc") or record.get("sample_time_utc") or record.get("last_sample_utc")
        )
        for raw_key, (variable, units) in OBSERVATION_VARIABLES.items():
            if raw_key not in record or record.get(raw_key) is None:
                continue
            value = normalize_observed_value(raw_key, record.get(raw_key))
            rows.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "record_type": "observation",
                    "run_date": run_date,
                    "run_id": run_id,
                    "provider": record.get("provider") or record.get("source") or "socib",
                    "station_id": station_id,
                    "station_name": record.get("station_name") or record.get("name"),
                    "sample_time_utc": sample_time,
                    "observed_at_utc": observed_at,
                    "collected_at_utc": collected_at_utc,
                    "variable": variable,
                    "source_field": raw_key,
                    "value": value,
                    "raw_value": record.get(raw_key),
                    "units": units,
                }
            )
    return rows


def build_forecast_rows(snapshots_by_route, routes, run_date, run_id):
    rows = []
    for route_id, snapshot in sorted((snapshots_by_route or {}).items()):
        route = routes.get(route_id, {})
        forecast = snapshot.get("forecast", {})
        forecast_source = snapshot.get("forecast_source", {})
        data_lineage = snapshot.get("data_lineage", {})
        validation = route.get("validation", {}) or {}
        current_validation = route.get("current_validation", {}) or {}
        for target in forecast.get("hourly") or []:
            target_time = normalize_timestamp(target.get("time_utc"))
            if not target_time:
                continue
            for source_field, (variable, units) in FORECAST_VARIABLES.items():
                if target.get(source_field) is None:
                    continue
                truth_station = truth_station_for_variable(variable, validation, current_validation)
                rows.append(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "record_type": "forecast",
                        "run_date": run_date,
                        "run_id": run_id,
                        "route_id": route_id,
                        "route_name": route.get("name") or snapshot.get("route"),
                        "forecast_created_at_utc": normalize_timestamp(snapshot.get("created_at_utc")),
                        "forecast_source_id": forecast_source.get("id"),
                        "forecast_source_label": forecast_source.get("label"),
                        "ocean_source": (data_lineage.get("ocean_forecast") or {}).get("source"),
                        "resolution_km": (data_lineage.get("ocean_forecast") or {}).get("resolution_km"),
                        "target_time_utc": target_time,
                        "target_local_time": target.get("time"),
                        "variable": variable,
                        "source_field": source_field,
                        "value": target.get(source_field),
                        "units": units,
                        "truth_station_id": truth_station,
                        "lead_time_hours": lead_time_hours(snapshot.get("created_at_utc"), target_time),
                    }
                )
    return rows


def truth_station_for_variable(variable, wave_validation, current_validation):
    if variable.startswith("current_"):
        return current_validation.get("truth_source")
    if variable.startswith("wave_") or variable.startswith("swell_") or variable.startswith("wind_wave_"):
        return wave_validation.get("truth_source")
    return None


def match_observations_to_forecasts(observation_rows, forecast_rows):
    observations_by_key = {}
    for row in observation_rows:
        key = (row.get("station_id"), row.get("variable"), row.get("observed_at_utc"))
        observations_by_key.setdefault(key, []).append(row)

    matches = []
    seen = set()
    for forecast in forecast_rows:
        if forecast.get("lead_time_hours") is not None and forecast["lead_time_hours"] < 0:
            continue
        station_id = forecast.get("truth_station_id")
        if not station_id:
            continue
        key = (station_id, forecast.get("variable"), forecast.get("target_time_utc"))
        for observation in observations_by_key.get(key, []):
            match_id = "|".join(
                str(part)
                for part in (
                    forecast.get("run_id"),
                    forecast.get("route_id"),
                    forecast.get("target_time_utc"),
                    forecast.get("variable"),
                    station_id,
                )
            )
            if match_id in seen:
                continue
            seen.add(match_id)
            forecast_value = numeric_value(forecast.get("value"))
            observed_value = numeric_value(observation.get("value"))
            matches.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "record_type": "matched_validation",
                    "match_id": match_id,
                    "route_id": forecast.get("route_id"),
                    "route_name": forecast.get("route_name"),
                    "truth_station_id": station_id,
                    "truth_station_name": observation.get("station_name"),
                    "forecast_run_id": forecast.get("run_id"),
                    "forecast_created_at_utc": forecast.get("forecast_created_at_utc"),
                    "target_time_utc": forecast.get("target_time_utc"),
                    "observed_at_utc": observation.get("observed_at_utc"),
                    "variable": forecast.get("variable"),
                    "forecast_value": forecast.get("value"),
                    "observed_value": observation.get("value"),
                    "units": forecast.get("units"),
                    "error": error_delta(forecast_value, observed_value),
                    "absolute_error": absolute_error(forecast_value, observed_value),
                    "lead_time_hours": forecast.get("lead_time_hours"),
                    "forecast_source_id": forecast.get("forecast_source_id"),
                    "ocean_source": forecast.get("ocean_source"),
                    "resolution_km": forecast.get("resolution_km"),
                }
            )
    return sorted(matches, key=lambda row: (row.get("target_time_utc") or "", row.get("route_id") or "", row.get("variable") or ""))


def build_validation_summary(run_date, run_id, observation_rows, forecast_rows, matched_rows):
    variable_counts = {}
    for row in matched_rows:
        variable_counts[row["variable"]] = variable_counts.get(row["variable"], 0) + 1
    return {
        "schema_version": SCHEMA_VERSION,
        "run_date": run_date,
        "run_id": run_id,
        "created_at_utc": current_timestamp_utc(),
        "observation_rows": len(observation_rows),
        "forecast_rows": len(forecast_rows),
        "matched_rows": len(matched_rows),
        "matched_variables": variable_counts,
        "metrics": metrics_by_variable(matched_rows),
        "notes": [
            "Observation archive contains the latest provider samples fetched by this ETL run.",
            "Matched validation links current observations to any saved forecast index with the same station, variable, and target time.",
            "Forecast rows with negative lead time are archived but excluded from matched validation.",
            "Rows accumulate across GitHub/GCS runs when prior forecast_index.jsonl files are available in the output tree.",
        ],
    }


def metrics_by_variable(matched_rows):
    metrics = {}
    for variable in sorted({row.get("variable") for row in matched_rows if row.get("variable")}):
        rows = [row for row in matched_rows if row.get("variable") == variable and row.get("absolute_error") is not None]
        if not rows:
            metrics[variable] = {"count": 0, "mae": None, "bias": None}
            continue
        errors = [row["error"] for row in rows if row.get("error") is not None]
        absolute_errors = [row["absolute_error"] for row in rows]
        metrics[variable] = {
            "count": len(rows),
            "mae": round(sum(absolute_errors) / len(absolute_errors), 3),
            "bias": round(sum(errors) / len(errors), 3) if errors else None,
        }
    return metrics


def load_historical_forecast_rows(output_root):
    root = Path(output_root)
    rows = []
    for path in sorted(root.glob("*/runs/*/validation/forecast_index.jsonl")):
        rows.extend(read_jsonl(path))
    return rows


def write_jsonl(path, rows):
    with Path(path).open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, sort_keys=True) + "\n")


def read_jsonl(path):
    rows = []
    try:
        with Path(path).open(encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    except FileNotFoundError:
        return []
    return rows


def normalize_timestamp(value):
    if not value:
        return None
    text = str(value).strip()
    if text.endswith(" UTC"):
        text = text[:-4] + "Z"
    if text.endswith("Z") and "T" not in text:
        text = text[:-1].replace(" ", "T") + "Z"
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%MZ", "%Y-%m-%d %H:%M UTC"):
        try:
            return datetime.strptime(str(value), fmt).replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            pass
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            pass
    return text


def lead_time_hours(created_at, target_time):
    created = parse_timestamp(created_at)
    target = parse_timestamp(target_time)
    if not created or not target:
        return None
    return round((target - created).total_seconds() / 3600, 2)


def parse_timestamp(value):
    normalized = normalize_timestamp(value)
    if not normalized:
        return None
    try:
        return datetime.strptime(normalized, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def current_timestamp_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def numeric_value(value):
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_observed_value(source_field, value):
    if source_field.endswith("_direction_deg") or source_field == "wave_from_direction_deg":
        if isinstance(value, str):
            compass = value.strip().upper()
            if compass in COMPASS_DEGREES:
                return COMPASS_DEGREES[compass]
    return value


def error_delta(forecast_value, observed_value):
    if forecast_value is None or observed_value is None:
        return None
    return round(forecast_value - observed_value, 3)


def absolute_error(forecast_value, observed_value):
    error = error_delta(forecast_value, observed_value)
    if error is None:
        return None
    return abs(error)
