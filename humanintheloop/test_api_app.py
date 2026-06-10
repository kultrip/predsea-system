import json
from pathlib import Path

from fastapi.testclient import TestClient

from api.app import create_app
from api.evidence_store import EvidenceStore, GcsEvidenceStore


def write_snapshot(root, date_text="2026-05-29", route_id="palma_ibiza"):
    route_dir = Path(root) / date_text / route_id
    route_dir.mkdir(parents=True)
    snapshot = {
        "route": "Palma -> Ibiza",
        "route_id": route_id,
        "vessel_class": "medium",
        "vessel_profile": {"label": "15-24m", "manageable_m": 1.5, "restricted_m": 2.2},
        "created_at_utc": "2026-05-29 06:30 UTC",
        "observations": {
            "canal_de_ibiza": {
                "name": "Buoy Canal de Ibiza",
                "last_sample_utc": "2026-05-29 06:30 UTC",
                "wave_height_m": 0.4,
            }
        },
        "forecast": {
            "wave_min_m": 0.3,
            "wave_max_m": 0.5,
            "wave_peak_time": "08:00",
            "current_max_kn": 0.3,
            "current_peak_time": "15:00",
            "hourly": [
                {"time": "08:00", "wave_m": 0.5, "current_kn": 0.1},
                {"time": "17:00", "wave_m": 0.4, "current_kn": 0.3},
            ],
        },
        "recommendation": {
            "best_window": "most daylight windows look manageable",
            "watch_out": "no major wave build-up in the 24h forecast",
            "confidence": "medium",
            "vessel_severity": "manageable",
            "vessel_advice": "manageable for vessels 15-24m",
        },
    }
    (route_dir / "daily_snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
    return snapshot


def write_run_snapshot(
    root,
    date_text="2026-05-29",
    run_id="2026-05-29T0630Z",
    route_id="palma_ibiza",
    wave_max=0.5,
    created_at_utc="2026-05-29 06:30 UTC",
):
    route_dir = Path(root) / date_text / "runs" / run_id / route_id
    route_dir.mkdir(parents=True)
    snapshot = write_snapshot_data(route_id, wave_max, created_at_utc=created_at_utc)
    (route_dir / "daily_snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
    (route_dir / "route_decision_map.png").write_bytes(b"fake-png")
    (Path(root) / date_text / "latest_run.json").write_text(
        json.dumps({"run_id": run_id, "path": f"runs/{run_id}"}),
        encoding="utf-8",
    )
    return snapshot


def write_map_overlay(root, date_text="2026-05-31", run_id="2026-05-31T1230Z", variable="wave_height"):
    maps_dir = Path(root) / date_text / "runs" / run_id / "maps" / variable
    maps_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{variable}_20260531_140000Z.png"
    grid_filename = f"{variable}_20260531_140000Z.grid.json"
    (maps_dir / filename).write_bytes(b"overlay-png")
    (maps_dir / grid_filename).write_text(
        json.dumps(
            {
                "latitudes": [38.5, 39.5, 40.5],
                "longitudes": [1.0, 2.0, 3.0, 4.5],
                "values": [
                    [0.4, 0.5, 0.6, 0.7],
                    [0.8, 0.9, 1.0, 1.1],
                    [1.2, 1.3, 1.4, 1.5],
                ],
            }
        ),
        encoding="utf-8",
    )
    midnight_filename = f"{variable}_20260531_000000Z.png"
    midnight_grid_filename = f"{variable}_20260531_000000Z.grid.json"
    (maps_dir / midnight_filename).write_bytes(b"midnight-png")
    (maps_dir / midnight_grid_filename).write_text(
        json.dumps(
            {
                "latitudes": [38.5, 39.5, 40.5],
                "longitudes": [1.0, 2.0, 3.0, 4.5],
                "values": [
                    [0.1, 0.2, 0.3, 0.4],
                    [0.5, 0.6, 0.7, 0.8],
                    [0.9, 1.0, 1.1, 1.2],
                ],
            }
        ),
        encoding="utf-8",
    )
    (maps_dir / "index.json").write_text(
        json.dumps(
            {
                "variable": variable,
                "units": "m",
                "color_scale": {"min": 0, "max": 2.5, "palette": "turbo"},
                "opacity": 0.698,
                "overlays": [
                    {
                        "time": "2026-05-31T00:00:00Z",
                        "filename": midnight_filename,
                        "grid_filename": midnight_grid_filename,
                        "bounds": [[38.5, 1.0], [40.5, 4.5]],
                    },
                    {
                        "time": "2026-05-31T14:00:00Z",
                        "filename": filename,
                        "grid_filename": grid_filename,
                        "bounds": [[38.5, 1.0], [40.5, 4.5]],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return filename


def write_regional_evidence(root, date_text="2026-05-31", run_id="2026-05-31T1230Z"):
    run_dir = Path(root) / date_text / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    regional = {
        "region_id": "balearics",
        "run_date": date_text,
        "run_id": run_id,
        "supported_modes": ["route_question", "location_question", "map_inspect"],
        "available_variables": {
            "wave_height": {"units": "m", "time_count": 2, "bounds": [[38.5, 1.0], [40.5, 4.5]]},
            "current_speed": {"units": "m/s", "time_count": 2, "bounds": [[38.5, 1.0], [40.5, 4.5]]},
        },
        "limitations": [
            "No seabed type",
            "No depth/bathymetry",
            "No anchoring restrictions",
            "No nearby shelter search",
        ],
    }
    (run_dir / "regional_evidence.json").write_text(json.dumps(regional), encoding="utf-8")
    return regional


def write_snapshot_data(route_id="palma_ibiza", wave_max=0.5, created_at_utc="2026-05-29 06:30 UTC"):
    return {
        "route": "Palma -> Ibiza",
        "route_id": route_id,
        "vessel_class": "medium",
        "vessel_profile": {"label": "15-24m", "manageable_m": 1.5, "restricted_m": 2.2},
        "created_at_utc": created_at_utc,
        "observations": {
            "canal_de_ibiza": {
                "name": "Buoy Canal de Ibiza",
                "last_sample_utc": "2026-05-29 06:30 UTC",
                "wave_height_m": 0.4,
            }
        },
        "forecast": {
            "wave_min_m": 0.3,
            "wave_max_m": wave_max,
            "wave_peak_time": "08:00",
            "current_max_kn": 0.3,
            "current_peak_time": "15:00",
            "hourly": [
                {"time": "08:00", "wave_m": wave_max, "current_kn": 0.1},
                {"time": "17:00", "wave_m": 0.4, "current_kn": 0.3},
            ],
        },
        "recommendation": {
            "best_window": "most daylight windows look manageable",
            "watch_out": "no major wave build-up in the 24h forecast",
            "confidence": "medium",
            "vessel_severity": "manageable",
            "vessel_advice": "manageable for vessels 15-24m",
        },
    }


def test_routes_endpoint_lists_routes_from_prediction_artifacts(tmp_path):
    write_snapshot(tmp_path)
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.get("/routes?date=2026-05-29")

    assert response.status_code == 200
    assert response.json() == {"date": "2026-05-29", "routes": ["palma_ibiza"]}


def test_local_store_uses_latest_run_folder_when_available(tmp_path):
    write_run_snapshot(tmp_path, run_id="2026-05-29T0630Z", wave_max=0.5)
    write_run_snapshot(tmp_path, run_id="2026-05-29T1230Z", wave_max=0.8)
    store = EvidenceStore(tmp_path)

    assert store.latest_run("2026-05-29") == "2026-05-29T1230Z"
    assert store.route_ids("2026-05-29") == ["palma_ibiza"]
    assert store.load_snapshot("palma_ibiza", "2026-05-29")["forecast"]["wave_max_m"] == 0.8
    assert store.load_snapshot("palma_ibiza", "2026-05-29", run_id="2026-05-29T0630Z")["forecast"]["wave_max_m"] == 0.5


def test_routes_endpoint_accepts_specific_run_id(tmp_path):
    write_run_snapshot(tmp_path, run_id="2026-05-29T0630Z", wave_max=0.5)
    write_run_snapshot(tmp_path, run_id="2026-05-29T1230Z", wave_max=0.8)
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.get("/routes/palma_ibiza/evidence?date=2026-05-29&run=2026-05-29T0630Z")

    assert response.status_code == 200
    payload = response.json()
    assert payload["date"] == "2026-05-29"
    assert payload["run"] == "2026-05-29T0630Z"
    assert payload["evidence"]["forecast"]["wave_max_m"] == 0.5


def test_question_endpoint_answers_from_stored_evidence(tmp_path):
    write_snapshot(tmp_path)
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.post(
        "/routes/palma_ibiza/question",
        json={
            "date": "2026-05-29",
            "question": "How will the sea be this afternoon?",
            "vessel_class": "medium",
            "location_label": "Palma Marina",
            "current_time": "09:30",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["route_id"] == "palma_ibiza"
    assert payload["intent"] == "conditions_soon"
    assert payload["freshness_status"] == "current"
    assert payload["freshness_warning"] is None
    assert payload["evidence_timestamp"] == "2026-05-29T06:30Z"
    assert payload["operational_stance"]["decision"] == "Conditions look workable for the next operational window."
    assert payload["operational_stance"]["best_window"] == "before late morning"
    assert payload["operational_stance"]["confidence"] == "Medium"
    assert "Conditions look workable" in payload["answer"]
    assert "Decision:" in payload["answer"]
    assert "Best window:" in payload["answer"]
    assert "Comfort:" in payload["answer"]
    assert "Risk:" in payload["answer"]
    assert "Why:" in payload["answer"]
    assert "What could change:" in payload["answer"]
    assert "Confidence:" in payload["answer"]
    assert "For this vessel size:" in payload["answer"]
    assert payload["evidence_used"]["hourly_points"] == 2
    assert payload["evidence_used"]["observations"] == ["canal_de_ibiza"]


def test_question_endpoint_exposes_wave_direction_evidence(tmp_path):
    run_id = "2026-06-09T0630Z"
    route_dir = Path(tmp_path) / "2026-06-09" / "runs" / run_id / "palma_ibiza"
    route_dir.mkdir(parents=True)
    snapshot = write_snapshot_data("palma_ibiza", wave_max=1.3, created_at_utc="2026-06-09 06:30 UTC")
    snapshot["observations"]["canal_de_ibiza"]["wave_from_direction_deg"] = 82.0
    snapshot["forecast"].update(
        {
            "wave_peak_direction_deg": 74.0,
            "swell_1_height_m": 0.8,
            "swell_1_direction_deg": 45.0,
            "swell_2_height_m": 0.4,
            "swell_2_direction_deg": 110.0,
            "wind_wave_height_m": 0.6,
            "wind_wave_direction_deg": 72.0,
            "hourly": [
                {
                    "time": "08:00",
                    "time_utc": "2026-06-09 06:00 UTC",
                    "wave_m": 1.0,
                    "wave_direction_deg": 70.0,
                    "wave_sea_state": "following sea",
                },
                {
                    "time": "10:00",
                    "time_utc": "2026-06-09 08:00 UTC",
                    "wave_m": 1.3,
                    "wave_direction_deg": 74.0,
                    "wave_sea_state": "stern quartering sea",
                },
            ],
        }
    )
    (route_dir / "daily_snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
    (Path(tmp_path) / "2026-06-09" / "latest_run.json").write_text(
        json.dumps({"run_id": run_id, "path": f"runs/{run_id}"}),
        encoding="utf-8",
    )
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.post(
        "/routes/palma_ibiza/question",
        json={
            "date": "2026-06-09",
            "run": "latest",
            "question": "Would Palma to Ibiza feel comfortable this morning?",
            "vessel_class": "medium",
            "current_date": "2026-06-09",
            "current_time": "07:30",
        },
    )

    assert response.status_code == 200
    sea_state = response.json()["evidence_used"]["sea_state"]
    assert sea_state["wave_direction_deg"]["peak"] == 74.0
    assert sea_state["wave_direction_deg"]["hourly"] == [
        {
            "time": "08:00",
            "time_utc": "2026-06-09 06:00 UTC",
            "wave_direction_deg": 70.0,
            "wave_sea_state": "following sea",
        },
        {
            "time": "10:00",
            "time_utc": "2026-06-09 08:00 UTC",
            "wave_direction_deg": 74.0,
            "wave_sea_state": "stern quartering sea",
        },
    ]
    assert sea_state["components"]["swell_1"]["direction_deg"] == 45.0
    assert sea_state["components"]["swell_2"]["direction_deg"] == 110.0
    assert sea_state["components"]["wind_wave"]["direction_deg"] == 72.0
    assert sea_state["observed_wave_height_m"]["canal_de_ibiza"]["observed_wave_direction_deg"] == 82.0


def test_question_endpoint_reports_passage_evidence_availability(tmp_path):
    route_dir = Path(tmp_path) / "2026-06-07" / "runs" / "2026-06-07T0630Z" / "palma_ibiza"
    route_dir.mkdir(parents=True)
    snapshot = write_snapshot_data(wave_max=1.5, created_at_utc="2026-06-07 06:30 UTC")
    snapshot["forecast"]["route_segments"] = {
        "departure_conditions": {"name": "Palma Bay offshore", "hourly": [{"time": "08:00", "wave_m": 0.5}]},
        "open_water_conditions": {"name": "Mid Palma-Ibiza", "hourly": [{"time": "10:00", "wave_m": 1.5}]},
        "arrival_conditions": {"name": "Ibiza Channel", "hourly": [{"time": "12:00", "wave_m": 1.1}]},
    }
    snapshot["forecast"]["passage_evidence"] = {
        "departure_time": "08:30",
        "vessel_speed_kn": 16,
        "priority": "comfort",
        "segments": [
            {
                "id": "open_water_conditions",
                "label": "Mid Palma-Ibiza",
                "eta": "10:15",
                "sample": {"time": "10:00", "wave_m": 1.5},
                "comfort": "moderate_to_poor",
            }
        ],
        "worst_segment": {
            "id": "open_water_conditions",
            "label": "Mid Palma-Ibiza",
            "time": "10:00",
            "wave_m": 1.5,
            "comfort": "moderate_to_poor",
        },
        "summary": "Worst expected section: Mid Palma-Ibiza near 1.5 m around 10:00.",
    }
    (route_dir / "daily_snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
    (route_dir / "route_decision_map.png").write_bytes(b"fake-png")
    (Path(tmp_path) / "2026-06-07" / "latest_run.json").write_text(
        json.dumps({"run_id": "2026-06-07T0630Z", "path": "runs/2026-06-07T0630Z"}),
        encoding="utf-8",
    )
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    evidence_response = client.get("/routes/palma_ibiza/evidence?date=2026-06-07&run=latest")
    question_response = client.post(
        "/routes/palma_ibiza/question",
        json={
            "date": "2026-06-07",
            "run": "latest",
            "question": "When is the best moment to leave from Palma to Ibiza today?",
            "vessel_class": "medium",
            "current_date": "2026-06-07",
            "current_time": "07:00",
        },
    )

    assert evidence_response.status_code == 200
    assert (
        evidence_response.json()["evidence"]["forecast"]["passage_evidence"]["summary"]
        == "Worst expected section: Mid Palma-Ibiza near 1.5 m around 10:00."
    )
    assert question_response.status_code == 200
    assert "Passage scenario: worst expected section is Mid Palma-Ibiza" in question_response.json()["answer"]
    evidence_used = question_response.json()["evidence_used"]
    assert evidence_used["passage_evidence"]["available"] is True
    assert evidence_used["passage_evidence"]["worst_segment"] == "Mid Palma-Ibiza"
    assert evidence_used["passage_evidence"]["departure_time"] == "08:30"


def test_question_endpoint_refreshes_stale_passage_evidence_from_route_segments(tmp_path):
    route_dir = Path(tmp_path) / "2026-06-07" / "runs" / "2026-06-07T1034Z" / "palma_ibiza"
    route_dir.mkdir(parents=True)
    snapshot = write_snapshot_data(wave_max=1.6, created_at_utc="2026-06-07 10:34 UTC")
    snapshot["forecast"]["wave_peak_time"] = "17:00"
    snapshot["forecast"]["route_segments"] = {
        "departure_conditions": {
            "name": "Palma Bay offshore",
            "hourly": [
                {"time": "09:00", "wave_m": 0.3, "wave_sea_state": "stern quartering sea"},
                {"time": "00:00", "wave_m": 0.4, "wave_sea_state": "stern quartering sea"},
            ],
        },
        "open_water_conditions": {
            "name": "Mid Palma-Ibiza",
            "hourly": [
                {"time": "11:00", "wave_m": 0.6, "wave_sea_state": "stern quartering sea"},
                {"time": "00:00", "wave_m": 0.7, "wave_sea_state": "stern quartering sea"},
            ],
        },
        "arrival_conditions": {
            "name": "Ibiza Channel",
            "hourly": [
                {"time": "12:00", "wave_m": 0.9, "wave_sea_state": "stern quartering sea"},
                {"time": "00:00", "wave_m": 0.8, "wave_sea_state": "stern quartering sea"},
            ],
        },
    }
    snapshot["forecast"]["passage_evidence"] = {
        "departure_time": "08:30",
        "vessel_speed_kn": 16,
        "priority": "comfort",
        "segments": [],
        "worst_segment": {"label": "Ibiza Channel", "time": "00:00", "wave_m": 0.8},
        "summary": "Worst expected section: Ibiza Channel near 0.8 m around 00:00.",
    }
    (route_dir / "daily_snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
    (Path(tmp_path) / "2026-06-07" / "latest_run.json").write_text(
        json.dumps({"run_id": "2026-06-07T1034Z", "path": "runs/2026-06-07T1034Z"}),
        encoding="utf-8",
    )
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.post(
        "/routes/palma_ibiza/question",
        json={
            "date": "2026-06-07",
            "run": "latest",
            "question": "When is the best moment to leave from Palma to Ibiza today?",
            "vessel_class": "medium",
            "current_date": "2026-06-07",
            "current_time": "12:45",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert "around 12:00" in payload["answer"]
    assert "around 00:00" not in payload["answer"]
    assert payload["evidence_used"]["passage_evidence"]["worst_time"] == "12:00"


def test_question_endpoint_uses_requested_departure_time_and_priority_for_passage_evidence(tmp_path):
    route_dir = Path(tmp_path) / "2026-06-07" / "runs" / "2026-06-07T1034Z" / "palma_ibiza"
    route_dir.mkdir(parents=True)
    snapshot = write_snapshot_data(wave_max=1.6, created_at_utc="2026-06-07 10:34 UTC")
    snapshot["forecast"]["wave_peak_time"] = "17:00"
    snapshot["forecast"]["route_segments"] = {
        "departure_conditions": {
            "name": "Palma Bay offshore",
            "hourly": [{"time": "10:00", "wave_m": 0.4}, {"time": "11:00", "wave_m": 0.5}],
        },
        "open_water_conditions": {
            "name": "Mid Palma-Ibiza",
            "hourly": [{"time": "12:00", "wave_m": 0.8}, {"time": "13:00", "wave_m": 1.2}],
        },
        "arrival_conditions": {
            "name": "Ibiza Channel",
            "hourly": [{"time": "13:00", "wave_m": 1.0}, {"time": "14:00", "wave_m": 1.4}],
        },
    }
    (route_dir / "daily_snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
    (Path(tmp_path) / "2026-06-07" / "latest_run.json").write_text(
        json.dumps({"run_id": "2026-06-07T1034Z", "path": "runs/2026-06-07T1034Z"}),
        encoding="utf-8",
    )
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.post(
        "/routes/palma_ibiza/question",
        json={
            "date": "2026-06-07",
            "run": "latest",
            "question": "If we leave at 10:00, what is the operational read?",
            "vessel_class": "medium",
            "departure_time": "10:00",
            "priority": "schedule",
            "current_date": "2026-06-07",
            "current_time": "09:30",
        },
    )

    assert response.status_code == 200
    passage = response.json()["evidence_used"]["passage_evidence"]
    assert passage["departure_time"] == "10:00"
    assert passage["priority"] == "schedule"
    assert passage["worst_time"] == "14:00"


def test_question_endpoint_uses_current_position_for_remaining_passage_evidence(tmp_path):
    route_dir = Path(tmp_path) / "2026-06-07" / "runs" / "2026-06-07T1034Z" / "palma_ibiza"
    route_dir.mkdir(parents=True)
    snapshot = write_snapshot_data(wave_max=1.6, created_at_utc="2026-06-07 10:34 UTC")
    snapshot["forecast"]["route_segments"] = {
        "departure_conditions": {"name": "Palma Bay offshore", "hourly": [{"time": "09:00", "wave_m": 0.5}]},
        "open_water_conditions": {"name": "Mid Palma-Ibiza", "hourly": [{"time": "11:00", "wave_m": 1.0}]},
        "arrival_conditions": {"name": "Ibiza Channel", "hourly": [{"time": "12:00", "wave_m": 1.3}]},
    }
    (route_dir / "daily_snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
    (Path(tmp_path) / "2026-06-07" / "latest_run.json").write_text(
        json.dumps({"run_id": "2026-06-07T1034Z", "path": "runs/2026-06-07T1034Z"}),
        encoding="utf-8",
    )
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.post(
        "/routes/palma_ibiza/question",
        json={
            "date": "2026-06-07",
            "run": "latest",
            "question": "What is ahead of us now?",
            "vessel_class": "medium",
            "departure_time": "08:30",
            "current_latitude": 39.19,
            "current_longitude": 2.04,
            "current_date": "2026-06-07",
            "current_time": "10:30",
        },
    )

    assert response.status_code == 200
    passage = response.json()["evidence_used"]["passage_evidence"]
    assert passage["position_status"] == "on_route"
    assert passage["remaining_segments"] == ["open_water_conditions", "arrival_conditions"]
    assert passage["segment_count"] == 2
    assert passage["worst_segment"] == "Ibiza Channel"


def test_question_endpoint_warns_when_current_position_is_far_from_route(tmp_path):
    route_dir = Path(tmp_path) / "2026-06-07" / "runs" / "2026-06-07T1034Z" / "palma_ibiza"
    route_dir.mkdir(parents=True)
    snapshot = write_snapshot_data(wave_max=1.6, created_at_utc="2026-06-07 10:34 UTC")
    snapshot["forecast"]["route_segments"] = {
        "departure_conditions": {"name": "Palma Bay offshore", "hourly": [{"time": "09:00", "wave_m": 0.5}]},
        "open_water_conditions": {"name": "Mid Palma-Ibiza", "hourly": [{"time": "11:00", "wave_m": 1.0}]},
        "arrival_conditions": {"name": "Ibiza Channel", "hourly": [{"time": "12:00", "wave_m": 1.3}]},
    }
    (route_dir / "daily_snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
    (Path(tmp_path) / "2026-06-07" / "latest_run.json").write_text(
        json.dumps({"run_id": "2026-06-07T1034Z", "path": "runs/2026-06-07T1034Z"}),
        encoding="utf-8",
    )
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.post(
        "/routes/palma_ibiza/question",
        json={
            "date": "2026-06-07",
            "run": "latest",
            "question": "What is ahead of us now?",
            "vessel_class": "medium",
            "current_latitude": 40.6,
            "current_longitude": 5.4,
            "current_date": "2026-06-07",
            "current_time": "10:30",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    warning = "Position is not close enough to the planned route; treating this as a location-based forecast instead."
    assert warning in payload["answer"]
    assert payload["evidence_used"]["passage_evidence"]["position_status"] == "off_route"
    assert payload["evidence_used"]["passage_evidence"]["position_warning"] == warning


def test_location_question_endpoint_answers_anchor_question_from_map_grids(tmp_path):
    write_run_snapshot(tmp_path, date_text="2026-05-31", run_id="2026-05-31T1230Z")
    write_map_overlay(tmp_path, date_text="2026-05-31", run_id="2026-05-31T1230Z", variable="wave_height")
    write_map_overlay(tmp_path, date_text="2026-05-31", run_id="2026-05-31T1230Z", variable="current_speed")
    write_regional_evidence(tmp_path, date_text="2026-05-31", run_id="2026-05-31T1230Z")
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.post(
        "/question",
        json={
            "date": "2026-05-31",
            "run": "latest",
            "question": "I am at this position, where should I anchor tonight?",
            "latitude": 39.45,
            "longitude": 2.1,
            "vessel_class": "small",
            "current_time": "19:00",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "location"
    assert payload["intent"] == "anchoring_guidance"
    assert payload["date"] == "2026-05-31"
    assert payload["run"] == "2026-05-31T1230Z"
    assert payload["location"]["requested_lat"] == 39.45
    assert payload["location"]["requested_lon"] == 2.1
    assert payload["environmental_evidence"]["wave_height"]["value"] == 0.9
    assert payload["environmental_evidence"]["current_speed"]["value"] == 0.9
    assert payload["regional_evidence"]["available"] is True
    assert payload["regional_evidence"]["supported_modes"] == ["route_question", "location_question", "map_inspect"]
    assert payload["regional_evidence"]["available_variables"] == ["current_speed", "wave_height"]
    assert "No seabed type" in payload["regional_evidence"]["limitations"]
    assert "Decision:" in payload["answer"]
    assert "Comfort:" in payload["answer"]
    assert "Risk:" in payload["answer"]
    assert "Why:" in payload["answer"]
    assert "Confidence:" in payload["answer"]
    assert "does not yet include seabed type" in payload["answer"]


def test_location_question_endpoint_marks_outside_forecast_domain(tmp_path):
    write_run_snapshot(tmp_path, date_text="2026-05-31", run_id="2026-05-31T1230Z")
    write_map_overlay(tmp_path, date_text="2026-05-31", run_id="2026-05-31T1230Z", variable="wave_height")
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.post(
        "/question",
        json={
            "date": "2026-05-31",
            "question": "Can I anchor here?",
            "latitude": 42.0,
            "longitude": 8.0,
            "vessel_class": "medium",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["location"]["inside_domain"] is False
    assert payload["decision"]["status"] == "manual_review"
    assert "outside the available forecast grid" in payload["answer"]


def test_question_endpoint_flags_last_night_evidence_and_avoids_repeated_window_copy(tmp_path):
    write_run_snapshot(
        tmp_path,
        date_text="2026-06-03",
        run_id="2026-06-03T1923Z",
        wave_max=1.3,
        created_at_utc="2026-06-03 19:23 UTC",
    )
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.post(
        "/routes/palma_ibiza/question",
        json={
            "date": "2026-06-03",
            "run": "2026-06-03T1923Z",
            "question": "When is the best moment to leave from Palma to Ibiza today?",
            "vessel_class": "medium",
            "location_label": "Palma",
            "current_date": "2026-06-04",
            "current_time": "10:14",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["evidence_timestamp"] == "2026-06-03T19:23Z"
    assert payload["freshness_status"] == "last_night_run"
    assert payload["freshness_warning"] == (
        "Latest available forecast package is from last night. Confirm with the morning run before committing."
    )
    assert "Latest available forecast package is from last night" in payload["answer"]
    assert "based on the latest available package" in payload["answer"]
    decision_line = payload["answer"].split("\n\n", 1)[0]
    best_window_line = payload["answer"].split("\n\n", 2)[1]
    assert decision_line != best_window_line
    assert "Decision: Palma -> Ibiza is workable today" in decision_line
    assert "Best window:" in best_window_line


def test_question_endpoint_filters_tomorrow_question_to_tomorrow_hourly_rows(tmp_path):
    run_id = "2026-06-05T1622Z"
    route_dir = Path(tmp_path) / "2026-06-05" / "runs" / run_id / "palma_ibiza"
    route_dir.mkdir(parents=True)
    snapshot = write_snapshot_data("palma_ibiza", wave_max=1.9, created_at_utc="2026-06-05 16:23 UTC")
    snapshot["forecast"].update(
        {
            "wave_min_m": 0.5,
            "wave_max_m": 1.9,
            "wave_peak_time": "11:00",
            "current_max_kn": 0.8,
            "current_peak_time": "11:00",
            "hourly": [
                {
                    "time": "11:00",
                    "time_utc": "2026-06-05 11:00 UTC",
                    "wave_m": 1.9,
                    "current_kn": 0.8,
                    "wave_direction_deg": 59.9,
                    "wave_sea_state": "following sea",
                },
                {
                    "time": "00:00",
                    "time_utc": "2026-06-05 22:00 UTC",
                    "wave_m": 1.2,
                    "current_kn": 0.4,
                    "wave_direction_deg": 73.0,
                    "wave_sea_state": "following sea",
                },
                {
                    "time": "08:00",
                    "time_utc": "2026-06-06 06:00 UTC",
                    "wave_m": 0.8,
                    "current_kn": 0.3,
                    "wave_direction_deg": 81.0,
                    "wave_sea_state": "following sea",
                },
                {
                    "time": "10:00",
                    "time_utc": "2026-06-06 08:00 UTC",
                    "wave_m": 0.7,
                    "current_kn": 0.2,
                    "wave_direction_deg": 84.0,
                    "wave_sea_state": "following sea",
                },
            ],
        }
    )
    (route_dir / "daily_snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
    (route_dir / "route_decision_map.png").write_bytes(b"fake-png")
    (Path(tmp_path) / "2026-06-05" / "latest_run.json").write_text(
        json.dumps({"run_id": run_id, "path": f"runs/{run_id}"}),
        encoding="utf-8",
    )
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.post(
        "/routes/palma_ibiza/question",
        json={
            "date": "2026-06-05",
            "run": "latest",
            "question": "Would Palma to Ibiza feel comfortable for a 15-24m vessel tomorrow morning?",
            "vessel_class": "medium",
            "current_date": "2026-06-05",
            "current_time": "21:00",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert "Tomorrow morning looks workable" in payload["answer"]
    assert "0.8 m" in payload["answer"]
    assert "08:00" in payload["answer"]
    assert "10:00" in payload["answer"]
    assert "within the requested morning window" in payload["answer"]
    assert "1.9 m" not in payload["answer"]
    assert "1.2 m" not in payload["answer"]
    assert payload["evidence_used"]["hourly_points"] == 2
    assert payload["evidence_used"]["target_local_date"] == "2026-06-06"
    assert payload["evidence_used"]["target_period_label"] == "morning"
    assert payload["evidence_used"]["route_segments"] == []


def test_question_endpoint_leave_window_tomorrow_does_not_use_late_today_message(tmp_path):
    run_id = "2026-06-05T1622Z"
    route_dir = Path(tmp_path) / "2026-06-05" / "runs" / run_id / "palma_ibiza"
    route_dir.mkdir(parents=True)
    snapshot = write_snapshot_data("palma_ibiza", wave_max=1.9, created_at_utc="2026-06-05 16:23 UTC")
    snapshot["forecast"].update(
        {
            "wave_min_m": 0.5,
            "wave_max_m": 1.9,
            "wave_peak_time": "11:00",
            "current_max_kn": 0.8,
            "current_peak_time": "11:00",
            "hourly": [
                {
                    "time": "11:00",
                    "time_utc": "2026-06-05 11:00 UTC",
                    "wave_m": 1.9,
                    "current_kn": 0.8,
                    "wave_direction_deg": 59.9,
                    "wave_sea_state": "following sea",
                },
                {
                    "time": "00:00",
                    "time_utc": "2026-06-05 22:00 UTC",
                    "wave_m": 1.2,
                    "current_kn": 0.4,
                    "wave_direction_deg": 73.0,
                    "wave_sea_state": "following sea",
                },
                {
                    "time": "08:00",
                    "time_utc": "2026-06-06 06:00 UTC",
                    "wave_m": 0.8,
                    "current_kn": 0.3,
                    "wave_direction_deg": 81.0,
                    "wave_sea_state": "following sea",
                },
                {
                    "time": "10:00",
                    "time_utc": "2026-06-06 08:00 UTC",
                    "wave_m": 0.7,
                    "current_kn": 0.2,
                    "wave_direction_deg": 84.0,
                    "wave_sea_state": "following sea",
                },
            ],
        }
    )
    (route_dir / "daily_snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
    (route_dir / "route_decision_map.png").write_bytes(b"fake-png")
    (Path(tmp_path) / "2026-06-05" / "latest_run.json").write_text(
        json.dumps({"run_id": run_id, "path": f"runs/{run_id}"}),
        encoding="utf-8",
    )
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.post(
        "/routes/palma_ibiza/question",
        json={
            "date": "2026-06-05",
            "run": "latest",
            "question": "When is the best moment to leave from Palma to Ibiza tomorrow?",
            "vessel_class": "medium",
            "current_date": "2026-06-05",
            "current_time": "21:15",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert "today's practical daylight window has passed" not in payload["answer"].lower()
    assert "workable tomorrow" in payload["answer"]
    assert "08:00" in payload["answer"]
    assert "1.9 m" not in payload["answer"]
    assert payload["evidence_used"]["target_local_date"] == "2026-06-06"
    assert payload["evidence_used"]["target_period_label"] == "tomorrow"
    assert payload["evidence_used"]["hourly_points"] == 3


def test_briefing_endpoint_renders_text_from_stored_evidence(tmp_path):
    write_snapshot(tmp_path)
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.get("/routes/palma_ibiza/briefing?date=2026-05-29&format=whatsapp")

    assert response.status_code == 200
    payload = response.json()
    assert payload["route"] == "Palma -> Ibiza"
    assert "PredSea Captain's Briefing" in payload["briefing"]


def test_artifact_endpoint_serves_latest_route_map(tmp_path):
    write_run_snapshot(tmp_path, run_id="2026-05-29T0630Z", wave_max=0.5)
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.get("/routes/palma_ibiza/artifacts/route_decision_map.png?date=2026-05-29&run=latest")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "public, max-age=300"
    assert response.content == b"fake-png"


def test_artifact_endpoint_rejects_non_public_artifacts(tmp_path):
    write_run_snapshot(tmp_path, run_id="2026-05-29T0630Z", wave_max=0.5)
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.get("/routes/palma_ibiza/artifacts/daily_snapshot.json?date=2026-05-29&run=latest")

    assert response.status_code == 404


class FakeGcsBlob:
    def __init__(self, name, text):
        self.name = name
        self._text = text

    def exists(self):
        return True

    def download_as_text(self, encoding="utf-8"):
        return self._text

    def download_as_bytes(self):
        if isinstance(self._text, bytes):
            return self._text
        return self._text.encode("utf-8")

    def generate_signed_url(self, version="v4", expiration=None, method="GET"):
        return f"https://signed.example/{self.name}?method={method}&version={version}"


class MissingFakeGcsBlob:
    def exists(self):
        return False


class FakeGcsBucket:
    def __init__(self, objects):
        self.objects = objects

    def blob(self, name):
        if name not in self.objects:
            return MissingFakeGcsBlob()
        return FakeGcsBlob(name, self.objects[name])


class FakeGcsIterator:
    def __init__(self, blobs, prefixes=None):
        self._blobs = blobs
        self.prefixes = prefixes or set()

    def __iter__(self):
        return iter(self._blobs)


class FakeGcsClient:
    def __init__(self, objects):
        self.objects = objects

    def bucket(self, bucket_name):
        return FakeGcsBucket(self.objects)

    def list_blobs(self, bucket_name, prefix="", delimiter=None):
        names = [name for name in self.objects if name.startswith(prefix)]
        if delimiter == "/":
            prefixes = set()
            for name in names:
                remaining = name[len(prefix) :]
                first_part = remaining.split("/", 1)[0]
                if first_part:
                    prefixes.add(f"{prefix}{first_part}/")
            return FakeGcsIterator([], prefixes=prefixes)
        return FakeGcsIterator([FakeGcsBlob(name, self.objects[name]) for name in names])


def test_gcs_evidence_store_reads_latest_snapshot_from_bucket():
    snapshot = write_snapshot_data = {
        "route": "Palma -> Ibiza",
        "route_id": "palma_ibiza",
        "forecast": {"hourly": []},
        "observations": {},
        "recommendation": {},
    }
    objects = {
        "predictions/2026-05-30/palma_ibiza/daily_snapshot.json": json.dumps({"route_id": "old"}),
        "predictions/2026-05-31/palma_ibiza/daily_snapshot.json": json.dumps(write_snapshot_data),
    }
    store = GcsEvidenceStore("predsea-daily-outputs", client=FakeGcsClient(objects))

    assert store.latest_date() == "2026-05-31"
    assert store.route_ids("2026-05-31") == ["palma_ibiza"]
    assert store.load_snapshot("palma_ibiza") == snapshot


def test_gcs_evidence_store_reads_latest_run_from_bucket():
    objects = {
        "predictions/2026-05-31/latest_run.json": json.dumps(
            {"run_id": "2026-05-31T1230Z", "path": "runs/2026-05-31T1230Z"}
        ),
        "predictions/2026-05-31/runs/2026-05-31T0630Z/palma_ibiza/daily_snapshot.json": json.dumps(
            write_snapshot_data(wave_max=0.4)
        ),
        "predictions/2026-05-31/runs/2026-05-31T1230Z/palma_ibiza/daily_snapshot.json": json.dumps(
            write_snapshot_data(wave_max=0.9)
        ),
    }
    store = GcsEvidenceStore("predsea-daily-outputs", client=FakeGcsClient(objects))

    assert store.latest_run("2026-05-31") == "2026-05-31T1230Z"
    assert store.route_ids("2026-05-31") == ["palma_ibiza"]
    assert store.load_snapshot("palma_ibiza", "2026-05-31")["forecast"]["wave_max_m"] == 0.9
    assert store.load_snapshot("palma_ibiza", "2026-05-31", run_id="2026-05-31T0630Z")["forecast"]["wave_max_m"] == 0.4


def test_media_endpoint_returns_api_and_signed_urls_for_route_artifacts():
    objects = {
        "predictions/2026-05-31/latest_run.json": json.dumps(
            {"run_id": "2026-05-31T1230Z", "path": "runs/2026-05-31T1230Z"}
        ),
        "predictions/2026-05-31/runs/2026-05-31T1230Z/palma_ibiza/daily_snapshot.json": json.dumps(
            write_snapshot_data(wave_max=0.9)
        ),
        "predictions/2026-05-31/runs/2026-05-31T1230Z/palma_ibiza/route_decision_map.png": b"map",
        "predictions/2026-05-31/runs/2026-05-31T1230Z/palma_ibiza/predsea_whatsapp_figure.png": b"chat",
    }
    client = TestClient(create_app(GcsEvidenceStore("predsea-daily-outputs", client=FakeGcsClient(objects))))

    response = client.get("/routes/palma_ibiza/media?date=2026-05-31&run=latest")

    assert response.status_code == 200
    payload = response.json()
    assert payload["run"] == "2026-05-31T1230Z"
    route_map = payload["artifacts"]["route_decision_map.png"]
    assert route_map["api_url"].endswith(
        "/routes/palma_ibiza/artifacts/route_decision_map.png?date=2026-05-31&run=2026-05-31T1230Z"
    )
    assert route_map["signed_url"].startswith("https://signed.example/")
    assert route_map["download_url"] == route_map["signed_url"]
    assert payload["artifacts"]["predsea_whatsapp_figure.png"]["media_type"] == "image/png"


def test_maps_endpoint_returns_leaflet_overlay_contract(tmp_path):
    write_run_snapshot(tmp_path, date_text="2026-05-31", run_id="2026-05-31T1230Z")
    filename = write_map_overlay(tmp_path)
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.get("/maps?date=2026-05-31&variable=wave_height&time=14:00")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["run"] == "2026-05-31T1230Z"
    assert payload["variable"] == "wave_height"
    assert payload["time"] == "2026-05-31T14:00:00Z"
    assert payload["bounds"] == [[38.5, 1.0], [40.5, 4.5]]
    assert payload["overlay_url"].endswith(
        f"/maps/overlays/wave_height/{filename}?date=2026-05-31&run=2026-05-31T1230Z"
    )
    assert payload["leaflet"]["method"] == "L.imageOverlay"


def test_maps_endpoint_serves_wave_partition_overlay_contract(tmp_path):
    write_run_snapshot(tmp_path, date_text="2026-05-31", run_id="2026-05-31T1230Z")
    filename = write_map_overlay(tmp_path, variable="swell_1_height")
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.get("/maps?date=2026-05-31&variable=swell_1_height&time=14:00")

    assert response.status_code == 200
    payload = response.json()
    assert payload["variable"] == "swell_1_height"
    assert payload["overlay_url"].endswith(
        f"/maps/overlays/swell_1_height/{filename}?date=2026-05-31&run=2026-05-31T1230Z"
    )


def test_map_overlay_endpoint_serves_overlay_png(tmp_path):
    write_run_snapshot(tmp_path, date_text="2026-05-31", run_id="2026-05-31T1230Z")
    filename = write_map_overlay(tmp_path)
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.get(f"/maps/overlays/wave_height/{filename}?date=2026-05-31&run=latest")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content == b"overlay-png"


def test_map_overlay_endpoint_serves_wave_partition_png(tmp_path):
    write_run_snapshot(tmp_path, date_text="2026-05-31", run_id="2026-05-31T1230Z")
    filename = write_map_overlay(tmp_path, variable="wind_wave_height")
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.get(f"/maps/overlays/wind_wave_height/{filename}?date=2026-05-31&run=latest")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content == b"overlay-png"


def test_map_inspect_endpoint_samples_nearest_grid_point(tmp_path):
    write_run_snapshot(tmp_path, date_text="2026-05-31", run_id="2026-05-31T1230Z")
    write_map_overlay(tmp_path)
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.get(
        "/maps/inspect?date=2026-05-31&variable=wave_height&time=14:00&lat=39.45&lon=2.1"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["run"] == "2026-05-31T1230Z"
    assert payload["time"] == "2026-05-31T14:00:00Z"
    assert payload["sampled_lat"] == 39.5
    assert payload["sampled_lon"] == 2.0
    assert payload["value"] == 0.9
    assert payload["units"] == "m"
    assert payload["inside_domain"] is True


def test_media_endpoint_download_url_falls_back_to_api_url_for_local_store(tmp_path):
    write_run_snapshot(tmp_path, date_text="2026-05-31", run_id="2026-05-31T1230Z")
    route_dir = Path(tmp_path) / "2026-05-31" / "runs" / "2026-05-31T1230Z" / "palma_ibiza"
    (route_dir / "predsea_whatsapp_figure.png").write_bytes(b"chat")
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.get("/routes/palma_ibiza/media?date=2026-05-31&run=latest")

    assert response.status_code == 200
    route_map = response.json()["artifacts"]["route_decision_map.png"]
    assert route_map["signed_url"] is None
    assert route_map["download_url"] == route_map["api_url"]


def test_health_reports_gcs_backend_when_gcs_store_is_injected():
    objects = {
        "predictions/2026-05-31/palma_ibiza/daily_snapshot.json": json.dumps(
            {
                "route": "Palma -> Ibiza",
                "route_id": "palma_ibiza",
                "forecast": {"hourly": []},
                "observations": {},
                "recommendation": {},
            }
        )
    }
    client = TestClient(create_app(GcsEvidenceStore("predsea-daily-outputs", client=FakeGcsClient(objects))))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "latest_date": "2026-05-31",
        "latest_run": None,
        "storage_backend": "gcs",
    }
