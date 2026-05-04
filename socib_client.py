from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import numpy as np
import xarray as xr


SOCIB_WMOP_OPENDAP_URL = "https://thredds.socib.es/thredds/dodsC/wmop/forecast/latest"

TIME_COORD_CANDIDATES = ("time", "ocean_time")
LAT_COORD_CANDIDATES = ("lat", "latitude", "lat_rho", "lat_uv", "lat_u", "lat_v")
LON_COORD_CANDIDATES = ("lon", "longitude", "lon_rho", "lon_uv", "lon_u", "lon_v")
SURFACE_DIM_MARKERS = ("depth", "depthu", "depthv", "s_rho", "s_w", "lev", "level")

VARIABLE_ALIASES = {
    "sea_surface_height": ("sea_surface_height", "ssh", "zos", "zeta"),
    "u_current": ("u_current", "uo", "u", "u_eastward", "eastward_sea_water_velocity"),
    "v_current": ("v_current", "vo", "v", "v_northward", "northward_sea_water_velocity"),
    "significant_wave_height": (
        "significant_wave_height",
        "sea_surface_wave_significant_height",
        "hs",
        "swh",
        "VHM0",
    ),
}


class SocibDataError(RuntimeError):
    """Raised when the SOCIB dataset cannot satisfy the requested slice."""


def get_ocean_data(lat: float, lon: float, timeframe: datetime | str | None) -> dict[str, Any]:
    """Return a 24-hour point slice from SOCIB WMOP as plain Python data."""

    dataset = xr.open_dataset(SOCIB_WMOP_OPENDAP_URL, decode_times=True)
    try:
        time_coord = _find_coord(dataset, TIME_COORD_CANDIDATES, "time")
        start = _parse_timeframe(timeframe, dataset, time_coord)
        end = start + np.timedelta64(24, "h")
        variables = _resolve_variables(dataset)

        windowed = dataset.sel({time_coord: slice(start, end)})
        point = _select_nearest_point(windowed, lat, lon)
        point = _select_surface(point)
        point = point[list(variables.values())].load()

        matched_lat, matched_lon = _matched_location(point)
        data = _serialize_rows(point, time_coord, variables)

        return {
            "source": SOCIB_WMOP_OPENDAP_URL,
            "location": {
                "requested_lat": float(lat),
                "requested_lon": float(lon),
                "matched_lat": matched_lat,
                "matched_lon": matched_lon,
            },
            "time_window": {
                "start": _iso_time(start),
                "end": _iso_time(end),
            },
            "data": data,
        }
    finally:
        close = getattr(dataset, "close", None)
        if close:
            close()


def _parse_timeframe(
    timeframe: datetime | str | None,
    dataset: xr.Dataset,
    time_coord: str,
) -> np.datetime64:
    if timeframe is None:
        values = dataset[time_coord].values
        if len(values) == 0:
            raise SocibDataError(f"Dataset has no values for time coordinate {time_coord!r}.")
        return np.datetime64(values[0], "ns")

    if isinstance(timeframe, datetime):
        if timeframe.tzinfo is not None:
            timeframe = timeframe.astimezone(timezone.utc).replace(tzinfo=None)
        return np.datetime64(timeframe, "ns")

    if isinstance(timeframe, str):
        normalized = timeframe.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return np.datetime64(parsed, "ns")

    raise SocibDataError("timeframe must be None, an ISO string, or a datetime.")


def _find_coord(dataset: xr.Dataset, candidates: tuple[str, ...], label: str) -> str:
    for name in candidates:
        if name in dataset.coords or name in dataset.dims:
            return name
    available = sorted(set(dataset.coords) | set(dataset.dims))
    raise SocibDataError(f"Could not find {label} coordinate. Available coordinates: {available}")


def _resolve_variables(dataset: xr.Dataset) -> dict[str, str]:
    resolved = {}
    missing = []
    for public_name, aliases in VARIABLE_ALIASES.items():
        match = _find_variable(dataset, aliases)
        if match is None:
            missing.append(public_name)
        else:
            resolved[public_name] = match

    if missing:
        available = sorted(dataset.data_vars)
        raise SocibDataError(
            "Missing required SOCIB variable(s): "
            f"{', '.join(missing)}. Available variables: {available}"
        )
    return resolved


def _find_variable(dataset: xr.Dataset, aliases: tuple[str, ...]) -> str | None:
    lowered_aliases = {alias.lower() for alias in aliases}
    for name in dataset.data_vars:
        if name.lower() in lowered_aliases:
            return name

    for name, variable in dataset.data_vars.items():
        metadata = " ".join(
            str(variable.attrs.get(key, ""))
            for key in ("standard_name", "long_name", "name", "units")
        ).lower()
        if any(alias.lower() in metadata for alias in aliases):
            return name
    return None


def _select_nearest_point(dataset: xr.Dataset, lat: float, lon: float) -> xr.Dataset:
    lat_coord = _find_coord(dataset, LAT_COORD_CANDIDATES, "latitude")
    lon_coord = _find_coord(dataset, LON_COORD_CANDIDATES, "longitude")
    lat_values = dataset[lat_coord]
    lon_values = dataset[lon_coord]

    if lat_values.ndim == 1 and lon_values.ndim == 1:
        return dataset.sel({lat_coord: lat, lon_coord: lon}, method="nearest")

    distance = (lat_values - lat) ** 2 + ((lon_values - lon) * np.cos(np.deg2rad(lat))) ** 2
    nearest = np.unravel_index(int(distance.argmin().values), distance.shape)
    indexers = {dim: index for dim, index in zip(distance.dims, nearest)}
    return dataset.isel(indexers)


def _select_surface(dataset: xr.Dataset) -> xr.Dataset:
    indexers = {}
    for dim in dataset.dims:
        lower = dim.lower()
        if any(marker == lower or marker in lower for marker in SURFACE_DIM_MARKERS):
            indexers[dim] = -1
    if not indexers:
        return dataset
    return dataset.isel(indexers)


def _matched_location(dataset: xr.Dataset) -> tuple[float | None, float | None]:
    lat_coord = _find_coord(dataset, LAT_COORD_CANDIDATES, "latitude")
    lon_coord = _find_coord(dataset, LON_COORD_CANDIDATES, "longitude")
    return _to_float(dataset[lat_coord].values), _to_float(dataset[lon_coord].values)


def _serialize_rows(
    dataset: xr.Dataset,
    time_coord: str,
    variables: dict[str, str],
) -> list[dict[str, Any]]:
    rows = []
    for index, time_value in enumerate(dataset[time_coord].values):
        row = {"time": _iso_time(time_value)}
        for public_name, dataset_name in variables.items():
            value = dataset[dataset_name]
            if time_coord in value.dims:
                value = value.isel({time_coord: index})
            row[public_name] = _to_float(value.values)
        rows.append(row)
    return rows


def _to_float(value: Any) -> float | None:
    array = np.asarray(value)
    if array.size == 0:
        return None
    scalar = array.reshape(-1)[0]
    if np.issubdtype(array.dtype, np.floating) and np.isnan(scalar):
        return None
    return float(scalar)


def _iso_time(value: Any) -> str:
    dt64 = np.datetime64(value, "s")
    return np.datetime_as_string(dt64, unit="s")
