"""BigQuery export helpers for normalized PredSea evidence rows.

The repository already produces two normalized JSONL streams per run:

* ``validation/observation_samples.jsonl``
* ``validation/forecast_index.jsonl``

This module turns those rows into a single BigQuery fact table so the
ETL can backfill historical runs and then append new runs automatically.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Sequence

import validation_archive


DEFAULT_DATASET = "predsea_validation"
DEFAULT_TABLE = "evidence_rows"
DEFAULT_LOCATION = "europe-west1"
BIGQUERY_SCOPE = "https://www.googleapis.com/auth/bigquery"
SCHEMA_VERSION = "predsea.bigquery.evidence_rows.v1"
INSERT_BATCH_SIZE = 500


@dataclass(frozen=True)
class BigQueryConfig:
    project_id: str
    dataset_id: str
    table_id: str
    location: str = DEFAULT_LOCATION


def resolve_config(
    project_id: str | None = None,
    dataset_id: str | None = None,
    table_id: str | None = None,
    location: str | None = None,
) -> BigQueryConfig | None:
    dataset_id = dataset_id or os.environ.get("PREDSEA_BIGQUERY_DATASET") or DEFAULT_DATASET
    table_id = table_id or os.environ.get("PREDSEA_BIGQUERY_TABLE") or DEFAULT_TABLE
    project_id = (
        project_id
        or os.environ.get("PREDSEA_BIGQUERY_PROJECT")
        or os.environ.get("GOOGLE_CLOUD_PROJECT")
    )
    if not project_id or not dataset_id or not table_id:
        return None
    return BigQueryConfig(
        project_id=project_id,
        dataset_id=dataset_id,
        table_id=table_id,
        location=location or os.environ.get("PREDSEA_BIGQUERY_LOCATION") or DEFAULT_LOCATION,
    )


def export_validation_archive_to_bigquery(
    run_dir,
    project_id: str | None = None,
    dataset_id: str | None = None,
    table_id: str | None = None,
    location: str | None = None,
    client=None,
    dry_run: bool = False,
):
    """Export normalized validation rows from a run directory to BigQuery.

    The function is intentionally best-effort. If BigQuery is not configured,
    it returns a skipped status instead of failing the ETL.
    """
    validation_dir = Path(run_dir) / "validation"
    if not validation_dir.exists():
        validation_dir = Path(run_dir)

    observation_rows = validation_archive.read_jsonl(validation_dir / "observation_samples.jsonl")
    forecast_rows = validation_archive.read_jsonl(validation_dir / "forecast_index.jsonl")
    rows = build_normalized_rows(observation_rows, forecast_rows)
    config = resolve_config(project_id=project_id, dataset_id=dataset_id, table_id=table_id, location=location)

    if not rows:
        return {
            "status": "skipped",
            "reason": "no normalized validation rows were found",
            "observation_rows": len(observation_rows),
            "forecast_rows": len(forecast_rows),
            "exported_rows": 0,
        }

    if config is None:
        return {
            "status": "skipped",
            "reason": "bigquery configuration is incomplete",
            "observation_rows": len(observation_rows),
            "forecast_rows": len(forecast_rows),
            "exported_rows": 0,
        }

    try:
        if dry_run:
            return {
                "status": "dry_run",
                "project_id": config.project_id,
                "dataset_id": config.dataset_id,
                "table_id": config.table_id,
                "observation_rows": len(observation_rows),
                "forecast_rows": len(forecast_rows),
                "exported_rows": len(rows),
            }

        session = client or authorized_bigquery_session()
        ensure_dataset(session, config)
        ensure_table(session, config)
        insert_result = insert_rows(session, config, rows)
        return {
            "status": insert_result["status"],
            "project_id": config.project_id,
            "dataset_id": config.dataset_id,
            "table_id": config.table_id,
            "observation_rows": len(observation_rows),
            "forecast_rows": len(forecast_rows),
            "exported_rows": len(rows),
            "failed_rows": insert_result.get("failed_rows", 0),
            "insert_errors": insert_result.get("insert_errors", []),
        }
    except Exception as error:
        return {
            "status": "error",
            "reason": str(error),
            "project_id": config.project_id,
            "dataset_id": config.dataset_id,
            "table_id": config.table_id,
            "observation_rows": len(observation_rows),
            "forecast_rows": len(forecast_rows),
            "exported_rows": len(rows),
        }


def export_validation_rows_to_bigquery(
    observation_rows,
    forecast_rows,
    project_id: str | None = None,
    dataset_id: str | None = None,
    table_id: str | None = None,
    location: str | None = None,
    client=None,
    dry_run: bool = False,
    run_date: str | None = None,
    run_id: str | None = None,
):
    """Export normalized validation rows that are already in memory.

    The optional run metadata is accepted for symmetry with the archive-based
    helper and for future provenance tracking, but the normalized rows already
    carry the values that BigQuery needs.
    """
    rows = build_normalized_rows(observation_rows, forecast_rows)
    config = resolve_config(project_id=project_id, dataset_id=dataset_id, table_id=table_id, location=location)

    if not rows:
        return {
            "status": "skipped",
            "reason": "no normalized validation rows were found",
            "observation_rows": len(observation_rows or []),
            "forecast_rows": len(forecast_rows or []),
            "exported_rows": 0,
        }

    if config is None:
        return {
            "status": "skipped",
            "reason": "bigquery configuration is incomplete",
            "observation_rows": len(observation_rows or []),
            "forecast_rows": len(forecast_rows or []),
            "exported_rows": 0,
        }

    try:
        if dry_run:
            return {
                "status": "dry_run",
                "project_id": config.project_id,
                "dataset_id": config.dataset_id,
                "table_id": config.table_id,
                "observation_rows": len(observation_rows or []),
                "forecast_rows": len(forecast_rows or []),
                "exported_rows": len(rows),
            }

        session = client or authorized_bigquery_session()
        ensure_dataset(session, config)
        ensure_table(session, config)
        insert_result = insert_rows(session, config, rows)
        return {
            "status": insert_result["status"],
            "project_id": config.project_id,
            "dataset_id": config.dataset_id,
            "table_id": config.table_id,
            "observation_rows": len(observation_rows or []),
            "forecast_rows": len(forecast_rows or []),
            "exported_rows": len(rows),
            "failed_rows": insert_result.get("failed_rows", 0),
            "insert_errors": insert_result.get("insert_errors", []),
        }
    except Exception as error:
        return {
            "status": "error",
            "reason": str(error),
            "project_id": config.project_id,
            "dataset_id": config.dataset_id,
            "table_id": config.table_id,
            "observation_rows": len(observation_rows or []),
            "forecast_rows": len(forecast_rows or []),
            "exported_rows": len(rows),
        }


def build_normalized_rows(observation_rows, forecast_rows):
    ingested_at_utc = current_timestamp_utc()
    rows = []
    for row in observation_rows or []:
        rows.append(normalize_observation_row(row, ingested_at_utc=ingested_at_utc))
    for row in forecast_rows or []:
        rows.append(normalize_forecast_row(row, ingested_at_utc=ingested_at_utc))
    return sorted(
        rows,
        key=lambda row: (
            row.get("run_id") or "",
            row.get("record_type") or "",
            row.get("reference_station_id") or row.get("station_id") or "",
            row.get("variable") or "",
            row.get("sample_time_utc") or "",
        ),
    )


def normalize_observation_row(row, ingested_at_utc):
    sample_time_utc = bigquery_timestamp(row.get("sample_time_utc") or row.get("observed_at_utc"))
    observed_at_utc = bigquery_timestamp(row.get("observed_at_utc") or row.get("sample_time_utc"))
    normalized = {
        "schema_version": SCHEMA_VERSION,
        "record_type": "observation",
        "run_date": row.get("run_date"),
        "run_id": row.get("run_id"),
        "ingested_at_utc": ingested_at_utc,
        "source_system": row.get("provider"),
        "source_label": row.get("station_name"),
        "route_id": None,
        "route_name": None,
        "station_id": row.get("station_id"),
        "station_name": row.get("station_name"),
        "reference_station_id": row.get("station_id"),
        "reference_station_name": row.get("station_name"),
        "variable": row.get("variable"),
        "value": numeric_value(row.get("value")),
        "units": row.get("units"),
        "sample_time_utc": sample_time_utc,
        "observed_at_utc": observed_at_utc,
        "forecast_created_at_utc": None,
        "target_time_utc": None,
        "target_local_time": None,
        "lead_time_hours": None,
        "resolution_km": None,
        "forecast_source_id": None,
        "forecast_source_label": None,
        "ocean_source": None,
        "truth_station_id": None,
        "truth_station_name": None,
        "source_field": row.get("source_field"),
    }
    normalized["row_hash"] = stable_row_hash(normalized)
    return normalized


def normalize_forecast_row(row, ingested_at_utc):
    target_time_utc = bigquery_timestamp(row.get("target_time_utc"))
    forecast_created_at_utc = bigquery_timestamp(row.get("forecast_created_at_utc"))
    normalized = {
        "schema_version": SCHEMA_VERSION,
        "record_type": "forecast",
        "run_date": row.get("run_date"),
        "run_id": row.get("run_id"),
        "ingested_at_utc": ingested_at_utc,
        "source_system": row.get("forecast_source_id") or row.get("ocean_source"),
        "source_label": row.get("forecast_source_label"),
        "route_id": row.get("route_id"),
        "route_name": row.get("route_name"),
        "station_id": None,
        "station_name": None,
        "reference_station_id": row.get("truth_station_id"),
        "reference_station_name": row.get("truth_station_name"),
        "variable": row.get("variable"),
        "value": numeric_value(row.get("value")),
        "units": row.get("units"),
        "sample_time_utc": target_time_utc,
        "observed_at_utc": None,
        "forecast_created_at_utc": forecast_created_at_utc,
        "target_time_utc": target_time_utc,
        "target_local_time": row.get("target_local_time"),
        "lead_time_hours": numeric_value(row.get("lead_time_hours")),
        "resolution_km": numeric_value(row.get("resolution_km")),
        "forecast_source_id": row.get("forecast_source_id"),
        "forecast_source_label": row.get("forecast_source_label"),
        "ocean_source": row.get("ocean_source"),
        "truth_station_id": row.get("truth_station_id"),
        "truth_station_name": row.get("truth_station_name"),
        "source_field": row.get("source_field"),
    }
    normalized["row_hash"] = stable_row_hash(normalized)
    return normalized


def stable_row_hash(row):
    payload = {key: row.get(key) for key in sorted(row) if key != "ingested_at_utc"}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    return digest


def bigquery_schema():
    return [
        {"name": "schema_version", "type": "STRING", "mode": "REQUIRED"},
        {"name": "row_hash", "type": "STRING", "mode": "REQUIRED"},
        {"name": "record_type", "type": "STRING", "mode": "REQUIRED"},
        {"name": "run_date", "type": "DATE", "mode": "REQUIRED"},
        {"name": "run_id", "type": "STRING", "mode": "REQUIRED"},
        {"name": "ingested_at_utc", "type": "TIMESTAMP", "mode": "REQUIRED"},
        {"name": "source_system", "type": "STRING", "mode": "NULLABLE"},
        {"name": "source_label", "type": "STRING", "mode": "NULLABLE"},
        {"name": "route_id", "type": "STRING", "mode": "NULLABLE"},
        {"name": "route_name", "type": "STRING", "mode": "NULLABLE"},
        {"name": "station_id", "type": "STRING", "mode": "NULLABLE"},
        {"name": "station_name", "type": "STRING", "mode": "NULLABLE"},
        {"name": "reference_station_id", "type": "STRING", "mode": "NULLABLE"},
        {"name": "reference_station_name", "type": "STRING", "mode": "NULLABLE"},
        {"name": "variable", "type": "STRING", "mode": "REQUIRED"},
        {"name": "value", "type": "FLOAT", "mode": "NULLABLE"},
        {"name": "units", "type": "STRING", "mode": "NULLABLE"},
        {"name": "sample_time_utc", "type": "TIMESTAMP", "mode": "NULLABLE"},
        {"name": "observed_at_utc", "type": "TIMESTAMP", "mode": "NULLABLE"},
        {"name": "forecast_created_at_utc", "type": "TIMESTAMP", "mode": "NULLABLE"},
        {"name": "target_time_utc", "type": "TIMESTAMP", "mode": "NULLABLE"},
        {"name": "target_local_time", "type": "STRING", "mode": "NULLABLE"},
        {"name": "lead_time_hours", "type": "FLOAT", "mode": "NULLABLE"},
        {"name": "resolution_km", "type": "FLOAT", "mode": "NULLABLE"},
        {"name": "forecast_source_id", "type": "STRING", "mode": "NULLABLE"},
        {"name": "forecast_source_label", "type": "STRING", "mode": "NULLABLE"},
        {"name": "ocean_source", "type": "STRING", "mode": "NULLABLE"},
        {"name": "truth_station_id", "type": "STRING", "mode": "NULLABLE"},
        {"name": "truth_station_name", "type": "STRING", "mode": "NULLABLE"},
        {"name": "source_field", "type": "STRING", "mode": "NULLABLE"},
    ]


def ensure_dataset(session, config: BigQueryConfig):
    dataset_url = f"https://bigquery.googleapis.com/bigquery/v2/projects/{config.project_id}/datasets/{config.dataset_id}"
    response = session.get(dataset_url)
    if response.status_code == 200:
        return response.json()
    if response.status_code != 404:
        response.raise_for_status()
    payload = {
        "datasetReference": {
            "projectId": config.project_id,
            "datasetId": config.dataset_id,
        },
        "location": config.location,
    }
    response = session.post(
        f"https://bigquery.googleapis.com/bigquery/v2/projects/{config.project_id}/datasets",
        json=payload,
    )
    if response.status_code not in (200, 201, 409):
        response.raise_for_status()
    return response.json() if response.text else payload


def ensure_table(session, config: BigQueryConfig):
    table_url = f"https://bigquery.googleapis.com/bigquery/v2/projects/{config.project_id}/datasets/{config.dataset_id}/tables/{config.table_id}"
    response = session.get(table_url)
    if response.status_code == 200:
        return response.json()
    if response.status_code != 404:
        response.raise_for_status()
    payload = {
        "tableReference": {
            "projectId": config.project_id,
            "datasetId": config.dataset_id,
            "tableId": config.table_id,
        },
        "schema": {"fields": bigquery_schema()},
        "timePartitioning": {"type": "DAY", "field": "run_date"},
        "clustering": {"fields": ["record_type", "route_id", "variable", "source_system"]},
    }
    response = session.post(
        f"https://bigquery.googleapis.com/bigquery/v2/projects/{config.project_id}/datasets/{config.dataset_id}/tables",
        json=payload,
    )
    if response.status_code not in (200, 201, 409):
        response.raise_for_status()
    return response.json() if response.text else payload


def insert_rows(session, config: BigQueryConfig, rows: Sequence[dict]):
    if not rows:
        return {"status": "skipped", "failed_rows": 0, "insert_errors": []}

    insert_url = (
        f"https://bigquery.googleapis.com/bigquery/v2/projects/{config.project_id}"
        f"/datasets/{config.dataset_id}/tables/{config.table_id}/insertAll"
    )
    failed_rows = 0
    insert_errors: List[dict] = []
    for batch in chunks(rows, INSERT_BATCH_SIZE):
        payload = {
            "skipInvalidRows": False,
            "ignoreUnknownValues": False,
            "rows": [
                {
                    "insertId": row.get("row_hash"),
                    "json": row,
                }
                for row in batch
            ],
        }
        response = session.post(insert_url, json=payload)
        response.raise_for_status()
        body = response.json() if response.text else {}
        batch_errors = body.get("insertErrors") or []
        if batch_errors:
            failed_rows += len(batch_errors)
            insert_errors.extend(batch_errors)
    return {
        "status": "written" if not insert_errors else "partial_failure",
        "failed_rows": failed_rows,
        "insert_errors": insert_errors,
    }


def chunks(rows: Sequence[dict], size: int):
    for index in range(0, len(rows), size):
        yield rows[index : index + size]


def authorized_bigquery_session():
    from google.auth.transport.requests import AuthorizedSession

    creds, _ = google_auth_default_project()
    return AuthorizedSession(creds)


def google_auth_default_project():
    import google.auth

    return google.auth.default(scopes=[BIGQUERY_SCOPE])


def current_timestamp_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def numeric_value(value):
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def bigquery_timestamp(value):
    parsed = validation_archive.parse_timestamp(value)
    if not parsed:
        return None
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
