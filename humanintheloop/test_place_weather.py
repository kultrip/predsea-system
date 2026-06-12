import json
from pathlib import Path

from place_weather import build_place_weather_record


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
    assert record["wind_kn"] == 12.0
    assert record["freshness_status"] == "fresh"
    assert record["observation"]["station_name"] == "Buoy Canal de Ibiza"
    assert record["hourly"][0]["time"] == "08:00"

