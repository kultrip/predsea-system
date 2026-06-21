from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
HUMANINTHELOOP_DIR = PROJECT_ROOT / "humanintheloop"
if str(HUMANINTHELOOP_DIR) not in sys.path:
    sys.path.insert(0, str(HUMANINTHELOOP_DIR))

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
    parser.add_argument("--start-date", default="2019-01-01")
    parser.add_argument("--end-date", default="2025-01-01")
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
    rows = query_bigquery(query, project_id=args.project, location=args.location)
    print(f"Computed {len(rows)} climatology rows.")

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
  ANY_VALUE(provider) AS provider,
  ANY_VALUE(network) AS network,
  station_id,
  ANY_VALUE(station_name) AS station_name,
  ANY_VALUE(latitude) AS latitude,
  ANY_VALUE(longitude) AS longitude,
  variable,
  ANY_VALUE(units) AS unit,
  EXTRACT(MONTH FROM sample_time_utc) AS month,
  EXTRACT(HOUR FROM sample_time_utc) AS hour_utc,
  AVG(value) AS clim_mean,
  STDDEV(value) AS clim_stddev,
  COUNT(*) AS sample_count,
  COUNT(DISTINCT EXTRACT(YEAR FROM sample_time_utc)) AS history_years,
  MIN(sample_time_utc) AS earliest_sample_utc,
  MAX(sample_time_utc) AS latest_sample_utc,
  CURRENT_TIMESTAMP() AS computed_at_utc
FROM `{project}.{dataset}.{evidence_table}`
WHERE record_type = 'observation'
  AND variable IN ({variable_list})
  AND sample_time_utc >= TIMESTAMP('{start_date}T00:00:00Z')
  AND sample_time_utc < TIMESTAMP('{end_date}T00:00:00Z')
  AND value IS NOT NULL
GROUP BY station_id, variable, month, hour_utc
HAVING sample_count >= 30 AND history_years >= 3
ORDER BY station_id, variable, month, hour_utc
"""


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


if __name__ == "__main__":
    raise SystemExit(main())
