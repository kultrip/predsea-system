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


def write_run_snapshot(root, date_text="2026-05-29", run_id="2026-05-29T0630Z", route_id="palma_ibiza", wave_max=0.5):
    route_dir = Path(root) / date_text / "runs" / run_id / route_id
    route_dir.mkdir(parents=True)
    snapshot = write_snapshot_data(route_id, wave_max)
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


def write_snapshot_data(route_id="palma_ibiza", wave_max=0.5):
    return {
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
    assert "conditions look workable" in payload["answer"]
    assert "Recommendation:" not in payload["answer"]
    assert "Reason:" not in payload["answer"]
    assert payload["evidence_used"]["hourly_points"] == 2
    assert payload["evidence_used"]["observations"] == ["canal_de_ibiza"]


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


def test_map_overlay_endpoint_serves_overlay_png(tmp_path):
    write_run_snapshot(tmp_path, date_text="2026-05-31", run_id="2026-05-31T1230Z")
    filename = write_map_overlay(tmp_path)
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.get(f"/maps/overlays/wave_height/{filename}?date=2026-05-31&run=latest")

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
