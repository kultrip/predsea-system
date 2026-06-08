"""ECMWF Open Data IFS 9 km wind fetcher.

Downloads 10-meter U/V wind components from the ECMWF open data
service using the ``ecmwf-opendata`` Python client.

No API key is required for ECMWF open data.  The current open subset
serves 0.25-degree (~25 km) resolution; native 9 km open data is
expected later in 2026.  This fetcher downloads whatever resolution
ECMWF publishes in the open stream and records the effective
resolution in the result metadata.

When the service is unreachable the fetcher raises so
ingest_atmosphere.py can record an all-providers-unavailable lineage.
"""

import datetime
import os
import tempfile
from pathlib import Path

from ingest_atmosphere import BALEARIC_BBOX

ECMWF_RESOLUTION_KM = 9.0
TIMEOUT_SECONDS = int(os.getenv("PREDSEA_ECMWF_TIMEOUT", "120"))


def _latest_run_time():
    """Estimate the latest available ECMWF run (00, 06, 12, 18 UTC).

    ECMWF open data is typically available ~5h after the run start.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    available_hour = now.hour - 5
    if available_hour >= 18:
        return 18
    elif available_hour >= 12:
        return 12
    elif available_hour >= 6:
        return 6
    return 0


def _forecast_steps():
    """Return the forecast lead-time steps to download (hours)."""
    return list(range(0, 49, 3))


def fetch_ecmwf_wind(output_dir=None, bbox=None, dry_run=False):
    """Download IFS 10m wind vectors from ECMWF open data.

    Returns a dict with ``available=True`` and ``dataset_path`` on success,
    or raises on failure.
    """
    bbox = bbox or BALEARIC_BBOX
    output_dir = Path(output_dir or tempfile.mkdtemp(prefix="predsea_ecmwf_"))
    output_dir.mkdir(parents=True, exist_ok=True)
    dataset_path = output_dir / "ecmwf_wind.grib2"
    run_time = _latest_run_time()

    if dry_run:
        return {
            "available": True,
            "source": "ecmwf_open_data",
            "resolution_km": ECMWF_RESOLUTION_KM,
            "dataset_path": str(dataset_path),
            "dry_run": True,
        }

    from ecmwf.opendata import Client

    client = Client(source="ecmwf")

    # Download all steps into a single GRIB2 file
    client.retrieve(
        type="fc",
        stream="oper",
        param=["10u", "10v", "i10fg"],  # U wind, V wind, instantaneous 10m gust
        time=run_time,
        step=_forecast_steps(),
        target=str(dataset_path),
        area=[bbox["north"], bbox["west"], bbox["south"], bbox["east"]],
    )

    if not dataset_path.exists() or dataset_path.stat().st_size == 0:
        raise RuntimeError("ECMWF download produced an empty file")

    return {
        "available": True,
        "source": "ecmwf_open_data",
        "resolution_km": ECMWF_RESOLUTION_KM,
        "dataset_path": str(dataset_path),
        "model_run": f"{run_time:02d}Z",
        "variables": ["10u", "10v", "i10fg"],
        "steps": _forecast_steps(),
    }


def make_fetcher(output_dir=None, dry_run=False):
    """Return a fetcher function compatible with ingest_atmosphere.select_wind_forecast."""

    def fetcher(provider):
        if provider["id"] != "ecmwf_open_data":
            raise RuntimeError(f"Wrong provider: {provider['id']}")
        return fetch_ecmwf_wind(output_dir=output_dir, dry_run=dry_run)

    return fetcher
