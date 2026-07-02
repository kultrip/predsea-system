import importlib.util
from pathlib import Path

import numpy as np
import xarray as xr


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "generate_ocean_conditions_map.py"


def load_map_script():
    spec = importlib.util.spec_from_file_location("generate_ocean_conditions_map", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_select_time_index_accepts_hour_or_iso_fragment():
    module = load_map_script()
    dataset = xr.Dataset(coords={"time": np.array(["2026-05-15T06:00:00", "2026-05-15T12:00:00"], dtype="datetime64[ns]")})

    assert module.select_time_index(dataset, "12:00") == 1
    assert module.select_time_index(dataset, "2026-05-15T06:00") == 0
    assert module.select_time_index(dataset, "18:00") == 0


def test_infer_extent_uses_wave_grid_with_padding():
    module = load_map_script()
    wave = xr.DataArray(
        np.zeros((2, 3)),
        coords={"latitude": [39.0, 40.0], "longitude": [1.0, 2.0, 3.0]},
        dims=("latitude", "longitude"),
    )

    assert module.infer_extent(wave, padding_degrees=0.1) == [0.9, 3.1, 38.9, 40.1]


def test_quiver_steps_are_thinned_for_readable_map():
    module = load_map_script()

    assert module.quiver_steps(85, 48, "normal") == (6, 4)
    assert module.quiver_steps(85, 48, "sparse") == (8, 6)
    assert module.quiver_steps(85, 48, "dense") == (3, 3)


def test_cli_defaults_to_black_current_arrows():
    module = load_map_script()

    assert module.parse_args(["--waves", "waves.nc", "--output", "map.png"]).arrow_color == "black"


def test_cli_accepts_scalar_and_vector_variables():
    module = load_map_script()
    args = module.parse_args([
        "--waves", "waves.nc",
        "--output", "map.png",
        "--scalar-var", "VHM0_SW1",
        "--vector-var", "wave_dir",
        "--wind", "wind.nc",
    ])
    assert args.scalar_var == "VHM0_SW1"
    assert args.vector_var == "wave_dir"
    assert args.wind == "wind.nc"

