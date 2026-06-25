#!/usr/bin/env python3
"""
PredSea GCP Spot VM Orchestrator.
Spins up ephemeral Spot VMs to run the WRF/ROMS simulation container.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone


def run_command(cmd: list[str]) -> str:
    print(f"Executing: {' '.join(cmd)}")
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        print(f"❌ Command failed with exit code {result.returncode}", file=sys.stderr)
        print(f"Stdout:\n{result.stdout}", file=sys.stderr)
        print(f"Stderr:\n{result.stderr}", file=sys.stderr)
        raise RuntimeError(f"Command failed: {cmd[0]}")
    return result.stdout.strip()


def get_gcp_project() -> str:
    import os
    # 1. Try environment variables (standard in Google Cloud Run/Build)
    project = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT")
    if project:
        return project

    # 2. Try GCP Metadata Server (standard for resources running on GCP)
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

    # 3. Fall back to gcloud config (local development)
    try:
        return run_command(["gcloud", "config", "get-value", "project"])
    except Exception:
        print("❌ Error: Unable to determine active GCP project. Please run 'gcloud config set project [PROJECT]' first.")
        sys.exit(1)



def launch_spot_vm(args):
    project = args.project or get_gcp_project()
    zone = args.zone
    gcs_bucket = args.gcs_bucket
    image_tag = args.image_tag

    now = datetime.now(timezone.utc)
    run_date = args.run_date or now.strftime("%Y-%m-%d")
    run_id = args.run_id or now.strftime("%Y-%m-%dT%H%MZ")

    # Instance naming convention
    instance_name = args.instance_name or f"predsea-sim-{run_date}-{now.strftime('%H%M%S')}"

    print("=============================================")
    # Format absolute path to startup script
    startup_script_path = str(argparse.Namespace()._get_kwargs) # placeholder for path checks
    import os
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    startup_script = os.path.join(scripts_dir, "vm_startup.sh")

    print(f"🚀 Preparing to launch Spot VM: {instance_name}")
    print(f"📍 Zone: {zone}")
    print(f"💻 Machine Type: {args.machine_type}")
    print(f"🪧 Startup Script: {startup_script}")
    print(f"📦 Bucket: {gcs_bucket}")
    print(f"🏷️ Run Date: {run_date} | Run ID: {run_id}")
    print("=============================================")

    # Construct the gcloud compute instances create command
    cmd = [
        "gcloud", "compute", "instances", "create", instance_name,
        f"--project={project}",
        f"--zone={zone}",
        f"--machine-type={args.machine_type}",
        "--provisioning-model=SPOT",
        "--instance-termination-action=DELETE",
        "--scopes=https://www.googleapis.com/auth/cloud-platform",
        f"--metadata-from-file=startup-script={startup_script}",
        f"--metadata=gcs-bucket={gcs_bucket},run-date={run_date},run-id={run_id},image-tag={image_tag}",
        "--quiet"
    ]

    try:
        output = run_command(cmd)
        print("✅ Instance successfully requested.")
        print(output)
        print(f"\n💡 Note: The instance will run, upload outputs to gs://{gcs_bucket}/predictions/{run_date}/runs/{run_id}/, and automatically delete itself when finished.")
        print(f"To monitor logs, check Serial Port 1 in the GCP Console, or run:")
        print(f"  gcloud compute instances get-serial-port-output {instance_name} --zone={zone} --project={project}")
    except Exception as e:
        print(f"❌ Failed to launch Spot VM: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Launch ephemeral Spot VMs for high-resolution WRF/ROMS runs.")
    parser.add_argument("--project", help="GCP Project ID (defaults to active gcloud config)")
    parser.add_argument("--zone", default="europe-west1-b", help="GCP Zone")
    parser.add_argument("--machine-type", default="c2d-standard-16", help="GCP Machine Type (e.g. c2d-standard-16, c2d-standard-8)")
    parser.add_argument("--gcs-bucket", default="predsea-daily-outputs", help="Cloud Storage Bucket name")
    parser.add_argument("--run-date", help="ISO run date YYYY-MM-DD (defaults to today)")
    parser.add_argument("--run-id", help="Run identifier timestamp (defaults to current time)")
    parser.add_argument("--image-tag", default="latest", help="Model Docker image tag")
    parser.add_argument("--instance-name", help="GCE Instance name (defaults to auto-generated)")

    args = parser.parse_args()
    launch_spot_vm(args)


if __name__ == "__main__":
    main()
