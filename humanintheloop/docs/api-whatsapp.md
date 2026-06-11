# PredSea API and WhatsApp guide

This guide explains how to use the API outputs and what the WhatsApp agent should expect from them.

## Core behavior

PredSea is a local marine briefing assistant, not an autopilot or a replacement for official forecasts. The captain owns the final decision.

The API now returns one canonical `operational_stance` per route/run/question context so the visible answer, briefing, and follow-up questions stay consistent.

## Response style

Visible answers should:

- speak in windows, not minutes
- use Europe/Madrid local time in the user-facing text
- avoid safety absolutes like `safe`, `guaranteed`, or `no issues`
- keep the default answer short and operational
- expand only when the captain asks `why?` or requests evidence

Typical answer sections:

- Decision
- Best window
- Current
- Trend
- Comfort
- Risk
- Watch out
- Why
- What could change
- Confidence

## Important fields returned by the API

### `operational_stance`

Shared internal summary used by the API and the WhatsApp agent.

### `evidence_used`

Shows the evidence behind the call, including:

- forecast variables used
- hourly points considered
- route segments
- observation alignment
- forecast sanity checks
- passage evidence

### `freshness_status` / `freshness_warning`

Helps the API tell the captain when the latest package is still from the previous run or should be rechecked before departure.

## WhatsApp integration notes

The WhatsApp layer should use the same canonical stance as the API and should not re-derive its own recommendation. It should render the answer from the API stance, then optionally add a short human-friendly wrapper.

## Common question types

- Departure timing
- Comfort / risk
- Route conditions
- What changed since the last check
- Position-aware passage questions
- Anchoring guidance from a GPS point

## Current source coverage

The ETL that feeds the API and WhatsApp currently uses:

- Copernicus Mediterranean waves and currents
- SOCIB via `api.socib.es`
- Puertos del Estado / REDEXT
- Portus observation and model-point data

## Local testing

Use the API question endpoint for the canonical answer, and compare it to the WhatsApp renderers if you want to inspect how the same stance is phrased in the chat surface.
