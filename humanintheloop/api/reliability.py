from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import place_weather
import route_analysis
from place_registry import default_place_id_for_query


CONFIDENCE_ORDER = {"Low": 0, "Medium": 1, "High": 2}


def compute_route_reliability(store, route_id, run_date, run_id, snapshot):
    route = _safe_load_route(route_id)
    origin_place_id, destination_place_id = _route_place_ids(route)
    current_records = _current_place_weather_records(
        store,
        run_date=run_date,
        run_id=run_id,
        place_ids=[origin_place_id, destination_place_id],
    )
    snapshot_timestamp = _timestamp_from_snapshot(snapshot)
    evidence_timestamp = _oldest_timestamp([snapshot_timestamp, *_record_timestamps(current_records)])
    age_minutes = _age_minutes(evidence_timestamp)

    method = _evaluation_method(current_records)
    if method == "multi_model_consensus":
        variance_pct = _multi_model_variance(snapshot, current_records)
    else:
        variance_pct = _single_model_variance(store, run_date, run_id, origin_place_id, destination_place_id)

    freshness_score = _score_from_age(age_minutes)
    variance_score = _score_from_variance(variance_pct, method)
    confidence_score = _lower_score(freshness_score, variance_score)

    return {
        "confidence_score": confidence_score,
        "evaluation_method": method,
        "age_minutes": age_minutes,
    }


def _safe_load_route(route_id):
    try:
        return route_analysis.load_route(route_id)
    except Exception:
        return {}


def _route_place_ids(route):
    origin = route.get("origin") or {}
    destination = route.get("destination") or {}
    origin_place_id = route.get("origin_place_id") or origin.get("place_id") or origin.get("id")
    destination_place_id = route.get("destination_place_id") or destination.get("place_id") or destination.get("id")
    if not origin_place_id and origin.get("name"):
        origin_place_id = default_place_id_for_query(origin.get("name"))
    if not destination_place_id and destination.get("name"):
        destination_place_id = default_place_id_for_query(destination.get("name"))
    return origin_place_id, destination_place_id


def _current_place_weather_records(store, run_date, run_id, place_ids):
    records = []
    for place_id in place_ids:
        if not place_id:
            continue
        try:
            payload = store.load_place_weather(place_id, run_date, run_id)
        except Exception:
            continue
        if isinstance(payload, dict):
            payload = dict(payload)
            payload["place_id"] = payload.get("place_id") or place_id
            records.append(payload)
    return records


def _timestamp_from_snapshot(snapshot):
    if not isinstance(snapshot, dict):
        return None
    candidates = [
        snapshot.get("created_at_utc"),
        (snapshot.get("forecast") or {}).get("created_at_utc"),
        (snapshot.get("forecast") or {}).get("source_snapshot_created_at_utc"),
    ]
    for candidate in candidates:
        timestamp = place_weather.parse_utc_timestamp(candidate)
        if timestamp is not None:
            return timestamp
    return None


def _record_timestamps(records):
    timestamps = []
    for record in records:
        for key in ("source_time_coordinate_utc", "observed_at_utc", "generated_at_utc", "last_sample_utc"):
            timestamp = place_weather.parse_utc_timestamp(record.get(key))
            if timestamp is not None:
                timestamps.append(timestamp)
                break
    return timestamps


def _oldest_timestamp(timestamps):
    valid = [timestamp for timestamp in timestamps if timestamp is not None]
    if not valid:
        return None
    return min(valid)


def _age_minutes(timestamp):
    if timestamp is None:
        return 999
    now = datetime.now(timezone.utc)
    delta = now - timestamp.astimezone(timezone.utc)
    return max(0, int(round(delta.total_seconds() / 60.0)))


def _evaluation_method(records):
    labels = {
        _source_identity(record)
        for record in records
        if _source_identity(record)
    }
    if len(labels) >= 2 and len(_numeric_values(records)) >= 2:
        return "multi_model_consensus"
    return "single_model_consistency"


def _source_identity(record):
    if not isinstance(record, dict):
        return None
    for key in ("source_label", "network", "source_system"):
        value = record.get(key)
        if value:
            return str(value).strip().lower()
    return None


def _numeric_values(records):
    values = []
    for record in records:
        value = _primary_metric(record)
        if value is not None:
            values.append((record, value))
    return values


def _primary_metric(record):
    if not isinstance(record, dict):
        return None
    for key in ("wave_height_m", "wave_m", "current_kn", "wind_kn"):
        value = record.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    observation = record.get("observation") if isinstance(record.get("observation"), dict) else None
    if observation:
        for key in ("wave_height_m", "wave_m", "current_kn", "wind_kn"):
            value = observation.get(key)
            if isinstance(value, (int, float)):
                return float(value)
    return None


def _route_forecast_metric(snapshot):
    if not isinstance(snapshot, dict):
        return None
    forecast = snapshot.get("forecast") or {}
    if isinstance(forecast.get("wave_max_m"), (int, float)):
        return float(forecast["wave_max_m"])
    passage = forecast.get("passage_evidence") or {}
    worst = passage.get("worst_segment") or {}
    for key in ("wave_m", "current_kn"):
        value = worst.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    for key in ("current_max_kn", "wave_min_m"):
        value = forecast.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _multi_model_variance(snapshot, records):
    forecast_metric = _route_forecast_metric(snapshot)
    if forecast_metric is None:
        values = _numeric_values(records)
        if len(values) < 2:
            return None
        forecast_metric = values[0][1]
        baseline_metric = values[1][1]
    else:
        values = _numeric_values(records)
        if not values:
            return None
        baseline_metric = sum(value for _, value in values) / float(len(values))
    return _variance_pct(forecast_metric, baseline_metric)


def _single_model_variance(store, run_date, run_id, origin_place_id, destination_place_id):
    current_records = _current_place_weather_records(store, run_date, run_id, [origin_place_id, destination_place_id])
    if not current_records:
        return None
    current_metric = _primary_metric(current_records[0])
    if current_metric is None:
        return None
    previous_run_id = _previous_run_id(store, run_date, run_id)
    if previous_run_id is None:
        return None
    previous_place_ids = [current_records[0].get("place_id")]
    previous_records = _current_place_weather_records(store, run_date, previous_run_id, previous_place_ids)
    if not previous_records:
        return None
    previous_metric = _primary_metric(previous_records[0])
    if previous_metric is None:
        return None
    return _variance_pct(current_metric, previous_metric)


def _previous_run_id(store, run_date, run_id):
    runs_dir = _runs_dir_for(store, run_date)
    if runs_dir is None or not runs_dir.exists():
        return None
    run_ids = sorted(path.name for path in runs_dir.iterdir() if path.is_dir())
    if not run_ids:
        return None
    if run_id in run_ids:
        index = run_ids.index(run_id)
        if index > 0:
            return run_ids[index - 1]
        return None
    prior = [candidate for candidate in run_ids if candidate < run_id]
    if prior:
        return prior[-1]
    return None


def _runs_dir_for(store, run_date):
    base = getattr(store, "predictions_root", None)
    if base is not None:
        return Path(base) / run_date / "runs"
    fallback = getattr(store, "fallback_store", None)
    fallback_base = getattr(fallback, "predictions_root", None)
    if fallback_base is not None:
        return Path(fallback_base) / run_date / "runs"
    return None


def _variance_pct(current, baseline):
    if current is None or baseline is None:
        return None
    baseline = float(baseline)
    if baseline == 0.0:
        return None
    return abs(float(current) - baseline) / abs(baseline) * 100.0


def _score_from_age(age_minutes):
    if age_minutes is None:
        return "Low"
    if age_minutes < 180:
        return "High"
    if age_minutes <= 360:
        return "Medium"
    return "Low"


def _score_from_variance(variance_pct, method):
    if variance_pct is None:
        return "Low"
    if method == "multi_model_consensus":
        if variance_pct < 15:
            return "High"
        if variance_pct <= 30:
            return "Medium"
        return "Low"
    if variance_pct < 10:
        return "High"
    if variance_pct <= 25:
        return "Medium"
    return "Low"


def _lower_score(*scores):
    filtered = [score for score in scores if score in CONFIDENCE_ORDER]
    if not filtered:
        return "Low"
    return min(filtered, key=lambda score: CONFIDENCE_ORDER[score])
