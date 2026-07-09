import os
import sys
from datetime import datetime, timezone, timedelta
import pandas as pd
import copernicusmarine

def fetch_copernicus_insitu_bundle(dry_run=False, lookback_hours=36):
    """
    Fetches real-time in-situ waves (VHM0) and temperatures (TEMP) for France, Italy, 
    and the broader Western Mediterranean from Copernicus Marine.
    """
    # 1. Bounding box coordinates for France & Italy nested grid (the entire Western Med)
    lat_min, lat_max = 35.0, 45.0
    lon_min, lon_max = -2.0, 16.0

    # 2. Time range (lookback_hours to now)
    now = datetime.now(timezone.utc)
    start_time = now - timedelta(hours=lookback_hours)

    # 3. Handle dry run
    if dry_run:
        return {
            "source": "copernicus_insitu",
            "available": True,
            "observations": {},
            "measurements": {},
            "stations": [],
            "errors": {},
            "lineage": {"source": "copernicus_insitu", "status": "dry_run"}
        }

    observations = {}
    measurements = {}
    stations = {}
    errors = {}

    try:
        # Retrieve credentials
        user = os.getenv("COPERNICUS_USERNAME") or os.getenv("COPERNICUS_MARINE_USER") or "charles.santana"
        pwd = os.getenv("COPERNICUS_PASSWORD") or os.getenv("COPERNICUS_MARINE_PASSWORD")
        if user and pwd:
            copernicusmarine.login(username=user, password=pwd, force_service_selection=True)

        print(f"📡 Downloading Copernicus In-Situ MED observations from {start_time.isoformat()} to {now.isoformat()}...")
        df = copernicusmarine.read_dataframe(
            dataset_id="cmems_obs-ins_med_phybgcwav_mynrt_na_irr",
            variables=["TEMP", "VHM0"],
            minimum_longitude=lon_min,
            maximum_longitude=lon_max,
            minimum_latitude=lat_min,
            maximum_latitude=lat_max,
            start_datetime=start_time.strftime("%Y-%m-%dT%H:%M:%S"),
            end_datetime=now.strftime("%Y-%m-%dT%H:%M:%S"),
        )

        if df is None or df.empty:
            print("⚠️ No observations returned from Copernicus.")
            return {
                "source": "copernicus_insitu",
                "available": False,
                "observations": {},
                "measurements": {},
                "stations": [],
                "errors": {},
                "lineage": {"source": "copernicus_insitu", "status": "empty"}
            }

        # Format rows into canonical records
        for _, row in df.iterrows():
            platform_id = str(row.get("platform_id"))
            if not platform_id or platform_id == "nan":
                continue

            station_id = f"copernicus_insitu_{platform_id.lower()}"
            var_name = row.get("variable")
            val = row.get("value")
            if pd.isna(val):
                continue

            raw_key = None
            variable = None
            units = None

            if var_name == "TEMP":
                raw_key = "water_temp_c"
                variable = "water_temperature"
                units = "celsius"
            elif var_name == "VHM0":
                raw_key = "wave_height_m"
                variable = "wave_height"
                units = "m"
            else:
                continue

            # Parse time
            time_str = str(row.get("time"))
            try:
                observed_at = pd.to_datetime(time_str).tz_localize(timezone.utc).isoformat()
            except Exception:
                observed_at = time_str

            latitude = float(row.get("latitude"))
            longitude = float(row.get("longitude"))
            depth = float(row.get("depth")) if not pd.isna(row.get("depth")) else 0.0

            measurement_item = {
                "provider": "copernicus_insitu",
                "source_system": "copernicus_insitu",
                "source_label": "Copernicus In-Situ",
                "network": "copernicus_insitu",
                "station_kind": "platform",
                "station_type": "platform",
                "station_id": station_id,
                "station_name": platform_id,
                "latitude": latitude,
                "longitude": longitude,
                "depth_m": depth,
                "catalog_url": "https://marine.copernicus.eu",
                "dataset_url": "https://marine.copernicus.eu",
                "sample_time_utc": observed_at,
                "observed_at_utc": observed_at,
                "source_time_coordinate_utc": observed_at,
                "freshness_status": "live",
                "freshness_state": "LIVE",
                "quality_score": 1.0,
                "qc_flag": int(row.get("value_qc")) if not pd.isna(row.get("value_qc")) else 1,
                "is_future": False,
                "is_future_timestamp": False,
                "is_qc_good": True,
                "raw_key": raw_key,
                "source_field": var_name,
                "variable": variable,
                "value": float(val),
                "units": units,
            }

            if station_id not in observations:
                observations[station_id] = {
                    "provider": "copernicus_insitu",
                    "source_system": "copernicus_insitu",
                    "source_label": "Copernicus In-Situ",
                    "network": "copernicus_insitu",
                    "station_id": station_id,
                    "station_name": platform_id,
                    "station_kind": "platform",
                    "station_type": "platform",
                    "latitude": latitude,
                    "longitude": longitude,
                    "depth_m": depth,
                    "catalog_url": "https://marine.copernicus.eu",
                    "dataset_url": "https://marine.copernicus.eu",
                    "sample_time_utc": observed_at,
                    "observed_at_utc": observed_at,
                    "source_time_coordinate_utc": observed_at,
                    "freshness_status": "live",
                    "freshness_state": "LIVE",
                    "quality_score": 1.0,
                    "qc_flag": 1,
                    "is_future": False,
                    "is_future_timestamp": False,
                    "is_qc_good": True,
                    "nearest_routes": [],
                    "distance_to_route_nm": None,
                    "measurements": [],
                }
                measurements[station_id] = []

            # Store flat attribute + nested measurements
            observations[station_id][raw_key] = float(val)
            observations[station_id]["measurements"].append(measurement_item)
            measurements[station_id].append(measurement_item)

            stations[station_id] = {
                "provider": "copernicus_insitu",
                "network": "copernicus_insitu",
                "station_id": station_id,
                "station_name": platform_id,
                "station_kind": "platform",
                "priority": "normal",
                "latitude": latitude,
                "longitude": longitude,
                "depth_m": depth,
                "variables_supported": sorted(list({m["variable"] for m in observations[station_id]["measurements"]})),
                "nearest_routes": [],
                "distance_to_route_nm": None,
                "distance_to_palma": None,
                "distance_to_ibiza": None,
                "distance_to_menorca": None,
                "source_label": "Copernicus In-Situ",
                "catalog_url": "https://marine.copernicus.eu",
                "dataset_url": "https://marine.copernicus.eu",
                "last_sample_utc": observed_at,
            }

        print(f"✅ Successfully loaded {len(observations)} stations from Copernicus In-Situ MED.")

    except Exception as e:
        print(f"❌ Error fetching Copernicus in-situ observations: {e}")
        errors["copernicus_insitu"] = str(e)

    return {
        "source": "copernicus_insitu",
        "available": bool(observations),
        "observations": observations,
        "measurements": measurements,
        "stations": sorted(stations.values(), key=lambda r: r.get("station_name", "")),
        "errors": errors,
        "lineage": {"source": "copernicus_insitu", "status": "completed" if not errors else "error"}
    }
