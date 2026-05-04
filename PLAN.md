# PredSea Decision Engine (v1) Plan

## Project

PredSea Decision Engine (v1)

## Objective

Build a Python-based middleware that fetches real-time oceanographic data from
the SOCIB THREDDS server via OpenDAP and exposes a Natural Language Ready API
for yacht captains.

## Core Tech Stack

- Data: `xarray`, `netCDF4`, `pydap` for remote slicing
- API: FastAPI
- Logic: Geopy for coordinate math

## Step 1: The Data Slicer (The Foundation)

Create `socib_client.py` with `get_ocean_data(lat, lon, timeframe)`.

The function must:

- Connect to the SOCIB WMOP, Western Mediterranean Operational model, OpenDAP URL:
  `https://thredds.socib.es/thredds/dodsC/wmop/forecast/latest`
- Use `xarray` to remotely slice the dataset for a specific GPS coordinate and a
  24-hour time window.
- Extract:
  - `sea_surface_height`
  - `u_current`
  - `v_current`
  - `significant_wave_height`
- Return a clean Python dictionary with these values.
- Avoid downloading the whole file by using remote indexing.

Current status: implemented in `socib_client.py` with unit tests in
`tests/test_socib_client.py`.

## Step 2: The Mariner Logic (The Brain)

Create `mariner_logic.py`. This is the Expert System for PredSea.

Create `evaluate_safety(data, vessel_type="yacht_20m")`.

The function must:

- Take the raw numbers from SOCIB.
- Apply Mariner Thresholds:
  - Green: waves below 1.0m, currents below 0.5 knots.
  - Yellow: waves from 1.0m to 1.8m, currents from 0.5 to 1.5 knots.
    Label: `Moderate discomfort`.
  - Red: waves above 2.0m.
    Label: `Safety Risk / Re-route suggested`.
- Return a `status` and a Plain English Summary that an LLM can use to talk to a
  captain.

## Step 3: The API (The Interface)

Create `main.py` using FastAPI.

The API must:

- Provide `GET /check-route` accepting `lat` and `lon`.
- Call `socib_client.get_ocean_data()` to fetch oceanographic data.
- Call `mariner_logic.evaluate_safety()` to produce the mariner evaluation.
- Return JSON containing the raw data and the human-readable Mariner Summary.
- Provide a health-check endpoint that verifies the SOCIB connection.

## Step 4: The AI Agent Connector (The Goal)

Create `agent_tool.py`.

The script must:

- Define a Pydantic schema for the `/check-route` tool.
- Describe how an LLM should call this API.
- Include this system prompt:

```text
You are a Master Mariner for the Balearics. Use the provided data to give concise, confident navigation advice. Mention specific conditions like the Menorca Channel if applicable.
```

## Why This Architecture

Zero Overhead: PredSea does not store oceanographic data. It streams the needed
slice from SOCIB when a captain or agent asks.

Context Aware: Kultrip itinerary waypoints can eventually provide the `lat` and
`lon` inputs directly.

Modular: If SOCIB changes its URL, only `socib_client.py` needs to change. If
PredSea later moves to deeper proprietary models, the client module can be
swapped without rewriting the API or mariner logic.
