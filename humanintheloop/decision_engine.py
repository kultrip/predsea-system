import copy
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import captain_knowledge


def classify_question(question):
    text = question.lower()
    if any(word in text for word in ["fuel", "another route", "alternative route", "save"]):
        return "fuel_efficiency"
    if any(word in text for word in ["safe to stay", "stay here", "anchorage", "move"]):
        return "location_safety"
    if any(word in text for word in ["best time", "leave", "depart", "calm window", "set off"]):
        return "leave_window"
    if any(word in text for word in ["in 4 hours", "later", "this afternoon", "how will"]):
        return "conditions_soon"
    if any(word in text for word in ["cross", "tonight", "tomorrow"]):
        return "route_timing"
    return "general_decision"


LOCAL_TIMEZONE = ZoneInfo("Europe/Madrid")


def answer_question(question, snapshot, location_label="shared location", current_time=None, current_date=None):
    intent = classify_question(question)
    requested_time = extract_requested_time(question)
    rec = snapshot.get("recommendation", {})
    timing_context = classify_timing_context(question)
    forecast = forecast_for_question_context(
        snapshot.get("forecast", {}),
        question,
        timing_context=timing_context,
        current_date=current_date,
    )
    best_window = rec.get("best_window", "check manually")
    watch_out = rec.get("watch_out", "conditions require manual review")
    confidence = rec.get("confidence", "low")
    vessel_advice = rec.get("vessel_advice")
    wave_max = forecast.get("wave_max_m", "N/A")
    wave_peak = forecast.get("wave_peak_time", "N/A")
    morning_window_passed = is_morning_window_passed(best_window, current_time)
    requested_time_summary = summarize_requested_time(requested_time, forecast)

    if requested_time_summary:
        recommendation = requested_time_summary["recommendation"]
        reason = requested_time_summary["reason"]
    elif intent == "location_safety":
        recommendation = "stay only if you are sheltered; move earlier if exposed"
        reason = f"near {location_label}, the main watch-out is: {watch_out}"
    elif intent == "fuel_efficiency":
        if morning_window_passed:
            recommendation = "do not optimize around the morning window now; reassess against the afternoon peak"
        else:
            recommendation = f"use the direct route during the {best_window} window; reassess if leaving later"
        reason = f"after the best window, waves/current can increase fuel burn and comfort risk. Current forecast peak: {wave_max} m around {wave_peak}"
    elif intent == "leave_window":
        route_window = summarize_best_departure_window(
            forecast,
            current_time=current_time,
            vessel_profile=snapshot.get("vessel_profile"),
        )
        if timing_context == "tomorrow":
            route_timing = summarize_route_timing(
                timing_context,
                forecast,
                best_window,
                watch_out,
                vessel_profile=snapshot.get("vessel_profile"),
            )
            recommendation = route_timing["recommendation"]
            reason = route_timing["reason"]
        elif route_window and not is_late_day(current_time) and not morning_window_passed:
            recommendation = route_window["recommendation"]
            reason = route_window["reason"]
        elif is_late_day(current_time):
            recommendation = "today's practical daylight window has passed; use this as tomorrow morning planning guidance"
            reason = f"latest route signal is: {watch_out}. Recheck the morning run and buoy observations before committing"
        elif morning_window_passed:
            if "before midday" in best_window:
                recommendation = "the calmer morning window has passed; avoid timing your departure near the forecast peak"
            else:
                recommendation = f"the morning part of that window has passed; avoid the {wave_peak} peak and reassess after it"
            reason = f"the previous best window was {best_window}, and the main remaining watch-out is: {watch_out}"
        else:
            recommendation = f"leave {best_window}"
            reason = watch_out
    elif intent == "conditions_soon":
        if is_manageable_peak(forecast, snapshot.get("vessel_profile", {})):
            recommendation = "conditions look workable; no narrow weather window flagged"
            reason = f"forecast wave peak is only near {wave_max} m around {wave_peak}, with no major wave build-up"
        else:
            recommendation = "expect conditions to worsen if your timing overlaps the forecast peak"
            reason = f"forecast wave peak is near {wave_max} m around {wave_peak}"
    elif intent == "route_timing":
        route_timing = summarize_route_timing(
            timing_context,
            forecast,
            best_window,
            watch_out,
            vessel_profile=snapshot.get("vessel_profile"),
        )
        recommendation = route_timing["recommendation"]
        reason = route_timing["reason"]
    else:
        recommendation = best_window
        reason = watch_out

    evidence_note = render_evidence_note(forecast)
    captain_rule_matches = captain_knowledge.match_rules(snapshot, question_intent=intent)
    answer = render_captain_answer(
        route=snapshot.get("route"),
        intent=intent,
        recommendation=recommendation,
        reason=reason,
        confidence=confidence,
        vessel_advice=vessel_advice,
        vessel_profile=snapshot.get("vessel_profile"),
        vessel_class=snapshot.get("vessel_class"),
        vessel_class_assumed=snapshot.get("vessel_class_assumed", False),
        forecast=forecast,
        freshness=snapshot.get("evidence_freshness"),
        evidence_note=evidence_note,
        captain_rule_matches=captain_rule_matches,
    )
    return {
        "intent": intent,
        "question": question,
        "answer": answer,
        "location_label": location_label,
        "captain_knowledge": captain_knowledge.summarize_matches(captain_rule_matches),
        "forecast_context": forecast,
    }


def render_captain_answer(
    route,
    intent,
    recommendation,
    reason,
    confidence,
    vessel_advice=None,
    vessel_profile=None,
    vessel_class=None,
    vessel_class_assumed=False,
    forecast=None,
    freshness=None,
    evidence_note=None,
    captain_rule_matches=None,
):
    route_prefix = f"{route}: " if route else ""
    forecast = forecast or {}
    display_recommendation = recommendation
    if intent == "conditions_soon" and recommendation.startswith("conditions look workable"):
        display_recommendation = "conditions look workable for the next operational window"

    comfort = render_comfort(forecast, vessel_advice, vessel_profile)
    vessel_context = render_vessel_context(vessel_advice, vessel_profile, vessel_class, vessel_class_assumed)
    if vessel_context:
        comfort = f"{comfort} {vessel_context}"

    freshness = freshness or {}
    freshness_warning = freshness.get("freshness_warning")

    route_segment_reason = render_route_segment_reason(forecast)
    captain_rule_reason = render_captain_rule_reason(captain_rule_matches)
    why_parts = [sentence_case(reason).rstrip(".")]
    if route_segment_reason:
        why_parts.append(route_segment_reason.rstrip("."))
    if captain_rule_reason:
        why_parts.append(captain_rule_reason.rstrip("."))

    lines = [
        f"Decision: {render_decision_line(route_prefix, intent, display_recommendation, forecast, freshness)}",
        f"Best window: {render_best_window(intent, display_recommendation, forecast)}",
        f"Comfort: {comfort}",
        f"Risk: {render_risk(forecast, vessel_advice, vessel_profile)}",
        f"Why: {'. '.join(unique_sentences(why_parts))}.",
    ]

    what_could_change = render_what_could_change(forecast, evidence_note, captain_rule_matches)
    if freshness_warning:
        what_could_change = f"{freshness_warning} {sentence_case(what_could_change)}"
    lines.append(f"What could change: {what_could_change}")

    lines.append(f"Confidence: {render_confidence(confidence, freshness)}")
    return "\n\n".join(lines)


def unique_sentences(parts):
    seen = set()
    unique = []
    for part in parts:
        normalized = " ".join(str(part).lower().split())
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(part)
    return unique


def sentence_case(text):
    if not text:
        return ""
    return text[0].upper() + text[1:]


def render_vessel_context(vessel_advice, vessel_profile=None, vessel_class=None, vessel_class_assumed=False):
    if not vessel_advice and not vessel_profile:
        return (
            "For this vessel size: vessel size was not provided; assuming a medium 15-24m profile. "
            "Share LOA or vessel class for a sharper read."
        )

    label = None
    if isinstance(vessel_profile, dict):
        label = vessel_profile.get("label")
    if not label:
        labels = {"small": "under 15m", "medium": "15-24m", "large": "over 24m"}
        label = labels.get(vessel_class, "the selected vessel class")

    assumption = "Assuming " if vessel_class_assumed else ""
    if not vessel_advice:
        return f"For this vessel size: {assumption}{label}."
    if vessel_advice.startswith("manageable for"):
        advice = vessel_advice.replace("manageable for vessels ", "manageable for ")
        return f"For this vessel size: {assumption}{label}, conditions look manageable."
    if vessel_advice.startswith("restricted for"):
        return f"For this vessel size: {assumption}{label}, treat it as {vessel_advice}."
    if vessel_advice.startswith("caution for"):
        return f"For this vessel size: {assumption}{label}, use conservative timing."
    if vessel_advice:
        return f"For this vessel size: {assumption}{label}, {vessel_advice}."
    return f"For this vessel size: {assumption}{label}."


def render_decision_line(route_prefix, intent, recommendation, forecast, freshness):
    stale = freshness.get("freshness_status") not in (None, "current")
    qualifier = " based on the latest available package" if stale else ""
    if intent == "leave_window":
        if "practical daylight window has passed" in recommendation:
            return f"{route_prefix}{sentence_case(recommendation)}."
        if (
            "looks better than" in recommendation
            or "near the forecast peak" in recommendation
            or "conservative timing" in recommendation
            or "night-crossing option" in recommendation
            or "not a comfort recommendation" in recommendation
        ):
            return f"{route_prefix}{sentence_case(recommendation)}."
        peak_time = forecast.get("wave_peak_time")
        route = route_prefix.replace(": ", "").strip() or "This route"
        target_label = render_target_window_label(forecast)
        if peak_time and peak_time != "N/A":
            return f"{route} is workable {target_label}{qualifier}, but avoid the local peak around {peak_time}."
        return f"{route} is workable {target_label}{qualifier}; no sharp peak is flagged in the available package."
    return f"{route_prefix}{sentence_case(recommendation)}."


def render_target_window_label(forecast):
    period = forecast.get("target_period_label")
    if period == "tomorrow":
        return "tomorrow"
    if period in ("morning", "afternoon", "evening"):
        return f"for the requested {period} window"
    if forecast.get("target_local_date"):
        return "for the requested forecast day"
    return "today"


def render_best_window(intent, recommendation, forecast):
    peak_time = forecast.get("wave_peak_time")
    best = extract_lower_sampled_window(recommendation)
    requested_period = forecast.get("target_period_label")
    departure_context = "if departing today"
    if requested_period in ("morning", "afternoon", "evening"):
        departure_context = f"within the requested {requested_period} window"
    elif forecast.get("target_local_date"):
        departure_context = "within the requested forecast day"
    if best:
        peak_wave = forecast.get("wave_max_m")
        peak_text = f", when wave height peaks around {peak_wave:.1f} m" if isinstance(peak_wave, (int, float)) else ""
        if peak_time and peak_time != "N/A":
            if "daylight" in recommendation:
                return f"Leave around {best} {departure_context}. Avoid the local peak around {peak_time}{peak_text}."
            return f"Leave around {best} {departure_context}. Conditions are expected to worsen near {peak_time}{peak_text}."
        return f"Leave around {best} {departure_context}."
    if "lower sampled window is around" in recommendation:
        return sentence_case(recommendation) + "."
    if "leave " in recommendation.lower() or "depart" in recommendation.lower():
        return sentence_case(recommendation) + "."
    if peak_time and peak_time != "N/A":
        return f"Prefer the lower sea-state window and avoid the forecast peak around {peak_time}."
    if intent == "location_safety":
        return "Stay only while sheltered; move earlier if exposure increases."
    return "No narrow departure window identified from the available evidence."


def extract_lower_sampled_window(text):
    match = re.search(
        r"lower sampled (?:practical daylight )?window is around ([0-2]?\d:[0-5]\d)",
        text or "",
        re.IGNORECASE,
    )
    if not match:
        return None
    hour, minute = match.group(1).split(":", 1)
    return f"{int(hour):02d}:{minute}"


def render_comfort(forecast, vessel_advice, vessel_profile):
    wave_max = forecast.get("wave_max_m")
    if wave_max is None:
        return "Unknown from this package; forecast wave height is missing."

    manageable = None
    restricted = None
    if isinstance(vessel_profile, dict):
        manageable = vessel_profile.get("manageable_m")
        restricted = vessel_profile.get("restricted_m")

    if restricted is not None and wave_max >= restricted:
        level = "Poor"
        detail = "Expect uncomfortable motion on exposed sections."
    elif manageable is not None and wave_max >= manageable:
        level = "Moderate to poor"
        detail = "Manageable only with conservative timing; guests may find it uncomfortable."
    elif vessel_advice and "caution" in vessel_advice:
        level = "Moderate"
        detail = "Workable, but not flat calm for guests or sensitive passengers."
    else:
        level = "Moderate to good"
        detail = "Generally manageable, with comfort still depending on period, direction, and passenger sensitivity."
    return f"{level}. {detail}"


def render_risk(forecast, vessel_advice, vessel_profile):
    wave_max = forecast.get("wave_max_m")
    peak_time = forecast.get("wave_peak_time")
    if wave_max is None:
        return "Manual review required; wave forecast is missing."
    if vessel_advice and "restricted" in vessel_advice:
        level = "High for this vessel size"
    elif vessel_advice and "caution" in vessel_advice:
        level = "Moderate"
    else:
        level = "Low to moderate"

    peak = f" Peak wave height is near {wave_max:.1f} m"
    if peak_time and peak_time != "N/A":
        peak = f"{peak} around {peak_time}"
    return f"{level}.{peak}."


def render_route_segment_reason(forecast):
    worst_segment = ((forecast.get("route_segments") or {}).get("worst_segment") or {})
    if not worst_segment:
        return None
    name = worst_segment.get("name")
    peak_time = worst_segment.get("peak_time")
    wave = worst_segment.get("max_wave_m")
    sea_state = worst_segment.get("sea_state")
    if not name or wave is None:
        return None
    detail = f"Worst route segment is {name}, near {wave:.1f} m"
    if peak_time:
        detail = f"{detail} around {peak_time}"
    if sea_state:
        detail = f"{detail}, with a {sea_state}"
    return f"{detail}."


def render_captain_rule_reason(captain_rule_matches):
    if not captain_rule_matches:
        return None
    rule = captain_rule_matches[0]
    consequence = rule.get("operational_consequence")
    if not consequence:
        return None
    return f"Captain knowledge: {consequence}"


def render_what_could_change(forecast, evidence_note, captain_rule_matches=None):
    checks = []
    if forecast.get("wave_peak_time") not in (None, "N/A"):
        checks.append("the timing or height of the forecast peak shifts in the next run")
    if not has_wave_partition_detail(forecast):
        checks.append("swell and wind-wave partition data changes the comfort read")
    if forecast.get("current_max_kn") is None:
        checks.append("current data is missing or updates materially")
    if not checks:
        checks.append("buoy observations or the next model run diverge from this forecast")
    if captain_rule_matches:
        action = captain_rule_matches[0].get("preferred_action")
        if action:
            checks.append(action.rstrip("."))

    detail = "; ".join(check.rstrip(".") for check in checks)
    if evidence_note:
        return f"{detail}. {evidence_note}"
    return f"{detail}."


def render_confidence(confidence, freshness):
    warning = freshness.get("freshness_warning")
    if warning:
        return f"{confidence}, because the latest evidence package should be confirmed with the next morning run."
    return f"{confidence}."


def has_wave_partition_detail(forecast):
    return any(
        forecast.get(key) is not None
        for key in (
            "swell_1_height_m",
            "swell_1_direction_deg",
            "swell_2_height_m",
            "swell_2_direction_deg",
            "wind_wave_height_m",
            "wind_wave_direction_deg",
        )
    )


def classify_timing_context(question):
    text = question.lower()
    if "tonight" in text:
        return "tonight"
    if "tomorrow" in text:
        return "tomorrow"
    if "this afternoon" in text or "afternoon" in text:
        return "afternoon"
    return None


def forecast_for_question_context(forecast, question, timing_context=None, current_date=None):
    target_date = target_local_date_for_question(question, timing_context=timing_context, current_date=current_date)
    if not target_date:
        return forecast

    hourly = forecast.get("hourly") or []
    day_part = requested_day_part(question, timing_context=timing_context)
    filtered_hourly = [
        localized_hourly_row(row)
        for row in hourly
        if row_local_date(row) == target_date and row_matches_day_part(row, day_part)
    ]
    if not filtered_hourly:
        return forecast

    filtered = copy.deepcopy(forecast)
    filtered["hourly"] = filtered_hourly
    filtered["target_local_date"] = target_date.isoformat()
    filtered["target_period_label"] = day_part or timing_context or "today"
    # Existing route_segments are aggregate summaries over the whole downloaded package.
    # Drop them after day filtering so the answer does not cite stale segment peaks.
    filtered["route_segments"] = {}
    update_forecast_extrema_from_hourly(filtered)
    return filtered


def requested_day_part(question, timing_context=None):
    text = question.lower()
    if "morning" in text:
        return "morning"
    if "afternoon" in text or timing_context == "afternoon":
        return "afternoon"
    if "evening" in text:
        return "evening"
    return None


def row_matches_day_part(row, day_part):
    if not day_part:
        return True
    parsed = parse_row_time_utc(row)
    if parsed is None:
        return True
    minutes = parsed.astimezone(LOCAL_TIMEZONE).hour * 60 + parsed.astimezone(LOCAL_TIMEZONE).minute
    if day_part == "morning":
        return 6 * 60 <= minutes < 12 * 60
    if day_part == "afternoon":
        return 12 * 60 <= minutes < 18 * 60
    if day_part == "evening":
        return 18 * 60 <= minutes <= 22 * 60
    return True


def localized_hourly_row(row):
    localized = copy.deepcopy(row)
    parsed = parse_row_time_utc(row)
    if parsed is None:
        return localized
    local_time = parsed.astimezone(LOCAL_TIMEZONE)
    localized.setdefault("time_model", localized.get("time"))
    localized["time"] = local_time.strftime("%H:%M")
    localized["time_local"] = local_time.strftime("%Y-%m-%d %H:%M")
    return localized


def target_local_date_for_question(question, timing_context=None, current_date=None):
    text = question.lower()
    base_date = parse_local_date(current_date)
    if base_date is None:
        return None
    timing_context = timing_context or classify_timing_context(question)
    if timing_context == "tomorrow":
        return base_date + timedelta(days=1)
    if timing_context == "tonight" or "today" in text:
        return base_date
    return None


def parse_local_date(value):
    if isinstance(value, date):
        return value
    if not value:
        return None
    text = str(value).strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def row_local_date(row):
    parsed = parse_row_time_utc(row)
    if parsed is None:
        return None
    return parsed.astimezone(LOCAL_TIMEZONE).date()


def parse_row_time_utc(row):
    value = row.get("time_utc")
    if not value:
        return None
    text = str(value).strip().replace(" UTC", "Z")
    for fmt in ("%Y-%m-%d %H:%MZ", "%Y-%m-%dT%H:%MZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=ZoneInfo("UTC"))
        except ValueError:
            continue
    return None


def update_forecast_extrema_from_hourly(forecast):
    hourly = forecast.get("hourly") or []
    wave_rows = [row for row in hourly if row.get("wave_m") is not None]
    if wave_rows:
        min_row = min(wave_rows, key=lambda row: row["wave_m"])
        peak_row = max(wave_rows, key=lambda row: row["wave_m"])
        forecast["wave_min_m"] = min_row.get("wave_m")
        forecast["wave_max_m"] = peak_row.get("wave_m")
        forecast["wave_peak_time"] = peak_row.get("time")
        copy_peak_field(forecast, peak_row, "wave_direction_deg", "wave_peak_direction_deg")
        copy_peak_field(forecast, peak_row, "wave_sea_state", "wave_peak_sea_state")
        for component in ("swell_1", "swell_2", "wind_wave"):
            copy_peak_field(forecast, peak_row, f"{component}_height_m", f"{component}_height_m")
            copy_peak_field(forecast, peak_row, f"{component}_direction_deg", f"{component}_direction_deg")

    current_rows = [row for row in hourly if row.get("current_kn") is not None]
    if current_rows:
        current_peak = max(current_rows, key=lambda row: row["current_kn"])
        forecast["current_max_kn"] = current_peak.get("current_kn")
        forecast["current_peak_time"] = current_peak.get("time")


def copy_peak_field(forecast, peak_row, source_key, target_key):
    if peak_row.get(source_key) is not None:
        forecast[target_key] = peak_row.get(source_key)


def summarize_route_timing(timing_context, forecast, best_window, watch_out, vessel_profile=None):
    wave_max = forecast.get("wave_max_m", "N/A")
    wave_peak = forecast.get("wave_peak_time", "N/A")
    current_max = forecast.get("current_max_kn")
    current_text = f" Current peak is near {current_max} kn." if current_max is not None else ""
    hourly_count = len(forecast.get("hourly") or [])

    if timing_context == "tonight":
        return {
            "recommendation": "Tonight looks workable on sea state, but treat it as a night crossing rather than a simple green light",
            "reason": (
                f"forecast wave peak is near {wave_max} m around {wave_peak}, with the main watch-out: {watch_out}."
                f"{current_text} Recheck the latest buoy observations before departure because darkness reduces visual margin"
            ),
        }
    if timing_context == "tomorrow":
        route_window = summarize_best_departure_window(
            forecast,
            current_time=None,
            vessel_profile=vessel_profile,
        )
        if isinstance(wave_max, (int, float)) and isinstance(vessel_profile, dict):
            restricted = vessel_profile.get("restricted_m")
            manageable = vessel_profile.get("manageable_m")
            coverage = render_hourly_coverage(hourly_count)
            if restricted is not None and wave_max >= restricted:
                return {
                    "recommendation": "tomorrow morning is not a comfort recommendation for this vessel size unless the morning run improves",
                    "reason": (
                        f"forecast peak is near {wave_max} m around {wave_peak}{coverage}. "
                        "That is above this vessel profile's restricted threshold, so the morning peak is the watch-out, not the best window"
                    ),
                }
            if manageable is not None and wave_max >= manageable:
                return {
                    "recommendation": (
                        route_window["recommendation"]
                        if route_window
                        else "tomorrow looks possible only with conservative timing for this vessel size"
                    ),
                    "reason": (
                        route_window["reason"]
                        if route_window
                        else f"forecast peak is near {wave_max} m around {wave_peak}{coverage}. "
                        "Use the lower sampled window and confirm with the morning run before committing"
                    ),
                }
        coverage = render_hourly_coverage(hourly_count)
        if route_window:
            requested_period = forecast.get("target_period_label")
            period_text = f" {requested_period}" if requested_period in ("morning", "afternoon", "evening") else ""
            return {
                "recommendation": f"tomorrow{period_text} looks workable; {route_window['recommendation']}",
                "reason": f"{route_window['reason']}. Confirm with the morning run before committing",
            }
        return {
            "recommendation": "Tomorrow looks workable based on the latest forecast package",
            "reason": (
                f"forecast peak is near {wave_max} m around {wave_peak}{coverage}. "
                "Morning should be the better planning window; confirm with the morning run before committing"
            ),
        }
    if timing_context == "afternoon":
        return {
            "recommendation": f"for the afternoon, use the {best_window} guidance and avoid any local peak window",
            "reason": f"main watch-out is: {watch_out}; forecast wave peak is near {wave_max} m around {wave_peak}.{current_text}",
        }
    return {
        "recommendation": best_window,
        "reason": watch_out,
    }


def render_hourly_coverage(hourly_count):
    if not hourly_count:
        return " in the current forecast package"
    if hourly_count == 1:
        return " in the available sampled forecast point"
    return f" across {hourly_count} forecast time points"


def extract_requested_time(question):
    match = re.search(r"\b([01]?\d|2[0-3])(?::([0-5]\d))?\b", question)
    if not match:
        return None
    hour = int(match.group(1))
    minute = match.group(2) or "00"
    return f"{hour:02d}:{minute}"


def summarize_requested_time(requested_time, forecast):
    if not requested_time:
        return None
    hourly = forecast.get("hourly") or []
    row = next((item for item in hourly if item.get("time") == requested_time), None)
    if not row:
        return None

    wave = row.get("wave_m")
    peak_time = forecast.get("wave_peak_time", "N/A")
    peak_wave = forecast.get("wave_max_m")
    if wave is None or peak_wave is None:
        return None

    if requested_time == peak_time:
        recommendation = f"{requested_time} is near the forecast peak; avoid it if comfort matters"
    elif wave < peak_wave:
        recommendation = f"{requested_time} looks better than the {peak_time} peak"
    else:
        recommendation = f"{requested_time} still looks exposed; reassess closer to departure"

    reason = f"forecast is about {wave:.1f} m at {requested_time}, versus the peak near {peak_wave:.1f} m around {peak_time}"
    current = row.get("current_kn")
    if current is not None:
        reason = f"{reason}; current about {current:.1f} kn"
    return {"recommendation": recommendation, "reason": reason}


def summarize_best_departure_window(forecast, current_time=None, vessel_profile=None):
    hourly = forecast.get("hourly") or []
    peak_time = forecast.get("wave_peak_time", "N/A")
    peak_wave = forecast.get("wave_max_m")
    candidates = [
        row for row in hourly
        if row.get("time") != peak_time
        and row.get("wave_m") is not None
        and is_future_or_current_time(row.get("time"), current_time)
    ]
    if not candidates or peak_wave is None or peak_time == "N/A":
        return None

    practical_candidates = [row for row in candidates if is_practical_daylight_time(row.get("time"))]
    non_peak_practical_candidates = [
        row for row in practical_candidates
        if not is_near_time(row.get("time"), peak_time, minutes=90)
    ]
    candidate_pool = non_peak_practical_candidates or practical_candidates or candidates
    best = best_operational_candidate(candidate_pool)
    best_time = best.get("time")
    best_wave = best.get("wave_m")
    if best_time is None or best_wave is None:
        return None

    peak_direction = forecast.get("wave_peak_direction_deg")
    direction_text = ""
    if peak_direction is not None:
        direction_text = f" Mean wave direction near the peak is about {peak_direction:.0f} degrees"

    practical_note = "practical daylight " if is_practical_daylight_time(best_time) else ""
    recommendation_prefix = f"avoid the local peak around {peak_time}; the lower sampled {practical_note}window is around {best_time}"
    if is_night_time(best_time):
        recommendation_prefix = (
            f"avoid the {peak_time} peak; the lower sampled window is around {best_time}, "
            "but that is a night-crossing option"
        )

    if isinstance(peak_wave, (int, float)) and isinstance(vessel_profile, dict):
        restricted = vessel_profile.get("restricted_m")
        manageable = vessel_profile.get("manageable_m")
        if restricted is not None and peak_wave >= restricted:
            recommendation_prefix = f"not a comfort recommendation during the local peak around {peak_time}; {recommendation_prefix}"
        elif manageable is not None and peak_wave >= manageable:
            recommendation_prefix = f"possible today with conservative timing; {recommendation_prefix}"

    return {
        "recommendation": recommendation_prefix,
        "reason": (
            f"forecast peak is near {peak_wave:.1f} m around {peak_time}, while the sampled route value "
            f"near {best_time} is about {best_wave:.1f} m.{direction_text}"
        ),
    }


def is_practical_daylight_time(candidate_time):
    minutes = time_to_minutes(candidate_time)
    if minutes is None:
        return False
    return 6 * 60 <= minutes <= 20 * 60


def best_operational_candidate(candidates, tolerance_m=0.15):
    if not candidates:
        return None
    best_wave = min(row.get("wave_m", 999) for row in candidates)
    near_best = [
        row for row in candidates
        if row.get("wave_m") is not None and row.get("wave_m", 999) <= best_wave + tolerance_m
    ]
    return min(near_best or candidates, key=lambda row: time_to_minutes(row.get("time")) or 9999)


def is_night_time(candidate_time):
    minutes = time_to_minutes(candidate_time)
    if minutes is None:
        return False
    return minutes > 20 * 60 or minutes < 6 * 60


def is_near_time(candidate_time, target_time, minutes=90):
    candidate_minutes = time_to_minutes(candidate_time)
    target_minutes = time_to_minutes(target_time)
    if candidate_minutes is None or target_minutes is None:
        return False
    return abs(candidate_minutes - target_minutes) <= minutes


def is_future_or_current_time(candidate_time, current_time):
    if not current_time or not candidate_time:
        return True
    candidate_minutes = time_to_minutes(candidate_time)
    current_minutes = time_to_minutes(current_time)
    if candidate_minutes is None or current_minutes is None:
        return True
    return candidate_minutes >= current_minutes


def time_to_minutes(value):
    match = re.search(r"\b([01]?\d|2[0-3])(?::([0-5]\d))?\b", str(value))
    if not match:
        return None
    return int(match.group(1)) * 60 + int(match.group(2) or "00")


def render_evidence_note(forecast):
    component_note = render_wave_component_note(forecast)
    if component_note:
        return component_note

    has_components = any(
        key in forecast
        for key in (
            "swell_1_height_m",
            "swell_1_direction_deg",
            "swell_2_height_m",
            "swell_2_direction_deg",
            "wind_wave_height_m",
            "wind_wave_direction_deg",
        )
    )
    if has_components:
        return None
    if forecast.get("wave_peak_direction_deg") is not None:
        return (
            "Evidence note: this uses combined wave height and mean wave direction; "
            "swell and wind-wave components are not available in this evidence package."
        )
    return (
        "Evidence note: this uses combined wave height only; swell direction and wind-wave "
        "components are not available in this evidence package."
    )


def render_wave_component_note(forecast):
    parts = []
    sea_state = forecast.get("wave_peak_sea_state")
    peak_direction = forecast.get("wave_peak_direction_deg")
    if sea_state and peak_direction is not None:
        parts.append(f"At the peak, combined seas are a {sea_state} from about {peak_direction:.0f} degrees")
    elif sea_state:
        parts.append(f"At the peak, combined seas are a {sea_state}")

    component_texts = []
    for component_name, label in (
        ("swell_1", "Primary swell"),
        ("swell_2", "secondary swell"),
        ("wind_wave", "wind wave"),
    ):
        height = forecast.get(f"{component_name}_height_m")
        direction = forecast.get(f"{component_name}_direction_deg")
        if height is None and direction is None:
            continue
        if height is not None and direction is not None:
            component_texts.append(f"{label} {height:.1f} m from {direction:.0f} degrees")
        elif height is not None:
            component_texts.append(f"{label} {height:.1f} m")
        else:
            component_texts.append(f"{label} from {direction:.0f} degrees")
    if component_texts:
        parts.append("; ".join(component_texts))

    if not parts:
        return None
    return "Sea-state detail: " + ". ".join(parts) + "."


def is_morning_window_passed(best_window, current_time):
    if "morning" not in best_window and best_window != "before midday":
        return False
    if not current_time:
        return False
    hour_text = str(current_time).split(":", 1)[0]
    try:
        hour = int(hour_text)
    except ValueError:
        return False
    return hour >= 12


def is_late_day(current_time):
    if not current_time:
        return False
    hour_text = str(current_time).split(":", 1)[0]
    try:
        hour = int(hour_text)
    except ValueError:
        return False
    return hour >= 20


def is_manageable_peak(forecast, vessel_profile):
    wave_max = forecast.get("wave_max_m")
    if wave_max is None:
        return False
    manageable_m = vessel_profile.get("manageable_m", 1.2)
    return float(wave_max) < float(manageable_m)


def render_decision_screenshot_script(decision):
    lines = [
        "Illustrative WhatsApp screenshot script",
        "Captain: [Shared live location]",
        f"Captain: {decision['question']}",
    ]
    for answer_line in decision["answer"].splitlines():
        lines.append(f"PredSea: {answer_line}")
    lines.append("Caption note: illustrative product example based on public marine data.")
    return "\n".join(lines)
