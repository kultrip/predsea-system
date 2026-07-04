#!/usr/bin/env python3
"""
PredSea Master Daily Orchestrator.
Unifies boundaries download, GCE Spot VM WRF/ROMS simulation monitoring,
observation ingestion, BigQuery validation logging, and climatology anomaly warnings.
"""
from __future__ import annotations

import argparse
import datetime
import os
import subprocess
import sys
import time
from pathlib import Path

# Resolve project paths
SCRIPTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPTS_DIR.parent


def log_step(name: str):
    print("\n" + "=" * 60)
    print(f"👉 [STEP] {name}")
    print("=" * 60)


def run_subprocess(cmd: list[str], dry_run: bool = False) -> int:
    """Run a subprocess with sys.executable and print its output in real-time."""
    print(f"Running: {' '.join(cmd)}")
    if dry_run:
        print("⚡ [DRY RUN] Skipping command execution.")
        return 0

    # Execute in the project root working directory
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        cwd=str(PROJECT_ROOT)
    )

    # Stream output in real-time
    if process.stdout:
        for line in process.stdout:
            print(line, end="")

    return_code = process.wait()
    if return_code != 0:
        print(f"❌ Command failed with return code {return_code}")
    return return_code


def check_gce_instance_exists(instance_name: str, zone: str, project_id: str | None = None) -> bool:
    """Check if the GCE instance exists using gcloud CLI."""
    cmd = [
        "gcloud", "compute", "instances", "describe", instance_name,
        f"--zone={zone}",
        "--format=value(status)"
    ]
    if project_id:
        cmd.append(f"--project={project_id}")

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
        status = result.stdout.strip()
        print(f"ℹ️ Instance {instance_name} status: {status}")
        return True
    except subprocess.CalledProcessError as e:
        # If gcloud returns 404 (not found), it's deleted
        if "not found" in e.stderr.lower() or "error" in e.stderr.lower():
            return False
        # Treat other CLI errors as still existing or transient API errors
        print(f"⚠️ Warning: error querying GCE instance: {e.stderr.strip()}")
        return True


def check_gcs_object_exists(gcs_path: str) -> bool:
    """Check if a GCS object exists using gcloud storage objects describe."""
    cmd = ["gcloud", "storage", "objects", "describe", gcs_path, "--format=value(name)"]
    try:
        subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
        return True
    except subprocess.CalledProcessError:
        return False


def delete_gce_instance(instance_name: str, zone: str, project_id: str | None = None):
    """Explicitly delete a GCE instance to avoid runaway costs."""
    print(f"⚠️ Safety Cleanup: Forcing deletion of GCE instance {instance_name} in {zone}...")
    cmd = [
        "gcloud", "compute", "instances", "delete", instance_name,
        f"--zone={zone}",
        "--quiet"
    ]
    if project_id:
        cmd.append(f"--project={project_id}")

    try:
        subprocess.run(cmd, check=True)
        print(f"✅ Instance {instance_name} deleted successfully.")
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to delete GCE instance {instance_name}: {e.stderr.strip()}")


def main():
    # Resolve project paths and import configuration defaults
    HUMANINTHELOOP_DIR = PROJECT_ROOT / "humanintheloop"
    if str(HUMANINTHELOOP_DIR) not in sys.path:
        sys.path.insert(0, str(HUMANINTHELOOP_DIR))

    try:
        from api.config import PREDSEA_GCS_BUCKET
    except ImportError:
        env = os.environ.get("PREDSEA_ENV", "test").strip().lower()
        if env not in ("test", "prod"):
            env = "test"
        PREDSEA_GCS_BUCKET = os.environ.get("PREDSEA_GCS_BUCKET") or f"predsea-daily-outputs-{env}"

    parser = argparse.ArgumentParser(description="PredSea daily master end-to-end forecasting orchestrator.")
    parser.add_argument("--run-date", help="ISO Run Date YYYY-MM-DD. Defaults to Europe/Madrid today.")
    parser.add_argument("--run-id", help="Run identifier timestamp (defaults to current time)")
    parser.add_argument("--gcs-bucket", default=PREDSEA_GCS_BUCKET, help="Cloud Storage Bucket name")
    parser.add_argument("--zone", default="europe-west1-b", help="GCP Zone")
    parser.add_argument("--machine-type", default="c2d-standard-32", help="GCP Machine Type for Spot VM")
    parser.add_argument("--image-tag", default="latest", help="Model Docker image tag")
    parser.add_argument("--api-url", default=os.getenv("PREDSEA_API_URL", "http://localhost:8000"), help="Base URL of the FastAPI application")
    parser.add_argument("--project", help="GCP Project ID (defaults to active gcloud config)")
    parser.add_argument("--dry-run", action="store_true", help="Perform dry-run for boundaries and simulation checks")
    parser.add_argument("--poll-interval", type=int, default=30, help="GCE status polling interval in seconds")
    parser.add_argument("--timeout-hours", type=float, default=4.0, help="Maximum execution wait time for the GCE Spot VM")
    parser.add_argument("--boot-disk-size", default="100GB", help="Boot disk size for GCE VM (e.g. 100GB)")

    args = parser.parse_args()

    # Dates calculation matching daily briefing timezone defaults
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    run_date = args.run_date or now_utc.strftime("%Y-%m-%d")
    run_id = args.run_id or now_utc.strftime("%Y-%m-%dT%H%MZ")

    # Generate a safe deterministic GCE instance name
    instance_name = f"predsea-sim-{run_date.replace('-', '')}-{now_utc.strftime('%H%M%S')}"

    print("=================================================================")
    print("🌅 PredSea Daily End-to-End Orchestrator Initialized")
    print(f"📅 Run Date: {run_date}")
    print(f"🆔 Run ID: {run_id}")
    print(f"💻 Spot VM Instance Name: {instance_name}")
    print(f"📦 GCS Bucket: {args.gcs_bucket}")
    print(f"📌 Zone: {args.zone} | Machine: {args.machine_type}")
    print(f"🐳 Image Tag: {args.image_tag}")
    print(f"⚠️ Dry-run: {args.dry_run}")
    print("=================================================================")

    # Define paths to scripts
    python_bin = sys.executable

    # Step 1: Download boundaries and upload raw forcing to GCS
    log_step("1. Fetching boundaries (ECMWF & CMEMS)")
    
    ecmwf_cmd = [
        python_bin, str(SCRIPTS_DIR / "fetch_ecmwf_forcing.py"),
        f"--run-date={run_date}",
        f"--gcs-bucket={args.gcs_bucket}",
    ]
    if args.dry_run:
        ecmwf_cmd.append("--dry-run")
    
    ecmwf_rc = run_subprocess(ecmwf_cmd)
    if ecmwf_rc != 0:
        print("❌ Error: Boundary condition download failed (ECMWF). Exiting.")
        sys.exit(1)

    cmems_cmd = [
        python_bin, str(SCRIPTS_DIR / "fetch_cmems_forcing.py"),
        f"--run-date={run_date}",
        f"--gcs-bucket={args.gcs_bucket}",
    ]
    if args.dry_run:
        cmems_cmd.append("--dry-run")

    cmems_rc = run_subprocess(cmems_cmd)
    if cmems_rc != 0:
        print("❌ Error: Boundary condition download failed (CMEMS). Exiting.")
        sys.exit(1)

    # Step 2: Trigger GCE Spot VM WRF/ROMS simulation
    log_step("2. Launching GCE Spot VM")
    orchestrator_cmd = [
        python_bin, str(SCRIPTS_DIR / "gcp_orchestrator.py"),
        f"--instance-name={instance_name}",
        f"--run-date={run_date}",
        f"--run-id={run_id}",
        f"--gcs-bucket={args.gcs_bucket}",
        f"--zone={args.zone}",
        f"--machine-type={args.machine_type}",
        f"--image-tag={args.image_tag}",
        f"--boot-disk-size={args.boot_disk_size}",
    ]
    if args.project:
        orchestrator_cmd.append(f"--project={args.project}")

    # Launch instance request
    launch_rc = run_subprocess(orchestrator_cmd, dry_run=args.dry_run)
    if launch_rc != 0:
        print("❌ Error: Spot VM launch script returned exit code failure. Exiting.")
        sys.exit(1)

    # Step 3: Monitor Spot VM Execution Tracking
    log_step("3. Polling Spot VM status until self-termination")
    if args.dry_run:
        print("⚡ [DRY RUN] Simulating Spot VM completion successfully.")
    else:
        # Give GCE a small moment to register the VM creation
        time.sleep(5)
        
        start_time = time.time()
        timeout_seconds = args.timeout_hours * 3600
        completed_normally = False

        while True:
            elapsed = time.time() - start_time
            if elapsed > timeout_seconds:
                print(f"🚨 Timeout: Spot VM execution exceeded limit of {args.timeout_hours} hours.")
                delete_gce_instance(instance_name, args.zone, args.project)
                sys.exit(1)

            exists = check_gce_instance_exists(instance_name, args.zone, args.project)
            if not exists:
                print(f"ℹ️ Spot VM '{instance_name}' no longer exists. Verifying workload completion in GCS...")
                success_gcs_path = f"gs://{args.gcs_bucket}/predictions/{run_date}/runs/{run_id}/SUCCESS"
                if check_gcs_object_exists(success_gcs_path):
                    print(f"🎉 SUCCESS: Workload completion marker found at {success_gcs_path}.")
                    completed_normally = True
                else:
                    print(f"❌ ERROR: Spot VM '{instance_name}' terminated, but NO completion marker was found at {success_gcs_path}.")
                    print("This indicates the simulation workload failed, ran out of disk, or the VM was preempted.")
                    completed_normally = False
                break

            print(f"⏳ Still running... Elapsed time: {elapsed/60:.1f} minutes. Checking again in {args.poll_interval}s...")
            time.sleep(args.poll_interval)

        if not completed_normally:
            print("❌ GCE Spot VM terminated unexpectedly or encountered error during run. Exiting.")
            sys.exit(1)

    # Step 3b: Ingest high-resolution simulations to BigQuery (WRF, ROMS, NEMO, SWAN)
    log_step("3b. Ingesting high-resolution simulations to BigQuery (WRF, ROMS, NEMO, SWAN)")
    
    wrf_cmd = [
        python_bin, str(SCRIPTS_DIR / "wrf_forecast_ingestor.py"),
        f"--run-date={run_date}",
        f"--run-id={run_id}",
        f"--gcs-bucket={args.gcs_bucket}",
    ]
    if args.project:
        wrf_cmd.append(f"--project={args.project}")
    if args.dry_run:
        wrf_cmd.append("--dry-run")
        
    wrf_rc = run_subprocess(wrf_cmd)
    if wrf_rc != 0:
        print("❌ Error: WRF forecast ingestion failed. Exiting.")
        sys.exit(1)
        
    croco_cmd = [
        python_bin, str(SCRIPTS_DIR / "croco_forecast_ingestor.py"),
        f"--run-date={run_date}",
        f"--run-id={run_id}",
        f"--gcs-bucket={args.gcs_bucket}",
    ]
    if args.project:
        croco_cmd.append(f"--project={args.project}")
    if args.dry_run:
        croco_cmd.append("--dry-run")
        
    croco_rc = run_subprocess(croco_cmd)
    if croco_rc != 0:
        print("❌ Error: CROCO forecast ingestion failed. Exiting.")
        sys.exit(1)

    nemo_cmd = [
        python_bin, str(SCRIPTS_DIR / "nemo_forecast_ingestor.py"),
        f"--run-date={run_date}",
        f"--run-id={run_id}",
        f"--gcs-bucket={args.gcs_bucket}",
    ]
    if args.project:
        nemo_cmd.append(f"--project={args.project}")
    if args.dry_run:
        nemo_cmd.append("--dry-run")
        
    nemo_rc = run_subprocess(nemo_cmd)
    if nemo_rc != 0:
        print("❌ Error: NEMO forecast ingestion failed. Exiting.")
        sys.exit(1)

    swan_cmd = [
        python_bin, str(SCRIPTS_DIR / "swan_forecast_ingestor.py"),
        f"--run-date={run_date}",
        f"--run-id={run_id}",
        f"--gcs-bucket={args.gcs_bucket}",
    ]
    if args.project:
        swan_cmd.append(f"--project={args.project}")
    if args.dry_run:
        swan_cmd.append("--dry-run")
        
    swan_rc = run_subprocess(swan_cmd)
    if swan_rc != 0:
        print("❌ Error: SWAN forecast ingestion failed. Exiting.")
        sys.exit(1)

    # Step 4: After VM termination, trigger observation ingestion & BigQuery export
    log_step("4. Observation Ingestion & BigQuery Validation Export")
    
    # We use generate_daily_briefing.py to fetch observations, compare them to the newly generated runs on GCS, 
    # write the validation archives locally/GCS, and push to BigQuery!
    briefing_cmd = [
        python_bin, str(SCRIPTS_DIR / "generate_daily_briefing.py"),
        f"--date={run_date}",
        f"--run-id={run_id}",
        "--skip-figures",  # Lighten execution in orchestrator runs
    ]
    
    briefing_rc = run_subprocess(briefing_cmd, dry_run=args.dry_run)
    if briefing_rc != 0:
        print("❌ Error: Daily briefing / Ingestion pipeline failed. Exiting.")
        sys.exit(1)

    # Step 5: Execute BigQuery Climatology Anomaly Checker
    log_step("5. BigQuery Climatology Anomaly Check & Warnings Dispatch")
    
    anomaly_cmd = [
        python_bin, str(SCRIPTS_DIR / "climatology_anomaly_check.py"),
        f"--api-url={args.api_url}",
    ]
    if args.project:
        anomaly_cmd.append(f"--project={args.project}")
    if args.dry_run:
        anomaly_cmd.append("--dry-run")

    anomaly_rc = run_subprocess(anomaly_cmd)
    if anomaly_rc != 0:
        print("❌ Error: Climatology Anomaly Check script returned an execution failure.")
        sys.exit(1)

    # Step 6: Real model-vs-observation validation (non-fatal -- validation reporting
    # must never block the core forecast pipeline from completing, same philosophy as
    # the rest of this ETL: e.g. BigQuery export failures don't break ingestion).
    log_step("6. Real Model Comparison (WRF/CROCO/NEMO/SWAN vs. real buoy observations)")

    comparison_cmd = [
        python_bin, str(HUMANINTHELOOP_DIR / "scripts" / "model_comparison.py"),
        f"--date={run_date}",
    ]
    if args.project:
        comparison_cmd.append(f"--project={args.project}")

    comparison_rc = run_subprocess(comparison_cmd, dry_run=args.dry_run)
    if comparison_rc != 0:
        print(
            "⚠️ Warning: model_comparison.py returned a non-zero exit code. This does NOT "
            "fail the daily run -- validation reporting is best-effort, same as the rest "
            "of this pipeline. Check logs for this step separately if the report looks stale."
        )

    print("\n🌟 =================================================================")
    print("🏆 PredSea end-to-end daily forecasting orchestrator run successfully!")
    print(f"Run date {run_date} completed successfully.")
    print("=================================================================\n")


if __name__ == "__main__":
    main()
