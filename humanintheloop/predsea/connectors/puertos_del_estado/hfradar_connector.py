from __future__ import annotations

import math

from .common import NETWORK_LABELS
from .etl import fetch_network_observations
from .normalize_observations import build_measurement_record, latest_valid_sample_from_dataarray


def _dataarray_for_name(ds, *names):
    for name in names:
        if name in ds.data_vars:
            return ds[name]
    return None


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
        try:
            sample = latest_valid_sample_from_dataarray(da)
            if sample is None:
                continue
            value = sample.get("value")
            if value is None:
                continue
            return int(value)
        except Exception:
            continue
    return None


def _radar_sample(ds, station_meta):
    try:
        latitude = station_meta.get("latitude")
        longitude = station_meta.get("longitude")
        u_da = _dataarray_for_name(ds, "u", "U")
        v_da = _dataarray_for_name(ds, "v", "V")
        if u_da is None or v_da is None:
            return None
        u_sample = latest_valid_sample_from_dataarray(u_da, latitude=latitude, longitude=longitude)
        v_sample = latest_valid_sample_from_dataarray(v_da, latitude=latitude, longitude=longitude)
        if not u_sample or not v_sample:
            return None
        if u_sample.get("sample_time_utc") != v_sample.get("sample_time_utc"):
            # Keep the latest common time when the two components drift slightly.
            latest_time = max(u_sample.get("sample_time_utc") or "", v_sample.get("sample_time_utc") or "")
            if latest_time:
                u_time = u_sample.get("sample_time_utc")
                v_time = v_sample.get("sample_time_utc")
                if u_time != latest_time:
                    u_sample = latest_valid_sample_from_dataarray(
                        u_da,
                        latitude=latitude,
                        longitude=longitude,
                        now_utc=latest_time,
                    )
                if v_time != latest_time:
                    v_sample = latest_valid_sample_from_dataarray(
                        v_da,
                        latitude=latitude,
                        longitude=longitude,
                        now_utc=latest_time,
                    )
        if not u_sample or not v_sample:
            return None
        u_value = u_sample.get("value")
        v_value = v_sample.get("value")
        if u_value is None or v_value is None:
            return None
        speed = round(math.sqrt(float(u_value) ** 2 + float(v_value) ** 2), 3)
        direction = (math.degrees(math.atan2(float(u_value), float(v_value))) + 360.0) % 360.0
        qc_flag = _qc_flag_for_measurement(ds, "u")
        if qc_flag is None:
            qc_flag = _qc_flag_for_measurement(ds, "v")
        sample = {
            "sample_time_utc": u_sample.get("sample_time_utc") or v_sample.get("sample_time_utc"),
            "observed_at_utc": u_sample.get("observed_at_utc") or v_sample.get("observed_at_utc"),
            "source_time_coordinate_utc": u_sample.get("source_time_coordinate_utc") or v_sample.get("source_time_coordinate_utc"),
            "qc_flag": qc_flag,
            "is_qc_good": u_sample.get("is_qc_good") if u_sample.get("is_qc_good") is not None else v_sample.get("is_qc_good"),
            "freshness_status": u_sample.get("freshness_status") or v_sample.get("freshness_status"),
            "freshness_state": u_sample.get("freshness_state") or v_sample.get("freshness_state"),
            "quality_score": max(u_sample.get("quality_score") or 0, v_sample.get("quality_score") or 0),
            "is_future_timestamp": bool(u_sample.get("is_future_timestamp") or v_sample.get("is_future_timestamp")),
            "is_future": bool(u_sample.get("is_future") or v_sample.get("is_future")),
        }
        return sample, speed, direction, u_value, v_value, qc_flag
    except Exception:
        return None


def parse_station_dataset(ds, station_meta, dataset_url=None):
    sample_tuple = _radar_sample(ds, station_meta)
    if not sample_tuple:
        return []
    sample, speed, direction, u_value, v_value, qc_flag = sample_tuple
    station_meta = dict(station_meta or {})
    station_meta.setdefault("station_kind", "radar")
    station_meta.setdefault("source_label", NETWORK_LABELS["hfradar"])
    records = [
        build_measurement_record(
            station_meta,
            raw_key="current_u_mps",
            variable="current_u",
            source_field="u",
            value=float(u_value),
            units=getattr(ds["u"], "attrs", {}).get("units"),
            sample=sample,
            qc_flag=qc_flag,
            is_qc_good=sample.get("is_qc_good"),
            source_label=NETWORK_LABELS["hfradar"],
            dataset_url=dataset_url,
            latitude=station_meta.get("latitude"),
            longitude=station_meta.get("longitude"),
            station_kind="radar",
        ),
        build_measurement_record(
            station_meta,
            raw_key="current_v_mps",
            variable="current_v",
            source_field="v",
            value=float(v_value),
            units=getattr(ds["v"], "attrs", {}).get("units"),
            sample=sample,
            qc_flag=qc_flag,
            is_qc_good=sample.get("is_qc_good"),
            source_label=NETWORK_LABELS["hfradar"],
            dataset_url=dataset_url,
            latitude=station_meta.get("latitude"),
            longitude=station_meta.get("longitude"),
            station_kind="radar",
        ),
        build_measurement_record(
            station_meta,
            raw_key="current_speed_mps",
            variable="current_speed",
            source_field="u+v",
            value=speed,
            units="m/s",
            sample=sample,
            qc_flag=qc_flag,
            is_qc_good=sample.get("is_qc_good"),
            source_label=NETWORK_LABELS["hfradar"],
            dataset_url=dataset_url,
            latitude=station_meta.get("latitude"),
            longitude=station_meta.get("longitude"),
            station_kind="radar",
        ),
        build_measurement_record(
            station_meta,
            raw_key="current_direction_deg",
            variable="current_direction",
            source_field="u+v",
            value=round(direction, 1),
            units="degree",
            sample=sample,
            qc_flag=qc_flag,
            is_qc_good=sample.get("is_qc_good"),
            source_label=NETWORK_LABELS["hfradar"],
            dataset_url=dataset_url,
            latitude=station_meta.get("latitude"),
            longitude=station_meta.get("longitude"),
            station_kind="radar",
        ),
    ]
    return records


def fetch_hfradar_observations(**kwargs):
    return fetch_network_observations("hfradar", parser_fn=parse_station_dataset, **kwargs)
