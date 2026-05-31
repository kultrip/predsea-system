import argparse
import importlib.util
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
    "evidence.json",
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


def current_run_id_utc():
    return datetime.utcnow().strftime("%Y-%m-%dT%H%MZ")


def load_mvp_modules():
    human_path = str(HUMANINTHELOOP_DIR)
    if human_path not in sys.path:
        sys.path.insert(0, human_path)

    import briefing
    import chat_figure
    import fetch_data
    import map_generator
    import route_analysis

    return SimpleNamespace(
        briefing=briefing,
        chat_figure=chat_figure,
        fetch_data=fetch_data,
        map_generator=map_generator,
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


def required_artifacts_for(skip_figures=False, skip_maps=False):
    artifacts = list(REQUIRED_TEXT_ARTIFACTS)
    if not skip_figures:
        artifacts.append("predsea_whatsapp_figure.png")
    if not skip_maps:
        artifacts.append("route_decision_map.png")
    return artifacts


def validate_route_artifacts(route_dir, skip_figures=False, skip_maps=False):
    missing = [name for name in required_artifacts_for(skip_figures, skip_maps) if not (route_dir / name).exists()]
    if missing:
        raise RuntimeError(f"{route_dir} missing required artifact(s): {', '.join(missing)}")


def resolve_repo_path(path):
    if path is None:
        return None
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return PROJECT_ROOT / candidate


def validate_forecast_available(forecast, route_id):
    missing = []
    if forecast.get("wave_max_m") is None:
        missing.append("wave forecast")
    if forecast.get("current_max_kn") is None:
        missing.append("current forecast")
    if missing:
        raise RuntimeError(f"Forecast layer unavailable for {route_id}: {', '.join(missing)}")


def maybe_generate_chat_figure(chat_figure, route_dir, logo_path, skip_figures=False):
    if skip_figures:
        return None
    resolved_logo_path = resolve_repo_path(logo_path)
    if not resolved_logo_path or not resolved_logo_path.exists():
        raise RuntimeError(f"Logo not found at {resolved_logo_path}; cannot generate WhatsApp-style figure.")

    output_path = route_dir / "predsea_whatsapp_figure.png"
    chat_figure.generate_chat_figure(
        route_dir / "briefing_whatsapp_screenshot_script.txt",
        resolved_logo_path,
        output_path,
        platform="WhatsApp",
    )
    return output_path


def maybe_generate_route_map(map_generator, route_dir, route, snapshot, waves_path, currents_path, skip_maps=False):
    if skip_maps:
        return None
    output_path = route_dir / "route_decision_map.png"
    publication_map = load_publication_map_generator()
    publication_map.generate_ocean_conditions_map(
        waves_path,
        output_path,
        currents_path=currents_path,
        requested_time=snapshot.get("forecast", {}).get("wave_peak_time"),
        title="PredSea Balearic Sea Conditions",
        resolution_label="Copernicus Med forecast grid",
        coastline_resolution="10m",
        extent=[0.9, 4.55, 38.55, 40.55],
        dpi=220,
        arrow_density="normal",
        arrow_color="black",
    )
    return output_path


def maybe_generate_leaflet_overlays(run_dir, waves_path, currents_path, skip_maps=False):
    if skip_maps:
        return None
    overlay_generator = load_leaflet_overlay_generator()
    return overlay_generator.generate_leaflet_overlays(
        waves_path,
        currents_path,
        run_dir,
        variables=["wave_height", "current_speed"],
    )


def load_publication_map_generator():
    module_path = PROJECT_ROOT / "scripts" / "generate_ocean_conditions_map.py"
    spec = importlib.util.spec_from_file_location("predsea_publication_map_generator", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_leaflet_overlay_generator():
    module_path = PROJECT_ROOT / "scripts" / "generate_leaflet_overlays.py"
    spec = importlib.util.spec_from_file_location("predsea_leaflet_overlay_generator", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_manifest(run_dir, run_date, run_id, routes, vessel_class):
    manifest = {
        "run_date": run_date,
        "run_id": run_id,
        "route_count": len(routes),
        "routes": routes,
        "vessel_class": vessel_class,
        "created_at_utc": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    }
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def write_latest_run(day_dir, run_date, run_id, routes, vessel_class):
    latest = {
        "run_date": run_date,
        "run_id": run_id,
        "path": f"runs/{run_id}",
        "route_count": len(routes),
        "routes": routes,
        "vessel_class": vessel_class,
        "created_at_utc": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    }
    (day_dir / "latest_run.json").write_text(json.dumps(latest, indent=2), encoding="utf-8")
    return latest


def generate_daily_briefings(
    output_root=DEFAULT_OUTPUT_ROOT,
    run_date=None,
    route_ids=None,
    vessel_class="medium",
    question=None,
    location_label="Palma Marina",
    current_time=None,
    run_id=None,
    logo_path=None,
    skip_figures=False,
    skip_maps=False,
):
    modules = load_mvp_modules()
    run_date = run_date or today_local()
    run_id = run_id or current_run_id_utc()
    current_time = current_time or current_time_local()
    logo_path = resolve_repo_path(logo_path)
    output_root = Path(output_root).resolve()
    day_dir = output_root / run_date
    day_dir.mkdir(parents=True, exist_ok=True)
    run_dir = day_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    selected_route_ids = route_ids_from_args(modules.route_analysis, route_ids)
    routes = modules.route_analysis.load_routes()

    with pushd(HUMANINTHELOOP_DIR):
        observations = modules.briefing.load_observations()
        modules.fetch_data.get_balearic_forecast(dry_run=False)
        waves_path = Path(modules.fetch_data.OUTPUT_DIR) / "balearic_waves.nc"
        currents_path = Path(modules.fetch_data.OUTPUT_DIR) / "balearic_currents.nc"
        maybe_generate_leaflet_overlays(run_dir, waves_path, currents_path, skip_maps=skip_maps)

        for route_id in selected_route_ids:
            route = routes[route_id]
            forecast = modules.route_analysis.forecast_summary_from_files(
                waves_path,
                currents_path,
                route=route,
            )
            validate_forecast_available(forecast, route_id)
            snapshot = modules.route_analysis.build_route_snapshot(
                observations,
                forecast,
                route=route,
                vessel_class=vessel_class,
            )
            route_dir = run_dir / route_id
            modules.briefing.write_outputs(
                snapshot,
                output_dir=route_dir,
                question=question,
                location_label=location_label,
                current_time=current_time,
                route=route,
            )
            figure_path = maybe_generate_chat_figure(
                modules.chat_figure,
                route_dir,
                logo_path,
                skip_figures=skip_figures,
            )
            map_path = maybe_generate_route_map(
                modules.map_generator,
                route_dir,
                route,
                snapshot,
                waves_path,
                currents_path,
                skip_maps=skip_maps,
            )
            validate_route_artifacts(route_dir, skip_figures=skip_figures, skip_maps=skip_maps)

    write_manifest(run_dir, run_date, run_id, selected_route_ids, vessel_class)
    write_latest_run(day_dir, run_date, run_id, selected_route_ids, vessel_class)
    return SimpleNamespace(output_dir=run_dir, day_dir=day_dir, run_id=run_id, routes=selected_route_ids)


def parse_args():
    parser = argparse.ArgumentParser(description="Generate daily PredSea route briefing artifacts.")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--date", dest="run_date", help="Local run date, YYYY-MM-DD. Defaults to Europe/Madrid today.")
    parser.add_argument("--run-id", help="Run identifier. Defaults to current UTC time, e.g. 2026-05-31T0630Z.")
    parser.add_argument("--route", action="append", dest="route_ids", help="Route ID to generate. Repeat for multiple.")
    parser.add_argument("--vessel-class", default="medium", choices=["small", "medium", "large"])
    parser.add_argument("--question", help="Optional captain question to answer for each route snapshot.")
    parser.add_argument("--location-label", default="Palma Marina")
    parser.add_argument("--current-time", help="Local HH:MM for timing-sensitive decision text.")
    parser.add_argument(
        "--logo-path",
        default=os.environ.get("PREDSEA_LOGO_PATH", str(PROJECT_ROOT / "assets" / "predsea_logo.png")),
        help="Logo path for WhatsApp-style figures. Relative paths resolve from the repo root.",
    )
    parser.add_argument("--skip-figures", action="store_true", help="Only generate text/JSON artifacts.")
    parser.add_argument("--skip-maps", action="store_true", help="Do not generate route Decision Map artifacts.")
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
        run_id=args.run_id,
        logo_path=args.logo_path,
        skip_figures=args.skip_figures,
        skip_maps=args.skip_maps,
    )
    print(f"Wrote PredSea daily briefing artifacts to {result.output_dir}")
    print(f"Run ID: {result.run_id}")
    print(f"Routes: {', '.join(result.routes)}")


if __name__ == "__main__":
    main()
