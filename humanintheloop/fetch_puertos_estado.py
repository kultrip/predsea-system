"""Puertos del Estado observation fetcher (REDEXT/REDCOS buoy networks).

Downloads real-time and recent buoy observations from the Puertos del
Estado public data service for Balearic-region stations.

This module provides ground-truth wave observations that complement
the SOCIB buoy network and enable validation against the Copernicus
and atmospheric forecasts.

Data is fetched via the Puertos del Estado public data portal at
https://www.puertos.es/en/services/oceanography.

No API key is required for public historical/real-time data.
"""

import datetime
import os
import re
from pathlib import Path

import requests

TIMEOUT_SECONDS = int(os.getenv("PREDSEA_PUERTOS_TIMEOUT", "60"))

# Puertos del Estado buoy stations relevant to Balearic routes
# Station IDs from the REDEXT (deep-water) and REDCOS (coastal) networks
BALEARIC_STATIONS = {
    "mahon": {
        "id": "2136",
        "name": "Boya de Mahón",
        "network": "REDEXT",
        "latitude": 39.72,
        "longitude": 4.44,
        "relevance": "Menorca Channel, Alcudia-Ciutadella route",
    },
    "dragonera": {
        "id": "2138",
        "name": "Boya de Dragonera",
        "network": "REDCOS",
        "latitude": 39.55,
        "longitude": 2.10,
        "relevance": "SW Mallorca, Palma-Ibiza route approach",
    },
    "valencia": {
        "id": "1901",
        "name": "Boya de Valencia",
        "network": "REDEXT",
        "latitude": 39.52,
        "longitude": -0.21,
        "relevance": "Western Mediterranean basin reference",
    },
    "tarragona_coast": {
        "id": "2120",
        "name": "Boya costera de Tarragona",
        "network": "REDCOS",
        "latitude": 41.07,
        "longitude": 1.19,
        "relevance": "NW Mediterranean reference point",
    },
}

# Puertos del Estado data access URLs
PORTUS_REALTIME_URL = "https://portus.puertos.es/portussvr/api/RTData/station"
PORTUS_TIMESERIES_URL = "https://portus.puertos.es/portussvr/api/TimeSeries/station"


def fetch_station_realtime(station_id, station_name="unknown"):
    """Fetch the latest real-time observation from a Puertos del Estado station.

    Returns a dict with the latest wave parameters or raises on failure.
    """
    url = f"{PORTUS_REALTIME_URL}/{station_id}"
    response = requests.get(url, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    data = response.json()

    return _normalize_observation(data, station_id, station_name)


def fetch_station_timeseries(station_id, station_name="unknown", hours_back=24):
    """Fetch recent time-series observations from a station.

    Returns a list of normalized hourly observation dicts.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    start = now - datetime.timedelta(hours=hours_back)

    url = f"{PORTUS_TIMESERIES_URL}/{station_id}"
    params = {
        "startDate": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "endDate": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    response = requests.get(url, params=params, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    data = response.json()

    if isinstance(data, list):
        return [_normalize_observation(entry, station_id, station_name) for entry in data]
    return [_normalize_observation(data, station_id, station_name)]


def _normalize_observation(data, station_id, station_name):
    """Normalize raw Puertos del Estado response into PredSea format."""
    if not data:
        return {
            "station_id": station_id,
            "station_name": station_name,
            "available": False,
            "error": "Empty response",
        }

    # Puertos del Estado uses various field names depending on the endpoint
    wave_height = (
        _safe_float(data.get("Hm0"))
        or _safe_float(data.get("hm0"))
        or _safe_float(data.get("significantWaveHeight"))
        or _safe_float(data.get("VHM0"))
    )
    wave_period = (
        _safe_float(data.get("Tp"))
        or _safe_float(data.get("tp"))
        or _safe_float(data.get("peakPeriod"))
    )
    wave_direction = (
        _safe_float(data.get("DirM"))
        or _safe_float(data.get("dirM"))
        or _safe_float(data.get("meanDirection"))
        or _safe_float(data.get("VMDR"))
    )
    water_temp = (
        _safe_float(data.get("Tw"))
        or _safe_float(data.get("waterTemperature"))
    )
    timestamp = data.get("time") or data.get("timestamp") or data.get("date")
    timestamp_utc = _normalize_timestamp(timestamp)

    return {
        "station_id": station_id,
        "station_name": station_name,
        "available": wave_height is not None,
        "wave_height_m": wave_height,
        "wave_period_s": wave_period,
        "wave_direction_deg": wave_direction,
        "water_temp_c": water_temp,
        "timestamp_utc": timestamp_utc,
        "raw": data,
    }


def _safe_float(value):
    """Convert a value to float, returning None if not possible."""
    if value is None:
        return None
    try:
        result = float(value)
        if result != result:  # NaN check
            return None
        return round(result, 2)
    except (ValueError, TypeError):
        return None


def _normalize_timestamp(value):
    """Normalize various timestamp formats to ISO 8601 UTC string."""
    if value is None:
        return None
    text = str(value).strip()
    # Try ISO format
    for fmt in (
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
    ):
        try:
            dt = datetime.datetime.strptime(text, fmt)
            return dt.strftime("%Y-%m-%d %H:%M UTC")
        except ValueError:
            continue
    # Try epoch milliseconds
    if text.isdigit() and len(text) >= 10:
        try:
            dt = datetime.datetime.fromtimestamp(int(text) / 1000, tz=datetime.timezone.utc)
            return dt.strftime("%Y-%m-%d %H:%M UTC")
        except (ValueError, OSError):
            pass
    return text


def fetch_balearic_observations(stations=None, dry_run=False):
    """Fetch observations from all configured Balearic stations.

    Returns a dict keyed by station name with normalized observation data.
    Compatible with the PredSea observation format used in route_analysis.
    """
    stations = stations or BALEARIC_STATIONS
    observations = {}
    errors = {}

    for station_key, station_config in stations.items():
        if dry_run:
            observations[station_key] = {
                "name": station_config["name"],
                "network": station_config["network"],
                "latitude": station_config["latitude"],
                "longitude": station_config["longitude"],
                "wave_height_m": None,
                "last_sample_utc": None,
                "source": "puertos_del_estado",
                "dry_run": True,
            }
            continue

        try:
            obs = fetch_station_realtime(
                station_config["id"],
                station_config["name"],
            )
            if obs.get("available"):
                observations[station_key] = {
                    "name": station_config["name"],
                    "network": station_config["network"],
                    "latitude": station_config["latitude"],
                    "longitude": station_config["longitude"],
                    "wave_height_m": obs.get("wave_height_m"),
                    "wave_period_s": obs.get("wave_period_s"),
                    "wave_direction_deg": obs.get("wave_direction_deg"),
                    "water_temp_c": obs.get("water_temp_c"),
                    "last_sample_utc": obs.get("timestamp_utc"),
                    "source": "puertos_del_estado",
                }
            else:
                errors[station_key] = obs.get("error", "unavailable")
        except Exception as error:
            errors[station_key] = str(error)

    return {
        "observations": observations,
        "errors": errors,
        "source": "puertos_del_estado",
        "network_ids": ["REDEXT", "REDCOS"],
    }


def lineage_for_puertos_observations(result):
    """Generate data lineage for Puertos del Estado observations."""
    obs = result.get("observations", {})
    matched = [key for key, value in obs.items() if value.get("wave_height_m") is not None]
    return {
        "source": "puertos_del_estado_redext",
        "status": "matched_successfully" if matched else "unavailable",
        "stations_matched": len(matched),
        "station_ids": matched,
    }
