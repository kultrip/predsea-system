import copy

import briefing_renderers
import decision_engine
import route_analysis


def snapshot_for_vessel_class(snapshot, vessel_class):
    adjusted = copy.deepcopy(snapshot)
    adjusted["vessel_class"] = vessel_class
    adjusted["vessel_profile"] = route_analysis.vessel_profile_for(vessel_class)
    forecast = adjusted.get("forecast", {})
    observations = adjusted.get("observations", {})
    canal = observations.get("canal_de_ibiza", {})
    wave_now = canal.get("wave_height_m")
    adjusted["recommendation"] = route_analysis.recommend_window(
        wave_now,
        forecast.get("wave_min_m"),
        forecast.get("wave_max_m"),
        forecast.get("wave_peak_time", "later today"),
        forecast.get("current_max_kn"),
        forecast.get("current_peak_time", "later today"),
        vessel_class=vessel_class,
    )
    return adjusted


def answer_question(snapshot, question_request):
    adjusted = snapshot_for_vessel_class(snapshot, question_request.vessel_class)
    decision = decision_engine.answer_question(
        question_request.question,
        adjusted,
        location_label=question_request.location_label,
        current_time=question_request.current_time,
    )
    return decision, adjusted


def render_briefing(snapshot, vessel_class, output_format):
    adjusted = snapshot_for_vessel_class(snapshot, vessel_class)
    if output_format == "linkedin":
        return briefing_renderers.render_linkedin(adjusted), adjusted
    return briefing_renderers.render_whatsapp(adjusted), adjusted


def evidence_used(snapshot):
    forecast = snapshot.get("forecast", {})
    observations = snapshot.get("observations", {})
    available_observations = [
        key for key, value in observations.items()
        if isinstance(value, dict) and value.get("last_sample_utc")
    ]
    return {
        "forecast_variables": sorted(
            key for key in ("wave_min_m", "wave_max_m", "current_max_kn")
            if forecast.get(key) is not None
        ),
        "hourly_points": len(forecast.get("hourly") or []),
        "observations": available_observations,
        "source_snapshot_created_at_utc": snapshot.get("created_at_utc"),
    }
