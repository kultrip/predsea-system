import decision_engine


def test_answer_uses_captain_knowledge_and_worst_segment():
    snapshot = {
        "route": "Palma -> Ibiza",
        "route_id": "palma_ibiza",
        "vessel_class": "small",
        "vessel_profile": {"label": "under 15m", "manageable_m": 1.2, "restricted_m": 1.8},
        "forecast": {
            "wave_min_m": 0.7,
            "wave_max_m": 1.3,
            "wave_peak_time": "14:00",
            "wave_peak_direction_deg": 315.0,
            "wave_peak_sea_state": "beam sea",
            "swell_1_height_m": 0.8,
            "swell_1_direction_deg": 315.0,
            "current_max_kn": 0.4,
            "hourly": [
                {"time": "09:00", "wave_m": 0.8, "wave_sea_state": "bow quartering sea"},
                {"time": "14:00", "wave_m": 1.3, "wave_sea_state": "beam sea"},
            ],
            "route_segments": {
                "worst_segment": {
                    "id": "open_water_conditions",
                    "name": "Mid Palma-Ibiza",
                    "max_wave_m": 1.3,
                    "peak_time": "14:00",
                    "sea_state": "beam sea",
                },
                "best_departure_window": {"time": "09:00", "wave_m": 0.8},
            },
        },
        "recommendation": {
            "best_window": "morning to early afternoon",
            "watch_out": "forecast peak near 1.3 m around 14:00",
            "confidence": "medium",
            "vessel_advice": "caution for vessels under 15m; use the best weather window",
        },
    }

    result = decision_engine.answer_question(
        "Would Palma to Ibiza feel comfortable for a 12m vessel tomorrow morning?",
        snapshot,
        current_time="21:30",
    )

    answer = result["answer"]

    assert "Decision:" in answer
    assert "Best window:" in answer
    assert "Comfort:" in answer
    assert "Risk:" in answer
    assert "Why:" in answer
    assert "What could change:" in answer
    assert "Confidence:" in answer
    assert "Confidence: Medium" in answer
    assert "Mid Palma-Ibiza" in answer
    assert "small vessels" in answer or "under 15m" in answer
    assert "NW" in answer or "beam sea" in answer
    assert "committing Captain knowledge" not in answer


def test_tomorrow_answer_does_not_call_restricted_small_vessel_workable():
    snapshot = {
        "route": "Palma -> Ibiza",
        "route_id": "palma_ibiza",
        "vessel_class": "small",
        "vessel_profile": {"label": "under 15m", "manageable_m": 1.2, "restricted_m": 1.8},
        "forecast": {
            "wave_min_m": 1.2,
            "wave_max_m": 2.1,
            "wave_peak_time": "09:00",
            "wave_peak_direction_deg": 50.0,
            "wave_peak_sea_state": "following sea",
            "current_max_kn": 0.4,
            "hourly": [
                {"time": "09:00", "wave_m": 2.1, "wave_sea_state": "following sea"},
                {"time": "14:00", "wave_m": 1.4, "wave_sea_state": "stern quartering sea"},
            ],
        },
        "recommendation": {
            "best_window": "avoid the exposed peak window",
            "watch_out": "forecast peak near 2.1 m around 09:00",
            "confidence": "low",
            "vessel_advice": "restricted for vessels under 15m",
        },
    }

    result = decision_engine.answer_question(
        "Would Palma to Ibiza feel comfortable for a 12m vessel tomorrow morning?",
        snapshot,
    )

    answer = result["answer"]
    decision_line = answer.split("\n\n", 1)[0]

    assert "looks workable" not in decision_line
    assert "not a comfort recommendation" in decision_line
    assert "Risk: High for this vessel size" in answer


def test_today_departure_window_prefers_daylight_over_lowest_night_sample():
    snapshot = {
        "route": "Palma -> Ibiza",
        "route_id": "palma_ibiza",
        "vessel_class": "medium",
        "vessel_profile": {"label": "15-24m", "manageable_m": 1.5, "restricted_m": 2.2},
        "forecast": {
            "wave_min_m": 0.9,
            "wave_max_m": 2.1,
            "wave_peak_time": "09:00",
            "wave_peak_direction_deg": 50.0,
            "wave_peak_sea_state": "following sea",
            "current_max_kn": 0.4,
            "hourly": [
                {"time": "08:00", "wave_m": 1.9, "wave_sea_state": "following sea"},
                {"time": "09:00", "wave_m": 2.1, "wave_sea_state": "following sea"},
                {"time": "12:00", "wave_m": 1.4, "wave_sea_state": "stern quartering sea"},
                {"time": "16:00", "wave_m": 1.2, "wave_sea_state": "stern quartering sea"},
                {"time": "22:00", "wave_m": 0.9, "wave_sea_state": "stern quartering sea"},
            ],
        },
        "recommendation": {
            "best_window": "avoid the exposed peak window",
            "watch_out": "forecast peak near 2.1 m around 09:00",
            "confidence": "low",
            "vessel_advice": "caution for vessels 15-24m; use the best weather window",
        },
    }

    result = decision_engine.answer_question(
        "When is the best moment to leave from Palma to Ibiza today?",
        snapshot,
        current_time="07:30",
    )

    answer = result["answer"]
    decision_line, best_window_line = answer.split("\n\n", 2)[:2]

    assert "workable today" not in decision_line
    assert "conservative timing" in decision_line
    assert "16:00" in best_window_line
    assert "22:00" not in best_window_line
    assert "daylight" in answer


def test_arome_lineage_adds_high_resolution_wind_context():
    snapshot = {
        "route": "Palma -> Ibiza",
        "route_id": "palma_ibiza",
        "vessel_class": "medium",
        "vessel_profile": {"label": "15-24m", "manageable_m": 1.5, "restricted_m": 2.2},
        "data_lineage": {
            "wind_forecast": {
                "source": "meteo_france_arome",
                "resolution_km": 1.3,
                "status": "blended",
            }
        },
        "forecast": {
            "wave_min_m": 0.7,
            "wave_max_m": 1.1,
            "wave_peak_time": "14:00",
            "current_max_kn": 0.4,
            "hourly": [{"time": "10:00", "wave_m": 0.8}],
        },
        "recommendation": {
            "best_window": "before midday",
            "watch_out": "conditions increase after midday",
            "confidence": "medium",
            "vessel_advice": "manageable for vessels 15-24m",
        },
    }

    result = decision_engine.answer_question(
        "When is the best moment to leave from Palma to Ibiza today?",
        snapshot,
        current_time="08:00",
    )

    assert "ultra-high-resolution 1.3 km" in result["answer"]
    assert "coastal breeze" in result["answer"]


def test_ecmwf_fallback_lineage_softens_coastal_specificity():
    snapshot = {
        "route": "Palma -> Ibiza",
        "route_id": "palma_ibiza",
        "vessel_class": "medium",
        "vessel_profile": {"label": "15-24m", "manageable_m": 1.5, "restricted_m": 2.2},
        "data_lineage": {
            "wind_forecast": {
                "source": "ecmwf_open_data",
                "resolution_km": 9.0,
                "status": "fallback",
            }
        },
        "forecast": {
            "wave_min_m": 0.7,
            "wave_max_m": 1.1,
            "wave_peak_time": "14:00",
            "current_max_kn": 0.4,
            "hourly": [{"time": "10:00", "wave_m": 0.8}],
        },
        "recommendation": {
            "best_window": "before midday",
            "watch_out": "conditions increase after midday",
            "confidence": "medium",
            "vessel_advice": "manageable for vessels 15-24m",
        },
    }

    result = decision_engine.answer_question(
        "When is the best moment to leave from Palma to Ibiza today?",
        snapshot,
        current_time="08:00",
    )

    assert "global structural models" in result["answer"]
    assert "localized coastal land breezes may vary" in result["answer"]


def test_missing_confidence_is_omitted_from_answer():
    snapshot = {
        "route": "Palma -> Ibiza",
        "route_id": "palma_ibiza",
        "vessel_class": "medium",
        "vessel_profile": {"label": "15-24m", "manageable_m": 1.5, "restricted_m": 2.2},
        "forecast": {
            "wave_min_m": 0.7,
            "wave_max_m": 1.1,
            "wave_peak_time": "14:00",
            "current_max_kn": 0.4,
            "hourly": [{"time": "10:00", "wave_m": 0.8}],
        },
        "recommendation": {
            "best_window": "before midday",
            "watch_out": "conditions increase after midday",
            "confidence": None,
            "vessel_advice": "manageable for vessels 15-24m",
        },
    }

    result = decision_engine.answer_question(
        "When is the best moment to leave from Palma to Ibiza today?",
        snapshot,
        current_time="08:00",
    )

    assert "Confidence:" not in result["answer"]


def test_comfort_language_stays_conservative():
    snapshot = {
        "route": "Palma -> Ibiza",
        "route_id": "palma_ibiza",
        "vessel_class": "small",
        "vessel_profile": {"label": "under 15m", "manageable_m": 1.2, "restricted_m": 1.8},
        "forecast": {
            "wave_min_m": 0.8,
            "wave_max_m": 1.1,
            "wave_peak_time": "14:00",
            "current_max_kn": 0.4,
            "hourly": [{"time": "10:00", "wave_m": 0.9}],
        },
        "recommendation": {
            "best_window": "before midday",
            "watch_out": "conditions increase after midday",
            "confidence": "medium",
            "vessel_advice": "manageable for vessels under 15m",
        },
    }

    result = decision_engine.answer_question(
        "Would Palma to Ibiza feel comfortable for a 12m vessel tomorrow morning?",
        snapshot,
        current_time="08:00",
    )

    assert "Moderate to good" not in result["answer"]
    assert "Comfort: Moderate" in result["answer"] or "Comfort: Moderate to poor" in result["answer"]
