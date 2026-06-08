"""Tests for Puertos del Estado observation fetcher."""

import pytest

import fetch_puertos_estado


def test_balearic_stations_configured():
    stations = fetch_puertos_estado.BALEARIC_STATIONS
    assert "mahon" in stations
    assert "dragonera" in stations
    assert stations["mahon"]["network"] == "REDEXT"
    assert stations["dragonera"]["network"] == "REDCOS"


def test_normalize_observation_handles_wave_height():
    raw = {"Hm0": "1.25", "Tp": "6.5", "DirM": "270.0", "time": "2026-06-08T10:00:00Z"}
    obs = fetch_puertos_estado._normalize_observation(raw, "2136", "Mahón")
    assert obs["available"] is True
    assert obs["wave_height_m"] == 1.25
    assert obs["wave_period_s"] == 6.5
    assert obs["wave_direction_deg"] == 270.0
    assert "2026-06-08 10:00 UTC" in obs["timestamp_utc"]


def test_normalize_observation_handles_missing_data():
    raw = {}
    obs = fetch_puertos_estado._normalize_observation(raw, "2136", "Mahón")
    assert obs["available"] is False


def test_normalize_observation_handles_none():
    obs = fetch_puertos_estado._normalize_observation(None, "2136", "Mahón")
    assert obs["available"] is False


def test_fetch_balearic_observations_dry_run():
    result = fetch_puertos_estado.fetch_balearic_observations(dry_run=True)
    assert "observations" in result
    for key, obs in result["observations"].items():
        assert obs["source"] == "puertos_del_estado"
        assert obs["dry_run"] is True


def test_lineage_for_dry_run_observations():
    result = fetch_puertos_estado.fetch_balearic_observations(dry_run=True)
    lineage = fetch_puertos_estado.lineage_for_puertos_observations(result)
    # Dry run has wave_height_m=None, so status should be unavailable
    assert lineage["source"] == "puertos_del_estado_redext"
    assert lineage["status"] == "unavailable"


def test_safe_float_handles_various_inputs():
    assert fetch_puertos_estado._safe_float("1.5") == 1.5
    assert fetch_puertos_estado._safe_float(None) is None
    assert fetch_puertos_estado._safe_float("invalid") is None
    assert fetch_puertos_estado._safe_float(float("nan")) is None
    assert fetch_puertos_estado._safe_float(0.0) == 0.0


def test_normalize_timestamp_formats():
    assert "2026-06-08 10:00 UTC" == fetch_puertos_estado._normalize_timestamp("2026-06-08T10:00:00Z")
    assert "2026-06-08 10:00 UTC" == fetch_puertos_estado._normalize_timestamp("2026-06-08 10:00:00")
    assert fetch_puertos_estado._normalize_timestamp(None) is None
