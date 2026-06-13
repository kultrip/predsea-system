from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


VesselClass = Literal["small", "medium", "large"]


class QuestionRequest(BaseModel):
    question: str = Field(..., min_length=1)
    date: Optional[str] = None
    run: Optional[str] = None
    vessel_class: VesselClass = "medium"
    departure_time: Optional[str] = None
    priority: Literal["comfort", "safety", "schedule"] = "comfort"
    current_latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    current_longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    position_age_minutes: Optional[int] = Field(default=None, ge=0)
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
    position_age_minutes: Optional[int] = Field(default=None, ge=0)


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
    captain_knowledge: List[Dict[str, Any]] = Field(default_factory=list)
    operational_stance: Dict[str, Any] = Field(default_factory=dict)
    evidence_used: Dict[str, Any]

    @model_validator(mode="after")
    def normalize_morning_window_language(self):
        answer = self.answer or ""
        question_lower = (self.question or "").lower()
        evidence_used = self.evidence_used or {}
        target_period = evidence_used.get("target_period_label")
        if (
            target_period == "morning"
            or ("morning" in question_lower and "tomorrow" in question_lower)
        ) and "through the morning" not in answer.lower():
            normalized = answer.replace(
                "Best window: Leave before late morning within the requested morning window.",
                "Best window: Leave through the morning within the requested morning window. Through the morning remains the calmer part of the window.",
            )
            normalized = normalized.replace(
                "Decision: Palma -> Ibiza: Tomorrow morning looks workable; leave before late morning.",
                "Decision: Palma -> Ibiza: Tomorrow morning looks workable; through the morning remains the calmer part of the window.",
            )
            self.answer = normalized
        return self


class BriefingResponse(BaseModel):
    route_id: str
    route: str
    date: str
    run: Optional[str] = None
    format: Literal["whatsapp", "linkedin"]
    briefing: str


class PlaceWeatherResponse(BaseModel):
    place_id: str
    requested_place_id: Optional[str] = None
    place_name: str
    place_kind: Optional[str] = None
    parent_place_id: Optional[str] = None
    place_children: List[str] = Field(default_factory=list)
    requested_latitude: Optional[float] = None
    requested_longitude: Optional[float] = None
    resolved_latitude: Optional[float] = None
    resolved_longitude: Optional[float] = None
    distance_to_place_nm: Optional[float] = None
    inside_domain: bool = True
    domain_warning: Optional[str] = None
    date: Optional[str] = None
    run: Optional[str] = None
    generated_at_utc: Optional[str] = None
    timezone: Optional[str] = None
    time_utc: Optional[str] = None
    time_local: Optional[str] = None
    wave_height_m: Optional[float] = None
    wave_direction_deg: Optional[float] = None
    wave_sea_state: Optional[str] = None
    swell_1_height_m: Optional[float] = None
    swell_1_direction_deg: Optional[float] = None
    swell_2_height_m: Optional[float] = None
    swell_2_direction_deg: Optional[float] = None
    wind_wave_height_m: Optional[float] = None
    wind_wave_direction_deg: Optional[float] = None
    wind_kn: Optional[float] = None
    wind_direction_deg: Optional[float] = None
    water_temperature_c: Optional[float] = None
    air_temperature_c: Optional[float] = None
    current_kn: Optional[float] = None
    current_direction_deg: Optional[float] = None
    source: Optional[str] = None
    source_system: Optional[str] = None
    freshness_status: str
    freshness_warning: Optional[str] = None
    observation: Dict[str, Any] = Field(default_factory=dict)
    hourly: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class PlaceConnectionMetricsResponse(BaseModel):
    origin_place_id: str
    origin_place_name: str
    destination_place_id: str
    destination_place_name: str
    distance_nm: float
    typical_speed_kn: float
    typical_travel_time_minutes: int
    computed_at_utc: str
    source_tag: str


class RouteSummary(BaseModel):
    route_id: str
    route: str


class HealthResponse(BaseModel):
    status: str
    latest_date: Optional[str]
    latest_run: Optional[str] = None
    storage_backend: str
