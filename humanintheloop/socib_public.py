import requests
from datetime import datetime, timezone

# This public DataDiscovery endpoint does NOT require an API key.
PUBLIC_URL = "https://apps.socib.es/DataDiscovery/list-moorings"
TARGET_PLATFORMS = {
    143: "Bahia de Palma Buoy",
    146: "Canal de Ibiza Buoy",
    512: "Porto Colom Buoy",
    14: "Pollença Station",
}
OBSERVATION_KEYS = {
    143: "bahia_de_palma",
    146: "canal_de_ibiza",
    512: "porto_colom",
    14: "pollensa",
}
TARGET_VARIABLES = {
    "sea_surface_wave_significant_height": "Wave Height",
    "sea_surface_wave_from_direction": "Wave From Direction",
    "sea_water_temperature": "Water Temp",
    "sea_water_practical_salinity": "Salinity",
    "air_pressure": "Air Pressure",
    "air_pressure_at_sea_level": "Sea-level Pressure",
}
NUMERIC_VARIABLES = {
    "sea_surface_wave_significant_height": "wave_height_m",
    "sea_surface_wave_from_direction": "wave_from_direction_deg",
    "sea_water_temperature": "water_temp_c",
    "sea_water_practical_salinity": "salinity_psu",
    "air_pressure": "air_pressure_hpa",
    "air_pressure_at_sea_level": "sea_level_pressure_hpa",
}


def format_timestamp(epoch_seconds):
    if not epoch_seconds:
        return "N/A"
    timestamp = datetime.fromtimestamp(epoch_seconds, tz=timezone.utc)
    return timestamp.strftime("%Y-%m-%d %H:%M UTC")


def important_values(platform):
    values = []
    for instrument in platform.get("jsonInstrumentList", []):
        for variable in instrument.get("jsonVariableList", []):
            standard_name = variable.get("standardName")
            if standard_name in TARGET_VARIABLES:
                values.append((TARGET_VARIABLES[standard_name], variable.get("lastSampleValue", "N/A")))
    return values

def get_public_data():
    print("--- Fetching Public SOCIB Data (No Key Required) ---")
    try:
        response = requests.get(PUBLIC_URL, timeout=30)
        if response.status_code != 200:
            print(f"Failed to reach SOCIB DataDiscovery: {response.status_code}")
            print(response.text[:300])
            return

        platforms = {
            platform.get("id"): platform
            for platform in response.json()
            if platform.get("id") in TARGET_PLATFORMS
        }
        for platform_id, name in TARGET_PLATFORMS.items():
            data = platforms.get(platform_id)
            if not data:
                print(f"{name}: not found in SOCIB DataDiscovery response")
                continue

            print(f"{name}:")
            print(f"  > SOCIB Name: {data.get('name', 'N/A')}")
            print(f"  > Last Sample: {format_timestamp(data.get('lastTimeSampleReceived'))}")
            for label, value in important_values(data):
                    print(f"  > {label}: {value}")
    except Exception as e:
        print(f"Error: {e}")


def extract_public_observations(platforms):
    observations = {}
    for platform in platforms:
        platform_id = platform.get("id")
        key = OBSERVATION_KEYS.get(platform_id)
        if not key:
            continue

        record = {
            "name": platform.get("name", "N/A"),
            "last_sample_utc": format_timestamp(platform.get("lastTimeSampleReceived")),
        }
        for instrument in platform.get("jsonInstrumentList", []):
            for variable in instrument.get("jsonVariableList", []):
                output_key = NUMERIC_VARIABLES.get(variable.get("standardName"))
                if output_key:
                    record[output_key] = variable.get("lastValue")
        observations[key] = record
    return observations

if __name__ == "__main__":
    get_public_data()
