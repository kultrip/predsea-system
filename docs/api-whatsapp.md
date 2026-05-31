# PredSea API and WhatsApp Integration

This document describes the deployed PredSea API, how Matt's WhatsApp platform
should call it, how run-based evidence works, and what should be added next.

## Current Purpose

The API is the decision interface over stored PredSea evidence.

It does not download Copernicus, SOCIB, or model data during a captain request.
It reads the latest ETL evidence package from Google Cloud Storage and returns
captain-ready guidance.

```text
WhatsApp platform
        -> PredSea API
        -> latest evidence package in GCS
        -> operational answer
```

## Production URL

Current Cloud Run URL:

```text
https://predsea-api-193957983101.europe-west1.run.app
```

Cloud Run service:

```text
predsea-api
```

Project:

```text
predsea-api
```

The API reads from:

```text
gs://predsea-daily-outputs/predictions
```

using these Cloud Run environment variables:

```text
PREDSEA_GCS_BUCKET=predsea-daily-outputs
PREDSEA_GCS_PREFIX=predictions
```

## Current Endpoints

### Health

```bash
curl https://predsea-api-193957983101.europe-west1.run.app/health
```

Response:

```json
{
  "status": "ok",
  "latest_date": "2026-05-31",
  "latest_run": "2026-05-31T0058Z",
  "storage_backend": "gcs"
}
```

`latest_run` can be `null` for older legacy daily folders that do not have
run-based outputs.

### Routes

Latest routes:

```bash
curl "https://predsea-api-193957983101.europe-west1.run.app/routes"
```

Routes for a date:

```bash
curl "https://predsea-api-193957983101.europe-west1.run.app/routes?date=2026-05-31"
```

Routes for a specific run:

```bash
curl "https://predsea-api-193957983101.europe-west1.run.app/routes?date=2026-05-31&run=2026-05-31T0058Z"
```

### Evidence

Latest evidence for a route:

```bash
curl "https://predsea-api-193957983101.europe-west1.run.app/routes/palma_ibiza/evidence?run=latest"
```

Evidence for a specific date and run:

```bash
curl "https://predsea-api-193957983101.europe-west1.run.app/routes/palma_ibiza/evidence?date=2026-05-31&run=2026-05-31T0058Z"
```

The API currently returns the `decision_context` snapshot from `evidence.json`.
This keeps the existing `/briefing` and `/question` behavior stable while the
evidence package evolves.

### Briefing

WhatsApp format:

```bash
curl "https://predsea-api-193957983101.europe-west1.run.app/routes/palma_ibiza/briefing?run=latest&format=whatsapp&vessel_class=medium"
```

LinkedIn format:

```bash
curl "https://predsea-api-193957983101.europe-west1.run.app/routes/palma_ibiza/briefing?run=latest&format=linkedin&vessel_class=medium"
```

Supported query parameters:

- `date`: optional, `YYYY-MM-DD`
- `run`: optional, `latest` or a specific run ID
- `vessel_class`: `small`, `medium`, or `large`
- `format`: `whatsapp` or `linkedin`

### Question

Ask a captain-style question:

```bash
curl -X POST \
  "https://predsea-api-193957983101.europe-west1.run.app/routes/palma_ibiza/question" \
  -H "Content-Type: application/json" \
  -d '{
    "date": "2026-05-31",
    "run": "latest",
    "question": "Can I cross to Ibiza this afternoon?",
    "vessel_class": "small",
    "location_label": "Palma Marina",
    "current_time": "09:30"
  }'
```

Request fields:

- `question`: required free text from the captain.
- `date`: optional. If omitted, the API uses the latest available date.
- `run`: optional. Use `latest` for the newest run of the selected date.
- `vessel_class`: optional. Defaults to `medium`.
- `location_label`: optional human-readable label.
- `current_time`: optional local time used for timing-sensitive demos.

Response includes:

- `answer`
- `intent`
- `date`
- `run`
- `evidence_used`

## Recommended WhatsApp Flow

Matt's platform can keep the first integration simple:

```text
captain message
        -> choose route_id
        -> POST /routes/{route_id}/question
        -> send answer text back to WhatsApp
```

Recommended default request:

```json
{
  "run": "latest",
  "question": "<captain message>",
  "vessel_class": "medium",
  "location_label": "shared location"
}
```

If the captain profile is known, Matt should pass the real `vessel_class`.

## Run Selection

Use `run=latest` for normal WhatsApp behavior.

Use a specific run only for debugging, validation, or replaying historical
answers.

```text
run=latest
run=2026-05-31T0058Z
```

If no run is supplied, the API also resolves the latest run when a run-based
folder exists. Explicit `run=latest` is clearer for Matt's integration.

## Route-Based Limitation

The current `/question` endpoint is route-based:

```text
/routes/{route_id}/question
```

That works for questions like:

- "Can I cross Palma to Ibiza this afternoon?"
- "What is the best window for Alcudia to Ciutadella?"
- "Is Ibiza to Formentera comfortable for a small vessel?"

It is not yet a full free-location anchoring engine.

If a captain asks:

```text
I am in Formentera. Where should I anchor tonight?
```

the system should not pretend to know a precise anchorage unless the evidence
package includes location/region/anchorage evidence.

Near-term fallback answer should ask for:

- shared GPS location
- intended anchorage
- vessel class
- time window

## Next API Additions

### 1. Location-Aware Questions

Add optional fields:

```json
{
  "location": {
    "lat": 38.72,
    "lon": 1.43
  },
  "destination": {
    "lat": 39.57,
    "lon": 2.64
  },
  "time_window": "tonight"
}
```

This will let the API choose between:

- route evidence
- point evidence
- region evidence
- anchorage evidence

### 2. Intent Router

Before answering, classify the captain question into an operational intent:

- `route_timing`
- `sea_state_here`
- `anchoring_advice`
- `fuel_efficiency`
- `go_no_go`
- `compare_routes`
- `general_forecast`
- `unsupported_question`

Unsupported questions should fail gracefully:

```text
I do not have enough local anchorage evidence to recommend a specific spot yet.
Share your position or intended anchorage and I can assess exposure and timing.
```

### 3. Media Responses

To send maps through WhatsApp, the API should return media metadata:

```json
{
  "answer": "...",
  "media": [
    {
      "type": "image",
      "title": "Balearic wave forecast",
      "url": "https://..."
    }
  ]
}
```

The image should be stored in GCS and exposed through a signed URL or controlled
public URL. Matt's platform can then send the media URL through WhatsApp.

### 4. Map Endpoint

Add endpoints such as:

```text
GET /maps?date=2026-05-31&run=latest&variable=wave_height&time=16:00
GET /routes/{route_id}/media?run=latest
```

These should return GCS URLs, not local file paths.

### 5. Evidence Package Endpoint

Eventually `/evidence` should expose the full `evidence.json`, while
`/question` continues using `decision_context` internally.

This allows a SaaS/web UI to show:

- decision text
- map
- route status
- data quality
- model comparison
- evidence used

## SaaS / Webpage Integration

The webpage should not fetch forecasts directly. It should call the API.

Useful calls:

```text
GET /health
GET /routes?run=latest
GET /routes/{route_id}/evidence?run=latest
GET /routes/{route_id}/briefing?run=latest&format=whatsapp
POST /routes/{route_id}/question
```

Future calls:

```text
GET /maps
GET /regions/{region_id}/evidence
POST /question
```

The web app should display the same operational pair that captains understand:

```text
decision + map evidence
```

## Operational Tone

PredSea should sound like a maritime operations desk:

- calm
- concise
- route-aware
- honest about uncertainty
- focused on timing and decisions

Avoid:

- hype
- exaggerated certainty
- generic weather summaries
- raw data dumps
- sounding like a chatbot

## Current Deployment Commands

Deploy Cloud Run from the repo root:

```bash
gcloud run deploy predsea-api \
  --source . \
  --region europe-west1 \
  --allow-unauthenticated \
  --set-env-vars PREDSEA_GCS_BUCKET=predsea-daily-outputs,PREDSEA_GCS_PREFIX=predictions
```

Run tests locally from `humanintheloop/`:

```bash
../.venv311/bin/python -m pytest -q
```
