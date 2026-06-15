from __future__ import annotations

from .common import SOURCE_SYSTEM, latest_sample_from_dataarray, normalize_text


def _qc_flag_for_measurement(ds, source_field):
    qc_candidates = (
        f"{source_field}_QC",
        f"{source_field}_qc",
        f"{source_field}_DM",
        f"{source_field}_dm",
    )
    for candidate in qc_candidates:
        if candidate not in ds.data_vars:
            continue
        da = ds[candidate]
        time_dim = next((dim for dim in da.dims if dim.lower() in {"time", "time_counter", "datetime"}), None)
        if time_dim is None:
            continue
        try:
            latest = da.isel({time_dim: -1}).squeeze(drop=True)
            value = latest.values
            if hasattr(value, "item"):
                value = value.item()
            return int(value) if value is not None else None
        except Exception:
            continue
    return None


def _variable_from_attrs(source_field, da):
    text = " ".join(
        part
        for part in (
            normalize_text(source_field),
            normalize_text(da.attrs.get("long_name")),
            normalize_text(da.attrs.get("standard_name")),
            normalize_text(da.name),
        )
        if part
    )
    if any(token in text for token in ("sea_level_residual", "residual")):
        return "sea_level_residual", "sea_level_residual_m"
    if any(token in text for token in ("slev", "sea_level", "observed_sea_level", "sea_surface_height")):
        return "sea_level", "sea_level_m"
    if any(token in text for token in ("deph", "depth")):
        return "depth", "depth_m"
    if "pressure" in text:
        return "air_pressure", "air_pressure_hpa"
    if "temperature" in text and "water" in text:
        return "water_temperature", "water_temperature_c"
    if "temperature" in text:
        return "air_temperature", "air_temperature_c"
    if "wind_direction" in text:
        return "wind_direction", "wind_direction_deg"
    if "wind_speed" in text:
        return "wind_speed", "wind_speed_mps"
    return None, None


def parse_station_dataset(ds, station_meta, dataset_url=None):
    records = []
    latitude = station_meta.get("latitude")
    longitude = station_meta.get("longitude")
    for source_field, da in ds.data_vars.items():
        source_key = normalize_text(source_field)
        if source_key.endswith("_qc") or source_key.endswith("_dm") or source_key in {"time_qc", "position_qc"}:
            continue
        variable, raw_key = _variable_from_attrs(source_field, da)
        if not variable or not raw_key:
            continue
        sample = latest_sample_from_dataarray(da, latitude=latitude, longitude=longitude)
        if not sample:
            continue
        value = sample["value"]
        sample_time = sample["sample_time_utc"]
        qc_flag = _qc_flag_for_measurement(ds, source_field)
        records.append(
            {
                "source": SOURCE_SYSTEM,
                "source_system": SOURCE_SYSTEM,
                "source_label": "REDMAR",
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
                "raw_key": raw_key,
                "value": value,
                "units": da.attrs.get("units"),
                "qc_flag": qc_flag,
                "is_qc_good": qc_flag in (1, 2) if qc_flag is not None else None,
                "is_future": sample.get("is_future", False),
                "source_time_coordinate_utc": sample.get("source_time_coordinate_utc"),
                "sample_time_utc": sample_time,
                "observed_at_utc": sample_time,
            }
        )
    return records
