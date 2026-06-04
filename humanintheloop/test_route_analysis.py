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
