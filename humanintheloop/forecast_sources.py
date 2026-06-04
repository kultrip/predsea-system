from pathlib import Path


COPERNICUS_SOURCE = {
    "id": "copernicus",
    "label": "Copernicus Marine Mediterranean forecast",
}
SOCIB_SOURCE = {
    "id": "socib",
    "label": "SOCIB WMOP/SAPO forecast",
}


def fetch_available_forecasts(fetch_data, output_dir=None, dry_run=False):
    """Fetch all configured forecast sources without letting one source block another."""
    sources = [
        fetch_copernicus_forecast(fetch_data, dry_run=dry_run),
        fetch_socib_forecast(fetch_data, output_dir=output_dir, dry_run=dry_run),
    ]
    mark_preferred_source(sources)
    return sources


def fetch_copernicus_forecast(fetch_data, dry_run=False):
    source = dict(COPERNICUS_SOURCE)
    try:
        fetch_data.get_balearic_forecast(dry_run=dry_run)
        output_dir = Path(fetch_data.OUTPUT_DIR)
        source.update(
            available=True,
            waves_path=output_dir / "balearic_waves.nc",
            currents_path=output_dir / "balearic_currents.nc",
        )
    except Exception as error:
        source.update(available=False, error=str(error))
    return source


def fetch_socib_forecast(fetch_data, output_dir=None, dry_run=False):
    source = dict(SOCIB_SOURCE)
    try:
        import socib_thredds

        target_dir = Path(output_dir or fetch_data.OUTPUT_DIR) / "socib_thredds"
        result = socib_thredds.get_balearic_forecast(output_dir=target_dir, dry_run=dry_run)
        source.update(
            available=True,
            waves_path=Path(result["waves_path"]),
            currents_path=Path(result["currents_path"]),
            metadata=result.get("metadata", {}),
        )
    except Exception as error:
        source.update(available=False, error=str(error))
    return source


def mark_preferred_source(sources, preferred_source_id="copernicus"):
    available = [source for source in sources if source.get("available")]
    for source in sources:
        source["preferred"] = False
    if not available:
        return sources

    preferred = next(
        (source for source in available if source.get("id") == preferred_source_id),
        available[0],
    )
    preferred["preferred"] = True
    return sources


def source_manifest_entry(source):
    entry = {
        "id": source.get("id"),
        "label": source.get("label"),
        "available": bool(source.get("available")),
        "preferred": bool(source.get("preferred")),
    }
    if source.get("error"):
        entry["error"] = source["error"]
    if source.get("metadata"):
        entry["metadata"] = source["metadata"]
    return entry
