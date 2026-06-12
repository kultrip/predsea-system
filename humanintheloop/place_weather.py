from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import route_analysis

try:
    import ingest_atmosphere
except Exception:  # pragma: no cover - import-time fallback
    ingest_atmosphere = None


LOCAL_TIMEZONE = "Europe/Madrid"

PLACE_CATALOG = {
    "ibiza": {
        "name": "Ibiza",
        "latitude": 38.98,
        "longitude": 1.43,
        "observation_keys": ("canal_de_ibiza", "ibiza"),
        "aliases": ("ibiza", "ibiza island"),
    },
    "palma": {
        "name": "Palma",
        "latitude": 39.57,
        "longitude": 2.65,
        "observation_keys": ("bahia_de_palma", "palma"),
        "aliases": ("palma", "palma de mallorca"),
    },
    "formentera": {
        "name": "Formentera",
        "latitude": 38.70,
        "longitude": 1.45,
        "observation_keys": ("formentera", "canal_de_ibiza"),
        "aliases": ("formentera",),
    },
    "menorca": {
        "name": "Menorca",
        "latitude": 39.95,
        "longitude": 4.07,
        "observation_keys": ("menorca", "pollensa"),
        "aliases": ("menorca",),
    },
    "cabrera": {
        "name": "Cabrera",
        "latitude": 39.17,
        "longitude": 2.95,
        "observation_keys": ("cabrera", "canal_de_ibiza"),
        "aliases": ("cabrera",),
    },
    "barcelona": {
        "name": "Barcelona",
        "latitude": 41.39,
        "longitude": 2.17,
        "observation_keys": ("barcelona", "pollensa"),
        "aliases": ("barcelona",),
    },
    "valencia": {
        "name": "Valencia",
        "latitude": 39.47,
        "longitude": -0.38,
        "observation_keys": ("valencia", "pollensa"),
        "aliases": ("valencia",),
    },
}


def available_place_ids():
    return sorted(PLACE_CATALOG)


def place_definition(place_id):
    try:
        return PLACE_CATALOG[place_id]
    except KeyError as error:
        available = ", ".join(available_place_ids())
        raise ValueError(f"Unknown place '{place_id}'. Available places: {available}") from error


def place_route(place_id):
    place = place_definition(place_id)
    point = {
        "name": place["name"],
        "latitude": place["latitude"],
        "longitude": place["longitude"],
    }
    return {
        "id": place_id,
        "name": place["name"],
        "origin": point,
        "destination": point,
        "sample_points": [point],
    }


def resolve_place(place_id, latitude=None, longitude=None):
    if latitude is None or longitude is None:
        place = place_definition(place_id)
        return {
            "requested_place_id": place_id,
            "place_id": place_id,
            "place_name": place["name"],
            "latitude": place["latitude"],
            "longitude": place["longitude"],
        }

    nearest_place_id, distance_nm = nearest_place_id(latitude, longitude)
    place = place_definition(nearest_place_id)
    return {
        "requested_place_id": place_id,
        "place_id": nearest_place_id,
        "place_name": place["name"],
        "latitude": place["latitude"],
        "longitude": place["longitude"],
        "requested_latitude": latitude,
        "requested_longitude": longitude,
        "distance_to_place_nm": round(distance_nm, 1),
    }


def nearest_place_id(latitude, longitude):
    nearest = min(
        available_place_ids(),
        key=lambda place_id: route_analysis.haversine_nm(
            latitude,
            longitude,
            PLACE_CATALOG[place_id]["latitude"],
            PLACE_CATALOG[place_id]["longitude"],
        ),
    )
    distance = route_analysis.haversine_nm(
        latitude,
        longitude,
        PLACE_CATALOG[nearest]["latitude"],
        PLACE_CATALOG[nearest]["longitude"],
    )
    return nearest, distance


def build_place_weather_record(
    place_id,
    forecast,
    observation=None,
    generated_at_utc=None,
    run_date=None,
    run_id=None,
    time_text=None,
    timezone_name=LOCAL_TIMEZONE,
    requested_latitude=None,
    requested_longitude=None,
):
    place = place_definition(place_id)
    hourly = list(forecast.get("hourly") or [])
    sample = select_hourly_sample(hourly, time_text) or {}
    generated_at = generated_at_utc or current_timestamp_utc()
    observation = normalize_observation(observation)
    observation_age_minutes = observation_age(observation, generated_at)
    freshness_status, freshness_warning = freshness_from_age(observation_age_minutes)
    resolved = resolve_place(place_id, requested_latitude, requested_longitude)
    inside_domain = in_supported_domain(resolved["latitude"], resolved["longitude"])
    payload = {
        "place_id": resolved["place_id"],
        "requested_place_id": resolved["requested_place_id"],
        "place_name": resolved["place_name"],
        "requested_latitude": resolved.get("requested_latitude"),
        "requested_longitude": resolved.get("requested_longitude"),
        "resolved_latitude": resolved["latitude"],
        "resolved_longitude": resolved["longitude"],
        "distance_to_place_nm": resolved.get("distance_to_place_nm"),
        "inside_domain": inside_domain,
        "domain_warning": None if inside_domain else "Requested place is outside the supported forecast domain; using the nearest supported sample.",
        "date": run_date,
        "run": run_id,
        "generated_at_utc": generated_at,
        "timezone": timezone_name,
        "time_utc": sample.get("time_utc"),
        "time_local": to_local_time(sample.get("time_utc"), timezone_name) or sample.get("time"),
        "wave_height_m": sample.get("wave_m"),
        "wave_direction_deg": sample.get("wave_direction_deg"),
        "wave_sea_state": sample.get("wave_sea_state"),
        "swell_1_height_m": sample.get("swell_1_height_m"),
        "swell_1_direction_deg": sample.get("swell_1_direction_deg"),
        "swell_2_height_m": sample.get("swell_2_height_m"),
        "swell_2_direction_deg": sample.get("swell_2_direction_deg"),
        "wind_wave_height_m": sample.get("wind_wave_height_m"),
        "wind_wave_direction_deg": sample.get("wind_wave_direction_deg"),
        "current_kn": sample.get("current_kn"),
        "current_direction_deg": sample.get("current_direction_deg"),
        "wind_kn": observation.get("wind_kn"),
        "wind_direction_deg": observation.get("wind_direction_deg"),
        "source": "copernicus_med",
        "source_system": "place_weather",
        "freshness_status": freshness_status,
        "freshness_warning": freshness_warning,
        "observation": observation,
        "hourly": hourly,
        "metadata": {
            "observation_age_minutes": observation_age_minutes,
            "catalog_place_name": place["name"],
        },
    }
    if observation.get("last_sample_utc"):
        payload["observed_at_utc"] = observation["last_sample_utc"]
    return payload


def build_place_weather_outputs(
    run_dir,
    run_date,
    run_id,
    waves_path,
    currents_path,
    observations=None,
    place_ids=None,
    time_text=None,
    timezone_name=LOCAL_TIMEZONE,
):
    run_dir = Path(run_dir)
    place_ids = list(place_ids or available_place_ids())
    results = {}
    for place_id in place_ids:
        record = build_place_weather_bundle_from_files(
            place_id,
            waves_path,
            currents_path,
            observations=observations,
            run_date=run_date,
            run_id=run_id,
            time_text=time_text,
            timezone_name=timezone_name,
        )
        place_dir = run_dir / "places" / place_id
        place_dir.mkdir(parents=True, exist_ok=True)
        (place_dir / "weather.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        results[place_id] = place_dir / "weather.json"

    (run_dir / "places").mkdir(parents=True, exist_ok=True)
    (run_dir / "places" / "index.json").write_text(
        json.dumps(
            {
                "run_date": run_date,
                "run_id": run_id,
                "places": place_ids,
                "created_at_utc": current_timestamp_utc(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return results


def build_place_weather_bundle_from_files(
    place_id,
    waves_path,
    currents_path,
    observations=None,
    run_date=None,
    run_id=None,
    time_text=None,
    timezone_name=LOCAL_TIMEZONE,
):
    route = place_route(place_id)
    forecast = route_analysis.forecast_summary_from_files(waves_path, currents_path, route=route)
    observation = select_observation_for_place(place_id, observations or {})
    return build_place_weather_record(
        place_id,
        forecast,
        observation=observation,
        generated_at_utc=current_timestamp_utc(),
        run_date=run_date,
        run_id=run_id,
        time_text=time_text,
        timezone_name=timezone_name,
    )


def select_hourly_sample(hourly, time_text=None):
    if not hourly:
        return None
    if not time_text:
        return hourly[0]
    return route_analysis.closest_hourly_sample(hourly, time_text)


def select_observation_for_place(place_id, observations):
    place = place_definition(place_id)
    observation_keys = list(place.get("observation_keys") or []) + [place_id]
    lowered_aliases = [alias.lower() for alias in place.get("aliases") or ()]

    for key in observation_keys:
        record = observations.get(key)
        if isinstance(record, dict):
            return normalize_observation(record, station_id=key)

    for station_id, record in observations.items():
        if not isinstance(record, dict):
            continue
        haystack = " ".join(
            str(value).lower()
            for value in (
                station_id,
                record.get("name"),
                record.get("station_name"),
            )
            if value
        )
        if place_id.lower() in haystack or place["name"].lower() in haystack or any(alias in haystack for alias in lowered_aliases):
            return normalize_observation(record, station_id=station_id)

    return {}


def normalize_observation(record, station_id=None):
    if not isinstance(record, dict):
        return {}
    normalized = dict(record)
    if station_id and "station_id" not in normalized:
        normalized["station_id"] = station_id
    if "station_name" not in normalized and normalized.get("name"):
        normalized["station_name"] = normalized.get("name")
    return normalized


def observation_age(observation, generated_at_utc):
    observed_at = parse_utc_timestamp(observation.get("last_sample_utc") or observation.get("observed_at_utc"))
    generated_at = parse_utc_timestamp(generated_at_utc)
    if observed_at is None or generated_at is None:
        return None
    delta = generated_at - observed_at
    return int(round(delta.total_seconds() / 60.0))


def freshness_from_age(age_minutes):
    if age_minutes is None:
        return "unknown", None
    if age_minutes < 90:
        return "fresh", None
    if age_minutes <= 180:
        return "usable", "Observation is getting older; recheck before committing."
    return "stale", "Observation is stale; recheck before departure."


def in_supported_domain(latitude, longitude):
    if ingest_atmosphere is None:
        return True
    bbox = getattr(ingest_atmosphere, "BALEARIC_BBOX", {"south": 38.0, "north": 41.5, "west": 0.5, "east": 4.5})
    return bbox["south"] <= latitude <= bbox["north"] and bbox["west"] <= longitude <= bbox["east"]


def parse_utc_timestamp(value):
    if not value:
        return None
    text = str(value).replace(" UTC", "Z")
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            return datetime.strptime(str(value), "%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc)
        except ValueError:
            return None


def to_local_time(value, timezone_name=LOCAL_TIMEZONE):
    timestamp = parse_utc_timestamp(value)
    if timestamp is None:
        return None
    try:
        local_timezone = ZoneInfo(timezone_name)
    except Exception:
        local_timezone = ZoneInfo("Europe/Madrid")
    return timestamp.astimezone(local_timezone).strftime("%Y-%m-%d %H:%M LT")


def current_timestamp_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
