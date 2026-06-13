import json
from pathlib import Path

from place_weather import (
    available_place_ids,
    build_place_weather_record,
    place_definition,
    select_observation_for_place,
)


def test_build_place_weather_record_uses_place_weather_fields():
    forecast = {
        "wave_min_m": 0.3,
        "wave_max_m": 0.8,
        "wave_peak_time": "08:00",
        "wave_peak_direction_deg": 72.0,
        "current_max_kn": 0.4,
        "current_peak_time": "10:00",
        "hourly": [
            {
                "time": "08:00",
                "time_utc": "2026-06-12 06:00 UTC",
                "wave_m": 0.8,
                "wave_direction_deg": 72.0,
                "wave_sea_state": "beam sea",
                "current_kn": 0.4,
                "swell_1_height_m": 0.5,
                "swell_1_direction_deg": 68.0,
                "swell_2_height_m": 0.2,
                "swell_2_direction_deg": 84.0,
                "wind_wave_height_m": 0.3,
                "wind_wave_direction_deg": 80.0,
            },
            {
                "time": "10:00",
                "time_utc": "2026-06-12 08:00 UTC",
                "wave_m": 0.6,
                "wave_direction_deg": 76.0,
                "current_kn": 0.2,
            },
        ],
    }
    observation = {
        "station_id": "canal_de_ibiza",
        "station_name": "Buoy Canal de Ibiza",
        "observed_at_utc": "2026-06-12 07:30 UTC",
        "wave_height_m": 0.4,
        "wave_from_direction_deg": 82.0,
        "wind_kn": 12.0,
        "wind_direction_deg": 70.0,
        "water_temperature_c": 22.4,
        "temperature_c": 23.1,
    }

    record = build_place_weather_record(
        "ibiza",
        forecast,
        observation=observation,
        generated_at_utc="2026-06-12 08:00 UTC",
        run_date="2026-06-12",
        run_id="2026-06-12T0750Z",
    )

    assert record["place_id"] == "ibiza"
    assert record["place_name"] == "Ibiza"
    assert record["date"] == "2026-06-12"
    assert record["run"] == "2026-06-12T0750Z"
    assert record["wave_height_m"] == 0.8
    assert record["wave_direction_deg"] == 72.0
    assert record["swell_1_height_m"] == 0.5
    assert record["swell_2_height_m"] == 0.2
    assert record["wind_kn"] == 12.0
    assert record["water_temperature_c"] == 22.4
    assert record["air_temperature_c"] == 23.1
    assert record["freshness_status"] == "fresh"
    assert record["observation"]["station_name"] == "Buoy Canal de Ibiza"
    assert record["hourly"][0]["time"] == "08:00"


def test_available_place_ids_include_new_locations():
    place_ids = available_place_ids()
    assert "ciutadella" in place_ids
    assert "alcudia" in place_ids
    assert "soller" in place_ids
    assert "portocolom" in place_ids


def test_portocolom_is_supported_and_prefers_its_observation_key():
    place = place_definition("portocolom")
    assert place["name"] == "Portocolom"
    assert place["observation_keys"][0] == "porto_colom"
    assert "alcudia" in place["observation_keys"]

    observation = {
        "station_id": "porto_colom",
        "station_name": "Portocolom",
        "wave_height_m": 0.7,
    }
    selected = select_observation_for_place("portocolom", {"porto_colom": observation})
    assert selected["station_id"] == "porto_colom"
    assert selected["station_name"] == "Portocolom"


def test_portocolom_falls_back_to_nearest_balearic_observation():
    selected = select_observation_for_place(
        "portocolom",
        {
            "alcudia": {
                "station_id": "alcudia",
                "station_name": "Alcudia",
                "wave_height_m": 0.6,
            }
        },
    )
    assert selected["station_id"] == "alcudia"
    assert selected["station_name"] == "Alcudia"


def test_build_place_weather_record_accepts_naive_observation_timestamp():
    forecast = {
        "wave_min_m": 0.2,
        "wave_max_m": 0.4,
        "wave_peak_time": "08:00",
        "wave_peak_direction_deg": 40.0,
        "current_max_kn": 0.1,
        "hourly": [],
    }
    observation = {
        "station_id": "alcudia",
        "station_name": "Alcudia",
        "observed_at_utc": "2026-06-12 07:30",
        "wave_height_m": 0.3,
    }
    record = build_place_weather_record(
        "alcudia",
        forecast,
        observation=observation,
        generated_at_utc="2026-06-12 08:00 UTC",
        run_date="2026-06-12",
        run_id="2026-06-12T0750Z",
    )
    assert record["freshness_status"] == "fresh"
    assert record["metadata"]["observation_age_minutes"] == 30
