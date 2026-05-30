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


def test_routes_endpoint_lists_routes_from_prediction_artifacts(tmp_path):
    write_snapshot(tmp_path)
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.get("/routes?date=2026-05-29")

    assert response.status_code == 200
    assert response.json() == {"date": "2026-05-29", "routes": ["palma_ibiza"]}


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


class FakeGcsBlob:
    def __init__(self, name, text):
        self.name = name
        self._text = text

    def exists(self):
        return True

    def download_as_text(self, encoding="utf-8"):
        return self._text


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
        "storage_backend": "gcs",
    }
