# PredSea Prediction and ETL

This document describes the current PredSea prediction pipeline: what it
fetches, what it produces, where outputs are stored, and where future data
sources should be added.

## Current Purpose

The ETL does not answer captain questions directly. Its job is to build a
decision-ready evidence package from external forecasts, SOCIB observations,
route geometry, vessel class, and operational interpretation.

```text
external forecasts + SOCIB observations + route sampling
        -> evidence package
        -> API / WhatsApp decision layer
```

The API should be able to answer many questions from the latest evidence
without downloading forecast data during the request.

## Current Data Sources

Current external sources:

- Copernicus Marine Mediterranean wave forecast.
- Copernicus Marine Mediterranean surface-current forecast.
- SOCIB public observations via DataDiscovery.

Current forecast variables:

- `VHM0`: significant wave height.
- `VMDR`: mean wave direction from.
- `uo`: eastward surface current component.
- `vo`: northward surface current component.

Current observation variables depend on each SOCIB platform, but can include:

- wave height
- wave direction
- water temperature
- salinity
- sea-level pressure
- air pressure

SOCIB observations older than the freshness threshold are filtered out before
they enter the evidence package.

## Current Routes

Routes are configured in:

```text
humanintheloop/routes.json
```

Current routes:

- `palma_ibiza`
- `palma_cabrera`
- `ibiza_formentera`
- `alcudia_ciutadella`

Each route defines:

- origin
- destination
- sample points
- operational route note
- wave validation truth source, when available
- current validation truth source, when available

Route decisions use the exposed route maximum per hour, not a broad Balearic
box average.

## Run Frequency

GitHub Actions currently runs the ETL three times per day:

- 08:30 Mallorca summer time
- 13:30 Mallorca summer time
- 17:30 Mallorca summer time

The workflow is:

```text
.github/workflows/predsea-daily.yml
```

GitHub cron runs in UTC, so the schedule may need seasonal adjustment if the
operational promise becomes exact local time all year.

## Output Layout

The ETL now writes run-based outputs.

```text
outputs/
  YYYY-MM-DD/
    latest_run.json
    runs/
      RUN_ID/
        run_manifest.json
        palma_ibiza/
          evidence.json
          daily_snapshot.json
          briefing_whatsapp.txt
          briefing_linkedin.txt
          briefing_whatsapp_screenshot_script.txt
          predsea_whatsapp_figure.png
          route_decision_map.png
```

Example run ID:

```text
2026-05-31T0058Z
```

The same structure is uploaded to Google Cloud Storage:

```text
gs://predsea-daily-outputs/predictions/YYYY-MM-DD/
```

The API reads GCS first and local bundled predictions only as fallback.

## Main Artifacts

`evidence.json`

The forward-compatible decision package. It contains:

- route subject
- forecast variables
- SOCIB observations
- operational interpretation
- data-quality notes
- `decision_context` for current `/briefing` and `/question` behavior

`daily_snapshot.json`

Legacy-compatible route snapshot. Still used as fallback and for some existing
renderers.

`briefing_whatsapp.txt`

Human-readable WhatsApp briefing.

`briefing_linkedin.txt`

LinkedIn-ready operational summary.

`predsea_whatsapp_figure.png`

Chat-style figure for demos and posts.

`route_decision_map.png`

Current oceanographic map artifact. Despite the name, the product direction is
to show physical sea conditions, not only route advice.

## How To Run Locally

From the repo root:

```bash
python scripts/generate_daily_briefing.py
```

Run one route:

```bash
python scripts/generate_daily_briefing.py \
  --route palma_ibiza
```

Run one route with a fixed date and run ID:

```bash
python scripts/generate_daily_briefing.py \
  --date 2026-05-31 \
  --run-id 2026-05-31T1230Z \
  --route palma_ibiza
```

Skip maps and chat figures for a fast smoke test:

```bash
python scripts/generate_daily_briefing.py \
  --output-root /tmp/predsea-smoke \
  --date 2026-05-31 \
  --run-id 2026-05-31T1230Z \
  --route palma_ibiza \
  --skip-figures \
  --skip-maps
```

Export a web-demo bundle from the latest run:

```bash
python scripts/export_web_demo_bundle.py \
  --input-root outputs \
  --output-dir outputs/web-demo \
  --featured-route palma_ibiza
```

## Cloud Upload

GitHub Actions authenticates with:

```text
GCP_SA_KEY
```

and syncs the latest dated output folder to:

```text
gs://predsea-daily-outputs/predictions/YYYY-MM-DD
```

Manual upload:

```bash
gcloud storage rsync --recursive \
  outputs/2026-05-31 \
  gs://predsea-daily-outputs/predictions/2026-05-31
```

## Where To Add More External Models

New external forecast sources should be added to the ETL/data layer, not the
API.

Recommended future structure:

```text
humanintheloop/providers/
  copernicus.py
  socib_thredds.py
  ecmwf.py
  noaa_gfs.py

humanintheloop/normalizers/
  waves.py
  currents.py
  wind.py

humanintheloop/samplers/
  route_sampling.py
  point_sampling.py
  region_sampling.py
```

Each provider should normalize into common variables before evidence packaging:

- wave height
- wave direction
- wave period
- current speed
- current direction
- wind speed
- wind direction
- water temperature
- model run time
- grid resolution
- coverage area
- source freshness

The API should not need to know whether the source was Copernicus, SOCIB WMOP,
ECMWF, or a future PredSea internal model.

## Where To Add Graham's Captain Knowledge

Captain knowledge should not live in the ETL. It belongs in the decision layer.

Recommended future structure:

```text
humanintheloop/captain_knowledge/
  graham_cases.json
  graham_rules.yaml
  vessel_thresholds.yaml
  route_exposure_notes.yaml
```

The ETL produces evidence. Graham's knowledge interprets evidence.

## Where Internal Dynamical Models Would Fit Later

Running WRF, ROMS, SWAN, or WaveWatch III is a separate numerical modeling
layer. It should not be embedded in the API or the lightweight ETL.

Future structure:

```text
modeling/
  wrf/
  roms/
  waves/
  coupling/
  postprocess/
```

Those model outputs should still be converted into the same evidence package
format. This keeps the WhatsApp/API layer stable whether forecasts come from
Copernicus, SOCIB, or PredSea's own model.

## Next Useful Additions

- Add SOCIB THREDDS / WMOP as a second external model.
- Add model metadata to `evidence.json`: model name, run time, resolution, and
  source URL.
- Add point and region evidence packages for questions such as "Is it safe to
  stay here?" or "Where can I anchor near Formentera?"
- Add signed GCS media URLs for maps and WhatsApp images.
- Add model comparison: Copernicus vs SOCIB vs buoy truth.
- Add data-quality warnings when observations are stale or model files are old.
