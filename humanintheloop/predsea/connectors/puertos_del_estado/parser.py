from __future__ import annotations

import re

import pandas as pd


SOURCE_SYSTEM = "puertos_del_estado"

VARIABLE_ALIASES = {
    "slev": "sea_level",
    "sea_level": "sea_level",
    "deph": "depth",
    "depth": "depth",
    "hm0": "wave_height",
    "hs": "wave_height",
    "vhm0": "wave_height",
    "hmax": "wave_height_max",
    "tm02": "wave_period",
    "tp": "wave_peak_period",
    "wspd": "wind_speed",
    "wind_speed": "wind_speed",
    "wdir": "wind_direction",
    "wind_direction": "wind_direction",
    "current_speed": "current_speed",
    "current_dir": "current_direction",
    "current_direction": "current_direction",
    "temp": "temperature",
    "temperature": "temperature",
    "air_temperature": "air_temperature",
    "water_temperature": "water_temperature",
    "sst": "water_temperature",
    "salinity": "salinity",
    "pressure": "air_pressure",
}

RAW_KEY_ALIASES = {
    "sea_level": "sea_level_m",
    "depth": "depth_m",
    "wave_height": "wave_height_m",
    "wave_height_max": "wave_height_max_m",
    "wave_period": "wave_period_s",
    "wave_peak_period": "wave_peak_period_s",
    "wind_speed": "wind_speed_mps",
    "wind_direction": "wind_direction_deg",
    "current_speed": "current_speed_mps",
    "current_direction": "current_direction_deg",
    "temperature": "temperature_c",
    "air_temperature": "air_temperature_c",
    "water_temperature": "water_temperature_c",
    "salinity": "salinity_psu",
    "air_pressure": "air_pressure_hpa",
}

SKIP_FIELD_SUFFIXES = ("_qc", "_dm")
SKIP_FIELDS = {"time_qc", "position_qc", "latitude", "longitude"}


def _normalize_text(value):
    key = re.sub(r"\s*\(.*?\)", "", str(value or "")).strip().lower()
    key = re.sub(r"[^a-z0-9]+", "_", key).strip("_")
    return key


def canonical_variable_name(source_field):
    key = _normalize_text(source_field)
    return VARIABLE_ALIASES.get(key, key)


def raw_key_for_variable(variable_name, units=None):
    key = RAW_KEY_ALIASES.get(variable_name, variable_name)
    if key == "wave_height_m" and units and str(units).lower().startswith("cm"):
        return "wave_height_cm"
    return key


def should_skip_field(source_field):
    key = _normalize_text(source_field)
    return key in SKIP_FIELDS or any(key.endswith(suffix) for suffix in SKIP_FIELD_SUFFIXES)


def _coerce_scalar(values):
    if getattr(values, "ndim", 0) == 0:
        return values.item() if hasattr(values, "item") else values
    flat = getattr(values, "flat", None)
    if flat is not None:
        return next(iter(flat))
    return values


def _timestamp_to_utc_text(value):
    ts = pd.to_datetime(value, utc=True)
    if pd.isna(ts):
        return None
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _time_dim_for_dataarray(da):
    for dim in da.dims:
        if dim.lower() == "time":
            return dim
    return None


def latest_measurement_for_dataarray(da, *, source_field, station_meta, dataset_url=None):
    time_dim = _time_dim_for_dataarray(da)
    if time_dim is None:
        return None
    candidate = da
    for dim in list(candidate.dims):
        if dim != time_dim and candidate.sizes.get(dim, 0) == 1:
            candidate = candidate.isel({dim: 0}, drop=True)
    candidate = candidate.where(candidate.notnull(), drop=True)
    if candidate.size == 0:
        return None
    latest = candidate.isel({time_dim: -1}).squeeze(drop=True)
    value = _coerce_scalar(latest.values)
    if value is None:
        return None
    variable = canonical_variable_name(source_field)
    units = da.attrs.get("units")
    sample_time = _timestamp_to_utc_text(candidate[time_dim].values[-1])
    if sample_time is None:
        return None
    return {
        "source": SOURCE_SYSTEM,
        "provider": SOURCE_SYSTEM,
        "station_id": station_meta.get("station_id"),
        "station_name": station_meta.get("station_name"),
        "station_code": station_meta.get("catalog_id"),
        "catalog_id": station_meta.get("catalog_id"),
        "catalog_url": station_meta.get("catalog_url"),
        "dataset_url": dataset_url,
        "latitude": station_meta.get("latitude"),
        "longitude": station_meta.get("longitude"),
        "source_field": source_field,
        "variable": variable,
        "raw_key": raw_key_for_variable(variable, units=units),
        "value": value.item() if hasattr(value, "item") else value,
        "units": units,
        "sample_time_utc": sample_time,
        "observed_at_utc": sample_time,
    }


def parse_station_dataset(ds, station_meta, dataset_url=None):
    records = []
    for source_field, da in ds.data_vars.items():
        if should_skip_field(source_field):
            continue
        measurement = latest_measurement_for_dataarray(
            da,
            source_field=source_field,
            station_meta=station_meta,
            dataset_url=dataset_url,
        )
        if measurement is not None:
            records.append(measurement)
    return records

