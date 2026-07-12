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
    """Convert GRIB2 packing from grid_ccsds to grid_simple using eccodes."""
    if eccodes is None:
        print(f"ℹ️ Skipping repacking for {input_path.name} (eccodes not installed).")
        return

    temp_output = input_path.with_suffix(".repacked")
    
    found_ccsds = False
    count = 0
    try:
        # First pass: check if any message is CCSDS
        with open(input_path, "rb") as f_in:
            while True:
                gid = eccodes.codes_grib_new_from_file(f_in)
                if gid is None:
                    break
                
                count += 1
                try:
                    packing_type = eccodes.codes_get(gid, "packingType")
                    if packing_type == "grid_ccsds":
                        found_ccsds = True
                        break
                except Exception:
                    pass
                finally:
                    eccodes.codes_release(gid)

        if not found_ccsds:
            print(f"ℹ️ No CCSDS packing found in {input_path.name} ({count} messages). No repacking needed.")
            return

        # Second pass: actual repacking
        print(f"🔄 Repacking {input_path.name} (found CCSDS, converting to simple packing)...")
        with open(input_path, "rb") as f_in, open(temp_output, "wb") as f_out:
            while True:
                gid = eccodes.codes_grib_new_from_file(f_in)
                if gid is None:
                    break
                try:
                    packing_type = eccodes.codes_get(gid, "packingType")
                    if packing_type == "grid_ccsds":
                        eccodes.codes_set(gid, "packingType", "grid_simple")
                except Exception:
                    pass
                eccodes.codes_write(gid, f_out)
                eccodes.codes_release(gid)
        
        temp_output.replace(input_path)
        print(f"✅ Repacked {input_path.name}.")

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
            type="fc",
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

    # 2. Retrieve Surface Parameters (including basic soil if available in sfc)
    print(f"📡 Downloading surface variables {SFC_VARS}...")
    try:
        # We try to get everything we can in one go.
        # Note: If st/swvl fail here, we catch and retry with sol levtype.
        client.retrieve(
            type="fc",
            levtype="sfc",
            param=SFC_VARS,
            time=run_time,
            step=steps,
            target=str(sfc_file),
        )
    except Exception as e:
        print(f"⚠️ Surface download warning/fail: {e}. Retrying with split requests...")
        # Fallback: Get core SFC vars only
        CORE_SFC = ["10u", "10v", "2t", "2d", "sp", "msl", "skt", "lsm", "sd"]
        client.retrieve(
            type="fc",
            levtype="sfc",
            param=CORE_SFC,
            time=run_time,
            step=steps,
            target=str(sfc_file),
        )
    
    # 3. Retrieve Soil Parameters (Explicitly as levtype="sol" to ensure WRF has soil data)
    print(f"📡 Downloading soil variables {SOIL_VARS} for layers {SOIL_LEVELS}...")
    soil_tmp = output_dir / "soil_temp.grib2"
    try:
        client.retrieve(
            type="fc",
            levtype="sol",
            levelist=SOIL_LEVELS,
            param=SOIL_VARS,
            time=run_time,
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
        # Some catalogs use 'st' and 'swvl' even in levtype sol
        try:
            client.retrieve(
                type="fc",
                levtype="sol",
                levelist=SOIL_LEVELS,
                param=["st", "swvl"],
                time=run_time,
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
    parser.add_argument("--run-time", type=int, choices=[0, 6, 12, 18], default=get_latest_run_time())
    parser.add_argument("--lead-hours", type=int, default=120)
    parser.add_argument("--output-dir", type=Path, default=Path("simulation/inputs"))
    parser.add_argument("--gcs-bucket", default=os.environ.get("PREDSEA_GCS_BUCKET", "predsea-daily-outputs"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-if-exists", action="store_true", help="Skip download if files already exist locally")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    steps = get_forecast_steps(args.lead_hours)

    try:
        # Check if files already exist if --skip-if-exists is set
        pl_target = args.output_dir / f"ecmwf_pl_{args.run_date}_{args.run_time:02d}Z.grib2"
        sfc_target = args.output_dir / f"ecmwf_sfc_{args.run_date}_{args.run_time:02d}Z.grib2"
        
        if args.skip_if_exists and pl_target.exists() and sfc_target.exists():
            print(f"✅ Files already exist locally. Skipping download due to --skip-if-exists.")
            paths = {"pl_path": pl_target, "sfc_path": sfc_target}
        else:
            paths = fetch_ecmwf_data(
                run_date=args.run_date,
                run_time=args.run_time,
                steps=steps,
                output_dir=args.output_dir,
                dry_run=args.dry_run,
            )

        if not args.dry_run:
            # 4. Repack files to ensure WPS/ungrib compatibility (CCSDS -> Simple)
            repack_grib_file(paths["pl_path"])
            repack_grib_file(paths["sfc_path"])

        if args.gcs_bucket and not args.dry_run:
            gcs_pl_path = f"forcing/ecmwf/{args.run_date}/{paths['pl_path'].name}"
            upload_to_gcs(args.gcs_bucket, paths["pl_path"], gcs_pl_path)

            gcs_sfc_path = f"forcing/ecmwf/{args.run_date}/{paths['sfc_path'].name}"
            upload_to_gcs(args.gcs_bucket, paths["sfc_path"], gcs_sfc_path)

            print(f"🎉 All files successfully archived in GCS.")

    except Exception as e:
        print(f"❌ Execution failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
