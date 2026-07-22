#!/usr/bin/env python3
"""
Prepare CROCO Initial (ini) and Climatology/Boundary (clm) conditions
from raw 3D Copernicus Marine (CMEMS) datasets.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import datetime as dt
import json
import multiprocessing
from pathlib import Path
import sys

import numpy as np
import xarray as xr
from scipy.interpolate import RegularGridInterpolator


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare CROCO initial and boundary/climatology files from CMEMS forcing."
    )
    parser.add_argument(
        "--grid",
        type=Path,
        default=Path("tmp/croco_grid_balearic_1km.nc"),
        help="Path to CROCO grid NetCDF file",
    )
    parser.add_argument(
        "--forcing-dir",
        type=Path,
        default=Path("tmp/forcing-croco-24h"),
        help="Path to raw CMEMS downloaded files",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("tmp/forcing-croco-24h"),
        help="Path to save croco_ini.nc and croco_clm.nc",
    )
    parser.add_argument(
        "--vertical-levels",
        type=int,
        default=30,
        help="Number of vertical sigma levels",
    )
    return parser.parse_args()


def fill_nans(data: np.ndarray) -> np.ndarray:
    """Propagate nearest non-nan values to avoid boundary interpolation issues."""
    if not np.isnan(data).any():
        return data
    filled = data.copy()
    nans = np.isnan(filled)
    if not nans.all():
        # Clean up 2D or 3D datasets along the lat-lon axes
        for i in range(filled.shape[0]):
            sub = filled[i]
            sub_nans = np.isnan(sub)
            if sub_nans.any() and not sub_nans.all():
                # Fill row-by-row
                mask = ~sub_nans
                for r in range(sub.shape[0]):
                    if sub_nans[r].any():
                        if mask[r].any():
                            sub[r, sub_nans[r]] = np.interp(
                                np.flatnonzero(sub_nans[r]),
                                np.flatnonzero(mask[r]),
                                sub[r, mask[r]]
                            )
    # Fill any remaining NaNs with the overall mean
    if np.isnan(filled).any():
        mean_val = np.nanmean(filled)
        if np.isnan(mean_val):
            mean_val = 0.0
        filled[np.isnan(filled)] = mean_val
    return filled


def interpolate_2d_timestep(t: int, var_data_t: np.ndarray, src_lat: np.ndarray, src_lon: np.ndarray, target_lat: np.ndarray, target_lon: np.ndarray) -> tuple[int, np.ndarray]:
    ssh_raw = fill_nans(var_data_t)
    interpolator = RegularGridInterpolator((src_lat, src_lon), ssh_raw, bounds_error=False, fill_value=None)
    return t, interpolator((target_lat, target_lon))


def interpolate_3d_timestep(t: int, var_data_t: np.ndarray, src_lat: np.ndarray, src_lon: np.ndarray, src_depth: np.ndarray, target_lat: np.ndarray, target_lon: np.ndarray, s_rho: np.ndarray, h: np.ndarray, N: int) -> tuple[int, np.ndarray]:
    nz_src = len(src_depth)
    ny_tgt, nx_tgt = target_lon.shape
    src_z = -src_depth[::-1]

    # Grid indexing coordinates
    grid_y, grid_x = np.meshgrid(np.arange(ny_tgt), np.arange(nx_tgt), indexing='ij')
    y_idx = np.broadcast_to(grid_y, (N, ny_tgt, nx_tgt))
    x_idx = np.broadcast_to(grid_x, (N, ny_tgt, nx_tgt))

    # 1. Horizontal interpolation for each source depth level
    horiz_staged = np.zeros((nz_src, ny_tgt, nx_tgt), dtype=np.float32)
    var_data_filled = fill_nans(var_data_t)
    for z in range(nz_src):
        interpolator = RegularGridInterpolator((src_lat, src_lon), var_data_filled[z], bounds_error=False, fill_value=None)
        horiz_staged[z] = interpolator((target_lat, target_lon))

    # 2. Vertical interpolation
    local_h = h[:ny_tgt, :nx_tgt]
    target_z = s_rho[:, np.newaxis, np.newaxis] * local_h[np.newaxis, :, :]
    target_z_clipped = np.clip(target_z, src_z[0], src_z[-1])

    idx = np.searchsorted(src_z, target_z_clipped.ravel())
    idx = np.clip(idx, 1, nz_src - 1)
    idx = idx.reshape(N, ny_tgt, nx_tgt)

    idx_low = idx - 1
    idx_high = idx
    z_low = src_z[idx_low]
    z_high = src_z[idx_high]

    dz = z_high - z_low
    dz = np.where(dz == 0.0, 1.0, dz)
    weight_high = (target_z_clipped - z_low) / dz
    weight_low = 1.0 - weight_high

    src_data_sorted = horiz_staged[::-1]
    val_low = src_data_sorted[idx_low, y_idx, x_idx]
    val_high = src_data_sorted[idx_high, y_idx, x_idx]

    return t, weight_low * val_low + weight_high * val_high


def croco_climatology_times(src_time: np.ndarray) -> dict[str, tuple[str, np.ndarray]]:
    """Return the explicit time axes required by CROCO climatology readers.

    This regional binary is compiled without ``USE_CALENDAR``. CROCO therefore
    expects elapsed model days, not CF-decoded datetimes, and it looks up four
    fixed variable names in the climatology file.
    """
    timestamps = np.asarray(src_time).astype("datetime64[ns]")
    if timestamps.ndim != 1 or timestamps.size < 2:
        raise ValueError("CROCO climatology requires at least two forcing timestamps")
    elapsed_days = (
        (timestamps - timestamps[0]) / np.timedelta64(1, "D")
    ).astype(np.float64)
    if not np.all(np.isfinite(elapsed_days)) or not np.all(np.diff(elapsed_days) > 0):
        raise ValueError("CROCO climatology timestamps must be finite and increasing")
    return {
        name: (name, elapsed_days.copy())
        for name in ("ssh_time", "uclm_time", "tclm_time", "sclm_time")
    }


def main() -> int:
    args = parse_args()
    print("=========================================================================")
    print("🌊 Starting CROCO Forcing Compiler")
    print(f"📂 Grid file: {args.grid}")
    print(f"📂 Forcing directory: {args.forcing_dir}")
    print(f"📂 Output directory: {args.output_dir}")
    print(f"📐 Vertical levels (N): {args.vertical_levels}")
    print("=========================================================================")

    # 1. Load the curvilinear grid
    if not args.grid.exists():
        print(f"❌ Error: Grid file not found: {args.grid}")
        return 1

    grid = xr.open_dataset(args.grid)
    lon_rho = grid["lon_rho"].values
    lat_rho = grid["lat_rho"].values
    lon_u = grid["lon_u"].values
    lat_u = grid["lat_u"].values
    lon_v = grid["lon_v"].values
    lat_v = grid["lat_v"].values
    h = grid["h"].values
    mask_rho = grid["mask_rho"].values

    eta_rho, xi_rho = lon_rho.shape
    eta_u, xi_u = lon_u.shape
    eta_v, xi_v = lon_v.shape
    N = args.vertical_levels

    # Define standard sigma coordinate stretching
    s_rho = np.linspace(-1.0 + 1.0 / (2 * N), 0.0 - 1.0 / (2 * N), N)

    # 2. Check input files
    forcing_files = {
        "currents": args.forcing_dir / "cmems_croco_currents_3d.nc",
        "temp": args.forcing_dir / "cmems_croco_temperature_3d.nc",
        "salinity": args.forcing_dir / "cmems_croco_salinity_3d.nc",
        "sea_level": args.forcing_dir / "cmems_croco_sea_level.nc",
    }

    for name, path in forcing_files.items():
        if not path.exists():
            print(f"❌ Error: Missing raw CMEMS file for {name}: {path}")
            return 1

    # 3. Load forcing datasets
    ds_cur = xr.open_dataset(forcing_files["currents"])
    ds_tem = xr.open_dataset(forcing_files["temp"])
    ds_sal = xr.open_dataset(forcing_files["salinity"])
    ds_ssh = xr.open_dataset(forcing_files["sea_level"])

    # Extract axes from CMEMS
    src_lon = ds_ssh["longitude"].values
    src_lat = ds_ssh["latitude"].values
    src_time = ds_ssh["time"].values
    src_depth = ds_cur["depth"].values

    nt = len(src_time)
    print(f"👉 Loaded {nt} hourly forcing timesteps.")
    print(f"👉 CMEMS bounds: Lon [{src_lon.min():.3f}, {src_lon.max():.3f}], Lat [{src_lat.min():.3f}, {src_lat.max():.3f}]")
    print(f"👉 CMEMS depth layers: {len(src_depth)} layers down to {src_depth.max():.1f}m")

    # Set up process pool based on available CPU count (capped at 32)
    max_workers = min(multiprocessing.cpu_count(), 32)
    print(f"🚀 Initializing parallel forcing compiler with {max_workers} processes...")

    # Interpolate SSH (zeta)
    print("🔄 Interpolating sea level (zeta) in parallel...")
    zeta_clm = np.zeros((nt, eta_rho, xi_rho), dtype=np.float32)
    zos_values = ds_ssh["zos"].values

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(
                interpolate_2d_timestep,
                t,
                zos_values[t],
                src_lat,
                src_lon,
                lat_rho,
                lon_rho
            )
            for t in range(nt)
        ]
        for fut in futures:
            t, result = fut.result()
            zeta_clm[t] = result

    # 3D interpolation helper (parallelized with ProcessPoolExecutor)
    def interpolate_3d(ds: xr.Dataset, var_name: str, target_lon: np.ndarray, target_lat: np.ndarray, shape_3d: tuple[int, int, int]) -> np.ndarray:
        out = np.zeros(shape_3d, dtype=np.float32)
        var_values = ds[var_name].values

        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(
                    interpolate_3d_timestep,
                    t,
                    var_values[t],
                    src_lat,
                    src_lon,
                    src_depth,
                    target_lat,
                    target_lon,
                    s_rho,
                    h,
                    N
                )
                for t in range(nt)
            ]
            for fut in futures:
                t, result = fut.result()
                out[t] = result
        return out

    print("🔄 Interpolating 3D Temperature...")
    temp_clm = interpolate_3d(ds_tem, "thetao", lon_rho, lat_rho, (nt, N, eta_rho, xi_rho))

    print("🔄 Interpolating 3D Salinity...")
    salt_clm = interpolate_3d(ds_sal, "so", lon_rho, lat_rho, (nt, N, eta_rho, xi_rho))

    print("🔄 Interpolating 3D Eastward velocity (u)...")
    u_clm = interpolate_3d(ds_cur, "uo", lon_u, lat_u, (nt, N, eta_rho, xi_u))

    print("🔄 Interpolating 3D Northward velocity (v)...")
    v_clm = interpolate_3d(ds_cur, "vo", lon_v, lat_v, (nt, N, eta_v, xi_v))

    print("🔄 Computing vertically integrated velocities (ubar, vbar)...")
    ubar_clm = u_clm.mean(axis=1)
    vbar_clm = v_clm.mean(axis=1)

    # Save output datasets
    args.output_dir.mkdir(parents=True, exist_ok=True)
    clm_path = args.output_dir / "croco_clm.nc"
    ini_path = args.output_dir / "croco_ini.nc"

    # Save Climatology dataset (all timesteps)
    print(f"💾 Saving Climatology/Boundary forcing to: {clm_path}...")
    clm_times = croco_climatology_times(src_time)
    ds_clm = xr.Dataset(
        data_vars={
            # This CROCO build resolves sea-surface-height climatology by its
            # canonical forcing name (SSH), not the ROMS history name (zeta).
            "SSH": (("ssh_time", "eta_rho", "xi_rho"), zeta_clm),
            "temp": (("tclm_time", "s_rho", "eta_rho", "xi_rho"), temp_clm),
            "salt": (("sclm_time", "s_rho", "eta_rho", "xi_rho"), salt_clm),
            "u": (("uclm_time", "s_rho", "eta_u", "xi_u"), u_clm),
            "v": (("uclm_time", "s_rho", "eta_v", "xi_v"), v_clm),
            "ubar": (("uclm_time", "eta_u", "xi_u"), ubar_clm),
            "vbar": (("uclm_time", "eta_v", "xi_v"), vbar_clm),
        },
        coords={
            **clm_times,
            "s_rho": s_rho,
            "lon_rho": (("eta_rho", "xi_rho"), lon_rho),
            "lat_rho": (("eta_rho", "xi_rho"), lat_rho),
        }
    )
    for time_name in clm_times:
        ds_clm[time_name].attrs.update(
            long_name="elapsed time since forecast initialization",
            units="days",
        )
    encoding_clm = {var: {"zlib": True, "complevel": 1} for var in ds_clm.data_vars}
    ds_clm.to_netcdf(clm_path, encoding=encoding_clm)

    # Save Initial condition dataset (t=0)
    print(f"💾 Saving Initial conditions to: {ini_path}...")
    ds_ini = xr.Dataset(
        data_vars={
            "zeta": (("ocean_time", "eta_rho", "xi_rho"), zeta_clm[0:1]),
            "temp": (("ocean_time", "s_rho", "eta_rho", "xi_rho"), temp_clm[0:1]),
            "salt": (("ocean_time", "s_rho", "eta_rho", "xi_rho"), salt_clm[0:1]),
            "u": (("ocean_time", "s_rho", "eta_u", "xi_u"), u_clm[0:1]),
            "v": (("ocean_time", "s_rho", "eta_v", "xi_v"), v_clm[0:1]),
            "ubar": (("ocean_time", "eta_u", "xi_u"), ubar_clm[0:1]),
            "vbar": (("ocean_time", "eta_v", "xi_v"), vbar_clm[0:1]),
            "scrum_time": (("ocean_time",), src_time[0:1]),
        },
        coords={
            "ocean_time": src_time[0:1],
            "s_rho": s_rho,
            "lon_rho": (("eta_rho", "xi_rho"), lon_rho),
            "lat_rho": (("eta_rho", "xi_rho"), lat_rho),
        }
    )
    encoding_ini = {var: {"zlib": True, "complevel": 1} for var in ds_ini.data_vars}
    ds_ini.to_netcdf(ini_path, encoding=encoding_ini)

    print("=========================================================================")
    print("✅ CROCO Forcing compiled successfully!")
    print(f"   - Climatology: {clm_path} ({clm_path.stat().st_size / (1024*1024):.1f} MB)")
    print(f"   - Initial State: {ini_path} ({ini_path.stat().st_size / (1024*1024):.1f} MB)")
    print("=========================================================================")
    return 0


if __name__ == "__main__":
    sys.exit(main())
