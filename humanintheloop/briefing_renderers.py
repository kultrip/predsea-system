def _canal(snapshot):
    return snapshot.get("observations", {}).get("canal_de_ibiza", {})


def _forecast(snapshot):
    return snapshot.get("forecast", {})


def _recommendation(snapshot):
    return snapshot.get("recommendation", {})


def render_linkedin(snapshot):
    canal = _canal(snapshot)
    forecast = _forecast(snapshot)
    rec = _recommendation(snapshot)
    return "\n".join(
        [
            f"PredSea Balearic Briefing | {snapshot['route']}",
            "",
            f"Now: {canal.get('name', 'SOCIB buoy')} reports {canal.get('wave_height_m', 'N/A')} m significant wave height and {canal.get('water_temp_c', 'N/A')} C water.",
            f"Next 24h: forecast wave peak near {forecast.get('wave_max_m', 'N/A')} m around {forecast.get('wave_peak_time', 'N/A')}.",
            f"Captain's read: best crossing window is {rec.get('best_window', 'check manually')}.",
            f"Watch-out: {rec.get('watch_out', 'conditions require manual review')}.",
            f"Confidence: {rec.get('confidence', 'low')}.",
            "",
            "Illustrative route intelligence example, based on public marine data.",
        ]
    )


def render_whatsapp(snapshot):
    canal = _canal(snapshot)
    forecast = _forecast(snapshot)
    rec = _recommendation(snapshot)
    return "\n".join(
        [
            "PredSea Captain's Briefing",
            f"Route: {snapshot['route']}",
            f"Now: {canal.get('wave_height_m', 'N/A')} m waves, water {canal.get('water_temp_c', 'N/A')} C.",
            f"Next 24h: peak near {forecast.get('wave_max_m', 'N/A')} m around {forecast.get('wave_peak_time', 'N/A')}.",
            f"Best window: {rec.get('best_window', 'check manually')}.",
            f"Watch-out: {rec.get('watch_out', 'conditions require manual review')}.",
            f"Confidence: {rec.get('confidence', 'low')}.",
        ]
    )


def render_whatsapp_screenshot_script(snapshot):
    rec = _recommendation(snapshot)
    return "\n".join(
        [
            "Illustrative WhatsApp screenshot script",
            "Captain: [Shared live location]",
            f"PredSea: Got it. You're near Palma Marina. For {snapshot['route']}, the best window looks {rec.get('best_window', 'check manually')}.",
            f"PredSea: Watch-out: {rec.get('watch_out', 'conditions require manual review')}.",
            f"PredSea: Confidence: {rec.get('confidence', 'low')}.",
            "Caption note: illustrative product example based on public marine data.",
        ]
    )
