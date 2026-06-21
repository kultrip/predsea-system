from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
HUMANINTHELOOP_DIR = PROJECT_ROOT / "humanintheloop"
if str(HUMANINTHELOOP_DIR) not in sys.path:
    sys.path.insert(0, str(HUMANINTHELOOP_DIR))

import validation_archive
from api.warnings_service import BIGQUERY_SCOPE, query_bigquery, resolve_env, sql_literal  # noqa: E402


CLIMATOLOGY_SCHEMA = [
    {"name": "provider", "type": "STRING", "mode": "NULLABLE"},
    {"name": "network", "type": "STRING", "mode": "NULLABLE"},
    {"name": "station_id", "type": "STRING", "mode": "REQUIRED"},
    {"name": "station_name", "type": "STRING", "mode": "NULLABLE"},
    {"name": "latitude", "type": "FLOAT", "mode": "NULLABLE"},
    {"name": "longitude", "type": "FLOAT", "mode": "NULLABLE"},
    {"name": "variable", "type": "STRING", "mode": "REQUIRED"},
    {"name": "unit", "type": "STRING", "mode": "NULLABLE"},
    {"name": "month", "type": "INTEGER", "mode": "REQUIRED"},
    {"name": "hour_utc", "type": "INTEGER", "mode": "REQUIRED"},
    {"name": "clim_mean", "type": "FLOAT", "mode": "NULLABLE"},
    {"name": "clim_stddev", "type": "FLOAT", "mode": "NULLABLE"},
    {"name": "sample_count", "type": "INTEGER", "mode": "NULLABLE"},
    {"name": "history_years", "type": "INTEGER", "mode": "NULLABLE"},
    {"name": "earliest_sample_utc", "type": "TIMESTAMP", "mode": "NULLABLE"},
    {"name": "latest_sample_utc", "type": "TIMESTAMP", "mode": "NULLABLE"},
    {"name": "computed_at_utc", "type": "TIMESTAMP", "mode": "NULLABLE"},
]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build PredSea climatology baseline from evidence_rows.")
    parser.add_argument("--project", default=resolve_env("PREDSEA_BIGQUERY_PROJECT", "GOOGLE_CLOUD_PROJECT"))
    parser.add_argument("--dataset", default=resolve_env("PREDSEA_BIGQUERY_DATASET", "BQ_DATASET", default="predsea_validation"))
    parser.add_argument("--evidence-table", default=resolve_env("PREDSEA_BIGQUERY_EVIDENCE_TABLE", "BQ_TABLE_EVIDENCE", default="evidence_rows"))
    parser.add_argument("--climatology-table", default=resolve_env("PREDSEA_BIGQUERY_CLIMATOLOGY_TABLE", "BQ_TABLE_CLIMATOLOGY", default="climatology_baseline"))
    parser.add_argument("--location", default=resolve_env("PREDSEA_BIGQUERY_LOCATION", "BQ_LOCATION", default="EU"))
    parser.add_argument("--gcs-bucket", default=resolve_env("PREDSEA_CLIMATOLOGY_GCS_BUCKET", default="predsea-daily-outputs"))
    parser.add_argument("--gcs-prefix", default=resolve_env("PREDSEA_CLIMATOLOGY_GCS_PREFIX", default="predictions"))
    parser.add_argument("--start-date", default="2019-01-01")
    parser.add_argument("--end-date", default="2025-01-01")
    parser.add_argument(
        "--min-sample-count",
        type=int,
        default=int(resolve_env("PREDSEA_CLIMATOLOGY_MIN_SAMPLE_COUNT", default="10")),
    )
    parser.add_argument(
        "--min-history-years",
        type=int,
        default=int(resolve_env("PREDSEA_CLIMATOLOGY_MIN_HISTORY_YEARS", default="1")),
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if not args.project:
        raise SystemExit("Missing BigQuery project. Set PREDSEA_BIGQUERY_PROJECT or GOOGLE_CLOUD_PROJECT.")

    query = build_climatology_query(
        project=args.project,
        dataset=args.dataset,
        evidence_table=args.evidence_table,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    bigquery_rows = query_bigquery(query, project_id=args.project, location=args.location)
    gcs_rows = load_gcs_observation_rows(
        bucket_name=args.gcs_bucket,
        prefix=args.gcs_prefix,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    rows = aggregate_climatology_rows(
        [*bigquery_rows, *gcs_rows],
        min_sample_count=args.min_sample_count,
        min_history_years=args.min_history_years,
    )
    print(
        "Computed "
        f"{len(rows)} climatology rows "
        f"(BigQuery: {len(bigquery_rows)}, GCS archives: {len(gcs_rows)})."
    )

    if args.dry_run:
        return 0

    session = bigquery_session()
    ensure_dataset(session, args.project, args.dataset, args.location)
    ensure_table(session, args.project, args.dataset, args.climatology_table, args.location)
    clear_table(session, args.project, args.dataset, args.climatology_table)
    insert_rows(session, args.project, args.dataset, args.climatology_table, rows)
    print("Climatology baseline uploaded.")
    return 0


def build_climatology_query(*, project, dataset, evidence_table, start_date, end_date):
    variables = [
        "air_temperature",
        "water_temperature",
        "sea_level",
        "salinity",
        "sea_level_pressure",
        "wave_height",
        "wave_height_max",
        "swell_1_height",
        "wind_speed",
        "current_speed",
        "current_u",
        "current_v",
        "wave_period_peak",
    ]
    variable_list = ", ".join(sql_literal(variable) for variable in variables)
    
    return f"""
SELECT
  source_system,
  source_label,
  station_id,
  station_name,
  CAST(NULL AS FLOAT64) AS latitude,
  CAST(NULL AS FLOAT64) AS longitude,
  variable,
  units,
  sample_time_utc,
  value
FROM `{project}.{dataset}.{evidence_table}`
WHERE record_type = 'observation'
  AND variable IN ({variable_list})
  AND sample_time_utc >= TIMESTAMP('{start_date}T00:00:00Z')
  AND sample_time_utc < TIMESTAMP('{end_date}T00:00:00Z')
  AND value IS NOT NULL
ORDER BY station_id, variable, sample_time_utc
"""


def load_gcs_observation_rows(*, bucket_name, prefix, start_date=None, end_date=None, client=None):
    try:
        from google.cloud import storage
    except Exception as error:
        raise RuntimeError(f"Unable to load Google Cloud Storage helpers: {error}") from error

    client = client or storage.Client()
    bucket = client.bucket(bucket_name)
    prefix = (prefix or "").strip("/")
    root_prefix = f"{prefix}/" if prefix else ""
    rows = []
    start_key = _date_key(start_date)
    end_key = _date_key(end_date)

    for blob in client.list_blobs(bucket, prefix=root_prefix):
        # --- FIX 1: Buscamos cualquier JSONL de EMODnet/Copernicus sin forzar carpeta 'validation' ---
        if not blob.name.endswith(".jsonl"):
            continue
            
        run_date = _run_date_from_blob_name(blob.name, prefix)
        # Solo aplicamos los filtros de fecha si el script consigue extraer una fecha de la estructura
        if run_date:
            if start_key and run_date < start_key:
                continue
            if end_key and run_date >= end_key:
                continue
                
        text = blob.download_as_text(encoding="utf-8")
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def aggregate_climatology_rows(rows, *, min_sample_count=10, min_history_years=1):
    groups = {}
    computed_at_utc = current_timestamp_utc()
    for row in rows:
        sample_time = validation_archive.parse_timestamp(
            row.get("sample_time_utc")
            or row.get("observed_at_utc")
            or row.get("source_time_coordinate_utc")
        )
        if sample_time is None:
            continue
        value = _as_float(row.get("value"))
        if value is None:
            continue
        provider = row.get("provider") or row.get("source_system") or row.get("source") or "unknown"
        network = row.get("network") or validation_archive.infer_network_from_record(row)
        station_id = row.get("station_id")
        variable = row.get("variable")
        if not station_id or not variable:
            continue
        station_name = row.get("station_name")
        latitude = _as_float(row.get("latitude"))
        longitude = _as_float(row.get("longitude"))
        unit = row.get("units") or row.get("unit")
        
        key = (
            provider,
            network,
            station_id,
            variable,
            sample_time.month,
            sample_time.hour,
        )
        bucket = groups.setdefault(
            key,
            {
                "provider": provider,
                "network": network,
                "station_id": station_id,
                "station_name": station_name,
                "latitude": None,
                "longitude": None,
                "variable": variable,
                "unit": unit,
                "month": sample_time.month,
                "hour_utc": sample_time.hour,
                "sample_count": 0,
                "sum": 0.0,
                "sumsq": 0.0,
                "years": set(),
                "earliest_sample_utc": sample_time,
                "latest_sample_utc": sample_time,
                "computed_at_utc": computed_at_utc,
            },
        )
        bucket["sample_count"] += 1
        bucket["sum"] += value
        bucket["sumsq"] += value * value
        bucket["years"].add(sample_time.year)
        if sample_time < bucket["earliest_sample_utc"]:
            bucket["earliest_sample_utc"] = sample_time
        if sample_time > bucket["latest_sample_utc"]:
            bucket["latest_sample_utc"] = sample_time
        if not bucket["provider"]:
            bucket["provider"] = provider
        if not bucket["network"]:
            bucket["network"] = network
        if not bucket["station_name"]:
            bucket["station_name"] = station_name
            
        if latitude is not None:
            bucket["latitude"] = latitude
        if longitude is not None:
            bucket["longitude"] = longitude
        if unit and not bucket["unit"]:
            bucket["unit"] = unit

    aggregated = []
    for bucket in groups.values():
        sample_count = bucket["sample_count"]
        history_years = len(bucket["years"])
        if sample_count < min_sample_count or history_years < min_history_years:
            continue
        mean = bucket["sum"] / sample_count
        stddev = None
        if sample_count > 1:
            variance = (bucket["sumsq"] - (bucket["sum"] ** 2) / sample_count) / (sample_count - 1)
            stddev = math.sqrt(max(variance, 0.0))
            
        # --- FIX 2: CONTROL ANTI-CRASH PARA VALORES FUERA DE RANGO JSON (NaN / INF) ---
        if mean is not None and (math.isnan(mean) or math.isinf(mean)):
            mean = None
        if stddev is not None and (math.isnan(stddev) or math.isinf(stddev)):
            stddev = None
        # -----------------------------------------------------------------------------

        aggregated.append(
            {
                "provider": bucket["provider"],
                "network": bucket["network"],
                "station_id": bucket["station_id"],
                "station_name": bucket["station_name"],
                "latitude": bucket["latitude"],
                "longitude": bucket["longitude"],
                "variable": bucket["variable"],
                "unit": bucket["unit"],
                "month": bucket["month"],
                "hour_utc": bucket["hour_utc"],
                "clim_mean": mean,
                "clim_stddev": stddev,
                "sample_count": sample_count,
                "history_years": history_years,
                "earliest_sample_utc": format_timestamp(bucket["earliest_sample_utc"]),
                "latest_sample_utc": format_timestamp(bucket["latest_sample_utc"]),
                "computed_at_utc": bucket["computed_at_utc"],
            }
        )
    return sorted(aggregated, key=lambda row: (row["station_id"], row["variable"], row["month"], row["hour_utc"]))


def bigquery_session():
    try:
        import google.auth
        from google.auth.transport.requests import AuthorizedSession
    except Exception as error:
        raise RuntimeError(f"Unable to load Google auth helpers: {error}") from error

    creds, _ = google.auth.default(scopes=[BIGQUERY_SCOPE])
    return AuthorizedSession(creds)


def ensure_dataset(session, project, dataset, location):
    url = f"https://bigquery.googleapis.com/bigquery/v2/projects/{project}/datasets/{dataset}"
    response = session.get(url)
    if response.status_code == 200:
        return response.json()
    if response.status_code != 404:
        response.raise_for_status()
    payload = {
        "datasetReference": {"projectId": project, "datasetId": dataset},
        "location": location,
    }
    response = session.post(f"https://bigquery.googleapis.com/bigquery/v2/projects/{project}/datasets", json=payload)
    if response.status_code not in (200, 201, 409):
        response.raise_for_status()
    return response.json() if response.text else payload


def ensure_table(session, project, dataset, table, location):
    url = f"https://bigquery.googleapis.com/bigquery/v2/projects/{project}/datasets/{dataset}/tables/{table}"
    response = session.get(url)
    if response.status_code == 200:
        return response.json()
    if response.status_code != 404:
        response.raise_for_status()
    payload = {
        "tableReference": {"projectId": project, "datasetId": dataset, "tableId": table},
        "schema": {"fields": CLIMATOLOGY_SCHEMA},
        "clustering": {"fields": ["station_id", "variable"]},
    }
    response = session.post(f"https://bigquery.googleapis.com/bigquery/v2/projects/{project}/datasets/{dataset}/tables", json=payload)
    if response.status_code not in (200, 201, 409):
        response.raise_for_status()
    return response.json() if response.text else payload


def clear_table(session, project, dataset, table):
    query = f"TRUNCATE TABLE `{project}.{dataset}.{table}`"
    response = session.post(
        f"https://bigquery.googleapis.com/bigquery/v2/projects/{project}/queries",
        json={"query": query, "useLegacySql": False, "timeoutMs": 30000},
    )
    if response.status_code not in (200, 201):
        response.raise_for_status()


def insert_rows(session, project, dataset, table, rows, batch_size=500):
    url = f"https://bigquery.googleapis.com/bigquery/v2/projects/{project}/datasets/{dataset}/tables/{table}/insertAll"
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        payload = {
            "skipInvalidRows": False,
            "ignoreUnknownValues": False,
            "rows": [{"insertId": row.get("station_id", "") + ":" + str(row.get("variable", "")) + ":" + str(row.get("month", "")) + ":" + str(row.get("hour_utc", "")), "json": row} for row in batch],
        }
        response = session.post(url, json=payload)
        response.raise_for_status()


def _run_date_from_blob_name(blob_name, prefix):
    parts = blob_name.split("/")
    if prefix:
        prefix_parts = [part for part in prefix.split("/") if part]
        if parts[: len(prefix_parts)] != prefix_parts:
            return None
        parts = parts[len(prefix_parts) :]
    if len(parts) < 4:
        return None
    return parts[0]


def _date_key(value):
    if not value:
        return None
    text = str(value)
    return text[:10] if len(text) >= 10 else text


def _as_float(value):
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def format_timestamp(value):
    if value is None:
        return None
    if hasattr(value, "astimezone"):
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def current_timestamp_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


if __name__ == "__main__":
    raise SystemExit(main())