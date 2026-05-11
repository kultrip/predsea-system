import copernicusmarine
import datetime
import os

OUTPUT_DIR = "./mvp_data"
os.makedirs(OUTPUT_DIR, exist_ok=True)
REQUIRED_COPERNICUS_ENV = (
    "COPERNICUSMARINE_SERVICE_USERNAME",
    "COPERNICUSMARINE_SERVICE_PASSWORD",
)

# Current Copernicus Marine Mediterranean analysis/forecast dataset IDs.
PHY_ID = "cmems_mod_med_phy-cur_anfc_4.2km-2D_PT1H-m"
WAV_ID = "cmems_mod_med_wav_anfc_4.2km_PT1H-i"

# Coordinates for the Balearic Islands
# Adjusted slightly to ensure we don't hit edge-case rounding errors
lon_min, lon_max = 1.0, 4.5
lat_min, lat_max = 38.5, 40.5

# Time window
start_time = (datetime.datetime.now() - datetime.timedelta(hours=6))
end_time = (datetime.datetime.now() + datetime.timedelta(days=1))


def validate_copernicus_credentials_available():
    if os.getenv("GITHUB_ACTIONS") != "true" and os.getenv("CI") != "true":
        return
    missing = [name for name in REQUIRED_COPERNICUS_ENV if not os.getenv(name)]
    if missing:
        raise RuntimeError(
            "Missing Copernicus Marine credential environment variable(s): "
            + ", ".join(missing)
        )


def subset_balearic_forecast(dataset_id, variables, output_filename, dry_run=False):
    return copernicusmarine.subset(
        dataset_id=dataset_id,
        variables=variables,
        minimum_longitude=lon_min,
        maximum_longitude=lon_max,
        minimum_latitude=lat_min,
        maximum_latitude=lat_max,
        start_datetime=start_time,
        end_datetime=end_time,
        output_directory=OUTPUT_DIR,
        output_filename=output_filename,
        file_format="netcdf",
        overwrite=True,
        dry_run=dry_run,
    )


def get_balearic_forecast(dry_run=False):
    print("Fetching Balearic Currents (4.2km resolution)...")
    try:
        if not dry_run:
            validate_copernicus_credentials_available()

        # subset() downloads a bounded region/time/variable slice.
        subset_balearic_forecast(
            dataset_id=PHY_ID,
            variables=["uo", "vo"],
            output_filename="balearic_currents.nc",
            dry_run=dry_run,
        )

        print("Fetching Balearic Waves (4.2km resolution)...")
        subset_balearic_forecast(
            dataset_id=WAV_ID,
            variables=["VHM0", "VMDR"],
            output_filename="balearic_waves.nc",
            dry_run=dry_run,
        )
        if dry_run:
            print("\nDry run complete. No files were downloaded.")
            return

        print(f"\nSuccess! Files downloaded to {OUTPUT_DIR}/")
        print("You can now open these with xarray to find the 'Certeza' for your captains.")

    except Exception as e:
        print(f"An error occurred: {e}")
        print("\nTroubleshooting tip: Run 'copernicusmarine login' again to refresh your token.")
        raise

if __name__ == "__main__":
    get_balearic_forecast()
