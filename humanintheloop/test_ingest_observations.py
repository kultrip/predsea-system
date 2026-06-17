"""Tests for observation ingestion orchestrator."""

import sys
import types

import ingest_observations


def test_fetch_all_observations_returns_puertos_first_bundle(monkeypatch):
    monkeypatch.delenv("PREDSEA_ENABLE_PUERTOS_OBSERVATIONS", raising=False)
    monkeypatch.delenv("PREDSEA_ENABLE_PORTUS_OBSERVATIONS", raising=False)

    puertos_result = {
        "observations": {"puertos_mallorca": {"wave_height_m": 0.8}},
        "measurements": {"puertos_mallorca": [{"raw_key": "wave_height_m", "value": 0.8}]},
        "errors": {},
        "catalog_stations": [{"station_id": "puertos_mallorca"}],
    }
    portus_result = {
        "observations": {"portus_ibiza": {"wave_height_m": 0.4}},
        "predictions": {},
        "errors": {},
    }

    monkeypatch.setitem(
        sys.modules,
        "fetch_puertos_estado",
        types.SimpleNamespace(fetch_balearic_observations=lambda dry_run=False: puertos_result),
    )
    monkeypatch.setattr(
        ingest_observations.fetch_portus,
        "fetch_portus_bundle",
        lambda dry_run=False: portus_result,
    )

    result = ingest_observations.fetch_all_observations(include_puertos=True, include_portus=True)
    assert "observations" in result
    assert result["ground_truth_lineage"]["source"] == "puertos_del_estado_and_puertos_portus"
    assert "puertos_puertos_mallorca" in result["observations"]
    assert "portus_ibiza" in result["observations"]
    assert "socib" not in result["errors"]


def test_puertos_enabled_by_default(monkeypatch):
    monkeypatch.delenv("PREDSEA_ENABLE_PUERTOS_OBSERVATIONS", raising=False)
    assert ingest_observations._puertos_enabled()


def test_puertos_enabled_by_env_var(monkeypatch):
    monkeypatch.setenv("PREDSEA_ENABLE_PUERTOS_OBSERVATIONS", "1")
    assert ingest_observations._puertos_enabled()


def test_puertos_can_be_disabled_explicitly(monkeypatch):
    monkeypatch.setenv("PREDSEA_ENABLE_PUERTOS_OBSERVATIONS", "0")
    assert not ingest_observations._puertos_enabled()


def test_portus_enabled_by_default(monkeypatch):
    monkeypatch.delenv("PREDSEA_ENABLE_PORTUS_OBSERVATIONS", raising=False)
    assert ingest_observations._portus_enabled()


def test_ground_truth_lineage_with_both_sources():
    observations = {"canal_de_ibiza": {}, "puertos_mahon": {}}
    lineage = ingest_observations._build_ground_truth_lineage(
        observations,
        ["puertos_del_estado", "puertos_portus"],
        {},
    )
    assert lineage["source"] == "puertos_del_estado_and_puertos_portus"
    assert lineage["status"] == "matched_successfully"
    assert lineage["station_count"] == 2


def test_ground_truth_lineage_puertos_only():
    lineage = ingest_observations._build_ground_truth_lineage(
        {"canal_de_ibiza": {}},
        ["puertos_del_estado"],
        {},
    )
    assert lineage["source"] == "puertos_del_estado"
    assert lineage["status"] == "matched_successfully"


def test_ground_truth_lineage_empty():
    lineage = ingest_observations._build_ground_truth_lineage({}, [], {})
    assert lineage["source"] is None
    assert lineage["status"] == "unavailable"
