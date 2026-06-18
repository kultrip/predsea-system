import json
from pathlib import Path

import bigquery_export
import validation_archive


def write_validation_archive(tmp_path):
    validation_dir = Path(tmp_path) / "validation"
    validation_dir.mkdir(parents=True)
    observation_rows = [
        {
            "schema_version": "predsea.validation.v1",
            "record_type": "observation",
            "run_date": "2026-06-10",
            "run_id": "2026-06-10T0600Z",
            "provider": "socib",
            "station_id": "canal_de_ibiza",
            "station_name": "Buoy Canal de Ibiza",
            "observed_at_utc": "2026-06-10 06:00 UTC",
            "variable": "wave_height",
            "source_field": "wave_height_m",
            "value": 0.47,
            "units": "m",
        }
    ]
    forecast_rows = [
        {
            "schema_version": "predsea.validation.v1",
            "record_type": "forecast",
            "run_date": "2026-06-10",
            "run_id": "2026-06-10T0600Z",
            "route_id": "palma_ibiza",
            "route_name": "Palma -> Ibiza",
            "forecast_created_at_utc": "2026-06-10 06:00 UTC",
            "forecast_source_id": "copernicus",
            "forecast_source_label": "Copernicus",
            "ocean_source": "copernicus_med",
            "truth_station_id": "canal_de_ibiza",
            "truth_station_name": "Buoy Canal de Ibiza",
            "target_time_utc": "2026-06-10T16:00:00Z",
            "target_local_time": "18:00",
            "variable": "wave_height",
            "source_field": "wave_m",
            "value": 0.9,
            "units": "m",
            "lead_time_hours": 10.0,
            "resolution_km": 4.0,
        }
    ]
    (validation_dir / "observation_samples.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in observation_rows),
        encoding="utf-8",
    )
    (validation_dir / "forecast_index.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in forecast_rows),
        encoding="utf-8",
    )
    return validation_dir


def test_build_normalized_rows_combines_forecast_and_observation(tmp_path):
    validation_dir = write_validation_archive(tmp_path)

    rows = bigquery_export.build_normalized_rows(
        bigquery_export.validation_archive.read_jsonl(validation_dir / "observation_samples.jsonl"),
        bigquery_export.validation_archive.read_jsonl(validation_dir / "forecast_index.jsonl"),
    )

    assert len(rows) == 2
    observation = next(row for row in rows if row["record_type"] == "observation")
    forecast = next(row for row in rows if row["record_type"] == "forecast")

    assert observation["reference_station_id"] == "canal_de_ibiza"
    assert observation["sample_time_utc"] == "2026-06-10T06:00:00Z"
    assert observation["row_hash"]
    assert forecast["route_id"] == "palma_ibiza"
    assert forecast["reference_station_id"] == "canal_de_ibiza"
    assert forecast["sample_time_utc"] == "2026-06-10T16:00:00Z"
    assert forecast["lead_time_hours"] == 10.0
    assert forecast["resolution_km"] == 4.0
    assert forecast["row_hash"]


def test_build_normalized_rows_supports_portus_observation_aliases():
    observation_records = {
        "portus_3545": {
            "source": "puertos_portus",
            "station_name": "Portus station 3545",
            "last_sample_utc": "2026-06-11 17:00 UTC",
            "wave_height_m": 0.42,
            "wind_speed_mps": 4.3,
            "current_speed_mps": 0.56,
            "temperature_c": 21.2,
            "water_temperature_c": 22.4,
        }
    }
    observation_rows = validation_archive.build_observation_rows(
        observation_records,
        "2026-06-11",
        "2026-06-11T1755Z",
    )

    rows = bigquery_export.build_normalized_rows(observation_rows, [])

    assert len(rows) == 5
    row_types = {row["variable"] for row in rows}
    assert {"wave_height", "wind_speed", "current_speed", "air_temperature", "water_temperature"}.issubset(row_types)
    wave_row = next(row for row in rows if row["variable"] == "wave_height")
    assert wave_row["source_system"] == "puertos_portus"
    assert wave_row["station_id"] == "portus_3545"
    assert wave_row["value"] == 0.42
    assert wave_row["sample_time_utc"] == "2026-06-11T17:00:00Z"
    assert wave_row["row_hash"]


def test_normalize_station_metadata_row_filters_unknown_fields():
    row = {
        "provider": "puertos_del_estado",
        "network": "redext",
        "station_id": "dragonera",
        "station_name": "Dragonera",
        "latitude": 39.59,
        "longitude": 2.33,
        "depth_m": 0.0,
        "variables_supported": ["wave_height", "wind_speed"],
        "nearest_routes": ["palma_ibiza"],
        "distance_to_route_nm": 1.7,
        "freshness_status": "live",
        "resolution_km": 4.2,
        "unexpected_column": "should be dropped",
    }

    normalized = bigquery_export.normalize_station_metadata_row(row, ingested_at_utc="2026-06-18T00:00:00Z")

    assert "unexpected_column" not in normalized
    assert "resolution_km" not in normalized
    assert normalized["row_hash"]
    assert normalized["provider"] == "puertos_del_estado"
    assert normalized["variables_supported"] == ["wave_height", "wind_speed"]


def test_export_validation_archive_to_bigquery_skips_without_config(tmp_path, monkeypatch):
    write_validation_archive(tmp_path)
    monkeypatch.delenv("PREDSEA_BIGQUERY_PROJECT", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("PREDSEA_BIGQUERY_DATASET", raising=False)
    monkeypatch.delenv("PREDSEA_BIGQUERY_TABLE", raising=False)

    result = bigquery_export.export_validation_archive_to_bigquery(tmp_path / "validation")

    assert result["status"] == "skipped"
    assert result["exported_rows"] == 0


def test_insert_rows_reports_failed_row_samples_and_messages():
    class FakeResponse:
        status_code = 200
        text = "{\"insertErrors\": [{\"index\": 1, \"errors\": [{\"reason\": \"invalid\", \"message\": \"bad value\"}]}]}"

        def json(self):
            return {
                "insertErrors": [
                    {
                        "index": 1,
                        "errors": [
                            {
                                "reason": "invalid",
                                "message": "bad value",
                            }
                        ],
                    }
                ]
            }

    class FakeSession:
        def post(self, url, json):
            return FakeResponse()

    rows = [
        {
            "row_hash": "row-1",
            "schema_version": "predsea.validation.v1",
            "record_type": "observation",
            "run_date": "2026-06-18",
            "run_id": "2026-06-18T1200Z",
            "provider": "puertos_del_estado",
            "station_id": "puertos_ibiza",
            "station_name": "Ibiza",
            "variable": "wave_height",
            "sample_time_utc": "2026-06-18T06:00:00Z",
            "value": 0.4,
            "units": "m",
        },
        {
            "row_hash": "row-2",
            "schema_version": "predsea.validation.v1",
            "record_type": "observation",
            "run_date": "2026-06-18",
            "run_id": "2026-06-18T1200Z",
            "provider": "puertos_del_estado",
            "station_id": "puertos_palma",
            "station_name": "Palma",
            "variable": "wind_speed",
            "sample_time_utc": "2026-06-18T07:00:00Z",
            "value": 4.2,
            "units": "m/s",
        },
    ]
    config = bigquery_export.BigQueryConfig("predsea-api", "predsea_validation", "evidence_rows")

    result = bigquery_export.insert_rows(FakeSession(), config, rows)

    assert result["status"] == "partial_failure"
    assert result["failed_rows"] == 1
    assert result["error_messages"] == ["bad value"]
    assert result["insert_errors"][0]["row_hash"] == "row-2"
    assert result["failed_row_samples"][0]["row_hash"] == "row-2"
    assert result["failed_row_samples"][0]["row_sample"]["station_id"] == "puertos_palma"
