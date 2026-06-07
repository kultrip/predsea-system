import route_analysis


def test_summarize_route_point_series_adds_operational_segments():
    route = {
        "id": "palma_ibiza",
        "origin": {"longitude": 2.65, "latitude": 39.57},
        "destination": {"longitude": 1.43, "latitude": 38.91},
        "sample_points": [
            {"name": "Palma Bay offshore", "longitude": 2.55, "latitude": 39.45},
            {"name": "Mid Palma-Ibiza", "longitude": 2.04, "latitude": 39.19},
            {"name": "Ibiza Channel", "longitude": 1.83, "latitude": 38.85},
        ],
    }

    summary = route_analysis.summarize_route_point_series(
        times=["09:00", "14:00", "18:00"],
        wave_points_by_time=[
            [0.5, 0.7, 0.6],
            [0.8, 1.4, 1.1],
            [0.6, 1.0, 0.9],
        ],
        current_points_by_time=[
            [0.1, 0.2, 0.1],
            [0.2, 0.3, 0.2],
            [0.1, 0.2, 0.1],
        ],
        wave_direction_points_by_time=[
            [300.0, 315.0, 310.0],
            [305.0, 315.0, 315.0],
            [300.0, 310.0, 310.0],
        ],
        route=route,
    )

    segments = summary["route_segments"]

    assert segments["departure_conditions"]["name"] == "Palma Bay offshore"
    assert segments["open_water_conditions"]["name"] == "Mid Palma-Ibiza"
    assert segments["arrival_conditions"]["name"] == "Ibiza Channel"
    assert segments["open_water_conditions"]["max_wave_m"] == 1.4
    assert segments["open_water_conditions"]["peak_time"] == "14:00"
    assert segments["worst_segment"]["id"] == "open_water_conditions"
    assert segments["worst_segment"]["max_wave_m"] == 1.4
    assert segments["best_departure_window"]["time"] == "09:00"
    assert segments["best_departure_window"]["wave_m"] == 0.7


def test_summarize_route_point_series_adds_segment_hourly_evidence():
    route = {
        "id": "palma_ibiza",
        "origin": {"longitude": 2.65, "latitude": 39.57},
        "destination": {"longitude": 1.43, "latitude": 38.91},
        "sample_points": [
            {"name": "Palma Bay offshore", "longitude": 2.55, "latitude": 39.45},
            {"name": "Mid Palma-Ibiza", "longitude": 2.04, "latitude": 39.19},
            {"name": "Ibiza Channel", "longitude": 1.83, "latitude": 38.85},
        ],
    }

    summary = route_analysis.summarize_route_point_series(
        times=["09:00", "10:00", "11:00"],
        wave_points_by_time=[
            [0.5, 0.8, 0.6],
            [0.7, 1.2, 0.9],
            [0.8, 1.5, 1.1],
        ],
        current_points_by_time=[
            [0.1, 0.2, 0.1],
            [0.2, 0.3, 0.2],
            [0.1, 0.2, 0.1],
        ],
        wave_direction_points_by_time=[
            [300.0, 315.0, 310.0],
            [305.0, 315.0, 315.0],
            [300.0, 310.0, 310.0],
        ],
        time_utc_values=[
            "2026-06-07 07:00 UTC",
            "2026-06-07 08:00 UTC",
            "2026-06-07 09:00 UTC",
        ],
        route=route,
    )

    open_water = summary["route_segments"]["open_water_conditions"]

    assert open_water["hourly"][0] == {
        "time": "09:00",
        "time_utc": "2026-06-07 07:00 UTC",
        "wave_m": 0.8,
        "wave_direction_deg": 315.0,
        "wave_relative_angle_deg": 79.5,
        "wave_sea_state": "beam sea",
        "current_kn": 0.4,
    }
    assert open_water["hourly"][2]["wave_m"] == 1.5


def test_build_passage_evidence_samples_segments_by_eta():
    route = {
        "id": "palma_ibiza",
        "origin": {"name": "Palma", "longitude": 2.65, "latitude": 39.57},
        "destination": {"name": "Ibiza", "longitude": 1.43, "latitude": 38.91},
        "sample_points": [
            {"name": "Palma Bay offshore", "longitude": 2.55, "latitude": 39.45},
            {"name": "Mid Palma-Ibiza", "longitude": 2.04, "latitude": 39.19},
            {"name": "Ibiza Channel", "longitude": 1.83, "latitude": 38.85},
        ],
    }
    forecast = {
        "route_segments": {
            "departure_conditions": {
                "name": "Palma Bay offshore",
                "hourly": [
                    {"time": "08:00", "wave_m": 0.5, "wave_sea_state": "following sea", "current_kn": 0.2},
                    {"time": "09:00", "wave_m": 0.6, "wave_sea_state": "following sea", "current_kn": 0.2},
                ],
            },
            "open_water_conditions": {
                "name": "Mid Palma-Ibiza",
                "hourly": [
                    {"time": "09:00", "wave_m": 0.8, "wave_sea_state": "beam sea", "current_kn": 0.3},
                    {"time": "10:00", "wave_m": 1.5, "wave_sea_state": "beam sea", "current_kn": 0.4},
                ],
            },
            "arrival_conditions": {
                "name": "Ibiza Channel",
                "hourly": [
                    {"time": "12:00", "wave_m": 1.1, "wave_sea_state": "stern quartering sea", "current_kn": 0.3},
                    {"time": "13:00", "wave_m": 0.9, "wave_sea_state": "stern quartering sea", "current_kn": 0.2},
                ],
            },
        }
    }

    passage = route_analysis.build_passage_evidence(
        forecast,
        route,
        departure_time="08:30",
        vessel_speed_kn=16,
        priority="comfort",
        vessel_class="medium",
    )

    assert passage["departure_time"] == "08:30"
    assert passage["vessel_speed_kn"] == 16
    assert passage["priority"] == "comfort"
    assert passage["worst_segment"]["id"] == "open_water_conditions"
    assert passage["worst_segment"]["wave_m"] == 1.5
    assert passage["segments"][0]["label"] == "Palma Bay offshore"
    assert passage["segments"][0]["eta"]
    assert passage["segments"][1]["sample"]["time"] == "10:00"
    assert passage["segments"][1]["comfort"] == "moderate_to_poor"
    assert passage["summary"] == "Worst expected section: Mid Palma-Ibiza near 1.5 m around 10:00."


def test_closest_hourly_sample_does_not_treat_midnight_as_eta():
    hourly = [
        {"time": "09:00", "wave_m": 0.6},
        {"time": "12:00", "wave_m": 1.1},
        {"time": "00:00", "wave_m": 0.8},
    ]

    sample = route_analysis.closest_hourly_sample(hourly, "12:06")

    assert sample["time"] == "12:00"
    assert sample["wave_m"] == 1.1


def test_build_route_snapshot_embeds_passage_evidence_when_segments_exist():
    route = {
        "id": "palma_ibiza",
        "name": "Palma -> Ibiza",
        "origin": {"name": "Palma", "longitude": 2.65, "latitude": 39.57},
        "destination": {"name": "Ibiza", "longitude": 1.43, "latitude": 38.91},
        "sample_points": [
            {"name": "Palma Bay offshore", "longitude": 2.55, "latitude": 39.45},
            {"name": "Mid Palma-Ibiza", "longitude": 2.04, "latitude": 39.19},
            {"name": "Ibiza Channel", "longitude": 1.83, "latitude": 38.85},
        ],
    }
    forecast = {
        "wave_min_m": 0.5,
        "wave_max_m": 1.5,
        "wave_peak_time": "10:00",
        "current_max_kn": 0.4,
        "current_peak_time": "10:00",
        "route_segments": {
            "departure_conditions": {"name": "Palma Bay offshore", "hourly": [{"time": "08:00", "wave_m": 0.5}]},
            "open_water_conditions": {"name": "Mid Palma-Ibiza", "hourly": [{"time": "10:00", "wave_m": 1.5}]},
            "arrival_conditions": {"name": "Ibiza Channel", "hourly": [{"time": "12:00", "wave_m": 1.0}]},
        },
    }

    snapshot = route_analysis.build_route_snapshot({}, forecast, route=route, vessel_class="medium")

    passage = snapshot["forecast"]["passage_evidence"]
    assert passage["departure_time"] == "08:30"
    assert passage["vessel_speed_kn"] == 16
    assert passage["worst_segment"]["label"] == "Mid Palma-Ibiza"
    assert passage["worst_segment"]["comfort"] == "moderate_to_poor"


def test_build_passage_evidence_falls_back_to_segment_summary_without_hourly():
    route = {
        "id": "palma_ibiza",
        "origin": {"name": "Palma", "longitude": 2.65, "latitude": 39.57},
        "destination": {"name": "Ibiza", "longitude": 1.43, "latitude": 38.91},
        "sample_points": [
            {"name": "Palma Bay offshore", "longitude": 2.55, "latitude": 39.45},
            {"name": "Mid Palma-Ibiza", "longitude": 2.04, "latitude": 39.19},
            {"name": "Ibiza Channel", "longitude": 1.83, "latitude": 38.85},
        ],
    }
    forecast = {
        "route_segments": {
            "departure_conditions": {"name": "Palma Bay offshore", "max_wave_m": 0.6, "peak_time": "09:00"},
            "open_water_conditions": {"name": "Mid Palma-Ibiza", "max_wave_m": 1.4, "peak_time": "11:00"},
            "arrival_conditions": {"name": "Ibiza Channel", "max_wave_m": 1.1, "peak_time": "12:00"},
        }
    }

    passage = route_analysis.build_passage_evidence(forecast, route, departure_time="08:30", vessel_speed_kn=16)

    assert passage["worst_segment"]["label"] == "Mid Palma-Ibiza"
    assert passage["worst_segment"]["wave_m"] == 1.4
    assert passage["worst_segment"]["time"] == "11:00"
    assert passage["summary"] == "Worst expected section: Mid Palma-Ibiza near 1.4 m around 11:00."
