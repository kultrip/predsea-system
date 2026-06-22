#!/usr/bin/env bash
# PredSea Spot VM Startup Script
# Configured to run on standard Debian/Ubuntu GCE instances.
set -euo pipefail

echo "============================================="
echo "🚀 PredSea VM Startup Script Initialized"
echo "============================================="

# 1. Variables (injected via metadata at creation)
PROJECT_ID=$(curl -s -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/project/project-id)
ZONE=$(curl -s -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/zone | awk -F/ '{print $4}')
NAME=$(curl -s -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/name)

GCS_BUCKET=$(curl -s -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/attributes/gcs-bucket || echo "predsea-daily-outputs")
RUN_DATE=$(curl -s -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/attributes/run-date || date -u +"%Y-%m-%d")
RUN_ID=$(curl -s -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/attributes/run-id || date -u +"%Y-%m-%dT%H%MZ")
IMAGE_TAG=$(curl -s -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/attributes/image-tag || echo "latest")

DOCKER_IMAGE="europe-west1-docker.pkg.dev/${PROJECT_ID}/predsea-simulations/wrf:${IMAGE_TAG}"

echo "Project ID: ${PROJECT_ID}"
echo "Instance: ${NAME} in zone ${ZONE}"
echo "Target Date/Run: ${RUN_DATE} / ${RUN_ID}"
echo "Docker Image: ${DOCKER_IMAGE}"
echo "============================================="

# 2. Install Docker if not already installed
if ! command -v docker &> /dev/null; then
  echo "Installing Docker..."
  apt-get update
  apt-get install -y apt-transport-https ca-certificates curl gnupg lsb-release
  mkdir -p /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian bullseye stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io
fi

# 3. Configure Docker credential helper for Artifact Registry
echo "Configuring docker credentials..."
gcloud auth configure-docker europe-west1-docker.pkg.dev --quiet

# 4. Pull WRF/ROMS model image
echo "Pulling model container image..."
docker pull "${DOCKER_IMAGE}"

# 5. Create workspaces and download forcing data (e.g. ECMWF and CMEMS inputs)
# In production, these scripts will pull the required boundary conditions from GCS or APIs
mkdir -p /workspace/inputs
mkdir -p /workspace/outputs

# Download ECMWF boundary forcing files from a coordinated GCS path
echo "Downloading boundary conditions from GCS..."
gsutil -m rsync -r "gs://${GCS_BUCKET}/forcing/ecmwf/${RUN_DATE}/" /workspace/inputs/

# 6. Run the simulation pipeline container
# Mounts inputs/outputs and runs the WRF/ROMS simulation
echo "Executing model simulation..."
docker run --rm \
  -v /workspace/inputs:/data \
  -v /workspace/outputs:/workspace/run \
  "${DOCKER_IMAGE}" \
  /opt/predsea/run_pipeline.sh

# 7. Upload outputs back to GCS
echo "Uploading outputs to GCS..."
gsutil -m rsync -r /workspace/outputs/ "gs://${GCS_BUCKET}/predictions/${RUN_DATE}/runs/${RUN_ID}/"

echo "============================================="
echo "🎉 Simulation pipeline complete!"
echo "============================================="

# 8. Self-terminate (delete instance) to save costs
echo "Triggering self-deletion..."
gcloud compute instances delete "${NAME}" --zone="${ZONE}" --quiet
