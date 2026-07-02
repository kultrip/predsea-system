#!/usr/bin/env python3
"""
scripts/model_comparison.py
Compares PredSea's own high-resolution model output (WRF wind, ROMS currents/water
temperature/sea level, SWAN waves) against real buoy/tide-gauge observations already
ingested into BigQuery `evidence_rows`, to see whether the own model is actually more
accurate than the CMEMS/AROME baseline it hopes to eventually replace.

IMPORTANT HISTORY: the previous version of this script fabricated its input data --
it generated synthetic observation/CMEMS/own-model values with `np.random.seed(42)`
and deliberately gave the "own model" a smaller error term than CMEMS, guaranteeing a
near-universal win before any real data was touched. That is why
`humanintheloop/hpc_cost_summary.json`'s "12/12 wins, proceed_to_production" claim was
not a measurement.

This version only ever reports a result when it finds real, time-matched
forecast/observation pairs in BigQuery. If it can't find enough real data (e.g.
because no real WRF/ROMS/SWAN run has been ingested yet, or no nearby buoy has
recent data), it says so explicitly in the output instead of inventing a number.

Matching approach:
1. Pull real forecast rows for our own models (provider in predsea_wrf/predsea_roms/
   predsea_swan) for the target date, including their sampling latitude/longitude
   (added to the ingestors in scripts/*_forecast_ingestor.py on 2026-07-02 -- older
   forecast rows ingested before that fix won't have coordinates and are skipped).
2. Pull the real, currently-known observation station catalog (BigQuery
   `station_metadata`) and, for each distinct forecast sampling point, find the
   nearest real station within --max-station-distance-nm. Forecast sampling points
   are place/route waypoints, not buoy IDs, so this nearest-neighbour match is
   required -- there is no shared ID space to join on directly.
3. Pull real observation rows for the matched stations and pair each forecast value
   with the nearest-in-time real observation within --time-tolerance-minutes.
4. Compute RMSE/bias/correlation/MAE on those real pairs only, with a minimum sample
   size per variable before it counts towards the win/loss summary.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

SCRIPTS_DIR = Path(__file__).resolve().parent
HUMANINTHELOOP_DIR = SCRIPTS_DIR.parent
if str(HUMANINTHELOOP_DIR) not in sys.path:
    sys.path.insert(0, str(HUMANINTHELOOP_DIR))

import route_analysis  # noqa: E402  (for haversine_nm)

BUCKET_NAME = "predsea-hpc-outputs"

DEFAULT_MAX_STATION_DISTANCE_NM = 25.0
DEFAULT_TIME_TOLERANCE_MINUTES = 30
DEFAULT_MIN_SAMPLE_SIZE = 5

# Maps each own-model forecast variable to the CMEMS-family equivalent it's meant to
# beat and to the real observation `variable` string it should be checked against.
# Observation variable names come from the canonical schema used by the Puertos del
# Estado and EMODnet Physics connectors (see
# humanintheloop/predsea/connectors/emodnet_physics/etl.py) -- NOT from this script.
COMPARISON_VARIABLES = {
    "wind_speed":        {"own_provider": "predsea_wrf",  "cmems_equivalent": "arome_1km",  "obs_variable": "wind_speed",        "units": "knots"},
    "wind_direction":    {"own_provider": "predsea_wrf",  "cmems_equivalent": "arome_1km",  "obs_variable": "wind_direction",    "units": "degree"},
    "current_speed":     {"own_provider": "predsea_roms", "cmems_equivalent": "cmems_nemo", "obs_variable": "current_speed",     "units": "m/s"},
    "water_temperature": {"own_provider": "predsea_roms", "cmems_equivalent": "cmems_nemo", "obs_variable": "water_temperature", "units": "celsius"},
    "sea_level":         {"own_provider": "predsea_roms", "cmems_equivalent": "cmems_nemo", "obs_variable": "sea_level",         "units": "m"},
    "wave_height":       {"own_provider": "predsea_swan", "cmems_equivalent": "cmems_swan", "obs_variable": "wave_height",       "units": "m"},
    "wave_direction":    {"own_provider": "predsea_swan", "cmems_equivalent": "cmems_swan", "obs_variable": "wave_direction",    "units": "degree"},
}


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Compare real own-model (WRF/ROMS/SWAN) forecasts against real buoy observations."
    )
    parser.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"), help="Evaluation target date (YYYY-MM-DD)")
    parser.add_argument("--lookback-days", type=int, default=1, help="How many days of forecast/observation history to include, ending on --date.")
    parser.add_argument("--project", help="GCP project ID (defaults to active gcloud/ADC project).")
    parser.add_argument("--dataset", default="predsea_validation", help="BigQuery dataset containing evidence_rows / station_metadata.")
    parser.add_argument("--evidence-table", default="evidence_rows", help="BigQuery table with forecast and observation rows.")
    parser.add_argument("--station-table", default="station_metadata", help="BigQuery table with the real observation station catalog.")
    parser.add_argument("--max-station-distance-nm", type=float, default=DEFAULT_MAX_STATION_DISTANCE_NM, help="Max distance to accept a forecast<->station match.")
    parser.add_argument("--time-tolerance-minutes", type=int, default=DEFAULT_TIME_TOLERANCE_MINUTES, help="Max time gap to accept a forecast<->observation match.")
    parser.add_argument("--min-sample-size", type=int, default=DEFAULT_MIN_SAMPLE_SIZE, help="Minimum real matched pairs required before a variable counts in the summary.")
    parser.add_argument("--no-upload", action="store_true", help="Skip uploading the report to GCS (still writes it locally). Useful for local runs/tests.")
    parser.add_argument("--output", default="accuracy_comparison.json", help="Local path to write the report JSON to.")
    return parser.parse_args(argv)


def compute_metrics(model_vals, obs_vals):
    """RMSE / bias / correlation / MAE over real matched pairs. Unchanged math from
    the original script -- only the data feeding it was ever fabricated."""
    model_vals = np.asarray(model_vals, dtype=float)
    obs_vals = np.asarray(obs_vals, dtype=float)

    mask = ~np.isnan(model_vals) & ~np.isnan(obs_vals)
    sample_size = int(np.sum(mask))
    if sample_size < 2:
        return None

    m = model_vals[mask]
    o = obs_vals[mask]
    errors = m - o

    rmse = float(np.sqrt(np.mean(errors ** 2)))
    bias = float(np.mean(errors))
    mae = float(np.mean(np.abs(errors)))

    std_m, std_o = np.std(m), np.std(o)
    correlation = float(np.corrcoef(m, o)[0, 1]) if std_m > 0 and std_o > 0 else None

    return {
        "rmse": round(rmse, 4),
        "bias": round(bias, 4),
        "correlation": round(correlation, 4) if correlation is not None else None,
        "mae": round(mae, 4),
        "sample_size": sample_size,
    }


def _bigquery_client(project_id):
    from google.cloud import bigquery
    return bigquery.Client(project=project_id)


def fetch_forecast_rows(client, project_id, dataset, table, target_date, lookback_days):
    """Real forecast rows for our own models, with sampling lat/lon.

    Requires the ingestor fix (2026-07-02) that adds `latitude`/`longitude` to every
    forecast row in scripts/wrf_forecast_ingestor.py, roms_forecast_ingestor.py, and
    swan_forecast_ingestor.py. Forecast rows ingested before that fix won't have
    coordinates and are filtered out here rather than guessed at.
    """
    from google.cloud import bigquery

    providers = sorted({cfg["own_provider"] for cfg in COMPARISON_VARIABLES.values()})
    table_ref = f"{project_id}.{dataset}.{table}"
    query = f"""
        SELECT
          variable,
          provider,
          reference_station_id,
          reference_station_name,
          value,
          target_time_utc,
          latitude,
          longitude
        FROM `{table_ref}`
        WHERE record_type = 'forecast'
          AND provider IN UNNEST(@providers)
          AND target_time_utc >= TIMESTAMP_SUB(TIMESTAMP(@target_date), INTERVAL @lookback_days DAY)
          AND target_time_utc < TIMESTAMP_ADD(TIMESTAMP(@target_date), INTERVAL 1 DAY)
          AND value IS NOT NULL
          AND latitude IS NOT NULL
          AND longitude IS NOT NULL
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ArrayQueryParameter("providers", "STRING", providers),
            bigquery.ScalarQueryParameter("target_date", "DATE", target_date),
            bigquery.ScalarQueryParameter("lookback_days", "INT64", lookback_days),
        ]
    )
    return [dict(row) for row in client.query(query, job_config=job_config).result()]


def fetch_station_catalog(client, project_id, dataset, table):
    """The real, currently-known observation stations with coordinates (buoys, tide
    gauges, radar) from the shared station_metadata table -- not a hardcoded list."""
    table_ref = f"{project_id}.{dataset}.{table}"
    query = f"""
        SELECT
          station_id,
          ANY_VALUE(station_name) AS station_name,
          ANY_VALUE(provider) AS provider,
          ANY_VALUE(latitude) AS latitude,
          ANY_VALUE(longitude) AS longitude
        FROM `{table_ref}`
        WHERE latitude IS NOT NULL AND longitude IS NOT NULL AND station_id IS NOT NULL
        GROUP BY station_id
    """
    return [dict(row) for row in client.query(query).result()]


def fetch_observation_rows(client, project_id, dataset, table, station_ids, target_date, lookback_days):
    from google.cloud import bigquery

    if not station_ids:
        return []
    table_ref = f"{project_id}.{dataset}.{table}"
    query = f"""
        SELECT station_id, variable, value, observed_at_utc
        FROM `{table_ref}`
        WHERE record_type = 'observation'
          AND station_id IN UNNEST(@station_ids)
          AND observed_at_utc >= TIMESTAMP_SUB(TIMESTAMP(@target_date), INTERVAL @lookback_days DAY)
          AND observed_at_utc < TIMESTAMP_ADD(TIMESTAMP(@target_date), INTERVAL 1 DAY)
          AND value IS NOT NULL
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ArrayQueryParameter("station_ids", "STRING", sorted(station_ids)),
            bigquery.ScalarQueryParameter("target_date", "DATE", target_date),
            bigquery.ScalarQueryParameter("lookback_days", "INT64", lookback_days),
        ]
    )
    return [dict(row) for row in client.query(query, job_config=job_config).result()]


def nearest_station(lat, lon, stations, max_distance_nm):
    """Real nearest-neighbour match using route_analysis.haversine_nm -- the same
    great-circle helper already used elsewhere in this codebase (e.g. the Puertos del
    Estado station catalog's route-distance metadata)."""
    best_station, best_distance = None, None
    for station in stations:
        distance_nm = route_analysis.haversine_nm(lat, lon, station["latitude"], station["longitude"])
        if distance_nm <= max_distance_nm and (best_distance is None or distance_nm < best_distance):
            best_station, best_distance = station, distance_nm
    return best_station, best_distance


def match_forecast_points_to_stations(forecast_rows, stations, max_distance_nm):
    """Groups forecast rows by their distinct sampling point and resolves each point
    to (at most) one nearby real station. Returns forecast_rows annotated with
    matched_station_id/matched_station_distance_nm, and the set of matched station ids."""
    point_cache = {}
    matched_station_ids = set()
    annotated_rows = []

    for row in forecast_rows:
        point_key = (round(row["latitude"], 4), round(row["longitude"], 4))
        if point_key not in point_cache:
            station, distance_nm = nearest_station(row["latitude"], row["longitude"], stations, max_distance_nm)
            point_cache[point_key] = (station, distance_nm)
        station, distance_nm = point_cache[point_key]
        if station is None:
            continue
        matched_station_ids.add(station["station_id"])
        annotated_rows.append(
            {
                **row,
                "matched_station_id": station["station_id"],
                "matched_station_name": station.get("station_name"),
                "matched_station_distance_nm": round(distance_nm, 2),
            }
        )
    return annotated_rows, matched_station_ids


def _as_utc(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return value


def pair_forecasts_with_observations(annotated_forecast_rows, observation_rows, time_tolerance_minutes):
    """Pairs each forecast value with the nearest-in-time real observation at its
    matched station, within tolerance. Returns {variable: {"own": [...], "obs": [...],
    "stations": {...}}}."""
    tolerance = timedelta(minutes=time_tolerance_minutes)

    obs_by_key = {}
    for obs in observation_rows:
        key = (obs["station_id"], obs["variable"])
        obs_by_key.setdefault(key, []).append((_as_utc(obs["observed_at_utc"]), obs["value"]))

    pairs_by_variable = {}
    for row in annotated_forecast_rows:
        obs_variable = COMPARISON_VARIABLES.get(row["variable"], {}).get("obs_variable")
        if not obs_variable:
            continue
        candidates = obs_by_key.get((row["matched_station_id"], obs_variable))
        if not candidates:
            continue

        target_time = _as_utc(row["target_time_utc"])
        best_value, best_delta = None, None
        for obs_time, obs_value in candidates:
            delta = abs(obs_time - target_time)
            if delta <= tolerance and (best_delta is None or delta < best_delta):
                best_value, best_delta = obs_value, delta
        if best_value is None:
            continue

        bucket = pairs_by_variable.setdefault(row["variable"], {"own": [], "obs": [], "stations": set()})
        bucket["own"].append(row["value"])
        bucket["obs"].append(best_value)
        bucket["stations"].add(row["matched_station_id"])

    return pairs_by_variable


def build_comparison_report(pairs_by_variable, min_sample_size, target_date):
    report = {
        "evaluation_date": target_date,
        "data_source": "real",
        "variables": {},
    }
    better_count, total_count = 0, 0

    for variable, cfg in COMPARISON_VARIABLES.items():
        bucket = pairs_by_variable.get(variable)
        if not bucket:
            report["variables"][variable] = {
                "own_model_provider": cfg["own_provider"],
                "cmems_equivalent": cfg["cmems_equivalent"],
                "units": cfg["units"],
                "status": "no_real_matched_pairs",
            }
            continue

        metrics = compute_metrics(bucket["own"], bucket["obs"])
        if metrics is None or metrics["sample_size"] < min_sample_size:
            report["variables"][variable] = {
                "own_model_provider": cfg["own_provider"],
                "cmems_equivalent": cfg["cmems_equivalent"],
                "units": cfg["units"],
                "status": "insufficient_sample_size",
                "sample_size": 0 if metrics is None else metrics["sample_size"],
                "min_sample_size_required": min_sample_size,
            }
            continue

        report["variables"][variable] = {
            "own_model_provider": cfg["own_provider"],
            "cmems_equivalent": cfg["cmems_equivalent"],
            "units": cfg["units"],
            "status": "compared",
            "stations_used": sorted(bucket["stations"]),
            "metrics_own_model": metrics,
            # NOTE: there is no real CMEMS-forecast-vs-observation comparison wired up
            # yet in this script -- that requires the same real matching logic against
            # whatever provider tag your Copernicus ingestion uses. Until that's added,
            # this only reports the own model's real accuracy against real buoys, not
            # a real own-vs-CMEMS win/loss. Do not backfill "own_beats_cmems" with a
            # guess; leave it absent rather than fabricate the comparison.
        }
        total_count += 1

    report["summary"] = {
        "variables_with_real_comparison": total_count,
        "variables_total": len(COMPARISON_VARIABLES),
        "note": (
            "own_beats_cmems is intentionally not reported yet -- this version only "
            "validates the own model against real buoy observations. Comparing "
            "against a real CMEMS forecast pull is a follow-up, not something to "
            "guess at here."
        ),
    }
    return report


def main(argv=None):
    args = parse_args(argv)
    target_date = args.date

    client = _bigquery_client(args.project)
    project_id = args.project or client.project

    print(f"Fetching real own-model forecast rows for {target_date} (lookback {args.lookback_days}d)...")
    forecast_rows = fetch_forecast_rows(client, project_id, args.dataset, args.evidence_table, target_date, args.lookback_days)

    if not forecast_rows:
        report = {
            "evaluation_date": target_date,
            "data_source": "real",
            "status": "no_forecast_data",
            "message": (
                "No real WRF/ROMS/SWAN forecast rows with coordinates were found in "
                f"{project_id}.{args.dataset}.{args.evidence_table} for this window. "
                "This is expected until a real model run has been ingested via "
                "scripts/{wrf,roms,swan}_forecast_ingestor.py. Nothing was fabricated."
            ),
        }
        _write_and_maybe_upload(report, args)
        print("No real forecast data yet -- wrote an honest 'no_forecast_data' report instead of inventing one.")
        return 0

    print(f"Found {len(forecast_rows)} real forecast rows. Fetching the real observation station catalog...")
    stations = fetch_station_catalog(client, project_id, args.dataset, args.station_table)

    annotated_rows, matched_station_ids = match_forecast_points_to_stations(
        forecast_rows, stations, args.max_station_distance_nm
    )
    if not matched_station_ids:
        report = {
            "evaluation_date": target_date,
            "data_source": "real",
            "status": "no_nearby_stations",
            "message": (
                f"Found {len(forecast_rows)} real forecast rows, but none were within "
                f"{args.max_station_distance_nm} nm of a known real observation station. "
                "Widen --max-station-distance-nm or check the station catalog before "
                "concluding anything."
            ),
        }
        _write_and_maybe_upload(report, args)
        print("No nearby real stations found -- wrote an honest report instead of inventing one.")
        return 0

    print(f"Matched forecast points to {len(matched_station_ids)} real station(s). Fetching real observations...")
    observation_rows = fetch_observation_rows(
        client, project_id, args.dataset, args.evidence_table, matched_station_ids, target_date, args.lookback_days
    )

    pairs_by_variable = pair_forecasts_with_observations(annotated_rows, observation_rows, args.time_tolerance_minutes)
    report = build_comparison_report(pairs_by_variable, args.min_sample_size, target_date)

    compared = report["summary"]["variables_with_real_comparison"]
    print(f"Real comparison complete. {compared}/{len(COMPARISON_VARIABLES)} variables had enough real matched data to report.")

    _write_and_maybe_upload(report, args)
    return 0


def _write_and_maybe_upload(report, args):
    with open(args.output, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"Wrote report to {args.output}")

    if args.no_upload:
        return

    from google.cloud import storage
    client = storage.Client()
    bucket = client.bucket(BUCKET_NAME)
    blob_path = f"reports/{report['evaluation_date']}/accuracy_comparison.json"
    bucket.blob(blob_path).upload_from_filename(args.output)
    print(f"Uploaded report to gs://{BUCKET_NAME}/{blob_path}")


if __name__ == "__main__":
    sys.exit(main())
