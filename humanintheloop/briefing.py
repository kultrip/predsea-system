import argparse
import json
from datetime import datetime
from pathlib import Path

import briefing_renderers
import decision_engine
import fetch_data
import route_analysis
import socib_public


OUTPUT_DIR = Path("mvp_data")


def load_observations():
    response = socib_public.requests.get(socib_public.PUBLIC_URL, timeout=30)
    response.raise_for_status()
    return socib_public.extract_public_observations(response.json())


def build_forecast_summary(route):
    fetch_data.get_balearic_forecast(dry_run=False)
    return route_analysis.forecast_summary_from_files(
        OUTPUT_DIR / "balearic_waves.nc",
        OUTPUT_DIR / "balearic_currents.nc",
        route=route,
    )


def route_output_dir(root, route):
    return Path(root) / "routes" / route["id"]


def write_outputs(snapshot, output_dir=OUTPUT_DIR, question=None, location_label="Palma Marina", current_time=None):
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    (output_path / "daily_snapshot.json").write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    (output_path / "briefing_linkedin.txt").write_text(briefing_renderers.render_linkedin(snapshot), encoding="utf-8")
    (output_path / "briefing_whatsapp.txt").write_text(briefing_renderers.render_whatsapp(snapshot), encoding="utf-8")
    screenshot_script = briefing_renderers.render_whatsapp_screenshot_script(snapshot)
    if question:
        decision = decision_engine.answer_question(
            question,
            snapshot,
            location_label=location_label,
            current_time=current_time,
        )
        (output_path / "decision_answer.txt").write_text(decision["answer"], encoding="utf-8")
        screenshot_script = decision_engine.render_decision_screenshot_script(decision)
    (output_path / "briefing_whatsapp_screenshot_script.txt").write_text(screenshot_script, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Generate PredSea briefing artifacts.")
    parser.add_argument("--route", default=route_analysis.DEFAULT_ROUTE_ID, help="Route ID from routes.json.")
    parser.add_argument(
        "--vessel-class",
        default="medium",
        choices=sorted(route_analysis.VESSEL_PROFILES),
        help="Vessel size class for recommendation thresholds.",
    )
    parser.add_argument("--list-routes", action="store_true", help="Print available routes and exit.")
    parser.add_argument("--question", help="Captain question to answer from the generated snapshot.")
    parser.add_argument("--location-label", default="Palma Marina", help="Human-friendly label for shared location demos.")
    parser.add_argument("--current-time", help="Override local HH:MM used for decision timing, useful for demos.")
    args = parser.parse_args()

    if args.list_routes:
        for route_id, route in sorted(route_analysis.load_routes().items()):
            print(f"{route_id}: {route['name']}")
        return

    route = route_analysis.load_route(args.route)
    observations = load_observations()
    forecast = build_forecast_summary(route)
    snapshot = route_analysis.build_route_snapshot(
        observations,
        forecast,
        route=route,
        vessel_class=args.vessel_class,
    )
    write_outputs(
        snapshot,
        output_dir=route_output_dir(OUTPUT_DIR, route),
        question=args.question,
        location_label=args.location_label,
        current_time=args.current_time or datetime.now().strftime("%H:%M"),
    )
    print(f"Wrote PredSea briefing artifacts to {route_output_dir(OUTPUT_DIR, route)}/")


if __name__ == "__main__":
    main()
