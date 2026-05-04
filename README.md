# PredSea System

PredSea is a vertically integrated oceanographic pipeline for proprietary marine
weather intelligence around the Balearic Sea. The system is designed to ingest
global atmospheric forcing, run high-resolution regional simulations, translate
model output into captain-ready intelligence, and preserve forecasts plus
observations in a PostGIS vault.

## Architecture

- `simulation/`: WRF/WPS Dockerfiles, Fortran namelists, domain setup, and run automation.
- `ingestion/`: GFS/ERA5 data acquisition from cloud object stores.
- `processing/`: NetCDF-to-JSON interpretation using `xarray` and `wrf-python`.
- `vault/`: PostgreSQL/PostGIS schema for forecasts, yacht telemetry, and bias analysis.
- `api/`: FastAPI gateway for the LLM agent.

## Execution Order

1. Phase 1: clear the old prototype and initialize the vertical pipeline layout.
2. Phase 3: build automated GFS ingestion first, so data is available while WRF builds.
3. Phase 2: build the WRF/WPS simulation environment and Balearic domain setup.
4. Phase 4: build the Captain's Intelligence Layer over `wrfout` files.
5. Phase 5: build the Data Assimilation Vault for forecasts, observations, and bias analysis.

## Development

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -v
```

Phase-specific compiled dependencies live beside their modules. For Phase 4,
install the WRF interpreter dependency separately:

```bash
pip install -r processing/requirements.txt
```

## Phase 3 Smoke Test

List the latest GFS keys for the Western Mediterranean without downloading:

```bash
python ingestion/gfs_puller.py --dry-run --max-files 5
```

Download and filter files after installing `wgrib2`:

```bash
conda install -c conda-forge wgrib2
python ingestion/gfs_puller.py --max-files 1
```

## Phase 2 WRF Scaffold

Generate the Balearic 1km nested WPS namelist:

```bash
python simulation/setup_domain.py --output simulation/namelist.wps
```

Build the WRF/WPS image when you are ready for the heavy compile:

```bash
docker build --platform linux/amd64 -t predsea-wrf:4.5 -f simulation/Dockerfile simulation
```

Run `simulation/run_pipeline.sh` inside the image with GFS GRIB2 files mounted at
`/data/gfs`.

## Phase 4 Captain Summary

Run the WRF interpreter against the sample `wrfout_d03` fixture:

```bash
python processing/run_phase4_summary.py
```

The interpreter returns LLM-ready JSON with condition, wind speed, direction,
gust factor, stability, risk assessment, source, location, and supporting
metrics.

Run a route sample across the WRF fixture:

```bash
python processing/run_route_summary.py
```

Run Dijkstra lowest-wind routing across the WRF grid:

```bash
python processing/run_optimal_route.py
```

Compare Dijkstra lowest-wind routing across the 9 km, 3 km, and 1 km sample
domains:

```bash
python processing/run_route_comparison.py
```

Validate forecast distributions against station-style observations:

```bash
python processing/run_observation_validation.py
```

The default observation CSV is a small development fixture. Replace
`ingestion/fixtures/balearic_observations_sample.csv` with SOCIB or Puertos del
Estado observations for real validation.
