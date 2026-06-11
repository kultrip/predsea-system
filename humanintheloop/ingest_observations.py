"""Multi-source observation ingestion orchestrator.

Combines SOCIB public observations (existing) with Puertos del Estado
buoy observations (new in Phase 2) to provide a unified ground-truth
observation layer for route validation and evidence packages.
"""

import os

import fetch_portus
import socib_api


def fetch_all_observations(include_puertos=True, include_portus=False, dry_run=False):
    """Fetch observations from all configured sources.

    Returns a merged dict of observations and a lineage record
    documenting which sources contributed.
    """
    all_observations = {}
    lineage_sources = []
    errors = {}

    # SOCIB observations via api.socib.es (hard cutover)
    try:
        socib_bundle = socib_api.fetch_socib_bundle(dry_run=dry_run)
        socib_obs = socib_bundle.get("observations", {})
        all_observations.update(socib_obs)
        if socib_obs:
            lineage_sources.append("socib_observations")
        if socib_bundle.get("errors"):
            errors["socib"] = socib_bundle["errors"]
    except Exception as error:
        errors["socib"] = str(error)

    # Puertos del Estado observations (Phase 2 addition)
    if include_puertos and _puertos_enabled():
        try:
            import fetch_puertos_estado
            puertos_result = fetch_puertos_estado.fetch_balearic_observations(dry_run=dry_run)
            puertos_obs = puertos_result.get("observations", {})
            # Prefix Puertos stations to avoid key collisions with SOCIB
            for key, value in puertos_obs.items():
                prefixed_key = f"puertos_{key}"
                all_observations[prefixed_key] = value
            if puertos_obs:
                lineage_sources.append("puertos_del_estado")
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
            if portus_result.get("errors"):
                errors["puertos_portus"] = portus_result["errors"]
        except Exception as error:
            errors["puertos_portus"] = str(error)

    ground_truth_lineage = _build_ground_truth_lineage(
        all_observations, lineage_sources, errors,
    )

    result = {
        "observations": all_observations,
        "ground_truth_lineage": ground_truth_lineage,
        "errors": errors,
    }
    if "socib_bundle" in locals():
        result["socib"] = socib_bundle
    if include_portus and _portus_enabled():
        result["portus"] = portus_result if "portus_result" in locals() else {
            "observations": {},
            "predictions": {},
            "errors": errors.get("puertos_portus", {}),
        }
    return result


def _puertos_enabled():
    """Check if Puertos del Estado ingestion is enabled."""
    return os.environ.get("PREDSEA_ENABLE_PUERTOS_OBSERVATIONS", "0") == "1"


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
    if "socib_observations" in sources and (puertos_present or portus_present):
        if portus_present and not puertos_present:
            source = "socib_and_puertos_portus"
        else:
            source = "socib_and_puertos_del_estado"
        status = "matched_successfully"
    elif portus_present:
        source = "puertos_portus"
        status = "matched_successfully"
    elif puertos_present:
        source = "puertos_del_estado_redext"
        status = "matched_successfully"
    elif "socib_observations" in sources:
        source = "socib_observations"
        status = "matched_successfully"
    else:
        source = None
        status = "unavailable"

    return {
        "source": source,
        "status": status,
        "providers": sources,
        "station_count": len(observations),
    }
