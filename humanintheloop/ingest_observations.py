"""Multi-source observation ingestion orchestrator.

Combines SOCIB public observations (existing) with Puertos del Estado
buoy observations (new in Phase 2) to provide a unified ground-truth
observation layer for route validation and evidence packages.
"""

import os

import socib_public


def fetch_all_observations(include_puertos=True, dry_run=False):
    """Fetch observations from all configured sources.

    Returns a merged dict of observations and a lineage record
    documenting which sources contributed.
    """
    all_observations = {}
    lineage_sources = []
    errors = {}

    # SOCIB public observations (existing baseline)
    try:
        socib_obs = socib_public.fetch_public_observations()
        all_observations.update(socib_obs)
        if socib_obs:
            lineage_sources.append("socib_observations")
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

    ground_truth_lineage = _build_ground_truth_lineage(
        all_observations, lineage_sources, errors,
    )

    return {
        "observations": all_observations,
        "ground_truth_lineage": ground_truth_lineage,
        "errors": errors,
    }


def _puertos_enabled():
    """Check if Puertos del Estado ingestion is enabled."""
    return os.environ.get("PREDSEA_ENABLE_PUERTOS_OBSERVATIONS", "0") == "1"


def _build_ground_truth_lineage(observations, sources, errors):
    """Build a ground-truth validation lineage record."""
    if not observations:
        return {
            "source": None,
            "status": "unavailable",
            "providers": [],
        }

    # Determine primary source based on availability
    if "puertos_del_estado" in sources and "socib_observations" in sources:
        source = "socib_and_puertos_del_estado"
        status = "matched_successfully"
    elif "puertos_del_estado" in sources:
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
