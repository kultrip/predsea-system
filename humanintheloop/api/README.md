# PredSea MVP API

This API reads existing prediction artifacts and answers questions from stored
route evidence. It does not fetch Copernicus or SOCIB forecast data per request.

For the full API and WhatsApp integration guide, see:

```text
docs/api-whatsapp.md
```

Run from `humanintheloop/`:

```bash
uvicorn api.app:app --reload --port 8000
```

Examples:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/routes
curl "http://127.0.0.1:8000/routes/palma_ibiza/evidence?date=2026-05-31&run=latest"
curl "http://127.0.0.1:8000/routes/palma_ibiza/briefing?date=2026-05-31&run=latest&vessel_class=medium&format=whatsapp"
```

Ask a captain-style question:

```bash
curl -X POST http://127.0.0.1:8000/routes/palma_ibiza/question \
  -H "Content-Type: application/json" \
  -d '{
    "date": "2026-05-31",
    "run": "latest",
    "question": "Can I leave Palma at 17:00?",
    "vessel_class": "medium",
    "location_label": "Palma Marina",
    "current_time": "09:30"
  }'
```

Ask a location-based question from a shared GPS point:

```bash
curl -X POST http://127.0.0.1:8000/question \
  -H "Content-Type: application/json" \
  -d '{
    "date": "2026-05-31",
    "run": "latest",
    "question": "I am at this position, where should I anchor tonight?",
    "latitude": 39.45,
    "longitude": 2.10,
    "vessel_class": "small",
    "current_time": "19:00"
  }'
```

`POST /question` is Phase 1 location intelligence. It samples the nearest
forecast map grids around the shared position and returns a conservative
operational read. It does not yet include seabed type, depth, anchoring
restrictions, or nearby shelter search.

By default, the API loads local files from
`predictions/YYYY-MM-DD/runs/RUN_ID/<route_id>/evidence.json`. If that richer
run-based evidence package is missing, it falls back to the older
`predictions/YYYY-MM-DD/<route_id>/evidence.json` and then
`predictions/YYYY-MM-DD/<route_id>/daily_snapshot.json`.

The evidence package is the forward-compatible format for WhatsApp questions:
it includes the route subject, observation records, forecast variables,
operational interpretation, data quality notes, and a `decision_context` block
that keeps the current `/briefing` and `/question` behavior stable.

In production, set these Cloud Run environment variables so the API reads the
latest ETL outputs from Google Cloud Storage first:

```bash
PREDSEA_GCS_BUCKET=predsea-daily-outputs
PREDSEA_GCS_PREFIX=predictions
```

If GCS is unavailable or an object is missing, the API falls back to local
bundled prediction files. As the ETL evolves, the same endpoints should read
richer evidence files with Copernicus, SOCIB WMOP/SAPO, model comparison, and
observations.
