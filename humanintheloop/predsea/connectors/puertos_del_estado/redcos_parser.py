from __future__ import annotations

from .common import SOURCE_SYSTEM, latest_value_from_dataarray, normalize_text


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
    if any(token in text for token in ("vhm0_sw1", "primary_swell", "swell_1")):
        return "swell_1_height", "swell_1_height_m"
    if any(token in text for token in ("vhm0_sw2", "secondary_swell", "swell_2")):
        return "swell_2_height", "swell_2_height_m"
    if any(token in text for token in ("significant_wave_height", "spectral_significant_wave_height", "vhm0", "wave_height")):
        return "wave_height", "wave_height_m"
    if any(token in text for token in ("wave_from_mean_direction", "mean_direction", "vmdr", "wave_direction")):
        return "wave_direction", "wave_direction_deg"
    if any(token in text for token in ("wave_from_direction_at_spectral_peak", "spectral_peak_direction", "vped", "peak_direction")):
        return "wave_peak_direction", "wave_peak_direction_deg"
    if any(token in text for token in ("wave_period_at_spectral_density_maximum", "peak_wave_period", "vtpk", "peak_period")):
        return "wave_period_peak", "wave_period_peak_s"
    if any(token in text for token in ("wave_mean_period", "vtmz", "mean_period", "second_frequency_moment")):
        return "wave_period_mean", "wave_period_mean_s"
    if "maximum_wave_height" in text or "hmax" in text:
        return "wave_height_max", "wave_height_max_m"
    if "current_speed" in text or "sea_water_velocity" in text:
        return "current_speed", "current_speed_mps"
    if "current_direction" in text or "sea_water_from_direction" in text:
        return "current_direction", "current_direction_deg"
    if "water_temperature" in text or "sea_temperature" in text:
        return "water_temperature", "water_temperature_c"
    if "salinity" in text:
        return "salinity", "salinity_psu"
    if "air_pressure" in text or "pressure" in text:
        return "air_pressure", "air_pressure_hpa"
    if "air_temperature" in text or "air_temp" in text:
        return "air_temperature", "air_temperature_c"
    if "wind_speed" in text:
        return "wind_speed", "wind_speed_mps"
    if "wind_direction" in text or "wind_from_direction" in text:
        return "wind_direction", "wind_direction_deg"
    return None, None


def parse_station_dataset(ds, station_meta, dataset_url=None):
    records = []
    latitude = station_meta.get("latitude")
    longitude = station_meta.get("longitude")
    for source_field, da in ds.data_vars.items():
        source_key = normalize_text(source_field)
        if source_key.endswith("_qc") or source_key.endswith("_dm"):
            continue
        variable, raw_key = _variable_from_attrs(source_field, da)
        if not variable or not raw_key:
            continue
        value, sample_time = latest_value_from_dataarray(da, latitude=latitude, longitude=longitude)
        if value is None or sample_time is None:
            continue
        records.append(
            {
                "source": SOURCE_SYSTEM,
                "source_system": SOURCE_SYSTEM,
                "source_label": "REDCOS",
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
                "sample_time_utc": sample_time,
                "observed_at_utc": sample_time,
            }
        )
    return records

