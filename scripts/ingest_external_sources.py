from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import requests  # <-- Añadido para manejar el timeout correctamente

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HUMANINTHELOOP_DIR = PROJECT_ROOT / "humanintheloop"
if str(HUMANINTHELOOP_DIR) not in sys.path:
    sys.path.insert(0, str(HUMANINTHELOOP_DIR))

try:
    import copernicusmarine
    import xarray as xr
except ImportError as e:
    print(f"Warning: Scientific dependencies missing ({e}).")

from api.warnings_service import BIGQUERY_SCOPE, query_bigquery, resolve_env


def main(argv=None):
    parser = argparse.ArgumentParser(description="Ingest historical observations directly from Copernicus and EMODnet.")
    parser.add_argument("--project", default=resolve_env("PREDSEA_BIGQUERY_PROJECT", "GOOGLE_CLOUD_PROJECT"))
    parser.add_argument("--dataset", default=resolve_env("PREDSEA_BIGQUERY_DATASET", default="predsea_validation"))
    parser.add_argument("--table", default=resolve_env("PREDSEA_BIGQUERY_EVIDENCE_TABLE", default="evidence_rows"))
    
    user = os.getenv("COPERNICUSMARINE_SERVICE_USERNAME") or os.getenv("COPERNICUS_MARINE_USER")
    pwd = os.getenv("COPERNICUSMARINE_SERVICE_PASSWORD") or os.getenv("COPERNICUS_MARINE_PASSWORD")
    
    parser.add_argument("--copernicus-user", default=user)
    parser.add_argument("--copernicus-pwd", default=pwd)
    parser.add_argument("--start-date", default=os.getenv("START_DATE", "2019-01-01"))
    parser.add_argument("--end-date", default=os.getenv("END_DATE", "2027-01-01"))
    args = parser.parse_args(argv)

    print(f"🚀 Starting Extraction Pipeline: {args.start_date} to {args.end_date}")

    # 1. COPERNICUS (Sincronizado con tus archivos de origen)
    if args.copernicus_user and args.copernicus_pwd:
        try:
            download_copernicus_data(args)
        except Exception as e:
            print(f"❌ Error downloading from Copernicus: {e}")
    else:
        print("⚠️ Skipping Copernicus: Ingestion bypassed due to empty credentials profile.")

    # 2. EMODNET
    try:
        download_emodnet_data(args)
    except Exception as e:
        print(f"❌ Error downloading from EMODnet: {e}")

    return 0


def download_copernicus_data(args):
    print("📡 Querying Copernicus Marine In-Situ Observations...")
    # Sincronizado con WAV_ID de tus fuentes oficiales fijadas en forecast_sources.py
    dataset_id = "cmems_mod_med_wav_anfc_4.2km_PT1H-i" 
    
    copernicusmarine.login(username=args.copernicus_user, password=args.copernicus_pwd)
    output_filename = "copernicus_temp.nc"
    
    # Bounding box extraído de tus configuraciones del MVP
    copernicusmarine.subset(
        dataset_id=dataset_id,
        variables=["VHM0"],
        minimum_longitude=0.5,
        maximum_longitude=4.5,
        minimum_latitude=38.0,
        maximum_latitude=41.5,
        start_datetime=f"{args.start_date}T00:00:00",
        end_datetime=f"{args.end_date}T00:00:00",
        output_directory=".",
        output_filename=output_filename,
        file_format="netcdf",
        overwrite=True
    )
    
    if not os.path.exists(output_filename):
        print("⚠️ Copernicus subset did not generate an output file.")
        return

    ds = xr.open_dataset(output_filename)
    df = ds.to_dataframe().reset_index()
    
    rows_to_insert = []
    # Usamos VHM0 (Significant wave height) tal cual está configurado en tu Readme
    if "VHM0" in df.columns:
        for _, row in df.dropna(subset=["VHM0"]).iterrows():
            rows_to_insert.append({
                "record_type": "observation",
                "source_system": "copernicus",
                "source_label": "cmems_mod_med_wav",
                "station_id": f"grid_{row.get('latitude', 0)}_{row.get('longitude', 0)}",
                "station_name": "Copernicus Mediterranean Grid Point",
                "variable": "wave_height",
                "units": "m",
                "sample_time_utc": pd.to_datetime(row.get("time") or row.get("TIME")).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "value": float(row["VHM0"]),
                "status": "validated"
            })
        
    if rows_to_insert:
        upload_to_evidence_rows(args, rows_to_insert)
    
    if os.path.exists(output_filename):
        os.remove(output_filename)


def download_emodnet_data(args):
    print("📡 Querying EMODnet Physics Open API (ERDDAP) for Moorings Stations...")
    # CAMBIADO: Usamos el dataset oficial de estaciones fijas (Moorings)
    base_url = "https://erddap.emodnet-physics.eu/erddap/tabledap/EP_ERD_INT_MO_NRT.csv"
    
    start_year = int(args.start_date.split("-")[0])
    end_year = int(args.end_date.split("-")[0])
    
    # Delimitamos geográficamente la consulta a la zona del MVP de PredSea para evitar errores 400
    # Longitudes: 0.5 a 4.5 E | Latitudes: 38.0 a 41.5 N
    geo_filter = "&latitude>=38.0&latitude<=41.5&longitude>=0.5&longitude<=4.5"
    
    for year in range(start_year, end_year):
        print(f"⏳ Querying Mooring records for year: {year}...")
        
        # Estructuramos la URL pidiendo solo lo necesario del recuadro Balear
        query_url = (
            f"{base_url}?platform_code,time,latitude,longitude,sea_water_temperature"
            f"&time>={year}-01-01T00:00:00Z"
            f"&time<={year}-12-31T23:59:59Z"
            f"{geo_filter}"
        )
        
        try:
            # Hacemos la petición con un timeout prudencial
            response = requests.get(query_url, timeout=45)
            
            # Si el servidor responde 404 o no hay datos en ese año/zona, pasamos al siguiente de forma segura
            if response.status_code == 404:
                print(f"ℹ️ No Mooring records found for year {year} in the Balearic box.")
                continue
                
            response.raise_for_status()
            
            from io import StringIO
            csv_data = StringIO(response.text)
            
            # Saltamos la segunda fila que ERDDAP usa para las unidades de texto
            df = pd.read_csv(csv_data, skiprows=[1])
            
            rows_to_insert = []
            for _, row in df.dropna(subset=["sea_water_temperature"]).iterrows():
                rows_to_insert.append({
                    "record_type": "observation",
                    "source_system": "emodnet",
                    "source_label": "emodnet_mooring",
                    "station_id": f"emod_{str(row['platform_code'])}",
                    "station_name": f"EMODnet Mooring Bouy {row['platform_code']}",
                    "variable": "water_temperature",
                    "units": "degrees_C",
                    "sample_time_utc": pd.to_datetime(row["time"]).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "latitude": float(row["latitude"]) if pd.notna(row.get("latitude")) else None,
                    "longitude": float(row["longitude"]) if pd.notna(row.get("longitude")) else None,
                    "value": float(row["sea_water_temperature"]),
                    "status": "validated"
                })

            if rows_to_insert:
                upload_to_evidence_rows(args, rows_to_insert)
                print(f"✅ Successfully ingested {len(rows_to_insert)} entries for year {year}.")
                
        except Exception as chunk_error:
            print(f"⚠️ Chunk {year} omitted due to API connection issue: {chunk_error}")
            continue


def upload_to_evidence_rows(args, rows, batch_size=500):
    print(f"📥 Streaming {len(rows)} raw entries to BigQuery...")
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
