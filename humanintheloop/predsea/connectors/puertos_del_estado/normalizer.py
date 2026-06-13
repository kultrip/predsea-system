from __future__ import annotations


def measurements_to_observation_record(station_meta, measurements):
    if not measurements:
        return None
    measurements = sorted(
        measurements,
        key=lambda item: (item.get("sample_time_utc") or "", item.get("source_field") or ""),
    )
    latest_sample_time = max(
        (measurement.get("sample_time_utc") for measurement in measurements if measurement.get("sample_time_utc")),
        default=None,
    )
    record = {
        "source": "puertos_del_estado",
        "provider": "puertos_del_estado",
        "station_id": station_meta.get("station_id"),
        "station_name": station_meta.get("station_name"),
        "catalog_id": station_meta.get("catalog_id"),
        "catalog_url": station_meta.get("catalog_url"),
        "last_sample_utc": latest_sample_time,
        "sample_time_utc": latest_sample_time,
        "observed_at_utc": latest_sample_time,
        "latitude": station_meta.get("latitude"),
        "longitude": station_meta.get("longitude"),
    }
    for measurement in measurements:
        raw_key = measurement.get("raw_key")
        if not raw_key:
            continue
        record[raw_key] = measurement.get("value")
        record[f"{raw_key}_source_field"] = measurement.get("source_field")
        if measurement.get("units") is not None:
            record[f"{raw_key}_units"] = measurement.get("units")
    return record

