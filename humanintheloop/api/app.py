from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from api.evidence_store import EvidenceNotFoundError, create_evidence_store_from_env
from api.schemas import BriefingResponse, HealthResponse, QuestionRequest, QuestionResponse
from api.services import answer_question, evidence_used, render_briefing


MEDIA_TYPES = {
    "route_decision_map.png": "image/png",
    "predsea_whatsapp_figure.png": "image/png",
}
PUBLIC_MEDIA_ARTIFACTS = tuple(MEDIA_TYPES)
MAP_VARIABLES = ("wave_height", "current_speed")


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
        variable: str = Query("wave_height", pattern="^(wave_height|current_speed)$"),
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
        variable: str = Query("wave_height", pattern="^(wave_height|current_speed)$"),
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

    @app.post("/routes/{route_id}/question", response_model=QuestionResponse)
    def route_question(route_id: str, request: QuestionRequest):
        try:
            run_date = store.resolve_date(request.date)
            run_id = store.resolve_run(run_date, request.run)
            snapshot = store.load_snapshot(route_id, run_date, run_id)
            decision, adjusted = answer_question(snapshot, request)
            return {
                "route_id": route_id,
                "route": adjusted.get("route", route_id),
                "date": run_date,
                "run": run_id,
                "question": request.question,
                "answer": decision["answer"],
                "intent": decision["intent"],
                "evidence_used": evidence_used(adjusted),
            }
        except EvidenceNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    return app


app = create_app()
