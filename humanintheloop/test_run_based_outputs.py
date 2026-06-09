import importlib.util
import json
from pathlib import Path


def load_script_module(path):
    spec = importlib.util.spec_from_file_location(Path(path).stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_daily_generator_writes_manifest_and_latest_run_pointer(tmp_path):
    generator = load_script_module(Path(__file__).resolve().parents[1] / "scripts" / "generate_daily_briefing.py")
    run_id = "2026-05-31T0630Z"
    day_dir = tmp_path / "2026-05-31"
    run_dir = day_dir / "runs" / run_id
    run_dir.mkdir(parents=True)

    generator.write_manifest(run_dir, "2026-05-31", run_id, ["palma_ibiza"], "medium")
    generator.write_latest_run(day_dir, "2026-05-31", run_id, ["palma_ibiza"], "medium")

    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    latest = json.loads((day_dir / "latest_run.json").read_text(encoding="utf-8"))

    assert manifest["run_date"] == "2026-05-31"
    assert manifest["run_id"] == run_id
    assert latest["run_id"] == run_id
    assert latest["path"] == f"runs/{run_id}"


def test_daily_generator_writes_validation_manifest_pointer(tmp_path):
    generator = load_script_module(Path(__file__).resolve().parents[1] / "scripts" / "generate_daily_briefing.py")
    run_id = "2026-05-31T0630Z"
    day_dir = tmp_path / "2026-05-31"
    run_dir = day_dir / "runs" / run_id
    run_dir.mkdir(parents=True)
    validation_summary = {
        "observation_rows": 3,
        "forecast_rows": 120,
        "matched_rows": 2,
        "matched_variables": {"wave_height": 2},
    }
    validation_entry = generator.validation_manifest_entry(validation_summary)

    generator.write_manifest(
        run_dir,
        "2026-05-31",
        run_id,
        ["palma_ibiza"],
        "medium",
        validation=validation_entry,
    )
    generator.write_latest_run(
        day_dir,
        "2026-05-31",
        run_id,
        ["palma_ibiza"],
        "medium",
        validation=validation_entry,
    )

    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    latest = json.loads((day_dir / "latest_run.json").read_text(encoding="utf-8"))

    assert manifest["validation"]["path"] == "validation/validation_summary.json"
    assert manifest["validation"]["matched_rows"] == 2
    assert latest["validation"]["forecast_index_path"] == "validation/forecast_index.jsonl"


def test_web_demo_exporter_uses_latest_run_folder(tmp_path):
    exporter = load_script_module(Path(__file__).resolve().parents[1] / "scripts" / "export_web_demo_bundle.py")
    run_id = "2026-05-31T0630Z"
    run_dir = tmp_path / "outputs" / "2026-05-31" / "runs" / run_id
    route_dir = run_dir / "palma_ibiza"
    route_dir.mkdir(parents=True)
    (tmp_path / "outputs" / "2026-05-31" / "latest_run.json").write_text(
        json.dumps({"run_id": run_id, "path": f"runs/{run_id}"}),
        encoding="utf-8",
    )
    (run_dir / "run_manifest.json").write_text(
        json.dumps({"run_date": "2026-05-31", "run_id": run_id, "routes": ["palma_ibiza"]}),
        encoding="utf-8",
    )
    for name in exporter.ROUTE_ARTIFACTS:
        (route_dir / name).write_text("demo", encoding="utf-8")

    result = exporter.export_web_demo_bundle(
        tmp_path / "outputs",
        tmp_path / "web-demo",
        featured_route="palma_ibiza",
    )

    manifest = json.loads((tmp_path / "web-demo" / "demo_manifest.json").read_text(encoding="utf-8"))
    assert result.run_date == "2026-05-31"
    assert manifest["run_id"] == run_id
    assert (tmp_path / "web-demo" / "latest.json").exists()


def test_daily_generator_requests_all_registered_leaflet_overlay_variables(tmp_path, monkeypatch):
    generator = load_script_module(Path(__file__).resolve().parents[1] / "scripts" / "generate_daily_briefing.py")
    requested = {}

    class OverlayGenerator:
        VARIABLES = {
            "wave_height": {},
            "current_speed": {},
            "swell_1_height": {},
            "swell_1_direction": {},
            "swell_2_height": {},
            "swell_2_direction": {},
            "wind_wave_height": {},
            "wind_wave_direction": {},
        }

        @staticmethod
        def generate_leaflet_overlays(waves_path, currents_path, run_dir, variables):
            requested["variables"] = variables
            return {}

    monkeypatch.setattr(generator, "load_leaflet_overlay_generator", lambda: OverlayGenerator)

    generator.maybe_generate_leaflet_overlays(
        tmp_path / "run",
        tmp_path / "waves.nc",
        tmp_path / "currents.nc",
    )

    assert requested["variables"] == sorted(OverlayGenerator.VARIABLES)


def test_daily_generator_atmospheric_context_is_disabled_by_default(monkeypatch):
    generator = load_script_module(Path(__file__).resolve().parents[1] / "scripts" / "generate_daily_briefing.py")
    monkeypatch.delenv("PREDSEA_ENABLE_ATMOSPHERIC_INGESTION", raising=False)

    context = generator.fetch_atmospheric_context(None, Path("/tmp/predsea-run"))

    assert context["enabled"] is False
    assert context["wind_lineage"]["status"] == "not_configured"


def test_daily_generator_snapshot_lineage_includes_wind_ocean_and_ground_truth():
    generator = load_script_module(Path(__file__).resolve().parents[1] / "scripts" / "generate_daily_briefing.py")
    snapshot = {}
    source = {"id": "copernicus", "label": "Copernicus Marine Mediterranean forecast"}
    atmospheric_context = {
        "wind_lineage": {
            "source": "ecmwf_open_data",
            "resolution_km": 9.0,
            "status": "active",
            "tier": 3,
        }
    }
    observations = {"canal_de_ibiza": {"wave_height_m": 0.8}}

    generator.annotate_snapshot_with_lineage(snapshot, source, atmospheric_context, observations)

    assert snapshot["data_lineage"] == {
        "wind_forecast": {
            "source": "ecmwf_open_data",
            "resolution_km": 9.0,
            "status": "active",
            "tier": 3,
        },
        "ocean_forecast": {
            "source": "copernicus_med",
            "resolution_km": 4.0,
            "status": "active",
        },
        "ground_truth_validation": {
            "source": "socib_observations",
            "status": "matched_successfully",
            "station_count": 1,
        },
    }


def test_daily_generator_fetches_atmospheric_context_when_enabled(monkeypatch, tmp_path):
    generator = load_script_module(Path(__file__).resolve().parents[1] / "scripts" / "generate_daily_briefing.py")
    monkeypatch.setenv("PREDSEA_ENABLE_ATMOSPHERIC_INGESTION", "1")

    class IngestAtmosphere:
        @staticmethod
        def run_atmospheric_ingestion(output_dir, dry_run=False):
            return {
                "wind_result": {"available": True, "source": "meteo_france_arome"},
                "wind_lineage": {
                    "source": "meteo_france_arome",
                    "resolution_km": 1.3,
                    "status": "active",
                    "tier": 1,
                },
                "fetchers_configured": ["meteo_france_arome", "ecmwf_open_data"],
            }

    context = generator.fetch_atmospheric_context(
        type("Modules", (), {"ingest_atmosphere": IngestAtmosphere}),
        tmp_path / "run",
    )

    assert context["enabled"] is True
    assert context["wind_result"]["source"] == "meteo_france_arome"
    assert context["wind_lineage"]["resolution_km"] == 1.3
