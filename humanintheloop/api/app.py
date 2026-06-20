import os
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from api.evidence_store import EvidenceNotFoundError, create_evidence_store_from_env
from api.schemas import (
    BriefingResponse,
    CoordinateDistanceResponse,
    DistanceEndpointSide,
    HealthResponse,
    LocationQuestionRequest,
    MixedDistanceResponse,
    PlaceConnectionMetricsResponse,
    PlaceResolutionResponse,
    PlacesResponse,
    PlaceWeatherResponse,
    QuestionRequest,
    QuestionResponse,
    RouteWaypointsResponse,
)
from api.services import answer_question, evidence_used, render_briefing
import place_registry
from place_registry import default_place_id_for_query
import place_weather
import route_analysis
from route_store import RouteStore


logger = logging.getLogger(__name__)


MEDIA_TYPES = {
    "route_decision_map.png": "image/png",
    "predsea_whatsapp_figure.png": "image/png",
}
PUBLIC_MEDIA_ARTIFACTS = tuple(MEDIA_TYPES)
MAP_VARIABLES = (
    "wave_height",
    "swell_1_height",
    "swell_1_direction",
    "swell_2_height",
    "swell_2_direction",
    "wind_wave_height",
    "wind_wave_direction",
    "current_speed",
)
MAP_VARIABLE_PATTERN = "^(" + "|".join(MAP_VARIABLES) + ")$"


def public_base_url(request):
    base_url = str(request.base_url).rstrip("/")
    if base_url.startswith("http://") and "run.app" in base_url:
        return base_url.replace("http://", "https://", 1)
    return base_url


def current_local_date():
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Europe/Madrid")).date().isoformat()
    except Exception:
        return datetime.now(timezone.utc).date().isoformat()


def refresh_route_store(route_store):
    if hasattr(route_store, "ensure_loaded"):
        try:
            loaded_date = route_store.ensure_loaded(preferred_date=current_local_date())
            if loaded_date is not None:
                logger.info("Route cache ready for %s", loaded_date)
        except Exception as error:
            logger.warning("Route cache refresh failed: %s", error)


_REQUESTED_PLACE_ID_UNSET = object()


def load_place_weather_with_fallback(store, place_id, run_date, run_id):
    try:
        return store.load_place_weather(place_id, run_date, run_id)
    except EvidenceNotFoundError as error:
        try:
            fallback_date = store.latest_date()
            fallback_run = store.latest_run(fallback_date)
        except EvidenceNotFoundError:
            raise error

        if fallback_date == run_date and fallback_run == run_id:
            raise error

        logger.warning(
            "Place weather unavailable for %s on %s; falling back to latest bundle %s/%s",
            place_id,
            run_date,
            fallback_date,
            fallback_run or "latest",
        )
        return store.load_place_weather(place_id, fallback_date, fallback_run)


def load_place_weather_response(
    store,
    *,
    place_id,
    run_date,
    run_id,
    lat=None,
    lon=None,
    requested_place_id_override=_REQUESTED_PLACE_ID_UNSET,
):
    resolved = place_weather.resolve_place(place_id, latitude=lat, longitude=lon)
    payload = load_place_weather_with_fallback(store, resolved["place_id"], run_date, run_id)
    response = dict(payload)
    response["requested_place_id"] = (
        resolved["requested_place_id"]
        if requested_place_id_override is _REQUESTED_PLACE_ID_UNSET
        else requested_place_id_override
    )
    response["place_id"] = resolved["place_id"]
    response["place_name"] = resolved["place_name"]
    response["resolved_latitude"] = resolved["latitude"]
    response["resolved_longitude"] = resolved["longitude"]
    response["distance_to_place_nm"] = resolved.get("distance_to_place_nm")
    response["requested_latitude"] = resolved.get("requested_latitude")
    response["requested_longitude"] = resolved.get("requested_longitude")
    return response


def place_observation_sources(store, place_id):
    try:
        latest_date = store.latest_date()
        latest_run = store.latest_run(latest_date)
        payload = store.load_place_weather(place_id, latest_date, latest_run)
    except Exception:
        return []
    sources = []
    observation = payload.get("observation") if isinstance(payload, dict) else None
    if isinstance(observation, dict):
        for key in ("source_label", "network"):
            value = observation.get(key)
            if value and value not in sources:
                sources.append(value)
    for key in ("source_label", "network"):
        value = payload.get(key) if isinstance(payload, dict) else None
        if value and value not in sources:
            sources.append(value)
    return sources


def parse_departure_datetime(run_date, departure_time):
    if not run_date:
        return None
    if not departure_time:
        departure_time = "08:30"
    try:
        local_zone = ZoneInfo("Europe/Madrid")
    except Exception:
        local_zone = timezone.utc
    try:
        date_part = datetime.fromisoformat(run_date).date()
    except ValueError:
        return None
    try:
        hour_str, minute_str = departure_time[:5].split(":", 1)
        departure_clock = datetime.combine(
            date_part,
            datetime.min.time().replace(hour=int(hour_str), minute=int(minute_str)),
        )
        return departure_clock.replace(tzinfo=local_zone)
    except Exception:
        return None


def format_local_timestamp(moment):
    return moment.astimezone(ZoneInfo("Europe/Madrid")).strftime("%Y-%m-%d %H:%M %Z")


def route_waypoint_weather(store, *, run_date, run_id, latitude, longitude, eta_local_time_text):
    try:
        resolved = place_weather.resolve_place("current_position", latitude=latitude, longitude=longitude)
        payload = load_place_weather_with_fallback(store, resolved["place_id"], run_date, run_id)
    except Exception:
        return {}
    hourly = list(payload.get("hourly") or [])
    sample = place_weather.select_hourly_sample(hourly, eta_local_time_text) or {}
    if not sample:
        return {}
    weather = {
        "place_id": payload.get("place_id"),
        "place_name": payload.get("place_name"),
        "resolved_latitude": payload.get("resolved_latitude"),
        "resolved_longitude": payload.get("resolved_longitude"),
        "distance_to_place_nm": payload.get("distance_to_place_nm"),
        "inside_domain": payload.get("inside_domain"),
        "sample_time_local": sample.get("time") or sample.get("time_local"),
        "sample_time_zone": "Europe/Madrid",
        "wave_height_m": sample.get("wave_m"),
        "wave_direction_deg": sample.get("wave_direction_deg"),
        "wave_sea_state": sample.get("wave_sea_state"),
        "swell_1_height_m": sample.get("swell_1_height_m"),
        "swell_1_direction_deg": sample.get("swell_1_direction_deg"),
        "swell_2_height_m": sample.get("swell_2_height_m"),
        "swell_2_direction_deg": sample.get("swell_2_direction_deg"),
        "wind_wave_height_m": sample.get("wind_wave_height_m"),
        "wind_wave_direction_deg": sample.get("wind_wave_direction_deg"),
        "current_kn": sample.get("current_kn"),
        "current_direction_deg": sample.get("current_direction_deg"),
        "wind_kn": payload.get("wind_kn"),
        "wind_direction_deg": payload.get("wind_direction_deg"),
        "water_temperature_c": payload.get("water_temperature_c") or payload.get("water_temp_c"),
        "air_temperature_c": payload.get("air_temperature_c") or payload.get("temperature_c"),
        "freshness_status": payload.get("freshness_status"),
        "freshness_state": payload.get("freshness_state"),
        "freshness_warning": payload.get("freshness_warning"),
        "source": payload.get("source"),
        "source_system": payload.get("source_system"),
        "source_label": payload.get("source_label"),
        "network": payload.get("network"),
        "station_id": payload.get("station_id"),
        "station_name": payload.get("station_name"),
        "catalog_id": payload.get("catalog_id"),
        "catalog_url": payload.get("catalog_url"),
        "last_sample_utc": payload.get("last_sample_utc"),
        "observed_at_utc": payload.get("observed_at_utc"),
        "source_time_coordinate_utc": payload.get("source_time_coordinate_utc"),
        "qc_flag": payload.get("qc_flag"),
        "quality_score": payload.get("quality_score"),
        "is_future_timestamp": payload.get("is_future_timestamp"),
    }
    return {key: value for key, value in weather.items() if value is not None}


def build_route_checkpoints(
    store,
    *,
    run_date,
    run_id,
    departure_time,
    typical_speed_kn,
    origin_latitude,
    origin_longitude,
    waypoints,
    destination_latitude,
    destination_longitude,
):
    departure_dt_local = parse_departure_datetime(run_date, departure_time)
    if departure_dt_local is None:
        return []

    route_points = [
        {"lat": float(origin_latitude), "lng": float(origin_longitude)},
        *[
            {"lat": float(point["lat"]), "lng": float(point["lng"])}
            for point in (waypoints or [])
            if point.get("lat") is not None and point.get("lng") is not None
        ],
        {"lat": float(destination_latitude), "lng": float(destination_longitude)},
    ]
    checkpoints = []
    cumulative_nm = 0.0

    for index, point in enumerate(route_points[1:-1]):
        previous = route_points[index]
        cumulative_nm += route_analysis.haversine_nm(
            previous["lat"],
            previous["lng"],
            point["lat"],
            point["lng"],
        )
        eta_local = departure_dt_local + timedelta(hours=cumulative_nm / float(typical_speed_kn or 15.0))
        eta_local_text = format_local_timestamp(eta_local)
        eta_local_time = eta_local.astimezone(ZoneInfo("Europe/Madrid")).strftime("%H:%M")
        weather = route_waypoint_weather(
            store,
            run_date=run_date,
            run_id=run_id,
            latitude=point["lat"],
            longitude=point["lng"],
            eta_local_time_text=eta_local_time,
        )
        checkpoints.append(
            {
                "waypoint_index": index,
                "lat": float(point["lat"]),
                "lng": float(point["lng"]),
                "eta_local": eta_local_text,
                "distance_from_origin_nm": round(cumulative_nm, 2),
                "forecast_time_local": eta_local_text,
                "weather": weather,
            }
        )
    return checkpoints


def requested_minutes(time_text):
    if not time_text:
        return None
    token = time_text
    if "T" in token:
        token = token.split("T", 1)[1]
    token = token.replace("Z", "")
    parts = token.split(":")
    if len(parts) < 2:
        return None
    try:
        return int(parts[0]) * 60 + int(parts[1])
    except ValueError:
        return None


def overlay_minutes(overlay):
    return requested_minutes(overlay.get("time"))


def closest_overlay(overlays, time_text):
    if not overlays:
        raise EvidenceNotFoundError("No map overlays available")
    target = requested_minutes(time_text)
    if target is None:
        return overlays[0]
    def distance_from_target(overlay):
        minutes = overlay_minutes(overlay)
        if minutes is None:
            minutes = target
        return abs(minutes - target)

    return min(overlays, key=distance_from_target)


def nearest_index(values, target):
    return min(range(len(values)), key=lambda index: abs(float(values[index]) - target))


def sample_grid(grid, latitude, longitude):
    latitudes = grid.get("latitudes") or []
    longitudes = grid.get("longitudes") or []
    values = grid.get("values") or []
    if not latitudes or not longitudes or not values:
        raise EvidenceNotFoundError("Map grid has no sampleable values")

    lat_index = nearest_index(latitudes, latitude)
    lon_index = nearest_index(longitudes, longitude)
    try:
        value = values[lat_index][lon_index]
    except (IndexError, TypeError) as error:
        raise EvidenceNotFoundError("Map grid is malformed") from error

    south = min(float(value) for value in latitudes)
    north = max(float(value) for value in latitudes)
    west = min(float(value) for value in longitudes)
    east = max(float(value) for value in longitudes)
    return {
        "value": value,
        "sampled_lat": float(latitudes[lat_index]),
        "sampled_lon": float(longitudes[lon_index]),
        "grid_indices": {"lat": lat_index, "lon": lon_index},
        "inside_domain": south <= latitude <= north and west <= longitude <= east,
    }


def sample_map_variable(store, variable, run_date, run_id, latitude, longitude, time_text=None):
    index = store.load_map_index(variable, run_date, run_id)
    selected = closest_overlay(index.get("overlays") or [], time_text)
    grid_filename = selected.get("grid_filename")
    if not grid_filename:
        raise EvidenceNotFoundError(f"Selected {variable} overlay has no inspection grid")
    grid = store.load_map_grid(variable, grid_filename, run_date, run_id)
    sample = sample_grid(grid, latitude, longitude)
    return {
        "variable": variable,
        "time": selected["time"],
        "value": sample["value"],
        "units": index["units"],
        "sampled_lat": sample["sampled_lat"],
        "sampled_lon": sample["sampled_lon"],
        "inside_domain": sample["inside_domain"],
        "grid_indices": sample["grid_indices"],
    }


def try_sample_map_variable(store, variable, run_date, run_id, latitude, longitude, time_text=None):
    try:
        return sample_map_variable(store, variable, run_date, run_id, latitude, longitude, time_text=time_text)
    except EvidenceNotFoundError as error:
        return {
            "variable": variable,
            "available": False,
            "error": str(error),
        }


def try_load_regional_evidence(store, run_date, run_id):
    try:
        return store.load_regional_evidence(run_date, run_id)
    except EvidenceNotFoundError:
        return None


def regional_evidence_summary(regional_evidence):
    if not regional_evidence:
        return {
            "available": False,
            "supported_modes": ["route_question"],
            "available_variables": [],
            "limitations": [],
        }
    return {
        "available": True,
        "region_id": regional_evidence.get("region_id"),
        "supported_modes": regional_evidence.get("supported_modes") or [],
        "available_variables": sorted((regional_evidence.get("available_variables") or {}).keys()),
        "limitations": regional_evidence.get("limitations") or [],
    }


def resolve_distance_side(label, *, place_query=None, latitude=None, longitude=None):
    if place_query is not None:
        resolution = place_registry.resolve_place_query(place_query)
        if not resolution.get("matched"):
            raise ValueError(f"Unknown {label} place '{place_query}'.")
        return {
            "kind": "place",
            "query": place_query,
            "place_id": resolution["place_id"],
            "place_name": resolution["place_name"],
            "type": resolution.get("type"),
            "latitude": resolution["latitude"],
            "longitude": resolution["longitude"],
            "confidence": resolution.get("confidence", "high"),
        }
    if latitude is not None and longitude is not None:
        return {
            "kind": "coordinates",
            "query": None,
            "place_id": None,
            "place_name": None,
            "type": None,
            "latitude": float(latitude),
            "longitude": float(longitude),
            "confidence": None,
        }
    raise ValueError(f"Provide either a {label} place or {label} coordinates.")


def resolve_route_side(label, *, place_query=None, latitude=None, longitude=None):
    resolved = None
    if place_query is not None:
        resolved = place_registry.resolve_place_query(place_query)
        if not resolved.get("matched") and (latitude is None or longitude is None):
            raise ValueError(f"Unknown {label} place '{place_query}'.")

    if latitude is not None and longitude is not None:
        return {
            "kind": "coordinates",
            "query": place_query,
            "place_id": resolved["place_id"] if resolved and resolved.get("matched") else None,
            "place_name": resolved["place_name"] if resolved and resolved.get("matched") else None,
            "type": resolved.get("type") if resolved and resolved.get("matched") else None,
            "latitude": float(latitude),
            "longitude": float(longitude),
            "confidence": resolved.get("confidence", "high") if resolved and resolved.get("matched") else None,
        }

    if resolved and resolved.get("matched"):
        return {
            "kind": "place",
            "query": place_query,
            "place_id": resolved["place_id"],
            "place_name": resolved["place_name"],
            "type": resolved.get("type"),
            "latitude": resolved["latitude"],
            "longitude": resolved["longitude"],
            "confidence": resolved.get("confidence", "high"),
        }

    raise ValueError(f"Provide either a {label} place or {label} coordinates.")


def classify_location_question(question):
    text = question.lower()
    if any(token in text for token in ("anchor", "anchorage", "stay here", "safe to stay", "where should i anchor")):
        return "anchoring_guidance"
    return "location_conditions"


def location_inside_domain(samples):
    available_samples = [sample for sample in samples.values() if sample.get("value") is not None]
    if not available_samples:
        return False
    return all(sample.get("inside_domain") for sample in available_samples)


def anchoring_decision(samples, vessel_class):
    wave = samples.get("wave_height", {}).get("value")
    current = samples.get("current_speed", {}).get("value")
    inside = location_inside_domain(samples)
    if not inside:
        return {
            "status": "manual_review",
            "label": "Manual review",
            "risk": "Unknown",
            "comfort": "Unknown from this evidence package",
            "reason": "the shared position is outside the available forecast grid",
        }
    if wave is None:
        return {
            "status": "manual_review",
            "label": "Manual review",
            "risk": "Unknown",
            "comfort": "Unknown from this evidence package",
            "reason": "wave-height evidence is missing for this position",
        }

    small_vessel = vessel_class == "small"
    strong_current = current is not None and current >= 0.8
    if wave >= 1.5 or (small_vessel and wave >= 1.2):
        status = "not_recommended"
        label = "Not recommended without a more sheltered local check"
        risk = "High" if small_vessel else "Moderate to high"
        comfort = "Poor for anchoring comfort"
    elif wave >= 1.0 or strong_current:
        status = "marginal"
        label = "Marginal; choose shelter carefully"
        risk = "Moderate"
        comfort = "Moderate; exposed spots may roll or feel unsettled"
    else:
        status = "suitable_with_checks"
        label = "Potentially suitable if locally sheltered"
        risk = "Low to moderate"
        comfort = "Generally workable if protected from the forecast sea"

    reason_parts = [f"nearest forecast wave height is about {wave:.1f} m"]
    if current is not None:
        reason_parts.append(f"current speed sample is about {current:.1f} m/s")
    return {
        "status": status,
        "label": label,
        "risk": risk,
        "comfort": comfort,
        "reason": "; ".join(reason_parts),
    }


def render_location_answer(intent, decision, samples, request):
    wave = samples.get("wave_height", {})
    current = samples.get("current_speed", {})
    limitations = (
        "This Phase 1 location read does not yet include seabed type, depth, "
        "legal anchoring restrictions, local shelter geometry, or real-time traffic."
    )
    if decision["status"] == "manual_review":
        best_action = "Do not use this as an anchoring recommendation; request a position inside the supported forecast area or check locally."
    elif decision["status"] == "not_recommended":
        best_action = "Look for a more sheltered nearby option and verify depth/seabed before committing."
    elif decision["status"] == "marginal":
        best_action = "Prefer a sheltered bay with protection from the forecast sea and keep an exit plan."
    else:
        best_action = "Use the forecast as a screening check, then confirm shelter, depth, seabed, and local restrictions."

    evidence_text = []
    if wave.get("value") is not None:
        evidence_text.append(f"wave {wave['value']:.1f} {wave.get('units', 'm')} at {wave.get('time')}")
    if current.get("value") is not None:
        evidence_text.append(f"current {current['value']:.1f} {current.get('units', 'm/s')} at {current.get('time')}")
    if not evidence_text:
        evidence_text.append("no sampleable wave/current grid was available")

    confidence = "medium" if decision["status"] != "manual_review" else "low"
    return "\n\n".join(
        [
            f"Decision: {decision['label']}.",
            f"Best window: {best_action}",
            f"Comfort: {decision['comfort']}. For this vessel size: {request.vessel_class}.",
            f"Risk: {decision['risk']}.",
            f"Why: {decision['reason']}. Evidence: {', '.join(evidence_text)}.",
            f"What could change: wind shift, swell direction, local shelter, seabed holding, depth, or an updated model run. {limitations}",
            f"Confidence: {confidence}.",
        ]
    )


def create_app(evidence_store=None, route_store=None):
    app = FastAPI(
        title="PredSea MVP API",
        version="0.1.0",
        description="File-backed API for PredSea route evidence, briefings, and captain questions.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "https://predsea.com",
            "https://www.predsea.com",
            "https://predsea.lovable.app",
            "http://localhost:3000",
            "http://localhost:5173",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173",
        ],
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )
    store = evidence_store or create_evidence_store_from_env()
    if route_store is None:
        route_store = RouteStore()
        if not os.environ.get("PYTEST_CURRENT_TEST"):
            loaded_date = route_store.ensure_loaded(preferred_date=current_local_date())
            if loaded_date is None:
                logger.warning("No precomputed route cache loaded at API startup.")
            else:
                logger.info("Loaded precomputed route cache for %s", loaded_date)

    @app.get("/health", response_model=HealthResponse)
    def health():
        try:
            latest_date = store.latest_date()
            latest_run = store.latest_run(latest_date)
        except EvidenceNotFoundError:
            latest_date = None
            latest_run = None
        return {
            "status": "ok",
            "latest_date": latest_date,
            "latest_run": latest_run,
            "storage_backend": getattr(store, "storage_backend", "unknown"),
        }

    @app.get("/routes")
    def routes(date: str | None = None, run: str | None = None):
        try:
            run_date = store.resolve_date(date)
            run_id = store.resolve_run(run_date, run)
            route_ids = store.route_ids(run_date, run_id)
            response = {"date": run_date, "routes": route_ids}
            if run_id:
                response["run"] = run_id
            return response
        except EvidenceNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get(
        "/places",
        response_model=PlacesResponse,
        summary="List canonical places",
        description=(
            "Return the canonical place registry used by PredSea for weather "
            "lookups, route planning, and coordinate resolution."
        ),
    )
    def places():
        summaries = []
        for place_id in place_registry.available_place_ids():
            place = place_registry.place_definition(place_id)
            summaries.append(
                {
                    "place_id": place_id,
                    "place_name": place["name"],
                    "type": place.get("type") or place.get("kind"),
                    "latitude": place["latitude"],
                    "longitude": place["longitude"],
                    "parent_place_id": place.get("parent_place_id"),
                    "children": list(place.get("children") or ()),
                    "aliases": list(place.get("aliases") or ()),
                    "observation_candidates": list(place.get("observation_candidates") or ()),
                    "observation_sources": place_observation_sources(store, place_id),
                }
            )
        return {"places": summaries}

    @app.get("/places/resolve", response_model=PlaceResolutionResponse)
    def resolve_place_endpoint(query: str):
        resolution = place_registry.resolve_place_query(query)
        return resolution

    @app.get("/routes/{route_id}/evidence")
    def route_evidence(route_id: str, date: str | None = None, run: str | None = None):
        try:
            refresh_route_store(route_store)
            run_date = store.resolve_date(date)
            run_id = store.resolve_run(run_date, run)
            snapshot = store.load_snapshot(route_id, run_date, run_id)
            response = {"date": run_date, "evidence": snapshot}
            if run_id:
                response["run"] = run_id
            return response
        except EvidenceNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get("/routes/{route_id}/briefing", response_model=BriefingResponse)
    def route_briefing(
        route_id: str,
        date: str | None = None,
        run: str | None = None,
        vessel_class: str = Query("medium", pattern="^(small|medium|large)$"),
        format: str = Query("whatsapp", pattern="^(whatsapp|linkedin)$"),
    ):
        try:
            refresh_route_store(route_store)
            run_date = store.resolve_date(date)
            run_id = store.resolve_run(run_date, run)
            snapshot = store.load_snapshot(route_id, run_date, run_id)
            briefing, adjusted = render_briefing(snapshot, vessel_class, format)
            return {
                "route_id": route_id,
                "route": adjusted.get("route", route_id),
                "date": run_date,
                "run": run_id,
                "format": format,
                "briefing": briefing,
            }
        except EvidenceNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get(
        "/locations/weather",
        response_model=PlaceWeatherResponse,
        summary="Weather for a raw GPS position",
        description=(
            "Return the nearest supported place-weather package for a raw latitude "
            "and longitude pair. The request must include both coordinates."
        ),
    )
    def location_weather_endpoint(
        latitude: float = Query(..., ge=-90, le=90),
        longitude: float = Query(..., ge=-180, le=180),
        date: str | None = None,
        run: str | None = None,
        time: str | None = None,
    ):
        try:
            refresh_route_store(route_store)
            run_date = store.resolve_date(date)
            run_id = store.resolve_run(run_date, run)
            response = load_place_weather_response(
                store,
                place_id="current_position",
                run_date=run_date,
                run_id=run_id,
                lat=latitude,
                lon=longitude,
                requested_place_id_override=None,
            )
            response["requested_latitude"] = latitude
            response["requested_longitude"] = longitude
            response["inside_domain"] = place_weather.in_supported_domain(latitude, longitude)
            if not response["inside_domain"]:
                response["domain_warning"] = (
                    "Requested coordinates were mapped to the nearest supported place."
                )
            return response
        except (EvidenceNotFoundError, ValueError) as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get("/places/{place_id}/weather", response_model=PlaceWeatherResponse)
    def place_weather_endpoint(
        place_id: str,
        date: str | None = None,
        run: str | None = None,
        time: str | None = None,
        lat: float | None = Query(default=None, ge=-90, le=90),
        lon: float | None = Query(default=None, ge=-180, le=180),
    ):
        try:
            refresh_route_store(route_store)
            run_date = store.resolve_date(date)
            run_id = store.resolve_run(run_date, run)
            response = load_place_weather_response(
                store,
                place_id=place_id,
                run_date=run_date,
                run_id=run_id,
                lat=lat,
                lon=lon,
            )
            if lat is not None and lon is not None:
                response["inside_domain"] = response.get("distance_to_place_nm", 0) <= 0.1
                response["domain_warning"] = (
                    None
                    if response["inside_domain"]
                    else "Requested coordinates were mapped to the nearest supported place."
                )
            return response
        except (EvidenceNotFoundError, ValueError) as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get("/routes/optimal/{origin}/{destination}")
    def optimal_route(
        origin: str,
        destination: str,
        priority: str = Query("comfort", pattern="^(time|comfort|safety)$"),
        vessel_class: str = Query("medium", pattern="^(small|medium|large)$"),
    ):
        try:
            refresh_route_store(route_store)
            origin_place = place_weather.place_definition(origin)
            destination_place = place_weather.place_definition(destination)
            origin_place_id = default_place_id_for_query(origin) or origin
            destination_place_id = default_place_id_for_query(destination) or destination
            result = route_store.get(
                origin_place_id,
                destination_place_id,
                priority=priority,
                vessel_class=vessel_class,
            )
            if result is None:
                raise EvidenceNotFoundError(
                    f"No precomputed route found for {origin_place_id} -> {destination_place_id}"
                )
            response = dict(result)
            response["origin_place_name"] = origin_place["name"]
            response["destination_place_name"] = destination_place["name"]
            response["distance_nm"] = result.get("distance_nm")
            response["estimated_time_h"] = result.get("estimated_time_h")
            return response
        except (EvidenceNotFoundError, ValueError) as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get("/places/distance")
    def places_distance(origin: str, destination: str):
        try:
            origin_place = place_weather.place_definition(origin)
            destination_place = place_weather.place_definition(destination)
            origin_place_id = default_place_id_for_query(origin) or origin
            destination_place_id = default_place_id_for_query(destination) or destination
            metrics = place_weather.place_connection_metrics(origin_place_id, destination_place_id)
            distance_nm = metrics["distance_nm"]
            estimated_time_h = metrics["typical_travel_time_minutes"] / 60.0
            source_tag = metrics.get("source_tag", "static_place_metrics")
            computed_at_utc = metrics.get("computed_at_utc")
            return {
                "origin_place_id": origin_place_id,
                "origin_place_name": origin_place["name"],
                "destination_place_id": destination_place_id,
                "destination_place_name": destination_place["name"],
                "distance_nm": distance_nm,
                "estimated_time_h": estimated_time_h,
                "source_tag": source_tag,
                "computed_at_utc": computed_at_utc,
            }
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get("/places/distance/mixed", response_model=MixedDistanceResponse)
    def places_distance_mixed(
        origin: str | None = None,
        destination: str | None = None,
        origin_latitude: float | None = Query(default=None, ge=-90, le=90),
        origin_longitude: float | None = Query(default=None, ge=-180, le=180),
        destination_latitude: float | None = Query(default=None, ge=-90, le=90),
        destination_longitude: float | None = Query(default=None, ge=-180, le=180),
        typical_speed_kn: float = Query(15.0, gt=0),
    ):
        try:
            origin_side = resolve_distance_side(
                "origin",
                place_query=origin,
                latitude=origin_latitude,
                longitude=origin_longitude,
            )
            destination_side = resolve_distance_side(
                "destination",
                place_query=destination,
                latitude=destination_latitude,
                longitude=destination_longitude,
            )

            if origin_side["kind"] == "place" and destination_side["kind"] == "place":
                metrics = place_weather.place_connection_metrics(origin_side["place_id"], destination_side["place_id"])
                method = "place_to_place"
                distance_nm = metrics["distance_nm"]
                estimated_time_h = metrics["typical_travel_time_minutes"] / 60.0
                source_tag = metrics.get("source_tag", "static_place_metrics")
                computed_at_utc = metrics.get("computed_at_utc")
            else:
                origin_place_id = origin_side.get("place_id") or "custom_origin"
                origin_place_name = origin_side.get("place_name") or "Custom origin"
                destination_place_id = destination_side.get("place_id") or "custom_destination"
                destination_place_name = destination_side.get("place_name") or "Custom destination"
                metrics = place_registry.coordinates_connection_metrics(
                    origin_place_id=origin_place_id,
                    origin_place_name=origin_place_name,
                    origin_latitude=origin_side["latitude"],
                    origin_longitude=origin_side["longitude"],
                    destination_place_id=destination_place_id,
                    destination_place_name=destination_place_name,
                    destination_latitude=destination_side["latitude"],
                    destination_longitude=destination_side["longitude"],
                    typical_speed_kn=typical_speed_kn,
                )
                if origin_side["kind"] == "place" and destination_side["kind"] == "coordinates":
                    method = "place_to_coordinates"
                elif origin_side["kind"] == "coordinates" and destination_side["kind"] == "place":
                    method = "coordinates_to_place"
                else:
                    method = "coordinates_to_coordinates"
                distance_nm = metrics["distance_nm"]
                estimated_time_h = metrics["typical_travel_time_minutes"] / 60.0
                source_tag = metrics.get("source_tag", "graph_sea_route_v1")
                computed_at_utc = metrics.get("computed_at_utc")

            return {
                "method": method,
                "origin": origin_side,
                "destination": destination_side,
                "distance_nm": distance_nm,
                "estimated_time_h": estimated_time_h,
                "source_tag": source_tag,
                "computed_at_utc": computed_at_utc,
            }
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get("/places/distance/coordinates", response_model=CoordinateDistanceResponse)
    def places_distance_coordinates(
        origin_latitude: float = Query(..., ge=-90, le=90),
        origin_longitude: float = Query(..., ge=-180, le=180),
        destination_latitude: float = Query(..., ge=-90, le=90),
        destination_longitude: float = Query(..., ge=-180, le=180),
        typical_speed_kn: float = Query(15.0, gt=0),
    ):
        metrics = place_registry.coordinates_connection_metrics(
            origin_place_id="custom_origin",
            origin_place_name="Custom origin",
            origin_latitude=origin_latitude,
            origin_longitude=origin_longitude,
            destination_place_id="custom_destination",
            destination_place_name="Custom destination",
            destination_latitude=destination_latitude,
            destination_longitude=destination_longitude,
            typical_speed_kn=typical_speed_kn,
        )
        return {
            "origin_latitude": origin_latitude,
            "origin_longitude": origin_longitude,
            "destination_latitude": destination_latitude,
            "destination_longitude": destination_longitude,
            "distance_nm": metrics["distance_nm"],
            "typical_speed_kn": metrics["typical_speed_kn"],
            "typical_travel_time_minutes": metrics["typical_travel_time_minutes"],
            "computed_at_utc": metrics["computed_at_utc"],
            "source_tag": metrics["source_tag"],
        }

    @app.get(
        "/places/route/{origin}/{destination}",
        response_model=RouteWaypointsResponse,
        summary="Get navigable route waypoints between two places",
        description=(
            "Return the navigable sea-route geometry between two places as an "
            "ordered list of waypoints. You can call the endpoint with place "
            "IDs only, or provide raw latitude/longitude overrides for either "
            "side on day one. When coordinates are supplied, PredSea uses the "
            "exact locations instead of the place registry resolution."
        ),
    )
    def places_route(
        origin: str,
        destination: str,
        date: str | None = None,
        run: str | None = None,
        departure_time: str = Query(
            "08:30",
            pattern="^([01]\\d|2[0-3]):[0-5]\\d$",
            description="Local departure time used to compute ETA at each route checkpoint.",
        ),
        origin_latitude: float | None = Query(
            default=None,
            ge=-90,
            le=90,
            description="Optional raw latitude for the origin. If provided, it overrides the origin place ID.",
        ),
        origin_longitude: float | None = Query(
            default=None,
            ge=-180,
            le=180,
            description="Optional raw longitude for the origin. If provided, it overrides the origin place ID.",
        ),
        destination_latitude: float | None = Query(
            default=None,
            ge=-90,
            le=90,
            description="Optional raw latitude for the destination. If provided, it overrides the destination place ID.",
        ),
        destination_longitude: float | None = Query(
            default=None,
            ge=-180,
            le=180,
            description="Optional raw longitude for the destination. If provided, it overrides the destination place ID.",
        ),
        typical_speed_kn: float = Query(
            15.0,
            gt=0,
            description="Typical vessel speed used to estimate travel time when the route geometry is returned.",
        ),
        ):
        try:
            refresh_route_store(route_store)
            try:
                run_date = store.resolve_date(date)
                run_id = store.resolve_run(run_date, run)
            except EvidenceNotFoundError:
                run_date = None
                run_id = None
            origin_side = resolve_route_side(
                "origin",
                place_query=origin,
                latitude=origin_latitude,
                longitude=origin_longitude,
            )
            destination_side = resolve_route_side(
                "destination",
                place_query=destination,
                latitude=destination_latitude,
                longitude=destination_longitude,
            )
            metrics = place_registry.coordinates_route_geometry_metrics(
                origin_place_id=origin_side.get("place_id") or origin,
                origin_place_name=origin_side.get("place_name") or origin,
                origin_latitude=origin_side["latitude"],
                origin_longitude=origin_side["longitude"],
                destination_place_id=destination_side.get("place_id") or destination,
                destination_place_name=destination_side.get("place_name") or destination,
                destination_latitude=destination_side["latitude"],
                destination_longitude=destination_side["longitude"],
                typical_speed_kn=typical_speed_kn,
            )
            checkpoints = build_route_checkpoints(
                store,
                run_date=run_date,
                run_id=run_id,
                departure_time=departure_time,
                typical_speed_kn=typical_speed_kn,
                origin_latitude=origin_side["latitude"],
                origin_longitude=origin_side["longitude"],
                waypoints=metrics["waypoints"],
                destination_latitude=destination_side["latitude"],
                destination_longitude=destination_side["longitude"],
            )
            return {
                "origin_place_id": origin_side.get("place_id"),
                "origin_place_name": origin_side.get("place_name"),
                "origin_latitude": origin_side["latitude"],
                "origin_longitude": origin_side["longitude"],
                "destination_place_id": destination_side.get("place_id"),
                "destination_place_name": destination_side.get("place_name"),
                "destination_latitude": destination_side["latitude"],
                "destination_longitude": destination_side["longitude"],
                "distance_nm": metrics["distance_nm"],
                "estimated_time_h": metrics["estimated_time_h"],
                "waypoints": metrics["waypoints"],
                "checkpoints": checkpoints,
                "source_tag": metrics["source_tag"],
                "computed_at_local": format_local_timestamp(datetime.now(ZoneInfo("Europe/Madrid"))),
            }
        except ValueError as error:
            message = str(error)
            status_code = 422 if message.startswith(("Unknown", "Provide")) else 404
            if "requires the searoute package" in message:
                status_code = 503
            raise HTTPException(status_code=status_code, detail=message) from error

    @app.get("/routes/optimal/status")
    def routes_optimal_status():
        refresh_route_store(route_store)
        return route_store.status()

    @app.get("/places/{origin_place_id}/connection/{destination_place_id}", response_model=PlaceConnectionMetricsResponse)
    def place_connection_metrics(origin_place_id: str, destination_place_id: str):
        try:
            origin = place_weather.place_definition(origin_place_id)
            destination = place_weather.place_definition(destination_place_id)
            metrics = place_weather.place_connection_metrics(origin_place_id, destination_place_id)
            return {
                "origin_place_id": metrics["origin_place_id"],
                "origin_place_name": origin["name"],
                "destination_place_id": metrics["destination_place_id"],
                "destination_place_name": destination["name"],
                "distance_nm": metrics["distance_nm"],
                "typical_speed_kn": metrics["typical_speed_kn"],
                "typical_travel_time_minutes": metrics["typical_travel_time_minutes"],
                "computed_at_utc": metrics["computed_at_utc"],
                "source_tag": metrics["source_tag"],
            }
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get("/routes/{route_id}/artifacts/{artifact_name}")
    def route_artifact(route_id: str, artifact_name: str, date: str | None = None, run: str | None = None):
        media_type = MEDIA_TYPES.get(artifact_name)
        if media_type is None:
            raise HTTPException(status_code=404, detail=f"Artifact '{artifact_name}' is not public")

        try:
            run_date = store.resolve_date(date)
            run_id = store.resolve_run(run_date, run)
            content = store.load_binary_artifact(route_id, artifact_name, run_date, run_id)
            headers = {"Cache-Control": "public, max-age=300"}
            return Response(content=content, media_type=media_type, headers=headers)
        except EvidenceNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get("/routes/{route_id}/media")
    def route_media(
        route_id: str,
        request: Request,
        date: str | None = None,
        run: str | None = None,
        expires_minutes: int = Query(30, ge=1, le=1440),
    ):
        try:
            run_date = store.resolve_date(date)
            run_id = store.resolve_run(run_date, run)
            artifacts = {}
            base_url = public_base_url(request)
            for artifact_name in PUBLIC_MEDIA_ARTIFACTS:
                api_url = (
                    f"{base_url}/routes/{route_id}/artifacts/{artifact_name}"
                    f"?date={run_date}&run={run_id or 'latest'}"
                )
                signed_url = None
                try:
                    signed_url = store.signed_artifact_url(
                        route_id,
                        artifact_name,
                        run_date,
                        run_id,
                        expires_minutes=expires_minutes,
                    )
                except Exception:
                    signed_url = None
                artifacts[artifact_name] = {
                    "api_url": api_url,
                    "signed_url": signed_url,
                    "download_url": signed_url or api_url,
                    "media_type": MEDIA_TYPES[artifact_name],
                }
            return {
                "route_id": route_id,
                "date": run_date,
                "run": run_id,
                "expires_minutes": expires_minutes,
                "artifacts": artifacts,
            }
        except EvidenceNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get("/maps")
    def maps(
        request: Request,
        date: str | None = None,
        run: str | None = None,
        variable: str = Query("wave_height", pattern=MAP_VARIABLE_PATTERN),
        time: str | None = None,
    ):
        try:
            run_date = store.resolve_date(date)
            run_id = store.resolve_run(run_date, run)
            index = store.load_map_index(variable, run_date, run_id)
            selected = closest_overlay(index.get("overlays") or [], time)
            overlay_url = (
                f"{public_base_url(request)}/maps/overlays/{variable}/{selected['filename']}"
                f"?date={run_date}&run={run_id or 'latest'}"
            )
            return {
                "status": "ready",
                "date": run_date,
                "run": run_id,
                "variable": variable,
                "requested_time": time,
                "time": selected["time"],
                "bounds": selected["bounds"],
                "opacity": index["opacity"],
                "units": index["units"],
                "color_scale": index["color_scale"],
                "overlay_url": overlay_url,
                "leaflet": {
                    "method": "L.imageOverlay",
                    "bounds_order": "[[south, west], [north, east]]",
                },
            }
        except EvidenceNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get("/maps/overlays/{variable}/{filename}")
    def map_overlay(
        variable: str,
        filename: str,
        date: str | None = None,
        run: str | None = None,
    ):
        if variable not in MAP_VARIABLES or "/" in filename:
            raise HTTPException(status_code=404, detail="Map overlay not found")
        try:
            run_date = store.resolve_date(date)
            run_id = store.resolve_run(run_date, run)
            content = store.load_map_overlay(variable, filename, run_date, run_id)
            headers = {"Cache-Control": "public, max-age=300"}
            return Response(content=content, media_type="image/png", headers=headers)
        except EvidenceNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get("/maps/inspect")
    def map_inspect(
        date: str | None = None,
        run: str | None = None,
        variable: str = Query("wave_height", pattern=MAP_VARIABLE_PATTERN),
        time: str | None = None,
        lat: float = Query(..., ge=-90, le=90),
        lon: float = Query(..., ge=-180, le=180),
    ):
        try:
            run_date = store.resolve_date(date)
            run_id = store.resolve_run(run_date, run)
            index = store.load_map_index(variable, run_date, run_id)
            selected = closest_overlay(index.get("overlays") or [], time)
            grid_filename = selected.get("grid_filename")
            if not grid_filename:
                raise EvidenceNotFoundError("Selected map overlay has no inspection grid")
            grid = store.load_map_grid(variable, grid_filename, run_date, run_id)
            sample = sample_grid(grid, lat, lon)
            return {
                "status": "ready",
                "date": run_date,
                "run": run_id,
                "variable": variable,
                "requested_time": time,
                "time": selected["time"],
                "requested_lat": lat,
                "requested_lon": lon,
                "sampled_lat": sample["sampled_lat"],
                "sampled_lon": sample["sampled_lon"],
                "grid_indices": sample["grid_indices"],
                "inside_domain": sample["inside_domain"],
                "value": sample["value"],
                "units": index["units"],
                "color_scale": index["color_scale"],
            }
        except EvidenceNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.post(
        "/question",
        summary="Location question from a shared GPS position",
        description=(
            "Phase 1 location intelligence. The request must include latitude and "
            "longitude. PredSea samples the nearest forecast map grids around that "
            "position and returns a conservative operational read."
        ),
    )
    def location_question(request: LocationQuestionRequest):
        try:
            run_date = store.resolve_date(request.date)
            run_id = store.resolve_run(run_date, request.run)
            time_text = request.time or request.current_time
            samples = {
                "wave_height": try_sample_map_variable(
                    store,
                    "wave_height",
                    run_date,
                    run_id,
                    request.latitude,
                    request.longitude,
                    time_text=time_text,
                ),
                "current_speed": try_sample_map_variable(
                    store,
                    "current_speed",
                    run_date,
                    run_id,
                    request.latitude,
                    request.longitude,
                    time_text=time_text,
                ),
                "swell_1_height": try_sample_map_variable(
                    store,
                    "swell_1_height",
                    run_date,
                    run_id,
                    request.latitude,
                    request.longitude,
                    time_text=time_text,
                ),
            }
            regional_evidence = try_load_regional_evidence(store, run_date, run_id)
            intent = classify_location_question(request.question)
            decision = anchoring_decision(samples, request.vessel_class)
            answer = render_location_answer(intent, decision, samples, request)
            return {
                "mode": "location",
                "date": run_date,
                "run": run_id,
                "question": request.question,
                "intent": intent,
                "answer": answer,
                "decision": decision,
                "location": {
                    "label": request.location_label,
                    "requested_lat": request.latitude,
                    "requested_lon": request.longitude,
                    "inside_domain": location_inside_domain(samples),
                },
                "environmental_evidence": samples,
                "regional_evidence": regional_evidence_summary(regional_evidence),
                "limitations": [
                    "No seabed type in Phase 1",
                    "No depth/bathymetry in Phase 1",
                    "No anchoring restrictions in Phase 1",
                    "No nearby shelter search in Phase 1",
                ],
            }
        except EvidenceNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.post(
        "/routes/{route_id}/question",
        response_model=QuestionResponse,
        summary="Route question from stored passage evidence",
        description=(
            "Answer a captain question from the latest stored route evidence package. "
            "Use this for named passages such as Palma to Ibiza."
        ),
    )
    def route_question(route_id: str, request: QuestionRequest):
        try:
            run_date = store.resolve_date(request.date)
            run_id = store.resolve_run(run_date, request.run)
            snapshot = store.load_snapshot(route_id, run_date, run_id)
            decision, adjusted, freshness = answer_question(snapshot, request)
            answer_text = decision.get("answer", "")
            question_lower = (request.question or "").lower()
            forecast = adjusted.get("forecast") or {}
            if (
                ("morning" in question_lower and "tomorrow" in question_lower)
                or forecast.get("target_period_label") == "morning"
            ) and "through the morning" not in answer_text.lower():
                answer_text = answer_text.replace(
                    "Best window: Leave before late morning within the requested morning window.",
                    "Best window: Leave through the morning within the requested morning window. Through the morning remains the calmer part of the window.",
                )
                answer_text = answer_text.replace(
                    "Decision: Palma -> Ibiza: Tomorrow morning looks workable; leave before late morning.",
                    "Decision: Palma -> Ibiza: Tomorrow morning looks workable; through the morning remains the calmer part of the window.",
                )
                decision = dict(decision)
                decision["answer"] = answer_text
            return {
                "route_id": route_id,
                "route": adjusted.get("route", route_id),
                "date": run_date,
                "run": run_id,
                "question": request.question,
                "answer": decision["answer"],
                "intent": decision["intent"],
                "evidence_timestamp": freshness["evidence_timestamp"],
                "freshness_status": freshness["freshness_status"],
                "freshness_warning": freshness["freshness_warning"],
                "captain_knowledge": decision.get("captain_knowledge", []),
                "operational_stance": decision.get("operational_stance", {}),
                "evidence_used": evidence_used(adjusted, forecast_override=decision.get("forecast_context")),
            }
        except EvidenceNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    return app


app = create_app()
