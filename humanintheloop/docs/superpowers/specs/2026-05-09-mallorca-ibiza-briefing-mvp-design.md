# PredSea Mallorca-Ibiza Briefing MVP Design

## Purpose

Build a simple, useful daily briefing generator for the Mallorca to Ibiza route. The MVP should help create public LinkedIn briefings first, then support private captain outreach with route-specific WhatsApp-style advice.

The product promise for the MVP is:

> PredSea tells a captain whether today's Mallorca-Ibiza crossing is earlier, later, rougher, or fuel-heavier than standard apps imply.

## Scope

The first version focuses on one route: Mallorca to Ibiza, with special attention to the Ibiza Channel.

The MVP produces two text outputs from the same data snapshot:

- A polished LinkedIn briefing for public authority-building.
- A screenshot-ready WhatsApp conversation script for LinkedIn posts.
- A concise WhatsApp briefing for direct captain advice.

The first version does not include a chat interface, a web app, notifications, account management, or global-app comparison. Those can come later once the briefing itself proves useful.

## Data Sources

The MVP uses data sources that already work in the local prototype.

SOCIB public observations provide the "now":

- Canal de Ibiza buoy for wave height, water temperature, salinity, and sea-level pressure.
- Pollença station as a secondary Balearic reference point for pressure and water temperature.

Copernicus Marine forecasts provide the "next 24 hours":

- Mediterranean waves: `cmems_mod_med_wav_anfc_4.2km_PT1H-i`
- Mediterranean surface currents: `cmems_mod_med_phy-cur_anfc_4.2km-2D_PT1H-m`

SOCIB WMOP/SAPO remain a planned upgrade. WMOP is stronger for ocean circulation and currents; SAPO is the better SOCIB path for local wave forecasts. They should be added after the first briefing workflow is working end to end.

## Architecture

Keep the first version as a command-line tool:

```bash
python briefing.py
```

The tool has four small responsibilities:

1. Fetch or load current SOCIB observations.
2. Ensure the Copernicus forecast files exist for the next 24 hours.
3. Build a route snapshot with normalized values.
4. Render LinkedIn and WhatsApp briefing text.

The important boundary is the route snapshot. Briefings should not read raw APIs or NetCDF files directly. They should consume a simple structured object so the same snapshot can later power question answering.

## Data Flow

1. `socib_public.py` fetches current public observations.
2. `fetch_data.py` downloads bounded Copernicus NetCDF files into `mvp_data/`.
3. A new route analysis module reads the forecast files with `xarray`.
4. The analysis extracts simple route-relevant values:
   - current wave height now
   - forecast wave range over 24 hours
   - hour of most notable wave increase
   - current speed estimate in the Ibiza Channel
   - broad crossing-window recommendation
5. The system writes:
   - `mvp_data/daily_snapshot.json`
   - `mvp_data/briefing_linkedin.txt`
   - `mvp_data/briefing_whatsapp_screenshot_script.txt`
   - `mvp_data/briefing_whatsapp.txt`

## Briefing Rules

Rules should be intentionally simple and explainable.

Examples:

- If forecast wave height rises materially later in the day, recommend the earlier window.
- If waves stay low and stable, call the crossing manageable.
- If current speed increases later in the day, mention fuel and comfort risk rather than only safety.
- If live observations and forecast disagree, lower confidence and say why.

The text should avoid overclaiming. Use phrases like "captain's read", "watch-out", and "confidence" rather than pretending to be a certified navigation system.

## LinkedIn Screenshot Format

For public LinkedIn posts, the MVP should produce a short WhatsApp-style conversation script that can be passed to an LLM or image generator to create an illustrative screenshot.

The screenshot script should show a realistic product moment:

- The captain asks a practical route question.
- PredSea answers with current conditions, forecast trend, recommended crossing window, watch-out, and confidence.
- The tone is professional, calm, and concise.

The generated screenshot should be framed as an illustrative product example, not as a real private conversation with an actual captain. This keeps the LinkedIn content credible while still showing the product in the format customers will intuitively understand.

## Future Q&A

The MVP should be shaped so later questions can use the same route snapshot, for example:

- "How will the sea be in Ibiza in 4 hours?"
- "What is the best time to leave Palma for Ibiza?"
- "Will the afternoon be bumpier than the morning?"

The later Q&A layer should not scrape raw data again for every answer. It should query the saved snapshot first, then refresh data only when the snapshot is stale.

## Error Handling

If SOCIB observations fail, the briefing should still render using forecast data and clearly mark confidence as low.

If Copernicus forecast download fails, the briefing should still render a "now-only" update and explain that the forecast layer is unavailable.

If both fail, the tool should produce no briefing and print a clear error.

## Testing

Use `unittest` for this prototype, matching the existing local tests.

Test coverage should include:

- SOCIB public endpoint selection.
- Copernicus forecast download call shape.
- Snapshot generation from sample or mocked values.
- LinkedIn and WhatsApp renderers producing the expected sections.
- Graceful output when one data source is unavailable.

## Acceptance Criteria

The MVP is ready when:

- Running `python briefing.py` produces LinkedIn and WhatsApp text files.
- The output mentions Mallorca-Ibiza, current conditions, next-24-hour trend, advice, and confidence.
- The LinkedIn assets include a WhatsApp-style screenshot script suitable for image generation.
- The tool can run without manual editing.
- The generated JSON snapshot is structured enough to support future Q&A.
- The tests pass.
