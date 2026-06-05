import copy
from datetime import datetime
from zoneinfo import ZoneInfo

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
    provided_fields = getattr(question_request, "model_fields_set", None)
    if provided_fields is None:
        provided_fields = getattr(question_request, "__fields_set__", set())
    adjusted["vessel_class_assumed"] = "vessel_class" not in provided_fields
    freshness = evidence_freshness(snapshot, question_request)
    adjusted["evidence_freshness"] = freshness
    decision = decision_engine.answer_question(
        question_request.question,
        adjusted,
        location_label=question_request.location_label,
        current_time=question_request.current_time,
        current_date=question_request.current_date,
    )
    return decision, adjusted, freshness


def render_briefing(snapshot, vessel_class, output_format):
    adjusted = snapshot_for_vessel_class(snapshot, vessel_class)
    if output_format == "linkedin":
        return briefing_renderers.render_linkedin(adjusted), adjusted
    return briefing_renderers.render_whatsapp(adjusted), adjusted


def evidence_used(snapshot, forecast_override=None):
    forecast = forecast_override or snapshot.get("forecast", {})
    observations = snapshot.get("observations", {})
    available_observations = [
        key for key, value in observations.items()
        if isinstance(value, dict) and value.get("last_sample_utc")
    ]
    evidence = {
        "forecast_variables": sorted(
            key for key in ("wave_min_m", "wave_max_m", "current_max_kn")
            if forecast.get(key) is not None
        ),
        "hourly_points": len(forecast.get("hourly") or []),
        "route_segments": sorted((forecast.get("route_segments") or {}).keys()),
        "observations": available_observations,
        "source_snapshot_created_at_utc": snapshot.get("created_at_utc"),
    }
    if forecast.get("target_local_date"):
        evidence["target_local_date"] = forecast.get("target_local_date")
    if forecast.get("target_period_label"):
        evidence["target_period_label"] = forecast.get("target_period_label")
    return evidence


def evidence_freshness(snapshot, question_request):
    evidence_timestamp = evidence_timestamp_from_snapshot(snapshot)
    evidence_date = date_from_timestamp(evidence_timestamp) or date_from_run_id(question_request.run)
    operational_date = (
        normalize_date(question_request.current_date)
        or date_from_timestamp(question_request.current_time)
        or normalize_date(question_request.date)
        or datetime.now(ZoneInfo("Europe/Madrid")).date().isoformat()
    )

    if not evidence_timestamp:
        return {
            "evidence_timestamp": None,
            "freshness_status": "unknown",
            "freshness_warning": "Evidence timestamp is unavailable. Treat this as planning guidance and verify before committing.",
        }

    if operational_date and evidence_date and evidence_date < operational_date:
        return {
            "evidence_timestamp": evidence_timestamp,
            "freshness_status": "last_night_run",
            "freshness_warning": "Latest available forecast package is from last night. Confirm with the morning run before committing.",
        }

    return {
        "evidence_timestamp": evidence_timestamp,
        "freshness_status": "current",
        "freshness_warning": None,
    }


def evidence_timestamp_from_snapshot(snapshot):
    created_at = snapshot.get("created_at_utc")
    if not created_at:
        return None
    parsed = parse_timestamp(created_at)
    if parsed:
        return parsed.strftime("%Y-%m-%dT%H:%MZ")
    return created_at


def parse_timestamp(value):
    if not value:
        return None
    text = str(value).strip().replace(" UTC", "Z")
    for fmt in ("%Y-%m-%dT%H:%MZ", "%Y-%m-%d %H:%MZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return None


def date_from_timestamp(value):
    parsed = parse_timestamp(value)
    if parsed:
        return parsed.date().isoformat()
    return normalize_date(value)


def date_from_run_id(run_id):
    if not run_id:
        return None
    return normalize_date(str(run_id).split("T", 1)[0])


def normalize_date(value):
    if not value:
        return None
    text = str(value).strip()
    if len(text) >= 10 and text[4:5] == "-" and text[7:8] == "-":
        return text[:10]
    return None
