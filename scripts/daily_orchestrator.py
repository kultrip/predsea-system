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
DEFAULT_FALLBACK_ZONES = ("europe-west1-b", "europe-west1-c", "europe-west1-d")
DEFAULT_FALLBACK_MACHINE_TYPES = ("c2d-standard-56", "c2d-standard-32")


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


def ordered_unique(primary: str, fallbacks: str, defaults: tuple[str, ...]) -> list[str]:
    """Return a stable, de-duplicated CLI fallback sequence."""
    values = [primary]
    values.extend(value.strip() for value in fallbacks.split(",") if value.strip())
    values.extend(defaults)
    return list(dict.fromkeys(values))


def launch_spot_vm_with_fallback(
    base_cmd: list[str],
    zones: list[str],
    machine_types: list[str],
    *,
    dry_run: bool = False,
) -> tuple[str, str]:
    """Try the preferred machine across zones before smaller machine types."""
    attempts = [(zone, machine_type) for machine_type in machine_types for zone in zones]
    for attempt_number, (zone, machine_type) in enumerate(attempts, start=1):
        print(
            f"🚀 Spot VM launch attempt {attempt_number}/{len(attempts)}: "
            f"zone={zone}, machine={machine_type}"
        )
        cmd = [*base_cmd, f"--zone={zone}", f"--machine-type={machine_type}"]
        if run_subprocess(cmd, dry_run=dry_run) == 0:
            print(f"✅ Spot VM selected: zone={zone}, machine={machine_type}")
            return zone, machine_type
        print(f"⚠️ Launch unavailable in {zone} with {machine_type}; trying next fallback.")

    attempted = ", ".join(f"{zone}/{machine}" for zone, machine in attempts)
    raise RuntimeError(f"Spot VM launch failed for all configured candidates: {attempted}")


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

def upload_file_to_gcs(bucket_name: str, local_path: Path, gcs_blob_path: str, dry_run: bool = False) -> None:
    """Upload a local file to GCS, using google-cloud-storage or gsutil fallback."""
    print(f"☁️ Uploading {local_path.name} to gs://{bucket_name}/{gcs_blob_path}...")
    if dry_run:
        print("⚡ [DRY RUN] Skipping upload.")
        return
    try:
        from google.cloud import storage
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(gcs_blob_path)
        blob.upload_from_filename(str(local_path))
        print("✅ Uploaded successfully via Python SDK.")
    except Exception as e:
        print(f"⚠️ SDK upload failed: {e}. Trying gsutil fallback...")
        try:
            cmd = ["gsutil", "cp", str(local_path), f"gs://{bucket_name}/{gcs_blob_path}"]
            subprocess.run(cmd, check=True)
            print("✅ Uploaded successfully via gsutil.")
        except Exception as e2:
            print(f"❌ Fallback also failed: {e2}")
            raise


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
    parser.add_argument("--machine-type", default="c2d-standard-56", help="GCP Machine Type for Spot VM")
    parser.add_argument(
        "--zones",
        default=",".join(DEFAULT_FALLBACK_ZONES),
        help="Comma-separated zone fallback order",
    )
    parser.add_argument(
        "--machine-types",
        default=",".join(DEFAULT_FALLBACK_MACHINE_TYPES),
        help="Comma-separated machine type fallback order",
    )
    parser.add_argument("--image-tag", default="latest", help="Model Docker image tag")
    parser.add_argument("--api-url", default=os.getenv("PREDSEA_API_URL", "http://localhost:8000"), help="Base URL of the FastAPI application")
    parser.add_argument("--project", help="GCP Project ID (defaults to active gcloud config)")
    parser.add_argument("--dry-run", action="store_true", help="Perform dry-run for boundaries and simulation checks")
    parser.add_argument("--poll-interval", type=int, default=30, help="GCE status polling interval in seconds")
    parser.add_argument("--timeout-hours", type=float, default=4.0, help="Maximum execution wait time for the GCE Spot VM")
    parser.add_argument("--boot-disk-size", default="200GB", help="Boot disk size for GCE VM (e.g. 100GB)")

    args = parser.parse_args()

    # Propagate GOOGLE_CLOUD_PROJECT to sub-processes if explicitly provided
    if args.project:
        os.environ["GOOGLE_CLOUD_PROJECT"] = args.project
    elif not os.environ.get("GOOGLE_CLOUD_PROJECT"):
        # Attempt to auto-detect if not set, to help sub-processes
        try:
            import google.auth
            _, project_id = google.auth.default()
            if project_id:
                os.environ["GOOGLE_CLOUD_PROJECT"] = project_id
        except Exception:
            pass

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
    notification_script = SCRIPTS_DIR / "notify_status.py"

    def notify(msg: str):
        """Helper to trigger the notification script."""
        n_cmd = [python_bin, str(notification_script), msg]
        if os.getenv("PREDSEA_NOTIFICATION_WEBHOOK"):
            run_subprocess(n_cmd)
        # Always log to stdout for GCP Log-based Alert
        print(f"📢 NOTIFICATION: {msg}")

    try:
        # Step 1: Download boundaries and upload raw forcing to GCS
        log_step("1. Fetching boundaries (ECMWF & CMEMS)")

        # Safety: Purge old forcing files to avoid mixing different runs or using corrupted old data
        if not args.dry_run:
            print(f"🧹 Cleaning old forcing files from gs://{args.gcs_bucket}/forcing/ecmwf/{run_date}/...")
            purge_cmd = ["gcloud", "storage", "rm", f"gs://{args.gcs_bucket}/forcing/ecmwf/{run_date}/*.grib2"]
            # We don't fail if this fails (might be empty)
            subprocess.run(purge_cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
            local_inputs_dir = PROJECT_ROOT / "simulation" / "inputs"
            for stale_path in local_inputs_dir.glob("ecmwf_*.grib2"):
                try:
                    stale_path.unlink()
                    print(f"🧹 Removed local stale forcing file: {stale_path}")
                except FileNotFoundError:
                    pass

        ecmwf_cmd = [
            python_bin, str(SCRIPTS_DIR / "fetch_ecmwf_forcing.py"),
            f"--run-date={run_date}",
            f"--gcs-bucket={args.gcs_bucket}",
            "--skip-if-exists",
        ]
        if args.dry_run:
            ecmwf_cmd.append("--dry-run")

        ecmwf_rc = run_subprocess(ecmwf_cmd)
        if ecmwf_rc != 0:
            raise RuntimeError("Boundary condition download failed (ECMWF)")

        cmems_cmd = [
            python_bin, str(SCRIPTS_DIR / "fetch_cmems_forcing.py"),
            f"--run-date={run_date}",
            f"--gcs-bucket={args.gcs_bucket}",
            "--skip-if-exists",
        ]
        if args.dry_run:
            cmems_cmd.append("--dry-run")

        cmems_rc = run_subprocess(cmems_cmd)
        if cmems_rc != 0:
            raise RuntimeError("Boundary condition download failed (CMEMS)")

        # Step 1.5: Pre-generate namelist.wps and upload to forcing directory
        log_step("1.5. Pre-generating namelist.wps for simulation run")
        run_date_dt = datetime.datetime.strptime(run_date, "%Y-%m-%d")
        end_date_dt = run_date_dt + datetime.timedelta(days=1)
        end_date_str = end_date_dt.strftime("%Y-%m-%d")

        # Create tmp directory in the workspace if it doesn't exist
        tmp_dir = PROJECT_ROOT / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        namelist_local_path = tmp_dir / "namelist.wps"

        setup_domain_cmd = [
            python_bin, str(PROJECT_ROOT / "simulation" / "setup_domain.py"),
            f"--output={namelist_local_path}",
            f"--start-date={run_date}_00:00:00",
            f"--end-date={end_date_str}_00:00:00",
        ]

        setup_rc = run_subprocess(setup_domain_cmd, dry_run=args.dry_run)
        if setup_rc != 0:
            raise RuntimeError("Generating namelist.wps locally failed")

        gcs_namelist_path = f"forcing/ecmwf/{run_date}/namelist.wps"
        upload_file_to_gcs(args.gcs_bucket, namelist_local_path, gcs_namelist_path, dry_run=args.dry_run)

        # Upload modified run_pipeline.sh to avoid expensive docker image rebuilds
        run_pipeline_local_path = PROJECT_ROOT / "simulation" / "run_pipeline.sh"
        gcs_run_pipeline_path = f"forcing/ecmwf/{run_date}/run_pipeline.sh"
        upload_file_to_gcs(args.gcs_bucket, run_pipeline_local_path, gcs_run_pipeline_path, dry_run=args.dry_run)

        # Upload updated setup_domain.py to allow dynamic patching inside the container
        setup_domain_local_path = PROJECT_ROOT / "simulation" / "setup_domain.py"
        gcs_setup_domain_path = f"forcing/ecmwf/{run_date}/setup_domain.py"
        upload_file_to_gcs(args.gcs_bucket, setup_domain_local_path, gcs_setup_domain_path, dry_run=args.dry_run)

        # Upload GRIB2 compatible Vtable to avoid missing Vtable or decoding failures
        vtable_local_path = PROJECT_ROOT / "simulation" / "Vtable.ECMWF_grib2"
        vtable_gcs_path = f"forcing/ecmwf/{run_date}/Vtable.ECMWF_grib2"
        upload_file_to_gcs(args.gcs_bucket, vtable_local_path, vtable_gcs_path, dry_run=args.dry_run)

        # Step 2: Trigger GCE Spot VM WRF/ROMS simulation
        log_step("2. Launching GCE Spot VM")
        orchestrator_cmd = [
            python_bin, str(SCRIPTS_DIR / "gcp_orchestrator.py"),
            f"--instance-name={instance_name}",
            f"--run-date={run_date}",
            f"--run-id={run_id}",
            f"--gcs-bucket={args.gcs_bucket}",
            f"--image-tag={args.image_tag}",
            f"--boot-disk-size={args.boot_disk_size}",
        ]
        if args.project:
            orchestrator_cmd.append(f"--project={args.project}")

        # Launch instance request
        zones = ordered_unique(args.zone, args.zones, DEFAULT_FALLBACK_ZONES)
        machine_types = ordered_unique(
            args.machine_type,
            args.machine_types,
            DEFAULT_FALLBACK_MACHINE_TYPES,
        )
        selected_zone, selected_machine_type = launch_spot_vm_with_fallback(
            orchestrator_cmd,
            zones,
            machine_types,
            dry_run=args.dry_run,
        )

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
                    # delete_gce_instance(instance_name, args.zone, args.project)
                    raise RuntimeError(f"Simulation timed out after {args.timeout_hours} hours")

                exists = check_gce_instance_exists(instance_name, selected_zone, args.project)
                if not exists:
                    print(f"ℹ️ Spot VM '{instance_name}' no longer exists. Verifying workload completion in GCS...")
                    success_gcs_path = f"gs://{args.gcs_bucket}/predictions/{run_date}/runs/{run_id}/SUCCESS"
                    if check_gcs_object_exists(success_gcs_path):
                        print(f"🎉 SUCCESS: Workload completion marker found at {success_gcs_path}.")
                        completed_normally = True
                    else:
                        print(f"❌ ERROR: Spot VM '{instance_name}' terminated, but NO completion marker was found at {success_gcs_path}.")
                        completed_normally = False
                    break

                print(f"⏳ Still running... Elapsed time: {elapsed/60:.1f} minutes. Checking again in {args.poll_interval}s...")
                time.sleep(args.poll_interval)

            if not completed_normally:
                raise RuntimeError("GCE Spot VM terminated unexpectedly or encountered error during run")

        # Step 3b: Ingest high-resolution simulations to BigQuery
        log_step("3b. Ingesting high-resolution simulations to BigQuery")

        for ingest_script in ["wrf_forecast_ingestor.py", "croco_forecast_ingestor.py", "nemo_forecast_ingestor.py", "swan_forecast_ingestor.py"]:
            cmd = [
                python_bin, str(SCRIPTS_DIR / ingest_script),
                f"--run-date={run_date}",
                f"--run-id={run_id}",
                f"--gcs-bucket={args.gcs_bucket}",
            ]
            if args.project:
                cmd.append(f"--project={args.project}")
            if args.dry_run:
                cmd.append("--dry-run")

            rc = run_subprocess(cmd)
            if rc != 0:
                print(f"⚠️ Warning: {ingest_script} failed, but continuing pipeline...")

        # Step 4: Observation Ingestion & BigQuery Validation Export
        log_step("4. Observation Ingestion & BigQuery Validation Export")
        briefing_cmd = [
            python_bin, str(SCRIPTS_DIR / "generate_daily_briefing.py"),
            f"--date={run_date}",
            f"--run-id={run_id}",
            "--skip-figures",
        ]

        briefing_rc = run_subprocess(briefing_cmd, dry_run=args.dry_run)
        if briefing_rc != 0:
            raise RuntimeError("Daily briefing / Ingestion pipeline failed")

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
            print("⚠️ Warning: Climatology Anomaly Check failed.")

        # Step 6: Real model-vs-observation validation
        log_step("6. Real Model Comparison")
        comparison_cmd = [
            python_bin, str(HUMANINTHELOOP_DIR / "scripts" / "model_comparison.py"),
            f"--date={run_date}",
        ]
        if args.project:
            comparison_cmd.append(f"--project={args.project}")
        run_subprocess(comparison_cmd, dry_run=args.dry_run)

        print("\n🌟 =================================================================")
        print("🏆 PredSea end-to-end daily forecasting orchestrator run successfully!")
        print(f"Run date {run_date} completed successfully.")
        print("=================================================================\n")

        notify(f"✅ PredSea Pipeline Success: Run {run_date} ({run_id}) finished normally.")

    except Exception as e:
        error_msg = f"🚨 PREDSEA_PIPELINE_CRITICAL_FAILURE: {str(e)}"
        print(f"\n{'!'*60}\n{error_msg}\n{'!'*60}\n")
        notify(f"❌ PredSea Pipeline Failure: Run {run_date} failed. Error: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
