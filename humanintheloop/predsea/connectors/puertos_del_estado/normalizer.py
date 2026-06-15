from __future__ import annotations

from datetime import datetime, timezone

from .common import parse_utc_timestamp


def freshness_state_from_sample_time(sample_time_utc, *, now_utc=None, tolerance_minutes=5):
    sample_dt = parse_utc_timestamp(sample_time_utc)
    reference_dt = parse_utc_timestamp(now_utc) if now_utc is not None else datetime.now(timezone.utc)
    if sample_dt is None or reference_dt is None:
        return "UNKNOWN"
    delta_minutes = (reference_dt - sample_dt).total_seconds() / 60.0
    if delta_minutes < -tolerance_minutes:
        return "FUTURE"
    if delta_minutes < 120:
        return "LIVE"
    if delta_minutes < 360:
        return "RECENT"
    if delta_minutes < 720:
        return "AGING"
    return "STALE"


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
    latest_measurement = max(
        measurements,
        key=lambda measurement: measurement.get("sample_time_utc") or "",
    )
    source_system = station_meta.get("source_system") or "puertos_del_estado"
    source_label = station_meta.get("source_label") or station_meta.get("network_label") or "Puertos del Estado"
    record = {
        "source": source_system,
        "source_system": source_system,
        "source_label": source_label,
        "provider": source_system,
        "network": station_meta.get("network"),
        "station_id": station_meta.get("station_id"),
        "station_name": station_meta.get("station_name"),
        "catalog_id": station_meta.get("catalog_id"),
        "catalog_url": station_meta.get("catalog_url"),
        "last_sample_utc": latest_sample_time,
        "sample_time_utc": latest_sample_time,
        "observed_at_utc": latest_sample_time,
        "source_time_coordinate_utc": latest_measurement.get("source_time_coordinate_utc") or latest_sample_time,
        "latitude": station_meta.get("latitude"),
        "longitude": station_meta.get("longitude"),
        "station_kind": station_meta.get("station_kind"),
        "qc_flag": latest_measurement.get("qc_flag"),
        "is_qc_good": latest_measurement.get("is_qc_good"),
        "is_future": bool(latest_measurement.get("is_future")),
        "freshness_state": latest_measurement.get("freshness_state")
        or freshness_state_from_sample_time(latest_sample_time),
    }
    for measurement in measurements:
        raw_key = measurement.get("raw_key")
        if not raw_key:
            continue
        record[raw_key] = measurement.get("value")
        record[f"{raw_key}_source_field"] = measurement.get("source_field")
        if measurement.get("units") is not None:
            record[f"{raw_key}_units"] = measurement.get("units")
        if measurement.get("qc_flag") is not None:
            record[f"{raw_key}_qc_flag"] = measurement.get("qc_flag")
        if measurement.get("source_time_coordinate_utc") is not None:
            record[f"{raw_key}_source_time_coordinate_utc"] = measurement.get("source_time_coordinate_utc")
    return record
