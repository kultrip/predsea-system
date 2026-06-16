import argparse
import importlib.util
import json
import os
import subprocess
import shutil
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
COPERNICUS_GCS_PREFIX = "gs://predsea-daily-outputs/copernicus"
COPERNICUS_LATEST_WAVES_GCS_URI = f"{COPERNICUS_GCS_PREFIX}/waves_latest.nc"
COPERNICUS_LATEST_CURRENTS_GCS_URI = f"{COPERNICUS_GCS_PREFIX}/currents_latest.nc"
ROUTES_GCS_PREFIX = "gs://predsea-daily-outputs/routes"
PRECOMPUTE_ROUTES_SCRIPT = HUMANINTHELOOP_DIR / "files" / "precompute_routes.py"
DEFAULT_LOCAL_TIMEZONE = "Europe/Madrid"
ROUTE_PRECOMPUTE_TIMEOUT_SECONDS = int(os.environ.get("PREDSEA_ROUTE_PRECOMPUTE_TIMEOUT_SECONDS", "1200"))
REQUIRED_TEXT_ARTIFACTS = (
    "daily_snapshot.json",
    "evidence.json",
    "briefing_linkedin.txt",
    "briefing_whatsapp.txt",
    "briefing_whatsapp_screenshot_script.txt",
)
DEFAULT_REGION_ID = "balearics"
REGIONAL_LIMITATIONS = (
    "No seabed type",
    "No depth/bathymetry",
    "No anchoring restrictions",
    "No nearby shelter search",
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

    import bigquery_export
    import briefing
    import chat_figure
    import fetch_data
    import forecast_sources
    import ingest_atmosphere
    import ingest_observations
    import map_generator
    import place_weather
    import route_analysis
    import validation_archive

    return SimpleNamespace(
        briefing=briefing,
        chat_figure=chat_figure,
        bigquery_export=bigquery_export,
        fetch_data=fetch_data,
        forecast_sources=forecast_sources,
        ingest_atmosphere=ingest_atmosphere,
        ingest_observations=ingest_observations,
        map_generator=map_generator,
        place_weather=place_weather,
        route_analysis=route_analysis,
        validation_archive=validation_archive,
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


def upload_file_to_gcs(local_path, gcs_uri):
    local_path = Path(local_path)
    if not local_path.exists():
        raise FileNotFoundError(f"Local file not found: {local_path}")
    if not gcs_uri.startswith("gs://"):
        raise ValueError(f"Expected GCS URI, got {gcs_uri!r}")
    from google.cloud import storage

    bucket_name, blob_name = gcs_uri[5:].split("/", 1)
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.upload_from_filename(str(local_path))
    return gcs_uri


def publish_latest_copernicus_files(source):
    published = {}
    uploads = {
        "waves_path": COPERNICUS_LATEST_WAVES_GCS_URI,
        "currents_path": COPERNICUS_LATEST_CURRENTS_GCS_URI,
    }
    for key, gcs_uri in uploads.items():
        local_path = source.get(key)
        if local_path is None:
            continue
        try:
            upload_file_to_gcs(local_path, gcs_uri)
            print(f"Uploaded {key} to {gcs_uri}", flush=True)
            published[key] = gcs_uri
        except Exception as error:
            print(
                f"Warning: could not upload {key} to {gcs_uri}; "
                f"continuing with local path {local_path}. {error}",
                flush=True,
            )
            published[key] = str(local_path)
    return published


def run_route_precompute(waves_path, currents_path, run_date, run_id):
    if not PRECOMPUTE_ROUTES_SCRIPT.exists():
        raise FileNotFoundError(f"Route precompute script not found: {PRECOMPUTE_ROUTES_SCRIPT}")

    command = [
        sys.executable,
        str(PRECOMPUTE_ROUTES_SCRIPT),
        "--waves",
        str(waves_path),
        "--currents",
        str(currents_path),
        "--output-dir",
        ROUTES_GCS_PREFIX,
        "--date",
        run_date,
        "--forecast-run-utc",
        run_id,
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            check=False,
            text=True,
            capture_output=True,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
            timeout=ROUTE_PRECOMPUTE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(
            f"Route precompute timed out after {ROUTE_PRECOMPUTE_TIMEOUT_SECONDS}s"
        ) from error
    if completed.stdout:
        print(completed.stdout.rstrip(), flush=True)
    if completed.stderr:
        print(completed.stderr.rstrip(), flush=True)
    if completed.returncode != 0:
        raise RuntimeError(
            f"Route precompute exited with code {completed.returncode}: "
            f"{(completed.stderr or completed.stdout or '').strip()}"
        )
    return True


def validate_forecast_available(forecast, route_id):
    missing = []
    if forecast.get("wave_max_m") is None:
        missing.append("wave forecast")
    if forecast.get("current_max_kn") is None:
        missing.append("current forecast")
    if missing:
        raise RuntimeError(f"Forecast layer unavailable for {route_id}: {', '.join(missing)}")


def safe_load_observations(briefing):
    try:
        return briefing.load_observations()
    except Exception as error:
        print(f"Warning: SOCIB observations unavailable; continuing without buoy truth. {error}")
        return {}


def safe_load_observation_bundle(briefing):
    try:
        if hasattr(briefing, "load_observation_bundle"):
            return briefing.load_observation_bundle()
    except Exception as error:
        print(f"Warning: observation bundle unavailable; continuing with empty observations. {error}")
    return {"observations": safe_load_observations(briefing), "station_metadata": []}


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


def maybe_generate_route_map(map_generator, route_dir, route, snapshot, waves_path, currents_path, skip_maps=False, resolution_label="Copernicus Med forecast grid"):
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
        resolution_label=resolution_label,
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
        variables=sorted(overlay_generator.VARIABLES),
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


def map_supported_modes(available_variables):
    modes = ["route_question"]
    if available_variables:
        modes.extend(["location_question", "map_inspect"])
    return modes


def collect_map_variable_metadata(run_dir):
    maps_dir = run_dir / "maps"
    if not maps_dir.exists():
        return {}

    variables = {}
    for index_path in sorted(maps_dir.glob("*/index.json")):
        index = json.loads(index_path.read_text(encoding="utf-8"))
        overlays = index.get("overlays") or []
        times = sorted(overlay["time"] for overlay in overlays if overlay.get("time"))
        first_with_bounds = next((overlay for overlay in overlays if overlay.get("bounds")), None)
        variable = index.get("variable") or index_path.parent.name
        variables[variable] = {
            "units": index.get("units"),
            "time_count": len(overlays),
            "time_start": times[0] if times else None,
            "time_end": times[-1] if times else None,
            "bounds": first_with_bounds.get("bounds") if first_with_bounds else None,
            "color_scale": index.get("color_scale"),
            "opacity": index.get("opacity"),
            "index_path": str(index_path.relative_to(run_dir)),
        }
    return variables


def write_regional_evidence(run_dir, run_date, run_id, routes, forecast_sources=None, region_id=DEFAULT_REGION_ID):
    available_variables = collect_map_variable_metadata(run_dir)
    regional_evidence = {
        "region_id": region_id,
        "run_date": run_date,
        "run_id": run_id,
        "supported_modes": map_supported_modes(available_variables),
        "routes": routes,
        "forecast_sources": forecast_sources or [],
        "available_variables": available_variables,
        "limitations": list(REGIONAL_LIMITATIONS),
        "created_at_utc": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    }
    (run_dir / "regional_evidence.json").write_text(json.dumps(regional_evidence, indent=2, default=str), encoding="utf-8")
    return regional_evidence


def regional_evidence_manifest_entry(regional_evidence):
    return {
        "path": "regional_evidence.json",
        "region_id": regional_evidence["region_id"],
        "supported_modes": regional_evidence["supported_modes"],
        "available_variables": sorted(regional_evidence["available_variables"]),
    }


def validation_manifest_entry(validation_summary):
    if not validation_summary:
        return None
    return {
        "path": "validation/validation_summary.json",
        "observation_samples_path": "validation/observation_samples.jsonl",
        "forecast_index_path": "validation/forecast_index.jsonl",
        "matched_validation_path": "validation/matched_validation.jsonl",
        "station_metadata_path": "validation/station_metadata.jsonl",
        "observation_rows": validation_summary.get("observation_rows", 0),
        "forecast_rows": validation_summary.get("forecast_rows", 0),
        "matched_rows": validation_summary.get("matched_rows", 0),
        "station_metadata_rows": validation_summary.get("station_metadata_rows", 0),
        "matched_variables": validation_summary.get("matched_variables", {}),
    }


def load_preferred_snapshots(run_dir, route_ids):
    snapshots = {}
    for route_id in route_ids:
        snapshot_path = Path(run_dir) / route_id / "daily_snapshot.json"
        snapshots[route_id] = json.loads(snapshot_path.read_text(encoding="utf-8"))
    return snapshots


def write_manifest(run_dir, run_date, run_id, routes, vessel_class, forecast_sources=None, regional_evidence=None, validation=None):
    manifest = {
        "run_date": run_date,
        "run_id": run_id,
        "route_count": len(routes),
        "routes": routes,
        "vessel_class": vessel_class,
        "forecast_sources": forecast_sources or [],
        "regional_evidence": regional_evidence,
        "validation": validation,
        "created_at_utc": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    }
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def write_latest_run(day_dir, run_date, run_id, routes, vessel_class, regional_evidence=None, validation=None):
    latest = {
        "run_date": run_date,
        "run_id": run_id,
        "path": f"runs/{run_id}",
        "route_count": len(routes),
        "routes": routes,
        "vessel_class": vessel_class,
        "regional_evidence": regional_evidence,
        "validation": validation,
        "created_at_utc": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    }
    (day_dir / "latest_run.json").write_text(json.dumps(latest, indent=2), encoding="utf-8")
    return latest


def fetch_forecast_sources(modules, run_dir):
    if hasattr(modules, "forecast_sources"):
        return modules.forecast_sources.fetch_available_forecasts(
            modules.fetch_data,
            output_dir=Path(modules.fetch_data.OUTPUT_DIR),
            dry_run=False,
        )

    modules.fetch_data.get_balearic_forecast(dry_run=False)
    output_dir = Path(modules.fetch_data.OUTPUT_DIR)
    return [
        {
            "id": "copernicus",
            "label": "Copernicus Marine Mediterranean forecast",
            "available": True,
            "preferred": True,
            "waves_path": output_dir / "balearic_waves.nc",
            "currents_path": output_dir / "balearic_currents.nc",
        }
    ]


def available_forecast_sources(sources):
    return [source for source in sources if source.get("available")]


def preferred_forecast_source(sources):
    available = available_forecast_sources(sources)
    if not available:
        return None
    return next((source for source in available if source.get("preferred")), available[0])


def cached_forecast_source(fetch_data):
    output_dir = Path(getattr(fetch_data, "OUTPUT_DIR", PROJECT_ROOT / "mvp_data"))
    candidate_dirs = [
        output_dir,
        output_dir / "copernicus",
        PROJECT_ROOT / "mvp_data",
        PROJECT_ROOT / "mvp_data" / "copernicus",
    ]
    seen = set()
    for candidate_dir in candidate_dirs:
        candidate_dir = Path(candidate_dir).resolve()
        if candidate_dir in seen:
            continue
        seen.add(candidate_dir)
        waves_path = candidate_dir / "balearic_waves.nc"
        currents_path = candidate_dir / "balearic_currents.nc"
        if waves_path.exists() and currents_path.exists():
            print(
                "Warning: no live forecast source available; reusing cached Copernicus bundle "
                f"from {candidate_dir}.",
                flush=True,
            )
            return {
                "id": "copernicus",
                "label": "Cached Copernicus Marine Mediterranean forecast",
                "available": True,
                "preferred": True,
                "cached": True,
                "waves_path": waves_path,
                "currents_path": currents_path,
                "metadata": {
                    "source_type": "cached_bundle",
                    "cache_dir": str(candidate_dir),
                },
            }
    return None


def source_manifest_entries(modules, sources):
    if hasattr(modules, "forecast_sources"):
        entries = []
        for source in sources:
            entry = modules.forecast_sources.source_manifest_entry(source)
            if source.get("metadata") and "metadata" not in entry:
                entry["metadata"] = source["metadata"]
            if source.get("cached") and "metadata" not in entry:
                entry["metadata"] = {
                    "source_type": "cached_bundle",
                    "cache_dir": str(Path(source.get("waves_path", "")).parent) if source.get("waves_path") else None,
                }
            entries.append(entry)
        return entries
    return [
        {
            "id": source.get("id"),
            "label": source.get("label"),
            "available": bool(source.get("available")),
            "preferred": bool(source.get("preferred")),
        }
        for source in sources
    ]


def atmospheric_ingestion_enabled():
    return os.environ.get("PREDSEA_ENABLE_ATMOSPHERIC_INGESTION", "0") == "1"


def fetch_atmospheric_context(modules, run_dir):
    if not atmospheric_ingestion_enabled():
        return {
            "enabled": False,
            "wind_result": {"available": False, "source": None},
            "wind_lineage": {
                "source": None,
                "resolution_km": None,
                "status": "not_configured",
                "tier": None,
            },
        }

    try:
        atmosphere_dir = Path(run_dir) / "atmosphere"
        result = modules.ingest_atmosphere.run_atmospheric_ingestion(
            output_dir=atmosphere_dir,
            dry_run=False,
        )
        result["enabled"] = True
        return result
    except Exception as error:
        return {
            "enabled": True,
            "wind_result": {"available": False, "source": None, "error": str(error)},
            "wind_lineage": {
                "source": None,
                "resolution_km": None,
                "status": "error",
                "tier": None,
            },
        }


def ocean_lineage_for_source(source):
    source_id = source.get("id")
    if source_id == "socib":
        return {
            "source": "socib_wmop_sapo",
            "resolution_km": source.get("metadata", {}).get("resolution_km"),
            "status": "active",
        }
    return {
        "source": "copernicus_med",
        "resolution_km": 4.0,
        "status": "active",
    }


def ground_truth_lineage_for_observations(observations):
    if observations:
        return {
            "source": "socib_observations",
            "status": "matched_successfully",
            "station_count": len(observations),
        }
    return {
        "source": None,
        "status": "unavailable",
        "station_count": 0,
    }


def data_lineage_for_snapshot(source, atmospheric_context, observations):
    return {
        "wind_forecast": atmospheric_context.get(
            "wind_lineage",
            {
                "source": None,
                "resolution_km": None,
                "status": "not_configured",
                "tier": None,
            },
        ),
        "ocean_forecast": ocean_lineage_for_source(source),
        "ground_truth_validation": ground_truth_lineage_for_observations(observations),
    }


def annotate_snapshot_with_source(snapshot, source):
    snapshot["forecast_source"] = {
        "id": source.get("id"),
        "label": source.get("label"),
        "preferred": bool(source.get("preferred")),
    }
    if source.get("cached"):
        snapshot["forecast_source"]["cached"] = True
    if source.get("metadata"):
        snapshot["forecast_source"]["metadata"] = source["metadata"]
    return snapshot


def annotate_snapshot_with_lineage(snapshot, source, atmospheric_context, observations):
    snapshot["data_lineage"] = data_lineage_for_snapshot(source, atmospheric_context, observations)
    return snapshot


def resolution_label_for(source):
    source_id = source.get("id")
    if source_id == "socib":
        return "SOCIB WMOP/SAPO forecast grid"
    return "Copernicus Med forecast grid"


def copy_preferred_route_artifacts(source_route_dir, preferred_route_dir):
    if preferred_route_dir.exists():
        shutil.rmtree(preferred_route_dir)
    shutil.copytree(source_route_dir, preferred_route_dir)


def generate_route_artifacts_for_source(
    modules,
    source,
    source_root_dir,
    selected_route_ids,
    routes,
    observations,
    vessel_class,
    question,
    location_label,
    current_time,
    logo_path,
    skip_figures,
    skip_maps,
    atmospheric_context=None,
):
    waves_path = Path(source["waves_path"])
    currents_path = Path(source["currents_path"])
    maybe_generate_leaflet_overlays(source_root_dir, waves_path, currents_path, skip_maps=skip_maps)
    generated_routes = {}

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
        annotate_snapshot_with_source(snapshot, source)
        annotate_snapshot_with_lineage(snapshot, source, atmospheric_context or {}, observations)
        route_dir = source_root_dir / route_id
        modules.briefing.write_outputs(
            snapshot,
            output_dir=route_dir,
            question=question,
            location_label=location_label,
            current_time=current_time,
            route=route,
        )
        maybe_generate_chat_figure(
            modules.chat_figure,
            route_dir,
            logo_path,
            skip_figures=skip_figures,
        )
        maybe_generate_route_map(
            modules.map_generator,
            route_dir,
            route,
            snapshot,
            waves_path,
            currents_path,
            skip_maps=skip_maps,
            resolution_label=resolution_label_for(source),
        )
        validate_route_artifacts(route_dir, skip_figures=skip_figures, skip_maps=skip_maps)
        generated_routes[route_id] = route_dir
    return generated_routes


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
        observation_bundle = safe_load_observation_bundle(modules.briefing)
        observations = observation_bundle.get("observations", {})
        station_metadata = observation_bundle.get("station_metadata", [])
        sources = fetch_forecast_sources(modules, run_dir)
        preferred_source = preferred_forecast_source(sources)
        if preferred_source is None:
            preferred_source = cached_forecast_source(modules.fetch_data)
            if preferred_source is None:
                raise RuntimeError(
                    "No forecast source available and no cached Copernicus bundle found; "
                    "cannot generate PredSea evidence package."
                )
            sources.append(preferred_source)
        atmospheric_context = fetch_atmospheric_context(modules, run_dir)

        for source in available_forecast_sources(sources):
            source_root_dir = run_dir / "sources" / source["id"]
            generated_routes = generate_route_artifacts_for_source(
                modules,
                source,
                source_root_dir,
                selected_route_ids,
                routes,
                observations,
                vessel_class,
                question,
                location_label,
                current_time,
                logo_path,
                skip_figures,
                skip_maps,
                atmospheric_context=atmospheric_context,
            )
            if source["id"] == preferred_source["id"]:
                maybe_generate_leaflet_overlays(run_dir, Path(source["waves_path"]), Path(source["currents_path"]), skip_maps=skip_maps)
                for route_id, source_route_dir in generated_routes.items():
                    copy_preferred_route_artifacts(source_route_dir, run_dir / route_id)

        place_weather_module = getattr(modules, "place_weather", None)
        if place_weather_module is not None:
            place_weather_module.write_place_weather_outputs(
                run_dir,
                run_date,
                run_id,
                preferred_source["waves_path"],
                preferred_source["currents_path"],
                observations=observations,
                station_metadata=station_metadata,
                place_ids=place_weather_module.available_place_ids(),
                time_text=current_time,
            )

    forecast_source_entries = source_manifest_entries(modules, sources)
    if atmospheric_context.get("enabled") or atmospheric_context.get("wind_lineage", {}).get("status") != "not_configured":
        forecast_source_entries.append(
            {
                "id": "atmospheric_wind",
                "label": "Tiered atmospheric wind forecast",
                "available": bool(atmospheric_context.get("wind_result", {}).get("available")),
                "preferred": False,
                "metadata": {
                    "wind_lineage": atmospheric_context.get("wind_lineage"),
                    "fetchers_configured": atmospheric_context.get("fetchers_configured", []),
                    "error": atmospheric_context.get("wind_result", {}).get("error"),
                },
            }
    )
    regional_evidence = write_regional_evidence(
        run_dir,
        run_date,
        run_id,
        selected_route_ids,
        forecast_sources=forecast_source_entries,
    )
    regional_manifest_entry = regional_evidence_manifest_entry(regional_evidence)
    preferred_snapshots = load_preferred_snapshots(run_dir, selected_route_ids)
    validation_summary = None
    if hasattr(modules, "validation_archive"):
        validation_summary = modules.validation_archive.write_validation_archive(
            run_dir,
            run_date,
            run_id,
            routes,
            preferred_snapshots,
            observations,
            output_root,
            station_metadata=station_metadata,
        )
    if hasattr(modules, "bigquery_export"):
        bigquery_export_result = modules.bigquery_export.export_validation_archive_to_bigquery(
            run_dir,
            dry_run=False,
        )
        print(
            f"BigQuery export: {bigquery_export_result.get('status')} "
            f"({bigquery_export_result.get('exported_rows', 0)} rows)",
            flush=True,
        )
        if hasattr(modules.bigquery_export, "export_station_metadata_to_bigquery"):
            station_metadata_export_result = modules.bigquery_export.export_station_metadata_to_bigquery(
                run_dir,
                dry_run=False,
            )
            print(
                f"Station metadata export: {station_metadata_export_result.get('status')} "
                f"({station_metadata_export_result.get('exported_rows', 0)} rows)",
                flush=True,
            )
    validation_entry = validation_manifest_entry(validation_summary)

    write_manifest(
        run_dir,
        run_date,
        run_id,
        selected_route_ids,
        vessel_class,
        forecast_sources=forecast_source_entries,
        regional_evidence=regional_manifest_entry,
        validation=validation_entry,
    )
    write_latest_run(
        day_dir,
        run_date,
        run_id,
        selected_route_ids,
        vessel_class,
        regional_evidence=regional_manifest_entry,
        validation=validation_entry,
    )

    if not os.environ.get("PYTEST_CURRENT_TEST"):
        try:
            published_sources = publish_latest_copernicus_files(preferred_source)
            run_route_precompute(
                waves_path=published_sources.get("waves_path", preferred_source["waves_path"]),
                currents_path=published_sources.get("currents_path", preferred_source["currents_path"]),
                run_date=run_date,
                run_id=run_id,
            )
        except Exception as error:
            print(f"Warning: route precompute skipped or failed; continuing without route cache. {error}", flush=True)

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
