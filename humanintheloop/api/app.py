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


def public_base_url(request):
    base_url = str(request.base_url).rstrip("/")
    if base_url.startswith("http://") and "run.app" in base_url:
        return base_url.replace("http://", "https://", 1)
    return base_url


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
        date: str | None = None,
        variable: str = Query("wave_height", pattern="^(wave_height|current_speed)$"),
        time: str | None = None,
    ):
        try:
            run_date = store.resolve_date(date)
            return {
                "status": "planned",
                "date": run_date,
                "variable": variable,
                "time": time,
                "message": (
                    "Leaflet-ready georeferenced map overlays are not generated by the ETL yet. "
                    "Use /routes/{route_id}/media for current PNG artifacts."
                ),
                "required_next_step": "Generate Web Mercator PNG tiles or a GeoTIFF/COG layer from the forecast grid.",
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
