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
