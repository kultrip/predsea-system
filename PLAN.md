# PredSea Vertically Integrated Pipeline Plan

## Phase 1: Repository Foundation

Create the new project structure:

- `simulation/`: WRF/WPS Dockerfiles and Fortran namelists.
- `ingestion/`: scripts that fetch global GFS/ERA5 data from AWS S3.
- `processing/`: NetCDF-to-JSON translation using `wrf-python`.
- `vault/`: PostGIS schema for predictions and future Yacht-as-a-Sensor data.
- `api/`: FastAPI gateway for the LLM Agent to query proprietary runs.

## Phase 2: Atmospheric Forcing Engine (WRF)

In `simulation/`:

- Create a Dockerfile for a high-performance WRF v4.5 environment.
- Use a multi-stage build to compile WRF and WPS with GNU compilers and NetCDF-4 support.
- Provide `setup_domain.py` to generate `namelist.wps` for a 1km high-resolution nest centered on the Balearic Sea, focusing on the Menorca and Ibiza channels.
- Include `run_pipeline.sh` to automate the transition from GRIB2 ingestion to `wrf.exe` output.

Current status: scaffolded in `simulation/` with a multi-stage WRF/WPS Dockerfile,
Balearic `namelist.wps` generator, generated default namelist, and pipeline
orchestration script. The Docker image has not been built locally in this
session because compiling WRF/WPS is a long-running workload.

## Phase 3: Automated GFS Data Ingestion

In `ingestion/`:

- Create `gfs_puller.py`.
- Use `boto3` to fetch the latest 0.25-degree GFS data from the `noaa-gfs-bdp-pds` S3 bucket.
- Download only the latest cycle: `00`, `06`, `12`, or `18` UTC.
- Implement a Western Mediterranean bounding-box flow to reduce bandwidth and compute time.
- Add a `tenacity` retry loop for transient 504/timeout issues.

## Phase 4: The Captain's Intelligence Layer

In `processing/`:

- Create `mariner_interpreter.py`.
- Use `xarray` and `wrf-python` to parse `wrfout` files.
- Implement `get_captain_summary(lat, lon, time)`.
- Calculate resultant wind, gust factors, and sea state stability.
- Return JSON structured for LLM consumption.

Example output:

```json
{
  "condition": "Gale Warning",
  "wind_knots": 35,
  "direction": "NW",
  "risk_assessment": "High risk of micro-bursts near Tramuntana cliffs"
}
```

## Phase 5: Data Assimilation Vault

In `vault/`:

- Create `schema.sql` for PostgreSQL/PostGIS.
- Create `forecast_ledger` with spatial indexing for WRF outputs.
- Create `observations` for real-time yacht telemetry: wind, pressure, and position.
- Create `bias_analysis` joining forecasts and observations by time/space proximity to calculate error margin for future ML training.

## Strategic Rationale

Ownership: PredSea becomes a data provider, not a wrapper.

Reliability: Uptime depends on cloud infrastructure rather than government servers.

Valuation: Proprietary model runs and a Truth Vault become defensible IP.
