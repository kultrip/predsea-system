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

try:
    import eccodes
except ImportError:
    print("WARNING: eccodes not found. GRIB repacking will be skipped.")
    eccodes = None


# Standard pressure levels required by WRF
PRESSURE_LEVELS = [1000, 925, 850, 700, 500, 400, 300, 250, 200, 150, 100, 50]

# Core variables for pressure levels
PL_VARS = ["z", "t", "r", "u", "v"]

# Core surface parameters (standard surface catalog)
SFC_VARS = [
    "10u", "10v", "2t", "2d", "sp", "msl", "skt", "lsm",
    "st", "swvl", "sd"
]

# Soil parameters (often require levtype="sol" and levelist in some catalogs)
# In ECMWF Open Data IFS, sot/vsw are often used for multi-layer soil.
SOIL_VARS = ["sot", "vsw"]
SOIL_LEVELS = [1, 2, 3, 4]


def expected_valid_times(run_date: str, run_time: int, steps: list[int]) -> set[tuple[int, int]]:
    base = datetime.datetime.strptime(f"{run_date} {run_time:02d}", "%Y-%m-%d %H")
    expected = set()
    for step in steps:
        valid = base + datetime.timedelta(hours=int(step))
        expected.add((int(valid.strftime("%Y%m%d")), int(valid.strftime("%H%M"))))
    return expected


def grib_valid_times(path: Path) -> set[tuple[int, int]]:
    if eccodes is None:
        raise RuntimeError("eccodes is required to validate ECMWF forcing times.")
    valid_times = set()
    with path.open("rb") as file_obj:
        while True:
            gid = eccodes.codes_grib_new_from_file(file_obj)
            if gid is None:
                break
            try:
                valid_times.add(
                    (
                        int(eccodes.codes_get(gid, "validityDate")),
                        int(eccodes.codes_get(gid, "validityTime")),
                    )
                )
            finally:
                eccodes.codes_release(gid)
    return valid_times


def validate_forcing_file(path: Path, run_date: str, run_time: int, steps: list[int]) -> None:
    if not path.exists():
        raise RuntimeError(f"Missing forcing file: {path}")
    expected = expected_valid_times(run_date, run_time, steps)
    observed = grib_valid_times(path)
    missing = sorted(expected - observed)
    if missing:
        preview = ", ".join(f"{date}:{time:04d}" for date, time in missing[:8])
        suffix = "" if len(missing) <= 8 else f", ... ({len(missing)} missing)"
        raise RuntimeError(
            f"{path.name} is missing required forecast valid times: {preview}{suffix}"
        )
    print(
        f"✅ Validated {path.name}: {len(observed)} valid times, "
        f"{len(expected)} required times present."
    )


def validate_forcing_files(paths: dict[str, Path], run_date: str, run_time: int, steps: list[int]) -> None:
    validate_forcing_file(paths["pl_path"], run_date, run_time, steps)
    validate_forcing_file(paths["sfc_path"], run_date, run_time, steps)


def get_latest_run_time() -> int:
    """Determine the latest available ECMWF run (00, 12, etc.)."""
    now = datetime.datetime.now(datetime.timezone.utc)
    if now.hour >= 17:
        return 12
    return 0


def get_forecast_steps(lead_hours: int) -> list[int]:
    """Generate forecast steps up to lead_hours."""
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
        print(f"⚠️ GCS Upload failed: {e}")


def repack_grib_file(input_path: Path) -> None:
    """
    Ensure GRIB2 file uses simple packing instead of CCSDS.
    WPS/ungrib often fails to decode CCSDS-packed ECMWF open data.
    Uses 'grib_set' CLI if available, otherwise falls back to eccodes-python.
    """
    if not input_path.exists():
        return

    # Try using grib_set CLI first (much faster and more robust)
    import subprocess
    try:
        temp_output = input_path.with_suffix(".repacked.tmp")
        # -s packingType=grid_simple: change packing
        # -w packingType=grid_ccsds: only process CCSDS messages (optimization)
        # But for simplicity, we'll just set all to simple.
        cmd = ["grib_set", "-s", "packingType=grid_simple", str(input_path), str(temp_output)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0 and temp_output.exists():
            temp_output.replace(input_path)
            print(f"✅ Repacked {input_path.name} using grib_set CLI.")
            return
        else:
            print(f"⚠️ grib_set CLI failed or not found. Falling back to Python API. Error: {result.stderr}")
    except Exception as e:
        print(f"⚠️ grib_set CLI error: {e}. Falling back to Python API.")

    # Fallback to Python API
    if eccodes is None:
        print(f"⚠️ eccodes not available. Skipping repacking for {input_path.name}.")
        return

    temp_output = input_path.with_suffix(".repack_py.tmp")
    try:
        # First pass: check if we actually need repacking (any CCSDS messages?)
        needs_repack = False
        with open(input_path, "rb") as f:
            while True:
                gid = eccodes.codes_grib_new_from_file(f)
                if gid is None:
                    break
                try:
                    if eccodes.codes_get(gid, "packingType") == "grid_ccsds":
                        needs_repack = True
                        eccodes.codes_release(gid)
                        break
                except Exception:
                    pass
                eccodes.codes_release(gid)

        if not needs_repack:
            print(f"ℹ️ No CCSDS packing found in {input_path.name}. No repacking needed.")
            return

        print(f"🔄 Repacking {input_path.name} via Python API (CCSDS -> Simple)...")
        msg_count = 0
        repack_count = 0
        with open(input_path, "rb") as f_in, open(temp_output, "wb") as f_out:
            while True:
                gid = eccodes.codes_grib_new_from_file(f_in)
                if gid is None:
                    break
                msg_count += 1
                try:
                    if eccodes.codes_get(gid, "packingType") == "grid_ccsds":
                        eccodes.codes_set(gid, "packingType", "grid_simple")
                        repack_count += 1
                except Exception:
                    pass
                eccodes.codes_write(gid, f_out)
                eccodes.codes_release(gid)

        temp_output.replace(input_path)
        print(f"✅ Repacked {input_path.name} via Python ({msg_count} messages, {repack_count} modified).")

    finally:
        if temp_output.exists():
            temp_output.unlink()


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
    # Target filenames include the specific date and time to avoid collisions during fallbacks
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
    print(f"📡 Downloading pressure level variables {PL_VARS}...")
    try:
        client.retrieve(
            date=run_date,
            time=run_time,
            type="fc",
            levtype="pl",
            levelist=PRESSURE_LEVELS,
            param=PL_VARS,
            step=steps,
            target=str(pl_file),
        )
        print(f"✅ Pressure levels saved to: {pl_file} ({pl_file.stat().st_size / 1024 / 1024:.1f} MB)")
    except Exception as e:
        print(f"❌ Pressure levels download failed for {run_date} {run_time:02d}Z: {e}", file=sys.stderr)
        raise

    # 2. Retrieve Surface Parameters
    print(f"📡 Downloading surface variables {SFC_VARS}...")
    try:
        client.retrieve(
            date=run_date,
            time=run_time,
            type="fc",
            levtype="sfc",
            param=SFC_VARS,
            step=steps,
            target=str(sfc_file),
        )
    except Exception as e:
        print(f"⚠️ Surface download warning/fail: {e}. Retrying with split requests...")
        # Fallback: Get core SFC vars only
        CORE_SFC = ["10u", "10v", "2t", "2d", "sp", "msl", "skt", "lsm", "sd"]
        client.retrieve(
            date=run_date,
            time=run_time,
            type="fc",
            levtype="sfc",
            param=CORE_SFC,
            step=steps,
            target=str(sfc_file),
        )

    # 3. Retrieve Soil Parameters
    print(f"📡 Downloading soil variables {SOIL_VARS} for layers {SOIL_LEVELS}...")
    soil_tmp = output_dir / "soil_temp.grib2"
    try:
        client.retrieve(
            date=run_date,
            time=run_time,
            type="fc",
            levtype="sol",
            levelist=SOIL_LEVELS,
            param=SOIL_VARS,
            step=steps,
            target=str(soil_tmp),
        )
        # Append soil data to the surface file
        with open(sfc_file, "ab") as f_sfc, open(soil_tmp, "rb") as f_soil:
            f_sfc.write(f_soil.read())
        soil_tmp.unlink()
        print(f"✅ Soil layers appended to surface file.")
    except Exception as e:
        print(f"⚠️ Soil layers download failed: {e}. Checking alternative names...")
        try:
            client.retrieve(
                date=run_date,
                time=run_time,
                type="fc",
                levtype="sol",
                levelist=SOIL_LEVELS,
                param=["st", "swvl"],
                step=steps,
                target=str(soil_tmp),
            )
            with open(sfc_file, "ab") as f_sfc, open(soil_tmp, "rb") as f_soil:
                f_sfc.write(f_soil.read())
            soil_tmp.unlink()
            print(f"✅ Soil layers (st/swvl) appended to surface file.")
        except Exception as e2:
            print(f"❌ Could not retrieve soil data: {e2}")

    print(f"✅ Surface parameters saved to: {sfc_file} ({sfc_file.stat().st_size / 1024 / 1024:.1f} MB)")
    return {"pl_path": pl_file, "sfc_path": sfc_file}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download ECMWF Open Data forcing for WRF.")
    parser.add_argument("--run-date", default=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d"))
    parser.add_argument("--run-time", type=int, choices=[0, 6, 12, 18], default=0, help="Target run time. Defaults to 00Z for daily forecast start.")
    parser.add_argument("--lead-hours", type=int, default=120)
    parser.add_argument("--output-dir", type=Path, default=Path("simulation/inputs"))
    parser.add_argument("--gcs-bucket", default=os.environ.get("PREDSEA_GCS_BUCKET", "predsea-daily-outputs"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-if-exists", action="store_true", help="Skip download if files already exist locally")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # Define primary target run
    target_date = args.run_date
    target_time = args.run_time
    lead_hours = args.lead_hours

    attempts = [
        # Primary attempt: requested date and time
        (target_date, target_time, lead_hours),
    ]

    # Fallback logic: if today's 00Z is not ready, try yesterday's 12Z or 18Z
    if target_time == 0:
        dt = datetime.datetime.strptime(target_date, "%Y-%m-%d")
        yesterday = (dt - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        # Fallback to yesterday 12Z (most likely available) or 18Z
        # We add 12h or 6h to lead_hours to ensure we cover the same future window
        attempts.append((yesterday, 12, lead_hours + 12))
        attempts.append((yesterday, 18, lead_hours + 6))
    elif target_time == 12:
        # Fallback to today 00Z
        attempts.append((target_date, 0, lead_hours + 12))

    last_error = None
    for attempt_date, attempt_time, attempt_lead in attempts:
        steps = get_forecast_steps(attempt_lead)
        pl_target = args.output_dir / f"ecmwf_pl_{attempt_date}_{attempt_time:02d}Z.grib2"
        sfc_target = args.output_dir / f"ecmwf_sfc_{attempt_date}_{attempt_time:02d}Z.grib2"

        if args.skip_if_exists and pl_target.exists() and sfc_target.exists():
            paths = {"pl_path": pl_target, "sfc_path": sfc_target}
            try:
                validate_forcing_files(paths, attempt_date, attempt_time, steps)
                print(f"✅ Files already exist for {attempt_date} {attempt_time:02d}Z and passed validation. Skipping.")
                break
            except Exception as e:
                print(f"⚠️ Existing files for {attempt_date} {attempt_time:02d}Z failed validation: {e}")
                for stale_path in (pl_target, sfc_target):
                    try:
                        stale_path.unlink()
                        print(f"🧹 Removed stale forcing file: {stale_path}")
                    except FileNotFoundError:
                        pass

        print(f"🚀 Attempting fetch for {attempt_date} {attempt_time:02d}Z (Lead: {attempt_lead}h)...")
        try:
            paths = fetch_ecmwf_data(
                run_date=attempt_date,
                run_time=attempt_time,
                steps=steps,
                output_dir=args.output_dir,
                dry_run=args.dry_run,
            )
            break # Success!
        except Exception as e:
            print(f"⚠️ Fetch failed for {attempt_date} {attempt_time:02d}Z: {e}")
            last_error = e
            continue
    else:
        # All attempts failed
        print(f"❌ All fetch attempts failed. Last error: {last_error}", file=sys.stderr)
        sys.exit(1)

    if not args.dry_run:
        # 4. Repack files to ensure WPS/ungrib compatibility (CCSDS -> Simple)
        repack_grib_file(paths["pl_path"])
        repack_grib_file(paths["sfc_path"])
        validate_forcing_files(paths, attempt_date, attempt_time, steps)

    if args.gcs_bucket and not args.dry_run:
        # We always upload using the ATTEMPT date/time to the GCS folder of the RUN date
        # to ensure the simulation scripts find the files they expect.
        gcs_pl_path = f"forcing/ecmwf/{args.run_date}/{paths['pl_path'].name}"
        upload_to_gcs(args.gcs_bucket, paths["pl_path"], gcs_pl_path)

        gcs_sfc_path = f"forcing/ecmwf/{args.run_date}/{paths['sfc_path'].name}"
        upload_to_gcs(args.gcs_bucket, paths["sfc_path"], gcs_sfc_path)

        # Write a metadata file to GCS explaining which run was actually used
        metadata_file = args.output_dir / "forcing_metadata.json"
        import json
        with open(metadata_file, "w") as f:
            json.dump({
                "requested_date": args.run_date,
                "requested_time": args.run_time,
                "actual_date": attempt_date,
                "actual_time": attempt_time,
                "actual_lead_hours": attempt_lead,
                "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }, f, indent=2)

        upload_to_gcs(args.gcs_bucket, metadata_file, f"forcing/ecmwf/{args.run_date}/forcing_metadata.json")

        print(f"🎉 Forcing data ({attempt_date} {attempt_time:02d}Z) successfully archived in GCS.")


if __name__ == "__main__":
    main()
