from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field


VesselClass = Literal["small", "medium", "large"]


class QuestionRequest(BaseModel):
    question: str = Field(..., min_length=1)
    date: Optional[str] = None
    vessel_class: VesselClass = "medium"
    location_label: str = "shared location"
    current_time: Optional[str] = None


class QuestionResponse(BaseModel):
    route_id: str
    route: str
    date: str
    question: str
    answer: str
    intent: str
    evidence_used: Dict[str, Any]


class BriefingResponse(BaseModel):
    route_id: str
    route: str
    date: str
    format: Literal["whatsapp", "linkedin"]
    briefing: str


class RouteSummary(BaseModel):
    route_id: str
    route: str


class HealthResponse(BaseModel):
    status: str
    latest_date: Optional[str]
    storage_backend: str
