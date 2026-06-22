from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HUMANINTHELOOP_DIR = PROJECT_ROOT / "humanintheloop"
if str(HUMANINTHELOOP_DIR) not in sys.path:
    sys.path.insert(0, str(HUMANINTHELOOP_DIR))

# Intentamos cargar dependencias científicas oficiales
try:
    import copernicusmarine
    import xarray as xr
except ImportError as e:
    print(f"Warning: Scientific dependencies missing ({e}). Copernicus download might fail.")

from api.warnings_service import BIGQUERY_SCOPE, query_bigquery, resolve_env


def main(argv=None):
    parser = argparse.ArgumentParser(description="Ingest historical observations directly from Copernicus and EMODnet.")
    parser.add_argument("--project", default=resolve_env("PREDSEA_BIGQUERY_PROJECT", "GOOGLE_CLOUD_PROJECT"))
    parser.add_argument("--dataset", default=resolve_env("PREDSEA_BIGQUERY_DATASET", default="predsea_validation"))
    parser.add_argument("--table", default=resolve_env("PREDSEA_BIGQUERY_EVIDENCE_TABLE", default="evidence_rows"))
    
    # --- FIJADO: Mapeo exacto de tus variables secretas de GitHub Actions ---
    parser.add_argument("--copernicus-user", default=os.getenv("COPERNICUSMARINE_SERVICE_USERNAME"))
    parser.add_argument("--copernicus-pwd", default=os.getenv("COPERNICUSMARINE_SERVICE_PASSWORD"))
    
    parser.add_argument("--start-date", default=os.getenv("START_DATE", "2019-01-01"))
    parser.add_argument("--end-date", default=os.getenv("END_DATE", "2025-01-01"))
    args = parser.parse_args(argv)

    if not args.project:
        raise SystemExit("Missing BigQuery project identifier.")

    print(f"🚀 Starting Extraction Pipeline: {args.start_date} to {args.end_date}")

    # --- 1. EXTRACCIÓN DESDE EMODNET (ERDDAP API - Pública sin credenciales) ---
    try:
        download_emodnet_data(args)
    except Exception as e:
        print(f"❌ Error downloading from EMODnet: {e}")

    # --- 2. EXTRACCIÓN DESDE COPERNICUS MARINE (Usando tus credenciales fijadas) ---
    if args.copernicus_user and args.copernicus_pwd:
        try:
            download_copernicus_data(args)
        except Exception as e:
            print(f"❌ Error downloading from Copernicus: {e}")
    else:
        print("⚠️ Skipping Copernicus: COPERNICUSMARINE_SERVICE_USERNAME or PASSWORD env variables are empty.")

    return 0


def download_emodnet_data(args):
    print("📡 Querying EMODnet Physics Open API (ERDDAP)...")
    base_url = "https://erddap.emodnet-physics.eu/erddap/tabledap/EP_ERD_INT_RV_NRT.csv"
    
    query_url = (
        f"{base_url}?platform_code,time,sea_water_temperature"
        f"&time>={args.start_date}T00:00:00Z"
        f"&time<={args.end_date}T00:00:00Z"
        f"&latitude>=38.0&latitude<=43.0&longitude>=0.0&longitude<=6.0"
    )
    
    print(f"Fetching CSV chunk via pandas from: {query_url}")
    df = pd.read_csv(query_url, skiprows=[1])
    
    rows_to_insert = []
    for _, row in df.dropna(subset=["sea_water_temperature"]).iterrows():
        rows_to_insert.append({
            "record_type": "observation",
            "source_system": "emodnet",
            "source_label": "emodnet_physics",
            "station_id": str(row["platform_code"]),
            "station_name": f"EMODnet Station {row['platform_code']}",
            "variable": "water_temperature",
            "units": "degrees_C",
            "sample_time_utc": pd.to_datetime(row["time"]).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "value": float(row["sea_water_temperature"]),
            "status": "validated"
        })

    if rows_to_insert:
        upload_to_evidence_rows(args, rows_to_insert)


def download_copernicus_data(args):
    print("📡 Querying Copernicus Marine In-Situ Near-Real-Time Observations...")
    dataset_id = "cmems_obs-ins_med_phy-bgc_nrt_ir_0.1deg_PT1H" 
    
    copernicusmarine.login(username=args.copernicus_user, password=args.copernicus_pwd)
    output_filename = "copernicus_temp.nc"
    
    copernicusmarine.subset(
        dataset_id=dataset_id,
        variables=["TEMP"],
        start_datetime=f"{args.start_date}T00:00:00",
        end_datetime=f"{args.end_date}T00:00:00",
        output_directory=".",
        output_filename=output_filename,
        force_download=True
    )
    
    print("📖 Parsing Copernicus NetCDF File via XArray...")
    ds = xr.open_dataset(output_filename)
    df = ds.to_dataframe().reset_index()
    
    rows_to_insert = []
    for _, row in df.dropna(subset=["TEMP"]).iterrows():
        rows_to_insert.append({
            "record_type": "observation",
            "source_system": "copernicus",
            "source_label": "cmems_insitu",
            "station_id": str(row.get("PLATFORM_CODE", "copernicus_station")),
            "station_name": str(row.get("PLATFORM_NAME", "Copernicus Buoy")),
            "variable": "water_temperature",
            "units": "degrees_C",
            "sample_time_utc": pd.to_datetime(row["TIME"]).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "value": float(row["TEMP"]),
            "status": "validated"
        })
        
    if rows_to_insert:
        upload_to_evidence_rows(args, rows_to_insert)
    
    if os.path.exists(output_filename):
        os.remove(output_filename)


def upload_to_evidence_rows(args, rows, batch_size=500):
    print(f"📥 Streaming {len(rows)} raw entries into BigQuery `{args.project}.{args.dataset}.{args.table}`...")
    
    try:
        import google.auth
        from google.auth.transport.requests import AuthorizedSession
    except ImportError as error:
        raise RuntimeError(f"Unable to load Google auth helpers: {error}")

    creds, _ = google.auth.default(scopes=[BIGQUERY_SCOPE])
    session = AuthorizedSession(creds)
    
    url = f"https://bigquery.googleapis.com/bigquery/v2/projects/{args.project}/datasets/{args.dataset}/tables/{args.table}/insertAll"
    
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        payload = {
            "skipInvalidRows": False,
            "ignoreUnknownValues": True,
            "rows": [{"json": row} for row in batch],
        }
        response = session.post(url, json=payload)
        response.raise_for_status()
    print("✅ Ingestion batch uploaded successfully.")


if __name__ == "__main__":
    raise SystemExit(main())
