SCHEMA_VERSION = "predsea.evidence.v1"


def build_route_evidence_package(snapshot, route):
    forecast = snapshot.get("forecast", {})
    recommendation = snapshot.get("recommendation", {})
    observations = snapshot.get("observations", {})
    validation = route.get("validation", {})
    current_validation = route.get("current_validation", {})

    return {
        "schema_version": SCHEMA_VERSION,
        "subject": {
            "type": "route",
            "id": route["id"],
            "name": route["name"],
            "note": route.get("route_note"),
            "origin": route.get("origin"),
            "destination": route.get("destination"),
            "sample_points": route.get("sample_points", []),
        },
        "created_at_utc": snapshot.get("created_at_utc"),
        "models": {
            "waves": "copernicus_med_forecast",
            "currents": "copernicus_med_forecast",
        },
        "observations": {
            "sources": sorted(observations),
            "records": observations,
        },
        "forecast": {
            "sampling_method": forecast.get("sampling_method"),
            "variables": {
                "wave_height_m": {
                    "min": forecast.get("wave_min_m"),
                    "max": forecast.get("wave_max_m"),
                    "peak_time": forecast.get("wave_peak_time"),
                    "peak_direction_deg": forecast.get("wave_peak_direction_deg"),
                    "hourly": [
                        {
                            key: row[key]
                            for key in ("time", "time_utc", "wave_m", "wave_direction_deg")
                            if key in row
                        }
                        for row in forecast.get("hourly", [])
                    ],
                },
                "current_speed_kn": {
                    "max": forecast.get("current_max_kn"),
                    "peak_time": forecast.get("current_peak_time"),
                    "hourly": [
                        {
                            key: row[key]
                            for key in ("time", "time_utc", "current_kn", "current_direction_deg")
                            if key in row
                        }
                        for row in forecast.get("hourly", [])
                    ],
                },
            },
        },
        "operational_interpretation": {
            "status": recommendation.get("vessel_severity", "unknown"),
            "best_window": recommendation.get("best_window"),
            "watch_out": recommendation.get("watch_out"),
            "vessel_advice": recommendation.get("vessel_advice"),
            "confidence": recommendation.get("confidence", "low"),
        },
        "data_quality": {
            "nearest_wave_truth_source": validation.get("truth_source"),
            "wave_truth_suitability": validation.get("suitability"),
            "nearest_current_truth_source": current_validation.get("truth_source"),
            "current_truth_suitability": current_validation.get("suitability"),
            "buoy_truth_available": bool(validation.get("truth_source") or current_validation.get("truth_source")),
        },
        "decision_context": snapshot,
    }


def snapshot_from_evidence(package):
    return package.get("decision_context", package)
