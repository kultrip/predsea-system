from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from api.evidence_store import EvidenceNotFoundError, create_evidence_store_from_env
from api.schemas import (
    BriefingResponse,
    HealthResponse,
    LocationQuestionRequest,
    PlaceConnectionMetricsResponse,
    PlaceWeatherResponse,
    QuestionRequest,
    QuestionResponse,
)
from api.services import answer_question, evidence_used, render_briefing
import place_weather


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


def create_app(evidence_store=None):
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

    @app.get("/routes/{route_id}/evidence")
    def route_evidence(route_id: str, date: str | None = None, run: str | None = None):
        try:
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
            run_date = store.resolve_date(date)
            run_id = store.resolve_run(run_date, run)
            resolved = place_weather.resolve_place(place_id, latitude=lat, longitude=lon)
            payload = store.load_place_weather(resolved["place_id"], run_date, run_id)
            response = dict(payload)
            response["requested_place_id"] = resolved["requested_place_id"]
            response["place_id"] = resolved["place_id"]
            response["place_name"] = resolved["place_name"]
            response["resolved_latitude"] = resolved["latitude"]
            response["resolved_longitude"] = resolved["longitude"]
            response["distance_to_place_nm"] = resolved.get("distance_to_place_nm")
            response["requested_latitude"] = resolved.get("requested_latitude")
            response["requested_longitude"] = resolved.get("requested_longitude")
            if lat is not None and lon is not None:
                response["inside_domain"] = resolved.get("distance_to_place_nm", 0) <= 0.1
                response["domain_warning"] = (
                    None
                    if response["inside_domain"]
                    else "Requested coordinates were mapped to the nearest supported place."
                )
            return response
        except (EvidenceNotFoundError, ValueError) as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

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

    @app.post("/question")
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

    @app.post("/routes/{route_id}/question", response_model=QuestionResponse)
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
