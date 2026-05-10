import argparse
import json
import os
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None


PROJECT_ROOT = Path(__file__).resolve().parents[1]
HUMANINTHELOOP_DIR = PROJECT_ROOT / "humanintheloop"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "outputs"
DEFAULT_LOCAL_TIMEZONE = "Europe/Madrid"
REQUIRED_TEXT_ARTIFACTS = (
    "daily_snapshot.json",
    "briefing_linkedin.txt",
    "briefing_whatsapp.txt",
    "briefing_whatsapp_screenshot_script.txt",
)


@contextmanager
def pushd(path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def today_local(timezone_name=DEFAULT_LOCAL_TIMEZONE):
    if ZoneInfo is None:
        return datetime.now().date().isoformat()
    return datetime.now(ZoneInfo(timezone_name)).date().isoformat()


def current_time_local(timezone_name=DEFAULT_LOCAL_TIMEZONE):
    if ZoneInfo is None:
        return datetime.now().strftime("%H:%M")
    return datetime.now(ZoneInfo(timezone_name)).strftime("%H:%M")


def load_mvp_modules():
    human_path = str(HUMANINTHELOOP_DIR)
    if human_path not in sys.path:
        sys.path.insert(0, human_path)

    import briefing
    import chat_figure
    import fetch_data
    import route_analysis

    return SimpleNamespace(
        briefing=briefing,
        chat_figure=chat_figure,
        fetch_data=fetch_data,
        route_analysis=route_analysis,
    )


def route_ids_from_args(route_analysis, route_ids):
    routes = route_analysis.load_routes()
    if not route_ids:
        return sorted(routes)

    unknown = sorted(set(route_ids) - set(routes))
    if unknown:
        available = ", ".join(sorted(routes))
        raise ValueError(f"Unknown route id(s): {', '.join(unknown)}. Available routes: {available}")
    return route_ids


def required_artifacts_for(skip_figures=False):
    artifacts = list(REQUIRED_TEXT_ARTIFACTS)
    if not skip_figures:
        artifacts.append("predsea_whatsapp_figure.png")
    return artifacts


def validate_route_artifacts(route_dir, skip_figures=False):
    missing = [name for name in required_artifacts_for(skip_figures) if not (route_dir / name).exists()]
    if missing:
        raise RuntimeError(f"{route_dir} missing required artifact(s): {', '.join(missing)}")


def maybe_generate_chat_figure(chat_figure, route_dir, logo_path, skip_figures=False):
    if skip_figures:
        return None
    if not logo_path or not Path(logo_path).exists():
        print(f"Logo not found at {logo_path}; skipping WhatsApp-style figure for {route_dir.name}.")
        return None

    output_path = route_dir / "predsea_whatsapp_figure.png"
    chat_figure.generate_chat_figure(
        route_dir / "briefing_whatsapp_screenshot_script.txt",
        logo_path,
        output_path,
        platform="WhatsApp",
    )
    return output_path


def write_manifest(day_dir, run_date, routes, vessel_class):
    manifest = {
        "run_date": run_date,
        "route_count": len(routes),
        "routes": routes,
        "vessel_class": vessel_class,
        "created_at_utc": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    }
    (day_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def generate_daily_briefings(
    output_root=DEFAULT_OUTPUT_ROOT,
    run_date=None,
    route_ids=None,
    vessel_class="medium",
    question=None,
    location_label="Palma Marina",
    current_time=None,
    logo_path=None,
    skip_figures=False,
):
    modules = load_mvp_modules()
    run_date = run_date or today_local()
    current_time = current_time or current_time_local()
    output_root = Path(output_root).resolve()
    day_dir = output_root / run_date
    day_dir.mkdir(parents=True, exist_ok=True)

    selected_route_ids = route_ids_from_args(modules.route_analysis, route_ids)
    routes = modules.route_analysis.load_routes()

    with pushd(HUMANINTHELOOP_DIR):
        observations = modules.briefing.load_observations()
        modules.fetch_data.get_balearic_forecast(dry_run=False)

        for route_id in selected_route_ids:
            route = routes[route_id]
            forecast = modules.route_analysis.forecast_summary_from_files(
                Path(modules.fetch_data.OUTPUT_DIR) / "balearic_waves.nc",
                Path(modules.fetch_data.OUTPUT_DIR) / "balearic_currents.nc",
                route=route,
            )
            snapshot = modules.route_analysis.build_route_snapshot(
                observations,
                forecast,
                route=route,
                vessel_class=vessel_class,
            )
            route_dir = day_dir / route_id
            modules.briefing.write_outputs(
                snapshot,
                output_dir=route_dir,
                question=question,
                location_label=location_label,
                current_time=current_time,
            )
            figure_path = maybe_generate_chat_figure(
                modules.chat_figure,
                route_dir,
                logo_path,
                skip_figures=skip_figures,
            )
            validate_route_artifacts(route_dir, skip_figures=skip_figures or figure_path is None)

    write_manifest(day_dir, run_date, selected_route_ids, vessel_class)
    return SimpleNamespace(output_dir=day_dir, routes=selected_route_ids)


def parse_args():
    parser = argparse.ArgumentParser(description="Generate daily PredSea route briefing artifacts.")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--date", dest="run_date", help="Local run date, YYYY-MM-DD. Defaults to Europe/Madrid today.")
    parser.add_argument("--route", action="append", dest="route_ids", help="Route ID to generate. Repeat for multiple.")
    parser.add_argument("--vessel-class", default="medium", choices=["small", "medium", "large"])
    parser.add_argument("--question", help="Optional captain question to answer for each route snapshot.")
    parser.add_argument("--location-label", default="Palma Marina")
    parser.add_argument("--current-time", help="Local HH:MM for timing-sensitive decision text.")
    parser.add_argument(
        "--logo-path",
        default=os.environ.get("PREDSEA_LOGO_PATH", str(PROJECT_ROOT / "assets" / "predsea_logo.png")),
        help="Logo path for WhatsApp-style figures. Figures are skipped if the file is missing.",
    )
    parser.add_argument("--skip-figures", action="store_true", help="Only generate text/JSON artifacts.")
    return parser.parse_args()


def main():
    args = parse_args()
    result = generate_daily_briefings(
        output_root=args.output_root,
        run_date=args.run_date,
        route_ids=args.route_ids,
        vessel_class=args.vessel_class,
        question=args.question,
        location_label=args.location_label,
        current_time=args.current_time,
        logo_path=args.logo_path,
        skip_figures=args.skip_figures,
    )
    print(f"Wrote PredSea daily briefing artifacts to {result.output_dir}")
    print(f"Routes: {', '.join(result.routes)}")


if __name__ == "__main__":
    main()
