"""Multi-source observation ingestion orchestrator.

Builds the canonical ground-truth observation layer from Puertos del Estado
and optional Portus observations. SOCIB is intentionally excluded from the
active ETL path so observation ingestion remains Puertos-first and resilient.
"""

import os

import fetch_portus
import validation_archive


def fetch_all_observations(include_puertos=True, include_portus=False, dry_run=False):
    """Fetch observations from all configured sources.

    Returns a merged dict of observations and a lineage record
    documenting which sources contributed.
    """
    all_observations = {}
    lineage_sources = []
    errors = {}
    station_metadata_candidates = []

    # Puertos del Estado observations (Phase 2 addition)
    if include_puertos and _puertos_enabled():
        try:
            import fetch_puertos_estado
            puertos_result = fetch_puertos_estado.fetch_balearic_observations(dry_run=dry_run)
            puertos_obs = puertos_result.get("observations", {})
            # Prefix Puertos stations to avoid key collisions across sources
            for key, value in puertos_obs.items():
                prefixed_key = f"puertos_{key}"
                all_observations[prefixed_key] = value
            if puertos_obs:
                lineage_sources.append("puertos_del_estado")
            station_metadata_candidates.extend(puertos_result.get("catalog_stations") or [])
            if puertos_result.get("errors"):
                errors["puertos_del_estado"] = puertos_result["errors"]
        except Exception as error:
            errors["puertos_del_estado"] = str(error)

    # Portus JSON observations and prediction/model metadata
    if include_portus and _portus_enabled():
        try:
            portus_result = fetch_portus.fetch_portus_bundle(dry_run=dry_run)
            portus_obs = portus_result.get("observations", {})
            for key, value in portus_obs.items():
                prefixed_key = key if key.startswith("portus_") else f"portus_{key}"
                all_observations[prefixed_key] = value
            if portus_obs:
                lineage_sources.append("puertos_portus")
            station_metadata_candidates.extend(portus_result.get("stations") or [])
            if portus_result.get("errors"):
                errors["puertos_portus"] = portus_result["errors"]
        except Exception as error:
            errors["puertos_portus"] = str(error)

    station_metadata = validation_archive.build_station_metadata_rows(
        all_observations,
        station_metadata=station_metadata_candidates,
    )

    ground_truth_lineage = _build_ground_truth_lineage(
        all_observations, lineage_sources, errors,
    )

    result = {
        "observations": all_observations,
        "station_metadata": station_metadata,
        "ground_truth_lineage": ground_truth_lineage,
        "errors": errors,
    }
    if include_portus and _portus_enabled():
        result["portus"] = portus_result if "portus_result" in locals() else {
            "observations": {},
            "predictions": {},
            "errors": errors.get("puertos_portus", {}),
        }
    return result


def _puertos_enabled():
    """Check if Puertos del Estado ingestion is enabled."""
    return os.environ.get("PREDSEA_ENABLE_PUERTOS_OBSERVATIONS", "1") == "1"


def _portus_enabled():
    """Check if Portus ingestion is enabled."""
    return os.environ.get("PREDSEA_ENABLE_PORTUS_OBSERVATIONS", "1") == "1"


def _build_ground_truth_lineage(observations, sources, errors):
    """Build a ground-truth validation lineage record."""
    if not observations:
        return {
            "source": None,
            "status": "unavailable",
            "providers": [],
        }

    # Determine primary source based on availability
    portus_present = "puertos_portus" in sources
    puertos_present = "puertos_del_estado" in sources
    if puertos_present and portus_present:
        source = "puertos_del_estado_and_puertos_portus"
        status = "matched_successfully"
    elif puertos_present:
        source = "puertos_del_estado"
        status = "matched_successfully"
    elif portus_present:
        source = "puertos_portus"
        status = "matched_successfully"
    else:
        source = "puertos_observations"
        status = "matched_successfully"

    return {
        "source": source,
        "status": status,
        "providers": sources,
        "station_count": len(observations),
    }
