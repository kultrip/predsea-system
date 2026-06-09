import importlib.util
import json
from pathlib import Path


def load_backfill_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "backfill_validation_archive.py"
    spec = importlib.util.spec_from_file_location("backfill_validation_archive", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_backfill_builds_archive_from_snapshots_and_history():
    backfill = load_backfill_module()
    routes = {
        "palma_ibiza": {
            "id": "palma_ibiza",
            "name": "Palma -> Ibiza",
            "validation": {"truth_source": "canal_de_ibiza"},
            "current_validation": {"truth_source": None},
        }
    }
    snapshots = {
        "palma_ibiza": {
            "route": "Palma -> Ibiza",
            "route_id": "palma_ibiza",
            "created_at_utc": "2026-06-09 16:00 UTC",
            "forecast_source": {"id": "copernicus"},
            "data_lineage": {"ocean_forecast": {"source": "copernicus_med", "resolution_km": 4.0}},
            "observations": {
                "canal_de_ibiza": {
                    "name": "Buoy Canal de Ibiza",
                    "last_sample_utc": "2026-06-09 16:00 UTC",
                    "wave_height_m": 0.43,
                }
            },
            "forecast": {
                "hourly": [
                    {
                        "time": "20:00",
                        "time_utc": "2026-06-09 20:00 UTC",
                        "wave_m": 0.8,
                    }
                ]
            },
        }
    }
    historical_rows = [
        {
            "run_id": "2026-06-09T0800Z",
            "route_id": "palma_ibiza",
            "route_name": "Palma -> Ibiza",
            "truth_station_id": "canal_de_ibiza",
            "target_time_utc": "2026-06-09T16:00:00Z",
            "forecast_created_at_utc": "2026-06-09T08:00:00Z",
            "forecast_source_id": "copernicus",
            "ocean_source": "copernicus_med",
            "resolution_km": 4.0,
            "variable": "wave_height",
            "value": 0.9,
            "units": "m",
            "lead_time_hours": 8.0,
        }
    ]

    archive = backfill.build_run_archive(
        "2026-06-09",
        "2026-06-09T1600Z",
        routes,
        snapshots,
        snapshots["palma_ibiza"]["observations"],
        historical_rows,
    )

    assert archive["summary"]["observation_rows"] == 1
    assert archive["summary"]["forecast_rows"] == 1
    assert archive["summary"]["matched_rows"] == 1
    assert archive["matched_rows"][0]["forecast_run_id"] == "2026-06-09T0800Z"
    assert archive["matched_rows"][0]["error"] == 0.47


def test_backfill_updates_manifest_payload_with_validation_entry():
    backfill = load_backfill_module()
    manifest = {"run_id": "2026-06-09T1600Z", "routes": ["palma_ibiza"]}
    entry = {
        "path": "validation/validation_summary.json",
        "matched_rows": 2,
    }

    updated = backfill.update_manifest_payload(manifest, entry)

    assert updated["validation"] == entry
    assert updated["run_id"] == "2026-06-09T1600Z"
    assert "validation" not in manifest


def test_backfill_jsonl_round_trip():
    backfill = load_backfill_module()
    rows = [{"a": 1}, {"b": "two"}]

    text = backfill.jsonl_text(rows)

    assert backfill.parse_jsonl(text) == rows
    assert json.loads(text.splitlines()[0]) == {"a": 1}
