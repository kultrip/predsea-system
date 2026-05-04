# SOCIB Data Slicer Design

## Goal

Build the first foundation module for PredSea Decision Engine v1: a Python function that reads a 24-hour, point-specific slice from the SOCIB WMOP forecast OpenDAP endpoint without downloading the full NetCDF dataset.

## Scope

Create `socib_client.py` with `get_ocean_data(lat, lon, timeframe)`. The function connects to `https://thredds.socib.es/thredds/dodsC/wmop/forecast/latest`, selects the nearest model grid point to the requested GPS coordinate, slices a 24-hour time window, and returns a plain Python dictionary suitable for later FastAPI and natural-language layers.

## Data Access

The module uses `xarray.open_dataset` against the OpenDAP URL. It keeps data lazy until after coordinate, time, and variable slicing have reduced the result to a small subset. Only then does it load values for dictionary serialization.

## Variable Mapping

The public response uses natural names:

- `sea_surface_height`
- `u_current`
- `v_current`
- `significant_wave_height`

SOCIB WMOP datasets may expose model names such as `zeta`, `u`, and `v`, so the module resolves aliases by variable name and CF metadata where possible. If a required variable is not present, the function raises a clear `SocibDataError` listing the missing field and available dataset variables. This is important because significant wave height may be provided by a wave model rather than the hydrodynamic WMOP surface dataset.

## Coordinates And Time

The function accepts `timeframe` as `None`, an ISO string, or a Python datetime. `None` means the first available forecast timestamp in the dataset. The selected window is `[timeframe, timeframe + 24 hours]`. Latitude and longitude coordinate names are detected from common SOCIB names such as `lat`, `latitude`, `lat_rho`, `lat_uv`, `lon`, `longitude`, `lon_rho`, and `lon_uv`.

## Return Shape

The function returns:

```python
{
    "source": "https://thredds.socib.es/thredds/dodsC/wmop/forecast/latest",
    "location": {
        "requested_lat": 39.5,
        "requested_lon": 2.6,
        "matched_lat": 39.49,
        "matched_lon": 2.61,
    },
    "time_window": {
        "start": "2026-05-04T00:00:00",
        "end": "2026-05-05T00:00:00",
    },
    "data": [
        {
            "time": "2026-05-04T00:00:00",
            "sea_surface_height": 0.1,
            "u_current": 0.2,
            "v_current": -0.1,
            "significant_wave_height": 0.8,
        }
    ],
}
```

## Testing

Tests use small in-memory xarray datasets and monkeypatch `xarray.open_dataset`, so they verify slicing and serialization behavior without requiring live SOCIB network access. Live OpenDAP verification is kept as a manual smoke test because it depends on external server availability and exact current catalog contents.
