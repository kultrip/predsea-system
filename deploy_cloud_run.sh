#!/usr/bin/env bash
# PredSea GCP Serverless Deployment Script (Option A)
# Automates Cloud Build image generation, Cloud Run Job setup, and Scheduler trigger creation.

set -euo pipefail

# Text coloring utilities
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}👉 [INFO] $1${NC}"
}

log_warn() {
    echo -e "${YELLOW}⚠️ [WARN] $1${NC}"
}

log_err() {
    echo -e "${RED}❌ [ERROR] $1${NC}"
}

# 1. Identify GCP Project
log_info "Identifying active Google Cloud Project..."
PROJECT_ID=$(gcloud config get-value project 2>/dev/null || true)

if [ -z "${PROJECT_ID}" ]; then
    log_err "No active Google Cloud Project found. Please login and configure your project first:"
    echo "  gcloud auth login"
    echo "  gcloud config set project [PROJECT_ID]"
    exit 1
fi

log_info "Active GCP Project ID: ${PROJECT_ID}"

REGION="europe-west1"
IMAGE_NAME="europe-west1-docker.pkg.dev/${PROJECT_ID}/cloud-run-source-deploy/predsea-api:latest"

# 2. Build the unified container image using Cloud Build
log_info "Submitting build to Google Cloud Build (Remote compilation)..."
gcloud builds submit --region="${REGION}" --default-buckets-behavior="regional-user-owned-bucket" --tag "${IMAGE_NAME}" .

# 3. Securely Load Environment Variables for API Integrations (CMEMS, AEMET, SOCIB)
ENV_VARS="GOOGLE_CLOUD_PROJECT=${PROJECT_ID}"
if [ -f "humanintheloop/.env" ]; then
    log_info "Loading environment variables from humanintheloop/.env..."
    while IFS= read -r line || [ -n "$line" ]; do
        # Skip comments and empty lines
        if [[ ! "$line" =~ ^# ]] && [[ ! "$line" =~ ^$ ]]; then
            # Map COPERNICUS keys to the SDK's expected environment variable names as well
            if [[ "$line" =~ ^COPERNICUS_USERNAME= ]]; then
                val="${line#COPERNICUS_USERNAME=}"
                line="COPERNICUS_USERNAME=$val,COPERNICUSMARINE_SERVICE_USERNAME=$val"
            elif [[ "$line" =~ ^COPERNICUS_PASSWORD= ]]; then
                val="${line#COPERNICUS_PASSWORD=}"
                line="COPERNICUS_PASSWORD=$val,COPERNICUSMARINE_SERVICE_PASSWORD=$val"
            fi

            if [ -z "$ENV_VARS" ]; then
                ENV_VARS="$line"
            else
                ENV_VARS="$ENV_VARS,$line"
            fi
        fi
    done < "humanintheloop/.env"
fi

# Append standard GCS bucket and prefix environment variables if they are not already set
ENV_VARS="$ENV_VARS,PREDSEA_GCS_BUCKET=ds-revenue-protection-predsea-outputs,PREDSEA_GCS_PREFIX=predictions"

log_info "Deploying the serverless Cloud Run Service: 'predsea-api'..."
gcloud run deploy predsea-api \
    --image "${IMAGE_NAME}" \
    --region "${REGION}" \
    --allow-unauthenticated \
    --memory 2Gi \
    --cpu 2 \
    ${ENV_VARS:+--set-env-vars="$ENV_VARS"} \
    --quiet

log_info "Cloud Run Service 'predsea-api' is now deployed and active!"

log_info "Deploying the serverless Cloud Run Job: 'daily-orchestrator'..."
gcloud run jobs deploy daily-orchestrator \
    --image "${IMAGE_NAME}" \
    --command "python" \
    --args "scripts/daily_orchestrator.py" \
    --region "${REGION}" \
    --max-retries 0 \
    --task-timeout 4h \
    --cpu 2 \
    --memory 8Gi \
    ${ENV_VARS:+--set-env-vars="$ENV_VARS"} \
    --quiet

log_info "Cloud Run Job 'daily-orchestrator' is now deployed and ready!"

# 4. Provide instructions for Cloud Scheduler Trigger
log_info "Deployment Successful! 🎉"
echo "========================================================="
echo -e "To schedule the orchestrator to run automatically every day,"
echo -e "you can create a Cloud Scheduler job with the following command:"
echo "========================================================="
echo ""
echo "gcloud scheduler jobs create http daily-forecaster-trigger \\"
echo "  --schedule=\"0 3 * * *\" \\"
echo "  --uri=\"https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/daily-orchestrator:run\" \\"
echo "  --http-method=POST \\"
echo "  --oauth-service-account-email=\"[YOUR_SERVICE_ACCOUNT_EMAIL]\" \\"
echo "  --location=\"${REGION}\""
echo ""
echo "========================================================="
echo -e "To execute a manual run of the deployed job immediately:"
echo "========================================================="
echo "  gcloud run jobs execute daily-orchestrator --region=${REGION}"
echo "========================================================="
