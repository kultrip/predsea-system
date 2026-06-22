import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HUMANINTHELOOP_DIR = PROJECT_ROOT / "humanintheloop"
if str(HUMANINTHELOOP_DIR) not in sys.path:
    sys.path.insert(0, str(HUMANINTHELOOP_DIR))

# Usamos las librerías oficiales ya instaladas en tu runner
try:
    import copernicusmarine
    import xarray as xr
except ImportError as e:
    print(f"Missing scientific dependencies: {e}. Ensure requirements.txt is installed.")

from api.warnings_service import query_bigquery, bigquery_session, resolve_env


def main():
    parser = argparse.ArgumentParser(description="Ingest 5-year historical observations directly from Copernicus and EMODnet.")
    parser.add_argument("--project", default=resolve_env("PREDSEA_BIGQUERY_PROJECT", "GOOGLE_CLOUD_PROJECT"))
    parser.add_argument("--dataset", default=resolve_env("PREDSEA_BIGQUERY_DATASET", default="predsea_validation"))
    parser.add_argument("--table", default=resolve_env("PREDSEA_BIGQUERY_EVIDENCE_TABLE", default="evidence_rows"))
    # Credenciales de Copernicus (Debes setearlas en los Secrets de tu GitHub Actions)
    parser.add_argument("--copernicus-user", default=os.getenv("COPERNICUS_MARINE_USER"))
    parser.add_argument("--copernicus-pwd", default=os.getenv("COPERNICUS_MARINE_PASSWORD"))
    args = parser.parse_args()

    # Calcular la ventana de 5 años hacia atrás
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=5 * 365)
    
    print(f"🚀 Starting External Ingestion Pipeline for window: {start_date.date()} to {end_date.date()}")

    # --- 1. EXTRACCIÓN DESDE COPERNICUS MARINE ---
    if args.copernicus_user and args.copernicus_pwd:
        try:
            download_copernicus_data(args, start_date, end_date)
        except Exception as e:
            print(f"❌ Error downloading from Copernicus: {e}")
    else:
        print("⚠️ Skipping Copernicus: COPERNICUS_MARINE_USER or PASSWORD secrets not set.")

    # --- 2. EXTRACCIÓN DESDE EMODNET (Via ERDDAP / API Abierta) ---
    try:
        download_emodnet_data(args, start_date, end_date)
    except Exception as e:
        print(f"❌ Error downloading from EMODnet: {e}")


def download_copernicus_data(args, start_date, end_date):
    print("📡 Querying Copernicus Marine In-Situ Near-Real-Time Observations...")
    
    # ID del Dataset oficial de Copernicus para observaciones In-Situ en el Mediterráneo
    dataset_id = "cmems_obs-ins_med_phy-bgc_nrt_ir_0.1deg_PT1H" 
    
    # login oficial con el SDK instalado
    copernicusmarine.login(username=args.copernicus_user, password=args.copernicus_pwd)
    
    # Descargamos el subset en un archivo temporal NetCDF (.nc)
    output_filename = "copernicus_temp.nc"
    
    copernicusmarine.subset(
        dataset_id=dataset_id,
        variables=["TEMP", "VHM0"],  # Temperatura del agua y altura de ola
        start_datetime=start_date.strftime("%Y-%m-%dT%H:%M:%S"),
        end_datetime=end_date.strftime("%Y-%m-%dT%H:%M:%S"),
        output_directory=".",
        output_filename=output_filename,
        force_download=True
    )
    
    print("📖 Parsing Copernicus NetCDF File via XArray...")
    ds = xr.open_dataset(output_filename)
    df = ds.to_dataframe().reset_index()
    
    # Transformamos el dataframe al esquema plano de tu 'evidence_rows'
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
            "sample_time_utc": row["TIME"].strftime("%Y-%m-%dT%H:%M:%SZ"),
            "value": float(row["TEMP"]),
            "status": "validated"
        })
        
    if rows_to_insert:
        upload_to_evidence_rows(args, rows_to_insert)
    
    # Limpieza
    if os.path.exists(output_filename):
        os.remove(output_filename)


def download_emodnet_data(args, start_date, end_date):
    print("📡 Querying EMODnet Physics Open API (ERDDAP)...")
    
    # EMODnet expone un servidor ERDDAP estándar donde podemos pedir archivos CSV directos
    base_url = "https://erddap.emodnet-physics.eu/erddap/tabledap/EP_ERD_INT_RV_NRT.csv"
    
    # Construimos los filtros de la query de los últimos 5 años para el mar Balear/Mediterráneo
    query_url = (
        f"{base_url}?platform_code,time,sea_water_temperature"
        f"&time>={start_date.strftime('%Y-%m-%dT%H:%M:%SZ')}"
        f"&time<={end_date.strftime('%Y-%m-%dT%H:%M:%SZ')}"
        f"&latitude>=38.0&latitude<=43.0&longitude>=0.0&longitude<=6.0" # Tu zona de interés
    )
    
    print(f"Downloading EMODnet chunk via pandas from: {query_url}")
    df = pd.read_csv(query_url, skiprows=[1]) # Saltamos la línea de unidades de ERDDAP
    
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


def upload_to_evidence_rows(args, rows, batch_size=500):
    print(f"📥 Streaming {len(rows)} raw entries into BigQuery `{args.project}.{args.dataset}.{args.table}`...")
    session = bigquery_session()
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
    print("✅ Batch uploaded successfully.")


if __name__ == "__main__":
    main()
