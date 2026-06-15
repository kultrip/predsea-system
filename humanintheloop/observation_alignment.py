from __future__ import annotations

from datetime import datetime, timezone
import re


FRESHNESS_THRESHOLDS_MINUTES = {
    "fresh": 90,
    "usable": 180,
}


def compute_observation_alignment(snapshot):
    observations = snapshot.get("observations") or {}
    forecast = snapshot.get("forecast") or {}
    observation = latest_wave_observation(observations)

    if observation["wave_height_m"] is None or forecast.get("wave_max_m") is None:
        return {
            "forecast_wave_m": forecast.get("wave_max_m"),
            "observed_wave_m": observation["wave_height_m"],
            "difference_pct": None,
            "agreement": "unavailable",
            "observation_age_minutes": observation["observation_age_minutes"],
            "freshness": observation["freshness"],
            "freshness_status": observation["freshness"],
            "warning": None,
        }

    forecast_wave = float(forecast["wave_max_m"])
    observed_wave = float(observation["wave_height_m"])
    difference_pct = abs(forecast_wave - observed_wave) / forecast_wave * 100.0 if forecast_wave else 0.0

    if difference_pct < 15:
        agreement = "excellent"
    elif difference_pct < 25:
        agreement = "good"
    elif difference_pct < 40:
        agreement = "poor"
    else:
        agreement = "very poor"

    warning = None
    if agreement in {"poor", "very poor"}:
        warning = (
            f"Latest buoy observations are lower than the forecast" if observed_wave < forecast_wave
            else "Latest buoy observations are higher than the forecast"
        )
        warning = f"{warning}, so confidence is reduced and the passage should be rechecked before departure."

    return {
        "forecast_wave_m": round(forecast_wave, 2),
        "observed_wave_m": round(observed_wave, 2),
        "difference_pct": round(difference_pct),
        "agreement": agreement,
        "observation_age_minutes": observation["observation_age_minutes"],
        "freshness": observation["freshness"],
        "freshness_status": observation["freshness"],
        "warning": warning,
    }


def latest_wave_observation(observations):
    candidates = []
    now = datetime.now(timezone.utc)
    for station_id, record in (observations or {}).items():
        if not isinstance(record, dict):
            continue
        wave_height = record.get("wave_height_m")
        if wave_height is None:
            continue
        sample_time = record.get("last_sample_utc") or record.get("observed_at_utc")
        parsed = parse_timestamp(sample_time)
        age_minutes = None
        freshness = "unavailable"
        if parsed:
            if parsed > now:
                continue
            age_minutes = int((datetime.now(timezone.utc) - parsed).total_seconds() / 60.0)
            if age_minutes < FRESHNESS_THRESHOLDS_MINUTES["fresh"]:
                freshness = "fresh"
            elif age_minutes < FRESHNESS_THRESHOLDS_MINUTES["usable"]:
                freshness = "usable"
            else:
                freshness = "stale"
        candidates.append(
            {
                "station_id": station_id,
                "name": record.get("name"),
                "wave_height_m": wave_height,
                "observed_at_utc": sample_time,
                "source_time_coordinate_utc": record.get("source_time_coordinate_utc") or sample_time,
                "observation_age_minutes": age_minutes,
                "freshness": freshness,
                "freshness_state": record.get("freshness_state") or freshness.upper(),
            }
        )

    if not candidates:
        return {
            "station_id": None,
            "name": None,
            "wave_height_m": None,
            "observed_at_utc": None,
            "source_time_coordinate_utc": None,
            "observation_age_minutes": None,
            "freshness": "unavailable",
            "freshness_state": "UNKNOWN",
        }

    return min(
        candidates,
        key=lambda item: item["observation_age_minutes"] if item["observation_age_minutes"] is not None else 10**9,
    )


def parse_timestamp(value):
    if not value:
        return None
    text = str(value).strip().replace(" UTC", "Z")
    for fmt in ("%Y-%m-%dT%H:%MZ", "%Y-%m-%d %H:%MZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None
