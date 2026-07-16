from __future__ import annotations

import numpy as np
import xarray as xr

from scripts.prepare_croco_grid import build_grid, smooth_bathymetry


def test_smooth_bathymetry_enforces_rx0():
    depth = np.array([[10.0, 1000.0], [10.0, 1000.0]])
    wet = np.ones_like(depth, dtype=bool)
    smoothed, iterations, achieved = smooth_bathymetry(
        depth, wet, maximum_rx0=0.2
    )
    assert iterations > 0
    assert achieved <= 0.2 + 1e-12
    assert smoothed.min() > 10.0


def test_build_grid_creates_complete_croco_staggered_grid():
    longitude, latitude = np.meshgrid(
        np.array([1.0, 1.01, 1.02, 1.03]),
        np.array([38.0, 38.01, 38.02]),
    )
    bathymetry = xr.Dataset(
        {
            "bathy": (("y", "x"), [[0.0, 20.0, 30.0, 40.0]] * 3),
            "nav_lon": (("y", "x"), longitude),
            "nav_lat": (("y", "x"), latitude),
        }
    )

    grid, report = build_grid(bathymetry)

    assert grid.sizes["eta_rho"] == 3
    assert grid.sizes["xi_rho"] == 4
    assert grid.sizes["xi_u"] == 3
    assert grid.sizes["eta_v"] == 2
    assert set(
        (
            "h",
            "hraw",
            "mask_rho",
            "mask_u",
            "mask_v",
            "mask_psi",
            "pm",
            "pn",
            "angle",
            "f",
        )
    ) <= set(grid.variables)
    assert report["maximum_rx0"] <= 0.2 + 1e-12
    assert report["wet_cell_count"] == 9
    assert 0.0 <= report["changed_wet_cell_fraction"] <= 1.0
    assert report["maximum_wet_cell_deepening_m"] >= 0.0
