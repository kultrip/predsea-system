import numpy as np
import pytest
import xarray as xr

from socib_client import SocibDataError, get_ocean_data


def make_dataset(include_wave=True):
    times = np.array(
        [
            "2026-05-04T00:00:00",
            "2026-05-04T12:00:00",
            "2026-05-05T00:00:00",
            "2026-05-05T12:00:00",
        ],
        dtype="datetime64[ns]",
    )
    lat = np.array([39.0, 39.5])
    lon = np.array([2.0, 2.5])
    shape = (len(times), len(lat), len(lon))
    variables = {
        "zeta": (("time", "lat_rho", "lon_rho"), np.arange(np.prod(shape)).reshape(shape)),
        "u": (("time", "lat_rho", "lon_rho"), np.ones(shape) * 0.2),
        "v": (("time", "lat_rho", "lon_rho"), np.ones(shape) * -0.1),
    }
    if include_wave:
        variables["hs"] = (("time", "lat_rho", "lon_rho"), np.ones(shape) * 0.8)
    return xr.Dataset(
        variables,
        coords={"time": times, "lat_rho": lat, "lon_rho": lon},
    )


def test_get_ocean_data_returns_nearest_24_hour_point_slice(monkeypatch):
    dataset = make_dataset()
    monkeypatch.setattr("xarray.open_dataset", lambda *args, **kwargs: dataset)

    result = get_ocean_data(39.45, 2.45, "2026-05-04T00:00:00")

    assert result["source"] == "https://thredds.socib.es/thredds/dodsC/wmop/forecast/latest"
    assert result["location"]["requested_lat"] == 39.45
    assert result["location"]["requested_lon"] == 2.45
    assert result["location"]["matched_lat"] == 39.5
    assert result["location"]["matched_lon"] == 2.5
    assert result["time_window"] == {
        "start": "2026-05-04T00:00:00",
        "end": "2026-05-05T00:00:00",
    }
    assert [row["time"] for row in result["data"]] == [
        "2026-05-04T00:00:00",
        "2026-05-04T12:00:00",
        "2026-05-05T00:00:00",
    ]
    assert result["data"][0]["sea_surface_height"] == 3.0
    assert result["data"][0]["u_current"] == 0.2
    assert result["data"][0]["v_current"] == -0.1
    assert result["data"][0]["significant_wave_height"] == 0.8


def test_get_ocean_data_uses_first_dataset_time_when_timeframe_is_none(monkeypatch):
    dataset = make_dataset()
    monkeypatch.setattr("xarray.open_dataset", lambda *args, **kwargs: dataset)

    result = get_ocean_data(39.45, 2.45, None)

    assert result["time_window"] == {
        "start": "2026-05-04T00:00:00",
        "end": "2026-05-05T00:00:00",
    }


def test_get_ocean_data_raises_clear_error_for_missing_required_variable(monkeypatch):
    dataset = make_dataset(include_wave=False)
    monkeypatch.setattr("xarray.open_dataset", lambda *args, **kwargs: dataset)

    with pytest.raises(SocibDataError, match="significant_wave_height"):
        get_ocean_data(39.45, 2.45, "2026-05-04T00:00:00")
