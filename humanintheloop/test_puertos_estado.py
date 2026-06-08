"""Tests for Puertos del Estado OPeNDAP fetcher."""

import pytest

import fetch_puertos_estado as fp


def test_tide_gauge_stations_configured():
    stations = fp.TIDE_GAUGE_STATIONS
    assert "mahon" in stations
    assert "ibiza" in stations
    assert "alcudia" in stations
    assert "mallorca" in stations
    assert "formentera" in stations


def test_fetch_balearic_wave_forecast_dry_run():
    result = fp.fetch_balearic_wave_forecast(dry_run=True)
    assert result["available"] is True
    assert result["source"] == "puertos_del_estado_wave"
    assert result["dry_run"] is True


def test_fetch_balearic_observations_dry_run():
    result = fp.fetch_balearic_observations(dry_run=True)
    assert "observations" in result
    for key, obs in result["observations"].items():
        assert obs["source"] == "puertos_del_estado"
        assert obs["dry_run"] is True


def test_lineage_for_dry_run_observations():
    result = fp.fetch_balearic_observations(dry_run=True)
    lineage = fp.lineage_for_puertos_observations(result)
    assert lineage["source"] == "puertos_del_estado_redext"
    assert lineage["status"] == "unavailable"


def test_discover_latest_wave_forecast_real():
    """Integration test — requires network access to opendap.puertos.es."""
    try:
        url = fp._discover_latest_wave_forecast()
        assert "opendap.puertos.es" in url
        assert "wave_regional_bal" in url
        assert url.endswith("-FC.nc")
    except Exception:
        pytest.skip("Puertos del Estado THREDDS not reachable")


def test_fetch_real_wave_forecast():
    """Integration test — requires network access to opendap.puertos.es."""
    try:
        result = fp.fetch_balearic_wave_forecast()
        assert result["available"] is True
        assert "VHM0" in result["variables"]
        assert result["grid_shape"]["time"] > 0
        assert result["grid_shape"]["latitude"] > 0
        assert result["grid_shape"]["longitude"] > 0
        result["dataset"].close()
    except Exception:
        pytest.skip("Puertos del Estado THREDDS not reachable")


def test_sample_wave_at_route_midpoint():
    """Integration test — sample wave at Palma-Ibiza route midpoint."""
    try:
        result = fp.fetch_balearic_wave_forecast()
        ds = result["dataset"]
        sample = fp.sample_wave_at_point(ds, 39.19, 2.04, "VHM0")
        assert len(sample["values"]) > 0
        assert all(isinstance(v, float) for v in sample["values"])
        ds.close()
    except Exception:
        pytest.skip("Puertos del Estado THREDDS not reachable")
