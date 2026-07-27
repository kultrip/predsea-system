#!/usr/bin/env bash
set -euo pipefail

# Set common variables for verified v20 build
IMAGE_URI="europe-west1-docker.pkg.dev/predsea-api/predsea-simulations/croco-batch:v2-forcing-patch"
BALEARIC_GRID_URI="gs://predsea-daily-outputs-test/static/native-marine/balearic_1km/croco-grid/20260722-v3/croco_grid.nc"
WRF_URI="gs://predsea-daily-outputs-test/predictions/2026-07-16/runs/2026-07-16T0733Z"
RUN_ID="2026-07-26T2120Z-croco-westernmed-24h-v35"
PYTHON_BIN="./.venv311/bin/python"

echo "========================================================================="
echo "🚀 Launching All 5 Western Mediterranean CROCO Shards (v20)"
echo "========================================================================="

# 1. Balearic 1km (Uses cached pre-built v3 grid)
${PYTHON_BIN} scripts/submit_gcp_batch_simulation.py \
  --region balearic_1km \
  --model croco \
  --run-date 2026-07-16 \
  --forecast-hours 24 \
  --run-id ${RUN_ID} \
  --image-uri ${IMAGE_URI} \
  --croco-grid-gcs-uri ${BALEARIC_GRID_URI} \
  --wrf-gcs-uri ${WRF_URI} \
  --machine-type c2d-highcpu-16 \
  --cpu-milli 16000 \
  --memory-mib 32768 \
  --mpi-ranks 16 \
  --project predsea-api \
  --location europe-west1 &

# 2. Alboran 1km (requires models.croco.grid_gcs_uri in its region profile)
${PYTHON_BIN} scripts/submit_gcp_batch_simulation.py \
  --region alboran_1km \
  --model croco \
  --run-date 2026-07-16 \
  --forecast-hours 24 \
  --run-id ${RUN_ID} \
  --image-uri ${IMAGE_URI} \
  --wrf-gcs-uri ${WRF_URI} \
  --machine-type c2d-highcpu-16 \
  --cpu-milli 16000 \
  --memory-mib 32768 \
  --mpi-ranks 16 \
  --project predsea-api \
  --location europe-west1 &

# 3. Gulf of Lion 1km (requires models.croco.grid_gcs_uri in its region profile)
${PYTHON_BIN} scripts/submit_gcp_batch_simulation.py \
  --region gulf_of_lion_1km \
  --model croco \
  --run-date 2026-07-16 \
  --forecast-hours 24 \
  --run-id ${RUN_ID} \
  --image-uri ${IMAGE_URI} \
  --wrf-gcs-uri ${WRF_URI} \
  --machine-type c2d-highcpu-16 \
  --cpu-milli 16000 \
  --memory-mib 32768 \
  --mpi-ranks 16 \
  --project predsea-api \
  --location europe-west1 &

# 4. Tyrrhenian 1km (requires models.croco.grid_gcs_uri in its region profile)
${PYTHON_BIN} scripts/submit_gcp_batch_simulation.py \
  --region tyrrhenian_1km \
  --model croco \
  --run-date 2026-07-16 \
  --forecast-hours 24 \
  --run-id ${RUN_ID} \
  --image-uri ${IMAGE_URI} \
  --wrf-gcs-uri ${WRF_URI} \
  --machine-type c2d-highcpu-16 \
  --cpu-milli 16000 \
  --memory-mib 32768 \
  --mpi-ranks 16 \
  --project predsea-api \
  --location europe-west1 &

# 5. Algerian 1km (requires models.croco.grid_gcs_uri in its region profile)
${PYTHON_BIN} scripts/submit_gcp_batch_simulation.py \
  --region algerian_1km \
  --model croco \
  --run-date 2026-07-16 \
  --forecast-hours 24 \
  --run-id ${RUN_ID} \
  --image-uri ${IMAGE_URI} \
  --wrf-gcs-uri ${WRF_URI} \
  --machine-type c2d-highcpu-16 \
  --cpu-milli 16000 \
  --memory-mib 32768 \
  --mpi-ranks 16 \
  --project predsea-api \
  --location europe-west1 &

wait
echo "========================================================================="
echo "✅ All 5 Western Mediterranean regional jobs successfully submitted to GCP Batch!"
echo "========================================================================="
