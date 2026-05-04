# predsea-system

PredSea Decision Engine (v1) is a Python-based middleware that fetches
real-time oceanographic data from the SOCIB THREDDS server via OpenDAP and
exposes a Natural Language Ready API for yacht captains.

## Project Plan

The full v1 roadmap lives in [PLAN.md](PLAN.md).

### Objective

Build a modular decision engine that can:

- Stream oceanographic data from SOCIB without storing datasets.
- Convert raw sea state and current values into mariner-friendly safety labels.
- Expose the result through FastAPI.
- Provide an AI-agent tool schema so an LLM can give concise route advice.

### Core Tech Stack

- Data: `xarray`, `netCDF4`, `pydap` for remote slicing
- API: FastAPI
- Logic: Geopy for coordinate math

## Implementation Roadmap

### Step 1: The Data Slicer (The Foundation)

Create `socib_client.py` with `get_ocean_data(lat, lon, timeframe)`.

The function connects to the SOCIB WMOP, Western Mediterranean Operational
model, OpenDAP URL:

```text
https://thredds.socib.es/thredds/dodsC/wmop/forecast/latest
```

It uses `xarray` to remotely slice the dataset for a specific GPS coordinate and
a 24-hour time window, then extracts:

- `sea_surface_height`
- `u_current`
- `v_current`
- `significant_wave_height`

It returns a clean Python dictionary and avoids downloading the whole file by
using remote indexing.

Current status: implemented in `socib_client.py`.

### Step 2: The Mariner Logic (The Brain)

Create `mariner_logic.py` with:

```python
evaluate_safety(data, vessel_type="yacht_20m")
```

This Expert System applies Mariner Thresholds:

- Green: waves below 1.0m, currents below 0.5 knots.
- Yellow: waves from 1.0m to 1.8m, currents from 0.5 to 1.5 knots.
  Label: `Moderate discomfort`.
- Red: waves above 2.0m.
  Label: `Safety Risk / Re-route suggested`.

It returns a status and Plain English Summary that an LLM can use to talk to a
captain.

### Step 3: The API (The Interface)

Create `main.py` using FastAPI.

The API will provide:

- `GET /check-route` accepting `lat` and `lon`.
- A call into `socib_client` for raw oceanographic data.
- A call into `mariner_logic` for the evaluation.
- JSON containing raw data and the human-readable Mariner Summary.
- A health-check endpoint to verify the SOCIB connection.

### Step 4: The AI Agent Connector (The Goal)

Create `agent_tool.py`.

This script will define a Pydantic schema for the `/check-route` tool and
include this AI system prompt:

```text
You are a Master Mariner for the Balearics. Use the provided data to give concise, confident navigation advice. Mention specific conditions like the Menorca Channel if applicable.
```

## Why This Architecture

Zero Overhead: PredSea does not store oceanographic data. It streams the needed
slice from SOCIB.

Context Aware: Kultrip itinerary waypoints can eventually provide `lat` and
`lon` inputs directly.

Modular: If SOCIB changes its URL, only `socib_client.py` needs to change. If
PredSea later moves to deeper proprietary models, the client module can be
swapped without rewriting the API or mariner logic.

## Setup

Use Python 3.11 or newer.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -v
```

## SOCIB Data Slicer

```python
from socib_client import get_ocean_data

data = get_ocean_data(39.57, 2.65, None)
print(data)
```

`get_ocean_data(lat, lon, timeframe)` reads from:

```text
https://thredds.socib.es/thredds/dodsC/wmop/forecast/latest
```

It selects the nearest model grid point, slices a 24-hour time window, and
returns a plain Python dictionary ready for an API layer.
