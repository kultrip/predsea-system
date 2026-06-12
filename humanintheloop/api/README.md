# PredSea MVP API

This API reads existing prediction artifacts and answers questions from stored
route evidence. It does not fetch Copernicus or SOCIB forecast data per request.

The guaranteed minimum surface is:

- daily briefing
- route questions
- place weather for named places or coordinates

Those surfaces are the stable contract for the API and WhatsApp layers.

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
curl "http://127.0.0.1:8000/places/ibiza/weather?date=2026-06-12&run=latest"
```

Current route IDs:

- `palma_ibiza`
- `palma_barcelona`
- `palma_cabrera`
- `palma_valencia`
- `ibiza_formentera`
- `alcudia_ciutadella`

Current place-weather IDs:

- `ibiza`
- `palma`
- `formentera`
- `menorca`
- `cabrera`
- `ciutadella`
- `alcudia`
- `soller`
- `barcelona`
- `valencia`

Current map variables:

- `wave_height`
- `swell_1_height`
- `swell_1_direction`
- `swell_2_height`
- `swell_2_direction`
- `wind_wave_height`
- `wind_wave_direction`
- `current_speed`

Current production forecast source:

- Copernicus Marine Mediterranean waves, about 4.2 km, hourly.
- Copernicus Marine Mediterranean surface currents, about 4.2 km, hourly.
- SOCIB observations via `api.socib.es` when fresh station data is available.
- Puertos del Estado / REDEXT observations.
- Portus observations and model-point metadata.
- SOCIB model forecasts and atmospheric wind providers remain optional ETL
  layers controlled by feature flags.

The scheduled ETL runs hourly at `:49` UTC and refreshes the validation archive
used by the API, BigQuery export, and WhatsApp outputs.

Ask a captain-style question:

```bash
curl -X POST http://127.0.0.1:8000/routes/palma_ibiza/question \
  -H "Content-Type: application/json" \
  -d '{
    "date": "2026-05-31",
    "run": "latest",
    "question": "When is the best moment to leave from Palma to Ibiza today?",
    "vessel_class": "medium",
    "departure_time": "10:00",
    "priority": "comfort",
    "location_label": "Palma Marina",
    "current_time": "09:30",
    "current_date": "2026-06-09"
  }'
```

Optional route-question fields:

- `departure_time`: requested departure time.
- `priority`: `comfort`, `safety`, or `schedule`.
- `current_latitude` and `current_longitude`: shared GPS position for
  position-aware passage evidence.
- `current_time` and `current_date`: local request context.

Route question responses keep the same top-level shape and add:

```json
{
  "captain_knowledge": [
    {
      "id": "small_vessels_need_conservative_timing",
      "consequence": "A sea state that is manageable for larger vessels can feel uncomfortable or limiting for vessels under 15m.",
      "preferred_action": "Use the calmest available window and avoid exposed peak periods.",
      "confidence": "high"
    }
  ],
  "evidence_used": {
    "sea_state": {
      "wave_height_m": {
        "min": 0.8,
        "max": 1.3,
        "peak_time": "14:00"
      },
      "wave_direction_deg": {
        "peak": 74.0,
        "hourly": [
          {
            "time": "10:00",
            "wave_direction_deg": 72.0,
            "wave_sea_state": "stern quartering sea"
          }
        ]
      },
      "components": {
        "swell_1": {"height_m": 0.8, "direction_deg": 45.0},
        "swell_2": {"height_m": 0.4, "direction_deg": 110.0},
        "wind_wave": {"height_m": 0.6, "direction_deg": 72.0}
      }
    },
    "route_segments": [
      "arrival_conditions",
      "best_departure_window",
      "departure_conditions",
      "open_water_conditions",
      "worst_segment"
    ]
  }
}
```

Matt's agent can use `captain_knowledge` as visible reasoning, while the
captain-facing `answer` remains a concise operational recommendation. The
`sea_state.wave_direction_deg.hourly[].wave_sea_state` field is the
route-relative interpretation, for example following sea, beam sea, head sea,
or stern quartering sea when available.
Confidence is normalized in the rendered text, and the `Confidence:` line is
omitted entirely when the evidence package does not include a confidence value.
The API also returns `operational_stance`, a compact shared summary of the same
decision so follow-up questions and WhatsApp replies can reuse it instead of
re-deriving the recommendation independently.

`operational_stance` is the canonical source for the visible recommendation.
The API and WhatsApp layers should render from it rather than generating fresh
reasoning for each follow-up question.

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

Get a Leaflet-compatible map overlay:

```bash
curl "http://127.0.0.1:8000/maps?variable=wave_height&time=14:00&run=latest"
```

Inspect one map value at a GPS point:

```bash
curl "http://127.0.0.1:8000/maps/inspect?variable=wave_height&time=14:00&run=latest&lat=39.57&lon=2.64"
```

Get route media URLs:

```bash
curl "http://127.0.0.1:8000/routes/palma_ibiza/media?run=latest"
```

Get place weather for a named location, with optional coordinate override:

```bash
curl "http://127.0.0.1:8000/places/ibiza/weather?date=2026-06-12&run=latest"
curl "http://127.0.0.1:8000/places/ibiza/weather?date=2026-06-12&run=latest&lat=38.97&lon=1.44"
```

The place weather endpoint returns the weather-only layer for the selected
place. It includes wave height and direction, swell components, wind, current
when available, water temperature when available, air temperature when
available, freshness metadata, and the nearest supported place when a
coordinate override is provided.

Current public media artifacts are:

- `route_decision_map.png`
- `predsea_whatsapp_figure.png`

When the ETL has written `regional_evidence.json`, the response also includes:

```json
{
  "regional_evidence": {
    "available": true,
    "region_id": "balearics",
    "supported_modes": ["route_question", "location_question", "map_inspect"],
    "available_variables": ["current_speed", "wave_height"],
    "limitations": ["No seabed type", "No depth/bathymetry"]
  }
}
```

This tells the WhatsApp agent which modes and variables the current run
officially supports. Older runs without `regional_evidence.json` still answer,
but return `"available": false` for that metadata block.

The most useful source freshness fields for operators are:

- `freshness_status`
- `freshness_warning`
- `evidence_timestamp`
- `operational_stance.confidence`

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
