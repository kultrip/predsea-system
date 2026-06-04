from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field


VesselClass = Literal["small", "medium", "large"]


class QuestionRequest(BaseModel):
    question: str = Field(..., min_length=1)
    date: Optional[str] = None
    run: Optional[str] = None
    vessel_class: VesselClass = "medium"
    location_label: str = "shared location"
    current_time: Optional[str] = None
    current_date: Optional[str] = None


class LocationQuestionRequest(BaseModel):
    question: str = Field(..., min_length=1)
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    date: Optional[str] = None
    run: Optional[str] = None
    vessel_class: VesselClass = "medium"
    location_label: str = "shared GPS position"
    current_time: Optional[str] = None
    current_date: Optional[str] = None
    time: Optional[str] = None


class QuestionResponse(BaseModel):
    route_id: str
    route: str
    date: str
    run: Optional[str] = None
    question: str
    answer: str
    intent: str
    evidence_timestamp: Optional[str] = None
    freshness_status: str
    freshness_warning: Optional[str] = None
    evidence_used: Dict[str, Any]


class BriefingResponse(BaseModel):
    route_id: str
    route: str
    date: str
    run: Optional[str] = None
    format: Literal["whatsapp", "linkedin"]
    briefing: str


class RouteSummary(BaseModel):
    route_id: str
    route: str


class HealthResponse(BaseModel):
    status: str
    latest_date: Optional[str]
    latest_run: Optional[str] = None
    storage_backend: str
