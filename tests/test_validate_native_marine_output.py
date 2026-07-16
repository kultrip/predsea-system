import numpy as np
import xarray as xr

from scripts.validate_native_marine_output import validate_dataset


def _swan_dataset():
    return xr.Dataset(
        data_vars={
            "hs": (("time", "y", "x"), np.ones((7, 2, 2))),
            "tps": (("time", "y", "x"), np.full((7, 2, 2), 7.0)),
            "dir": (("time", "y", "x"), np.full((7, 2, 2), 225.0)),
            "latitude": (("y", "x"), [[38.0, 38.0], [41.0, 41.0]]),
            "longitude": (("y", "x"), [[1.0, 5.0], [1.0, 5.0]]),
        },
        coords={"time": np.arange(7)},
    )


def test_swan_validation_passes_complete_physical_product():
    report = validate_dataset(
        _swan_dataset(),
        model="swan",
        expected_timestamps=7,
        expected_bbox=(1.0, 38.0, 5.0, 41.0),
    )
    assert report["status"] == "passed"
    assert report["timestamp_count"] == 7
    assert report["variables"]["hs"]["finite_fraction"] == 1.0


def test_swan_validation_rejects_missing_timestamp_and_implausible_wave():
    dataset = _swan_dataset().isel(time=slice(0, 6)).copy()
    dataset["hs"][0, 0, 0] = 30.0
    report = validate_dataset(dataset, model="swan", expected_timestamps=7)
    assert report["status"] == "failed"
    assert any("expected 7 timestamps" in error for error in report["errors"])
    assert any("hs range" in error for error in report["errors"])


def test_croco_validation_rejects_missing_required_fields():
    dataset = xr.Dataset(
        data_vars={
            "zeta": (("ocean_time", "y", "x"), np.zeros((2, 2, 2))),
            "lat_rho": (("y", "x"), [[38.0, 38.0], [41.0, 41.0]]),
            "lon_rho": (("y", "x"), [[1.0, 5.0], [1.0, 5.0]]),
        },
        coords={"ocean_time": np.arange(2)},
    )
    report = validate_dataset(dataset, model="croco", expected_timestamps=2)
    assert report["status"] == "failed"
    assert "missing required variable temp" in report["errors"]
    assert "missing required variable salt" in report["errors"]
