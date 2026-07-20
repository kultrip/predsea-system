#!/usr/bin/env python3
"""
PredSea GCP Batch Job Submission Utility.
Validates declarative regional profiles, computes dynamic grid sizes,
maps scaling requirements, generates Batch JSON manifests, and submits jobs.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv


def get_gcp_project() -> str:
    # 1. Try environment variables
    project = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT")
    if project:
        return project

    # 2. Try GCP Metadata Server
    import urllib.request
    try:
        req = urllib.request.Request(
            "http://metadata.google.internal/computeMetadata/v1/project/project-id",
            headers={"Metadata-Flavor": "Google"}
        )
        with urllib.request.urlopen(req, timeout=2) as response:
            project_id = response.read().decode("utf-8").strip()
            if project_id:
                return project_id
    except Exception:
        pass

    # 3. Fall back to gcloud CLI config
    try:
        res = subprocess.run(
            ["gcloud", "config", "get-value", "project"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
        return res.stdout.strip()
    except Exception:
        print("❌ Error: Unable to determine active GCP project.", file=sys.stderr)
        sys.exit(1)


def validate_and_load_region(profile_path: Path) -> dict:
    if not profile_path.exists():
        raise FileNotFoundError(f"Region profile not found: {profile_path}")

    # Import validation routine dynamically
    sys.path.insert(0, str(profile_path.resolve().parents[2]))
    try:
        from scripts.validate_marine_region import validate_region
        report = validate_region(profile_path)
        if report["status"] != "succeeded":
            raise ValueError(f"Region validation failed: {report['errors']}")
    except ImportError:
        # Fallback basic validation
        pass

    with profile_path.open() as f:
        return json.load(f)


def calculate_resources(region_cfg: dict) -> tuple[str, int, int, int]:
    """
    Computes grid points and maps them to:
    (GCP Machine Type, CPU Millis, Memory MiB, MPI Ranks)
    """
    bbox = region_cfg["bbox"]
    lat_min = bbox["latitude_min"]
    lat_max = bbox["latitude_max"]
    lon_min = bbox["longitude_min"]
    lon_max = bbox["longitude_max"]
    lat_mid = (lat_min + lat_max) / 2.0

    # 111km is approximately 111,000 meters
    d_lat = (lat_max - lat_min) * 111000.0
    d_lon = (lon_max - lon_min) * 111000.0 * math.cos(math.radians(lat_mid))

    h_res = region_cfg.get("horizontal_resolution_m", 1000)
    grid_points = (d_lat / h_res) * (d_lon / h_res)

    print(f"📊 Grid calculations for {region_cfg['region_id']}:")
    print(f"   - Physical dimensions: {d_lon/1000.0:.1f} km (W-E) x {d_lat/1000.0:.1f} km (S-N)")
    print(f"   - Resolution: {h_res} m")
    print(f"   - Estimated Grid points: {grid_points:,.0f}")

    # Map to resource matrix
    if grid_points < 500000:
        # Small tile
        return "c2d-highcpu-4", 4000, 8192, 2
    elif grid_points <= 2000000:
        # Medium tile (e.g., Balearic)
        return "c2d-highcpu-8", 8000, 16384, 4
    else:
        # Large tile (e.g., Tyrrhenian)
        return "c2d-highcpu-32", 32000, 65536, 16


def build_batch_job_json(
    project_id: str,
    region_id: str,
    model_type: str,
    forecast_hours: int,
    gcs_bucket: str,
    machine_type: str,
    cpu_milli: int,
    memory_mib: int,
    mpi_ranks: int,
    image_uri: str,
    run_date: str,
    run_id: str,
    timeout_seconds: int,
    copernicus_username: str | None = None,
    copernicus_password: str | None = None,
) -> dict:
    runnable_cmd = (
        f"python3 /app/scripts/run_marine_simulation.py "
        f"--region {region_id} "
        f"--model {model_type} "
        f"--forecast-hours {forecast_hours} "
        f"--mpi-ranks {mpi_ranks} "
        f"--gcs-bucket {gcs_bucket}"
    )

    environment_variables = {
        "GOOGLE_CLOUD_PROJECT": project_id,
        "PREDSEA_RUN_DATE": run_date,
        "PREDSEA_RUN_ID": run_id,
    }
    if copernicus_username and copernicus_password:
        environment_variables.update(
            {
                "COPERNICUS_USERNAME": copernicus_username,
                "COPERNICUS_PASSWORD": copernicus_password,
            }
        )

    job_def = {
        "taskGroups": [
          {
            "taskSpec": {
              "runnables": [
                {
                  "environment": {
                    "variables": environment_variables
                  },
                  "container": {
                    "imageUri": image_uri,
                    "commands": ["-c", runnable_cmd],
                    "entrypoint": "/bin/bash"
                  }
                }
              ],
              "computeResource": {
                "cpuMilli": str(cpu_milli),
                "memoryMib": str(memory_mib)
              },
              "maxRetryCount": 1,
              "maxRunDuration": f"{timeout_seconds}s"
            },
            "taskCount": 1
          }
        ],
        "allocationPolicy": {
          "instances": [
            {
              "policy": {
                "machineType": machine_type,
                "provisioningModel": "SPOT"
              }
            }
          ]
        },
        "logsPolicy": {
          "destination": "CLOUD_LOGGING"
        }
    }
    return job_def


def default_timeout_seconds(forecast_hours: int) -> int:
    """Give long horizons explicit margin instead of inheriting a 4 h wall."""
    if forecast_hours <= 0 or forecast_hours > 120:
        raise ValueError("forecast_hours must be between 1 and 120")
    projected_hours = math.ceil((forecast_hours / 24.0) * 1.5)
    return max(4, projected_hours) * 3600


def main():
    load_dotenv(Path(__file__).resolve().parents[1] / "humanintheloop" / ".env")
    parser = argparse.ArgumentParser(description="Submit parallel marine simulation jobs to GCP Batch.")
    parser.add_argument("--region", required=True, help="Region ID (e.g., balearic_1km, alboran_1km)")
    parser.add_argument("--model", choices=["swan", "croco", "both"], default="both", help="Model to run")
    parser.add_argument("--forecast-hours", type=int, default=24, help="Forecast horizon hours")
    parser.add_argument(
        "--image-uri",
        required=True,
        help="Immutable Artifact Registry image URI containing @sha256:",
    )
    parser.add_argument("--gcs-bucket", help="GCS bucket for output products")
    parser.add_argument("--project", help="GCP Project ID")
    parser.add_argument("--location", default="europe-west1", help="GCP Batch location")
    parser.add_argument("--run-date", help="UTC model cycle date YYYY-MM-DD")
    parser.add_argument("--run-id", help="Immutable run identifier")
    parser.add_argument("--timeout-seconds", type=int, help="Batch task timeout")
    parser.add_argument("--dry-run", action="store_true", help="Print manifest without submitting")

    args = parser.parse_args()

    project = args.project or get_gcp_project()
    gcs_bucket = args.gcs_bucket or "predsea-daily-outputs-test"
    now = dt.datetime.now(dt.timezone.utc)
    run_date = args.run_date or now.strftime("%Y-%m-%d")
    run_id = args.run_id or now.strftime("%Y-%m-%dT%H%MZ")
    timeout_seconds = args.timeout_seconds or default_timeout_seconds(args.forecast_hours)
    if timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")
    if "@sha256:" not in args.image_uri and not args.dry_run:
        parser.error("--image-uri must be pinned by digest for a real submission")

    # Find the region JSON profile
    scripts_dir = Path(__file__).resolve().parent
    project_root = scripts_dir.parent
    profile_path = project_root / "simulation" / "marine" / "regions" / f"{args.region}.json"

    try:
        region_cfg = validate_and_load_region(profile_path)
    except Exception as e:
        print(f"❌ Error loading region profile: {e}", file=sys.stderr)
        sys.exit(1)

    machine_type, cpu_milli, memory_mib, mpi_ranks = calculate_resources(region_cfg)

    print(f"✨ Scheduled execution parameters:")
    print(f"   - Target Machine: {machine_type} (Spot VM)")
    print(f"   - CPUs / RAM: {cpu_milli/1000:.1f} vCPUs / {memory_mib/1024:.1f} GiB")
    print(f"   - MPI Parallel Decomposition: {mpi_ranks} ranks")

    # Generate job manifest
    job_manifest = build_batch_job_json(
        project_id=project,
        region_id=args.region,
        model_type=args.model,
        forecast_hours=args.forecast_hours,
        gcs_bucket=gcs_bucket,
        machine_type=machine_type,
        cpu_milli=cpu_milli,
        memory_mib=memory_mib,
        mpi_ranks=mpi_ranks,
        image_uri=args.image_uri,
        run_date=run_date,
        run_id=run_id,
        timeout_seconds=timeout_seconds,
        copernicus_username=os.getenv("COPERNICUS_USERNAME")
        or os.getenv("COPERNICUSMARINE_SERVICE_USERNAME"),
        copernicus_password=os.getenv("COPERNICUS_PASSWORD")
        or os.getenv("COPERNICUSMARINE_SERVICE_PASSWORD"),
    )

    job_json_str = json.dumps(job_manifest, indent=2)

    if args.dry_run:
        redacted_manifest = json.loads(job_json_str)
        variables = redacted_manifest["taskGroups"][0]["taskSpec"]["runnables"][0][
            "environment"
        ]["variables"]
        if "COPERNICUS_PASSWORD" in variables:
            variables["COPERNICUS_PASSWORD"] = "<redacted>"
        print("\n================= GCP BATCH JOB MANIFEST (DRY RUN) =================")
        print(json.dumps(redacted_manifest, indent=2))
        print("====================================================================")
        return

    # Submit job using gcloud batch jobs submit command
    job_id = f"predsea-sim-{args.region}-{args.model}-{os.urandom(4).hex()}".replace("_", "-")
    manifest_tmp_path = project_root / "tmp" / f"{job_id}.json"
    manifest_tmp_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_tmp_path.write_text(job_json_str)

    print(f"\n📂 Written manifest to temporary location: {manifest_tmp_path}")
    print(f"🚀 Submitting job '{job_id}' to GCP Batch in {args.location}...")

    cmd = [
        "gcloud", "batch", "jobs", "submit", job_id,
        f"--location={args.location}",
        f"--config={manifest_tmp_path}",
        f"--project={project}",
        "--quiet"
    ]

    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        print("✅ Job successfully submitted!")
        print(res.stdout)
        print(f"\n💡 Monitor your job in real-time:")
        print(f"  gcloud batch jobs describe {job_id} --location={args.location} --project={project}")
        print(f"  gcloud logging read \"resource.type=batch_job AND resource.labels.job_id={job_id}\" --project={project} --limit=50")
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to submit GCP Batch job:")
        print(e.stderr, file=sys.stderr)
        sys.exit(1)
    finally:
        # Clean up temporary manifest
        if manifest_tmp_path.exists():
            manifest_tmp_path.unlink()


if __name__ == "__main__":
    main()
