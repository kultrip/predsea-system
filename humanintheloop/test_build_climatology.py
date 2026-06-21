import importlib.util
from pathlib import Path


def load_script_module(path):
    spec = importlib.util.spec_from_file_location(Path(path).stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_climatology_defaults_to_eu_location(monkeypatch):
    script = load_script_module(Path(__file__).resolve().parents[1] / "scripts" / "build_climatology.py")
    captured = {}

    monkeypatch.delenv("PREDSEA_BIGQUERY_LOCATION", raising=False)
    monkeypatch.delenv("BQ_LOCATION", raising=False)

    def fake_query_bigquery(sql, *, project_id, location=None):
        captured["location"] = location
        captured["project_id"] = project_id
        return []

    monkeypatch.setattr(script, "query_bigquery", fake_query_bigquery)

    assert script.main(["--project", "predsea-api", "--dry-run"]) == 0
    assert captured["project_id"] == "predsea-api"
    assert captured["location"] == "EU"


def test_build_climatology_query_uses_evidence_source_columns():
    script = load_script_module(Path(__file__).resolve().parents[1] / "scripts" / "build_climatology.py")

    query = script.build_climatology_query(
        project="predsea-api",
        dataset="predsea_validation",
        evidence_table="evidence_rows",
        start_date="2019-01-01",
        end_date="2026-01-01",
    )

    assert "ANY_VALUE(source_system) AS provider" in query
    assert "ANY_VALUE(source_label) AS network" in query
    assert "ANY_VALUE(provider) AS provider" not in query
