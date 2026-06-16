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
    assert lineage["source"] == "puertos_del_estado"
    assert lineage["status"] == "unavailable"


def test_station_key_from_label_strips_accents_and_parentheses():
    from predsea.connectors.puertos_del_estado.catalog import station_key_from_label

    assert station_key_from_label("Mahón (Menorca)") == "mahon"
    assert station_key_from_label("Port de Sóller") == "port_de_soller"


def test_parse_station_dataset_uses_netcdf_time_coordinate():
    import pandas as pd
    import xarray as xr

    from predsea.connectors.puertos_del_estado.parser import parse_station_dataset

    ds = xr.Dataset(
        {
            "SLEV": ("TIME", [0.1, 0.2, 0.08]),
            "DEPH": ("TIME", [3.0, 3.0, 3.0]),
            "TIME_QC": ("TIME", [0, 0, 0]),
        },
        coords={
            "TIME": pd.to_datetime([
                "2026-06-13T00:00:00Z",
                "2026-06-13T01:00:00Z",
                "2026-06-13T02:00:00Z",
            ], utc=True),
        },
    )
    station = {
        "station_id": "puertos_alcudia",
        "station_name": "Alcudia",
        "catalog_id": "tidegauge_alcu",
        "catalog_url": "https://opendap.puertos.es/thredds/catalog/tidegauge_alcu/catalog.html",
        "network": "redmar",
    }

    records = parse_station_dataset(ds, station, dataset_url="https://example.test/dataset.nc4")

    assert {record["raw_key"] for record in records} == {"sea_level_m", "depth_m"}
    latest = next(record for record in records if record["raw_key"] == "sea_level_m")
    assert latest["sample_time_utc"] == "2026-06-13T02:00:00Z"
    assert latest["observed_at_utc"] == "2026-06-13T02:00:00Z"
    assert latest["source_field"] == "SLEV"
    assert latest["source_label"] == "REDMAR"


def test_latest_value_from_dataarray_skips_future_coordinate():
    import pandas as pd
    import xarray as xr

    from predsea.connectors.puertos_del_estado.common import latest_value_from_dataarray

    ds = xr.Dataset(
        {
            "VHM0": ("time", [0.2, 0.4]),
        },
        coords={
            "time": pd.to_datetime(
                ["2026-06-15T23:59:59Z", "2026-06-16T23:59:59Z"],
                utc=True,
            ),
        },
    )

    value, sample_time = latest_value_from_dataarray(ds["VHM0"], now_utc="2026-06-16T00:00:00Z")
    assert value == 0.2
    assert sample_time == "2026-06-15T23:59:59Z"


def test_redext_parser_uses_station_coordinates_for_grid_sampling():
    import pandas as pd
    import xarray as xr

    from predsea.connectors.puertos_del_estado.redext_parser import parse_station_dataset

    ds = xr.Dataset(
        {
            "VHM0": (("time", "y", "x"), [[[0.2, 0.3], [0.4, 0.5]], [[0.6, 0.7], [0.8, 0.9]]]),
        },
        coords={
            "time": pd.to_datetime(["2026-06-13T00:00:00Z", "2026-06-13T01:00:00Z"], utc=True),
            "latitude": (("y", "x"), [[38.9, 38.9], [39.1, 39.1]]),
            "longitude": (("y", "x"), [[1.4, 1.6], [1.4, 1.6]]),
        },
    )
    station = {
        "station_id": "puertos_ibiza",
        "station_name": "Ibiza",
        "catalog_id": "wave_local_a12a",
        "catalog_url": "https://opendap.puertos.es/thredds/catalog/wave_local_a12a/catalog.xml",
        "latitude": 38.9,
        "longitude": 1.4,
        "network": "redext",
    }

    records = parse_station_dataset(ds, station, dataset_url="https://example.test/dataset.nc4")
    assert len(records) == 1
    record = records[0]
    assert record["raw_key"] == "wave_height_m"
    assert record["value"] == 0.6
    assert record["sample_time_utc"] == "2026-06-13T01:00:00Z"
    assert record["observed_at_utc"] == "2026-06-13T01:00:00Z"
    assert record["source_label"] == "REDEXT"


def test_redcos_parser_marks_coastal_network():
    import pandas as pd
    import xarray as xr

    from predsea.connectors.puertos_del_estado.redcos_parser import parse_station_dataset

    ds = xr.Dataset(
        {
            "VHM0": (("time", "y", "x"), [[[1.0, 1.1], [1.2, 1.3]]]),
            "VTPK": (("time", "y", "x"), [[[8.0, 8.1], [8.2, 8.3]]]),
        },
        coords={
            "time": pd.to_datetime(["2026-06-13T04:00:00Z"], utc=True),
            "latitude": (("y", "x"), [[39.3, 39.3], [39.4, 39.4]]),
            "longitude": (("y", "x"), [[2.6, 2.7], [2.6, 2.7]]),
        },
    )
    station = {
        "station_id": "puertos_palma",
        "station_name": "Palma",
        "catalog_id": "wave_coast_s11",
        "catalog_url": "https://opendap.puertos.es/thredds/catalog/wave_coast_s11/catalog.xml",
        "latitude": 39.3,
        "longitude": 2.6,
        "network": "redcos",
    }

    records = parse_station_dataset(ds, station, dataset_url="https://example.test/dataset.nc4")
    assert {record["raw_key"] for record in records} == {"wave_height_m", "wave_period_peak_s"}
    assert all(record["source_label"] == "REDCOS" for record in records)


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
