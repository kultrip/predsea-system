from __future__ import annotations

from fastapi import APIRouter, Query

from api.schemas import WarningsResponse
from api.warnings_service import build_warnings_response


router = APIRouter(tags=["warnings"])


@router.get(
    "/warnings",
    response_model=WarningsResponse,
    summary="Operational warnings from official alerts and anomaly detection",
    description=(
        "Combine AEMET official CAP alerts with PredSea anomaly warnings "
        "computed from the latest evidence rows and climatology baseline."
    ),
)
def warnings_endpoint(
    route: str | None = Query(default=None, description="Optional route id, e.g. palma_ibiza"),
    place: str | None = Query(default=None, description="Optional place id, e.g. palma"),
    date: str | None = Query(default=None, description="Optional ISO date YYYY-MM-DD"),
    z_threshold: float = Query(default=1.5, ge=0.0),
    lookback_hours: int = Query(default=240, ge=1),
    min_window_hours: int = Query(default=240, ge=1),
    min_sample_count: int = Query(default=10, ge=1),
    include_aemet: bool = Query(default=True),
    include_anomaly: bool = Query(default=True),
):
    return build_warnings_response(
        route=route,
        place=place,
        date=date,
        z_threshold=z_threshold,
        lookback_hours=lookback_hours,
        min_window_hours=min_window_hours,
        min_sample_count=min_sample_count,
        include_aemet=include_aemet,
        include_anomaly=include_anomaly,
    )
