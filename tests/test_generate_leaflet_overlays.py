import importlib.util
import json
from pathlib import Path

import numpy as np
import xarray as xr
from PIL import Image


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "generate_leaflet_overlays.py"


def load_overlay_script():
    spec = importlib.util.spec_from_file_location("generate_leaflet_overlays", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_test_forecasts(tmp_path):
    times = np.array(["2026-05-31T12:00:00", "2026-05-31T14:00:00"], dtype="datetime64[ns]")
    lats = [38.5, 39.5, 40.5]
    lons = [1.0, 2.0, 3.0, 4.5]
    waves = xr.Dataset(
        {
            "VHM0": (
                ("time", "latitude", "longitude"),
                np.array(
                    [
                        np.full((3, 4), 0.5),
                        np.full((3, 4), 1.2),
                    ]
                ),
            )
        },
        coords={"time": times, "latitude": lats, "longitude": lons},
    )
    currents = xr.Dataset(
        {
            "uo": (("time", "latitude", "longitude"), np.full((2, 3, 4), 0.2)),
            "vo": (("time", "latitude", "longitude"), np.full((2, 3, 4), 0.1)),
        },
        coords={"time": times, "latitude": lats, "longitude": lons},
    )
    waves_path = tmp_path / "waves.nc"
    currents_path = tmp_path / "currents.nc"
    waves.to_netcdf(waves_path)
    currents.to_netcdf(currents_path)
    return waves_path, currents_path


def test_generate_leaflet_overlays_writes_index_and_png(tmp_path):
    module = load_overlay_script()
    waves_path, currents_path = write_test_forecasts(tmp_path)

    module.generate_leaflet_overlays(
        waves_path,
        currents_path,
        tmp_path / "run",
        variables=["wave_height"],
    )

    index_path = tmp_path / "run" / "maps" / "wave_height" / "index.json"
    payload = json.loads(index_path.read_text(encoding="utf-8"))

    assert payload["variable"] == "wave_height"
    assert payload["units"] == "m"
    assert payload["bounds"] if "bounds" in payload else True
    assert len(payload["overlays"]) == 2
    assert payload["overlays"][0]["bounds"] == [[38.5, 1.0], [40.5, 4.5]]
    image_path = index_path.parent / payload["overlays"][0]["filename"]
    assert image_path.exists()
    assert Image.open(image_path).mode == "RGBA"


def test_current_speed_overlay_uses_current_vector_magnitude(tmp_path):
    module = load_overlay_script()
    waves_path, currents_path = write_test_forecasts(tmp_path)

    module.generate_leaflet_overlays(
        waves_path,
        currents_path,
        tmp_path / "run",
        variables=["current_speed"],
    )

    payload = json.loads((tmp_path / "run" / "maps" / "current_speed" / "index.json").read_text())
    assert payload["variable"] == "current_speed"
    assert payload["units"] == "m/s"
    assert len(payload["overlays"]) == 2


def test_filename_for_is_stable_and_url_safe():
    module = load_overlay_script()

    assert (
        module.filename_for("wave_height", "2026-05-31T14:00:00Z")
        == "wave_height_20260531_140000Z.png"
    )
