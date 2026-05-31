import json
from pathlib import Path

import briefing
import evidence_package
from api.evidence_store import EvidenceStore


def sample_snapshot():
    return {
        "route": "Palma -> Ibiza",
        "route_id": "palma_ibiza",
        "route_note": "Exposed SW Mallorca to Ibiza crossing.",
        "vessel_class": "medium",
        "vessel_profile": {"label": "15-24m", "manageable_m": 1.5, "restricted_m": 2.2},
        "created_at_utc": "2026-05-31 06:30 UTC",
        "observations": {
            "canal_de_ibiza": {
                "name": "Buoy Canal de Ibiza",
                "last_sample_utc": "2026-05-31 06:20 UTC",
                "wave_height_m": 0.4,
            }
        },
        "forecast": {
            "wave_min_m": 0.2,
            "wave_max_m": 0.8,
            "wave_peak_time": "17:00",
            "current_max_kn": 0.6,
            "current_peak_time": "16:00",
            "hourly": [
                {"time": "09:00", "wave_m": 0.3, "current_kn": 0.2},
                {"time": "17:00", "wave_m": 0.8, "current_kn": 0.6},
            ],
            "sampling_method": "route_exposed_max",
        },
        "recommendation": {
            "best_window": "before late afternoon",
            "watch_out": "waves build toward 0.8 m around 17:00",
            "confidence": "medium",
            "vessel_severity": "manageable",
            "vessel_advice": "manageable for vessels 15-24m",
        },
    }


def sample_route():
    return {
        "id": "palma_ibiza",
        "name": "Palma -> Ibiza",
        "route_note": "Exposed SW Mallorca to Ibiza crossing.",
        "origin": {"name": "Palma", "longitude": 2.6502, "latitude": 39.5696},
        "destination": {"name": "Ibiza", "longitude": 1.435, "latitude": 38.9089},
        "validation": {
            "truth_source": "canal_de_ibiza",
            "suitability": "representative for Ibiza Channel exposure",
        },
        "current_validation": {
            "truth_source": None,
            "suitability": "no route-specific SOCIB current observation configured",
        },
        "sample_points": [
            {"name": "Palma Bay offshore", "longitude": 2.55, "latitude": 39.45},
            {"name": "Ibiza Channel", "longitude": 1.83, "latitude": 38.85},
        ],
    }


def test_build_route_evidence_package_has_decision_ready_structure():
    package = evidence_package.build_route_evidence_package(sample_snapshot(), sample_route())

    assert package["schema_version"] == "predsea.evidence.v1"
    assert package["subject"] == {
        "type": "route",
        "id": "palma_ibiza",
        "name": "Palma -> Ibiza",
        "note": "Exposed SW Mallorca to Ibiza crossing.",
        "origin": {"name": "Palma", "longitude": 2.6502, "latitude": 39.5696},
        "destination": {"name": "Ibiza", "longitude": 1.435, "latitude": 38.9089},
        "sample_points": [
            {"name": "Palma Bay offshore", "longitude": 2.55, "latitude": 39.45},
            {"name": "Ibiza Channel", "longitude": 1.83, "latitude": 38.85},
        ],
    }
    assert package["forecast"]["variables"]["wave_height_m"]["max"] == 0.8
    assert package["forecast"]["variables"]["current_speed_kn"]["peak_time"] == "16:00"
    assert package["operational_interpretation"]["best_window"] == "before late afternoon"
    assert package["data_quality"]["nearest_wave_truth_source"] == "canal_de_ibiza"
    assert package["decision_context"] == sample_snapshot()


def test_write_outputs_writes_evidence_json_beside_daily_snapshot(tmp_path):
    snapshot = sample_snapshot()
    briefing.write_outputs(snapshot, output_dir=tmp_path, route=sample_route())

    evidence_path = tmp_path / "evidence.json"

    assert evidence_path.exists()
    package = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert package["subject"]["id"] == "palma_ibiza"
    assert package["decision_context"]["forecast"]["wave_max_m"] == 0.8


def test_evidence_store_prefers_evidence_decision_context_over_daily_snapshot(tmp_path):
    route_dir = Path(tmp_path) / "2026-05-31" / "palma_ibiza"
    route_dir.mkdir(parents=True)
    (route_dir / "daily_snapshot.json").write_text(
        json.dumps({"route_id": "palma_ibiza", "forecast": {"wave_max_m": 9.9}}),
        encoding="utf-8",
    )
    (route_dir / "evidence.json").write_text(
        json.dumps(
            {
                "schema_version": "predsea.evidence.v1",
                "decision_context": {
                    "route_id": "palma_ibiza",
                    "forecast": {"wave_max_m": 0.8},
                },
            }
        ),
        encoding="utf-8",
    )

    snapshot = EvidenceStore(tmp_path).load_snapshot("palma_ibiza", "2026-05-31")

    assert snapshot["forecast"]["wave_max_m"] == 0.8
