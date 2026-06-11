"""Tests for observation ingestion orchestrator."""

import os

import ingest_observations


def test_fetch_all_observations_includes_socib(monkeypatch):
    monkeypatch.delenv("PREDSEA_ENABLE_PUERTOS_OBSERVATIONS", raising=False)
    result = ingest_observations.fetch_all_observations(include_puertos=False)
    # SOCIB may or may not succeed depending on network, but the function should not crash
    assert "observations" in result
    assert "ground_truth_lineage" in result


def test_puertos_disabled_by_default(monkeypatch):
    monkeypatch.delenv("PREDSEA_ENABLE_PUERTOS_OBSERVATIONS", raising=False)
    assert not ingest_observations._puertos_enabled()


def test_puertos_enabled_by_env_var(monkeypatch):
    monkeypatch.setenv("PREDSEA_ENABLE_PUERTOS_OBSERVATIONS", "1")
    assert ingest_observations._puertos_enabled()


def test_portus_enabled_by_default(monkeypatch):
    monkeypatch.delenv("PREDSEA_ENABLE_PORTUS_OBSERVATIONS", raising=False)
    assert ingest_observations._portus_enabled()


def test_ground_truth_lineage_with_both_sources():
    observations = {"canal_de_ibiza": {}, "puertos_mahon": {}}
    lineage = ingest_observations._build_ground_truth_lineage(
        observations,
        ["socib_observations", "puertos_del_estado"],
        {},
    )
    assert lineage["source"] == "socib_and_puertos_del_estado"
    assert lineage["status"] == "matched_successfully"
    assert lineage["station_count"] == 2


def test_ground_truth_lineage_socib_only():
    lineage = ingest_observations._build_ground_truth_lineage(
        {"canal_de_ibiza": {}},
        ["socib_observations"],
        {},
    )
    assert lineage["source"] == "socib_observations"
    assert lineage["status"] == "matched_successfully"


def test_ground_truth_lineage_empty():
    lineage = ingest_observations._build_ground_truth_lineage({}, [], {})
    assert lineage["source"] is None
    assert lineage["status"] == "unavailable"
