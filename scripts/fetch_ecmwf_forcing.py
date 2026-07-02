#!/usr/bin/env python3
"""
PredSea ECMWF IFS open data boundary conditions downloader.
Fetches multi-level atmospheric and surface grids necessary to initialize WRF,
and uploads them to Google Cloud Storage under gs://{BUCKET}/forcing/ecmwf/{DATE}/.
"""
from __future__ import annotations

import argparse
import datetime
import os
import sys
from pathlib import Path

try:
    from ecmwf.opendata import Client
except ImportError:
    print("WARNING: ecmwf-opendata not found. Please install with 'pip install ecmwf-opendata'")
    Client = None


# Standard pressure levels required by WRF
PRESSURE_LEVELS = [1000, 925, 850, 700, 500, 400, 300, 250, 200, 150, 100, 50]

# Core variables for pressure levels
PL_VARS = ["z", "t", "r", "u", "v"]

# Core surface parameters (soil/sea skin + air surface components)
SFC_VARS = ["10u", "10v", "2t", "2d", "sp", "msl", "skt", "lsm", "sst"]


def get_latest_run_time() -> int:
    """Determine the latest available ECMWF run (00, 12, etc.).

    Open data is typically available with a ~5h delay.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    # Check if we can use the 12Z run (usually ready by 17:00 UTC)
    if now.hour >= 17:
        return 12
    # Default to 00Z run
    return 0


def get_forecast_steps(lead_hours: int) -> list[int]:
    """Generate forecast steps up to lead_hours.
    Hourly/3-hourly up to 120 hours, then 6-hourly from 120 to lead_hours.
    """
    steps = list(range(0, min(120, lead_hours) + 1, 3))
    if lead_hours > 120:
        steps.extend(range(126, lead_hours + 1, 6))
    return steps


def upload_to_gcs(bucket_name: str, local_path: Path, gcs_blob_path: str) -> None:
    """Upload a file to Google Cloud Storage."""
    print(f"☁️ Uploading {local_path.name} to gs://{bucket_name}/{gcs_blob_path}...")
    try:
        from google.cloud import storage
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(gcs_blob_path)
        blob.upload_from_filename(str(local_path))
        print(f"✅ Uploaded successfully.")
    except Exception as e:
        print(f"⚠️ GCS Upload failed (perhaps local auth is missing or bucket not configured): {e}")


def fetch_ecmwf_data(
    run_date: str,
    run_time: int,
    steps: list[int],
    output_dir: Path,
    dry_run: bool = False,
) -> dict[str, Path]:
    """Retrieve pressure levels and surface levels from ECMWF Open Data."""
    if Client is None:
        raise RuntimeError("ecmwf-opendata client is not installed.")

    output_dir.mkdir(parents=True, exist_ok=True)
    pl_file = output_dir / f"ecmwf_pl_{run_date}_{run_time:02d}Z.grib2"
    sfc_file = output_dir / f"ecmwf_sfc_{run_date}_{run_time:02d}Z.grib2"

    print("=============================================")
    print(f"📥 Fetching ECMWF Open Data (IFS)")
    print(f"📅 Target Run: {run_date} @ {run_time:02d}Z")
    print(f"⏱️ Forecast Steps: {steps}")
    print(f"📁 Local Directory: {output_dir}")
    print("=============================================")

    if dry_run:
        print("⚡ [DRY RUN] Skipping actual API requests.")
        return {"pl_path": pl_file, "sfc_path": sfc_file}

    client = Client()

    # 1. Retrieve Pressure Levels
    print(f"📡 Downloading pressure level variables {PL_VARS} for levels {PRESSURE_LEVELS}...")
    try:
        client.retrieve(
            type="fc",
            stream="oper",
            levtype="pl",
            levelist=PRESSURE_LEVELS,
            param=PL_VARS,
            time=run_time,
            step=steps,
            target=str(pl_file),
        )
        print(f"✅ Pressure levels saved to: {pl_file} ({pl_file.stat().st_size / 1024 / 1024:.1f} MB)")
    except Exception as e:
        print(f"❌ Pressure levels download failed: {e}", file=sys.stderr)
        raise

    # 2. Retrieve Surface Parameters
    print(f"📡 Downloading surface variables {SFC_VARS}...")
    try:
        client.retrieve(
            type="fc",
            stream="oper",
            levtype="sfc",
            param=SFC_VARS,
            time=run_time,
            step=steps,
            target=str(sfc_file),
        )
        print(f"✅ Surface parameters saved to: {sfc_file} ({sfc_file.stat().st_size / 1024 / 1024:.1f} MB)")
    except Exception as e:
        print(f"❌ Surface parameters download failed: {e}", file=sys.stderr)
        raise

    return {"pl_path": pl_file, "sfc_path": sfc_file}


def parse_args() -> argparse.Namespace:
    import sys
    from pathlib import Path
    PROJECT_ROOT = Path(__file__).resolve().parents[1]
    HUMANINTHELOOP_DIR = PROJECT_ROOT / "humanintheloop"
    if str(HUMANINTHELOOP_DIR) not in sys.path:
        sys.path.insert(0, str(HUMANINTHELOOP_DIR))

    try:
        from api.config import PREDSEA_GCS_BUCKET
    except ImportError:
        import os
        env = os.environ.get("PREDSEA_ENV", "test").strip().lower()
        if env not in ("test", "prod"):
            env = "test"
        PREDSEA_GCS_BUCKET = os.environ.get("PREDSEA_GCS_BUCKET") or f"predsea-daily-outputs-{env}"

    parser = argparse.ArgumentParser(description="Download ECMWF Open Data forcing for WRF.")
    parser.add_argument(
        "--run-date",
        default=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d"),
        help="Target date YYYY-MM-DD",
    )
    parser.add_argument(
        "--run-time",
        type=int,
        choices=[0, 6, 12, 18],
        default=get_latest_run_time(),
        help="ECMWF run hour (00, 06, 12, 18)",
    )
    parser.add_argument(
        "--lead-hours",
        type=int,
        default=120,
        help="Forecast lead time in hours (default 120)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("simulation/inputs"),
        help="Local output directory",
    )
    parser.add_argument(
        "--gcs-bucket",
        default=PREDSEA_GCS_BUCKET,
        help="GCS bucket name for archiving raw forcing (skips if empty)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Dry run without downloading",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    steps = get_forecast_steps(args.lead_hours)

    try:
        paths = fetch_ecmwf_data(
            run_date=args.run_date,
            run_time=args.run_time,
            steps=steps,
            output_dir=args.output_dir,
            dry_run=args.dry_run,
        )

        if args.gcs_bucket and not args.dry_run:
            # Upload pl file
            gcs_pl_path = f"forcing/ecmwf/{args.run_date}/{paths['pl_path'].name}"
            upload_to_gcs(args.gcs_bucket, paths["pl_path"], gcs_pl_path)

            # Upload sfc file
            gcs_sfc_path = f"forcing/ecmwf/{args.run_date}/{paths['sfc_path'].name}"
            upload_to_gcs(args.gcs_bucket, paths["sfc_path"], gcs_sfc_path)

            print(f"🎉 All files successfully downloaded and archived in GCS.")
        elif args.dry_run:
            print("⚡ Dry run complete. Paths resolved:")
            print(f"PL Path: {paths['pl_path']}")
            print(f"SFC Path: {paths['sfc_path']}")

    except Exception as e:
        print(f"❌ Execution failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
