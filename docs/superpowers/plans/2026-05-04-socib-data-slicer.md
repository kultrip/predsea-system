# SOCIB Data Slicer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `get_ocean_data(lat, lon, timeframe)` for remote SOCIB WMOP point and 24-hour slicing.

**Architecture:** A single `socib_client.py` module owns dataset access, variable alias resolution, coordinate selection, time-window selection, and dictionary serialization. Tests monkeypatch xarray dataset opening and use small in-memory datasets to prove the function requests a narrow slice before loading values.

**Tech Stack:** Python, xarray, numpy, pandas-style datetime handling through xarray/numpy, pytest.

---

## File Structure

- `socib_client.py`: public `get_ocean_data` function, `SocibDataError`, constants, and small helper functions.
- `tests/test_socib_client.py`: in-memory dataset tests for time slicing, nearest coordinate selection, alias mapping, and missing-variable errors.
- `requirements.txt`: runtime and test dependencies for the first Python environment.

### Task 1: Test The Public Slicer Contract

**Files:**
- Create: `tests/test_socib_client.py`

- [ ] **Step 1: Write failing tests**

```python
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


def test_get_ocean_data_raises_clear_error_for_missing_required_variable(monkeypatch):
    dataset = make_dataset(include_wave=False)
    monkeypatch.setattr("xarray.open_dataset", lambda *args, **kwargs: dataset)

    with pytest.raises(SocibDataError, match="significant_wave_height"):
        get_ocean_data(39.45, 2.45, "2026-05-04T00:00:00")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_socib_client.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'socib_client'`.

### Task 2: Implement The Data Slicer

**Files:**
- Create: `socib_client.py`
- Create: `requirements.txt`

- [ ] **Step 1: Write minimal implementation**

Implement:

- `SOCIB_WMOP_OPENDAP_URL`
- `SocibDataError`
- `get_ocean_data(lat, lon, timeframe)`
- helper functions for timeframe parsing, coordinate discovery, variable alias resolution, point selection, and JSON-safe scalar conversion

- [ ] **Step 2: Run tests to verify pass**

Run: `pytest tests/test_socib_client.py -v`

Expected: PASS for both tests.

### Task 3: Manual Smoke Guidance

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Document setup and smoke usage**

Add a short README section with:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -v
```

and:

```python
from socib_client import get_ocean_data

print(get_ocean_data(39.57, 2.65, None))
```

- [ ] **Step 2: Run full test suite**

Run: `pytest -v`

Expected: PASS.
