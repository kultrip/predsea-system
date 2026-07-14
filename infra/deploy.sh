#!/usr/bin/env bash
# PredSea GCP Multi-Environment Deployment Script
# Compiles container remote, loads env parameters, deploys Cloud Run Service,
# Cloud Run Job, and Cloud Scheduler triggers for the specified environment.
# Usage: ./infra/deploy.sh [test|prod]

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

# 1. Validate Environment Argument
if [ $# -ne 1 ]; then
    log_err "Missing environment argument."
    echo "Usage: ./infra/deploy.sh [test|prod]"
    exit 1
fi

ENV=$(echo "$1" | tr '[:upper:]' '[:lower:]')
if [ "${ENV}" != "test" ] && [ "${ENV}" != "prod" ]; then
    log_err "Invalid environment: '${ENV}'. Must be 'test' or 'prod'."
    exit 1
fi

log_info "Deploying to environment: [${ENV}]"

# 2. Identify and verify active GCP Project
log_info "Identifying active Google Cloud Project..."
PROJECT_ID=$(gcloud config get-value project 2>/dev/null || true)

if [ -z "${PROJECT_ID}" ] || [ "${PROJECT_ID}" != "predsea-api" ]; then
    log_err "Active GCP Project ID is not 'predsea-api' (found: '${PROJECT_ID:-None}')."
    log_err "Please set the active project to 'predsea-api' before deploying:"
    echo "  gcloud config set project predsea-api"
    exit 1
fi

log_info "Active GCP Project ID: ${PROJECT_ID}"

REGION="europe-west1"
IMAGE_NAME="gcr.io/${PROJECT_ID}/predsea-system:latest"

# 3. Build the unified container image using Cloud Build
log_info "Submitting build to Google Cloud Build (Remote compilation)..."
gcloud builds submit --tag "${IMAGE_NAME}" .

# 4. Securely Load Environment Variables for API Integrations (CMEMS, AEMET, SOCIB)
ENV_VARS="GOOGLE_CLOUD_PROJECT=${PROJECT_ID}"
if [ -f "humanintheloop/.env" ]; then
    log_info "Loading base environment variables from humanintheloop/.env..."
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

# Append isolated environment specific environment variables
ENV_VARS="${ENV_VARS},PREDSEA_ENV=${ENV},PREDSEA_GCS_BUCKET=predsea-daily-outputs-${ENV},PREDSEA_BIGQUERY_DATASET=predsea_validation_${ENV},PREDSEA_GCS_PREFIX=predictions"

# 5. Deploy Cloud Run Service (API)
SERVICE_NAME="predsea-api-${ENV}"
API_SA="predsea-api-${ENV}@${PROJECT_ID}.iam.gserviceaccount.com"

log_info "Deploying the serverless Cloud Run Service: '${SERVICE_NAME}'..."
gcloud run deploy "${SERVICE_NAME}" \
    --image "${IMAGE_NAME}" \
    --region "${REGION}" \
    --allow-unauthenticated \
    --memory 2Gi \
    --cpu 2 \
    --service-account "${API_SA}" \
    --set-env-vars="${ENV_VARS}" \
    --labels="env=${ENV}" \
    --quiet

log_info "Cloud Run Service '${SERVICE_NAME}' is now deployed and active!"

# 6. Deploy Cloud Run Job (ETL)
JOB_NAME="daily-orchestrator-${ENV}"
ETL_SA="predsea-etl-${ENV}@${PROJECT_ID}.iam.gserviceaccount.com"

log_info "Deploying the serverless Cloud Run Job: '${JOB_NAME}'..."
gcloud run jobs deploy "${JOB_NAME}" \
    --image "${IMAGE_NAME}" \
    --command "python" \
    --args "scripts/daily_orchestrator.py" \
    --region "${REGION}" \
    --max-retries 0 \
    --task-timeout 14h \
    --cpu 2 \
    --memory 8Gi \
    --service-account "${ETL_SA}" \
    --set-env-vars="${ENV_VARS}" \
    --labels="env=${ENV}" \
    --quiet

log_info "Cloud Run Job '${JOB_NAME}' is now deployed and ready!"

# 7. Grant Project Invoker Permission to the ETL SA for triggering Cloud Run jobs
log_info "Granting Project Run Invoker role to ETL service account ${ETL_SA}..."
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${ETL_SA}" \
    --role="roles/run.invoker" \
    --quiet >/dev/null

# 8. Setup corresponding Cloud Scheduler trigger
TRIGGER_NAME="predsea-etl-trigger-${ENV}"
log_info "Setting up Cloud Scheduler trigger: '${TRIGGER_NAME}'..."

# Delete old trigger job if exists
gcloud scheduler jobs delete "${TRIGGER_NAME}" --location="${REGION}" --quiet >/dev/null 2>&1 || true

# Create new trigger
gcloud scheduler jobs create http "${TRIGGER_NAME}" \
    --schedule="0 5 * * *" \
    --time-zone="Europe/Madrid" \
    --uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run" \
    --http-method=POST \
    --oauth-service-account-email="${ETL_SA}" \
    --location="${REGION}" \
    --quiet

log_info "Cloud Scheduler Trigger '${TRIGGER_NAME}' successfully scheduled (05:00 AM Europe/Madrid time)!"

log_info "Deployment for [${ENV}] completed successfully! 🎉"
echo "========================================================="
echo -e "To execute a manual run of the deployed job immediately:"
echo "========================================================="
echo "  gcloud run jobs execute ${JOB_NAME} --region=${REGION}"
echo "========================================================="
