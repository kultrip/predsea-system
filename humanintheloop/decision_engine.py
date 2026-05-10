import re


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
    return "general_decision"


def answer_question(question, snapshot, location_label="shared location", current_time=None):
    intent = classify_question(question)
    requested_time = extract_requested_time(question)
    rec = snapshot.get("recommendation", {})
    forecast = snapshot.get("forecast", {})
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
        if morning_window_passed:
            if "before midday" in best_window:
                recommendation = "the calmer morning window has passed; avoid timing your departure near the forecast peak"
            else:
                recommendation = f"the morning part of that window has passed; avoid the {wave_peak} peak and reassess after it"
            reason = f"the previous best window was {best_window}, and the main remaining watch-out is: {watch_out}"
        else:
            recommendation = f"leave {best_window}"
            reason = watch_out
    elif intent == "conditions_soon":
        recommendation = "expect conditions to worsen if your timing overlaps the forecast peak"
        reason = f"forecast wave peak is near {wave_max} m around {wave_peak}"
    else:
        recommendation = best_window
        reason = watch_out

    answer = "\n".join(
        [
            f"Recommendation: {recommendation}.",
            f"Reason: {reason}.",
            *([f"Vessel class: {vessel_advice}."] if vessel_advice else []),
            f"Confidence: {confidence}",
        ]
    )
    return {
        "intent": intent,
        "question": question,
        "answer": answer,
        "location_label": location_label,
    }


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
