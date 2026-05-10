import json
import math
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_ROUTE_ID = "palma_ibiza"
ROUTES_PATH = Path(__file__).with_name("routes.json")
MPS_TO_KNOTS = 1.94384
VESSEL_PROFILES = {
    "small": {
        "label": "under 15m",
        "manageable_m": 1.2,
        "restricted_m": 1.8,
    },
    "medium": {
        "label": "15-24m",
        "manageable_m": 1.5,
        "restricted_m": 2.2,
    },
    "large": {
        "label": "over 24m",
        "manageable_m": 2.0,
        "restricted_m": 2.8,
    },
}


def load_routes(path=ROUTES_PATH):
    with Path(path).open(encoding="utf-8") as file:
        routes = json.load(file)
    return routes


def load_route(route_id=DEFAULT_ROUTE_ID, path=ROUTES_PATH):
    routes = load_routes(path)
    try:
        return routes[route_id]
    except KeyError as error:
        available = ", ".join(sorted(routes))
        raise ValueError(f"Unknown route '{route_id}'. Available routes: {available}") from error


def route_sample_points(route):
    return list(route.get("sample_points", []))


def default_forecast_summary():
    return {
        "wave_min_m": None,
        "wave_max_m": None,
        "wave_peak_time": "N/A",
        "current_max_kn": None,
        "current_peak_time": "N/A",
        "wave_peak_direction_deg": None,
    }


def build_route_snapshot(observations, forecast=None, route=None, vessel_class="medium"):
    route = route or load_route(DEFAULT_ROUTE_ID)
    vessel_profile = vessel_profile_for(vessel_class)
    forecast = forecast or {}
    canal = observations.get("canal_de_ibiza", {})
    wave_now = canal.get("wave_height_m")
    wave_max = forecast.get("wave_max_m")
    wave_min = forecast.get("wave_min_m")
    wave_peak_time = forecast.get("wave_peak_time", "later today")
    current_max = forecast.get("current_max_kn")
    current_peak_time = forecast.get("current_peak_time", "later today")

    recommendation = recommend_window(
        wave_now,
        wave_min,
        wave_max,
        wave_peak_time,
        current_max,
        current_peak_time,
        vessel_class=vessel_class,
    )

    return {
        "route": route["name"],
        "route_id": route["id"],
        "route_note": route.get("route_note"),
        "vessel_class": vessel_class,
        "vessel_profile": vessel_profile,
        "created_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "observations": observations,
        "forecast": forecast,
        "recommendation": recommendation,
    }


def vessel_profile_for(vessel_class):
    if vessel_class not in VESSEL_PROFILES:
        available = ", ".join(sorted(VESSEL_PROFILES))
        raise ValueError(f"Unknown vessel class '{vessel_class}'. Available classes: {available}")
    return VESSEL_PROFILES[vessel_class]


def classify_vessel_severity(wave_max, vessel_profile):
    if wave_max is None:
        return "unknown"
    if wave_max >= vessel_profile["restricted_m"]:
        return "restricted"
    if wave_max >= vessel_profile["manageable_m"]:
        return "caution"
    return "manageable"


def vessel_advice_for(wave_max, vessel_class):
    profile = vessel_profile_for(vessel_class)
    severity = classify_vessel_severity(wave_max, profile)
    label = profile["label"]
    if severity == "restricted":
        advice = f"restricted for vessels {label}"
    elif severity == "caution":
        advice = f"caution for vessels {label}; use the best weather window"
    elif severity == "manageable":
        if vessel_class == "large":
            advice = "manageable for larger vessels, still monitor the exposed peak"
        else:
            advice = f"manageable for vessels {label}"
    else:
        advice = f"manual check needed for vessels {label}"
    return severity, advice


def recommend_window(wave_now, wave_min, wave_max, wave_peak_time, current_max, current_peak_time, vessel_class="medium"):
    if wave_max is None:
        severity, vessel_advice = vessel_advice_for(wave_max, vessel_class)
        return {
            "best_window": "check manually",
            "watch_out": "forecast layer unavailable",
            "confidence": "low",
            "vessel_severity": severity,
            "vessel_advice": vessel_advice,
        }

    wave_build = wave_now is not None and wave_max - wave_now >= 0.5
    strong_current = current_max is not None and current_max >= 1.0
    severity, vessel_advice = vessel_advice_for(wave_max, vessel_class)

    if wave_build:
        best_window = "avoid the exposed peak window" if severity == "restricted" else "before midday"
        watch_out = f"waves build toward {wave_max:.1f} m around {wave_peak_time}"
    elif wave_max <= 1.0:
        best_window = "most daylight windows look manageable"
        watch_out = "no major wave build-up in the 24h forecast"
    else:
        best_window = "morning to early afternoon"
        watch_out = f"forecast peak near {wave_max:.1f} m around {wave_peak_time}"

    if strong_current:
        watch_out = f"{watch_out}; current may reach {current_max:.1f} kn around {current_peak_time}"

    confidence = "medium" if wave_now is not None else "low"
    return {
        "best_window": best_window,
        "watch_out": watch_out,
        "confidence": confidence,
        "vessel_severity": severity,
        "vessel_advice": vessel_advice,
    }


def summarize_forecast_series(
    times,
    wave_heights_m,
    current_speeds_mps,
    wave_directions_deg=None,
    current_directions_deg=None,
    time_utc_values=None,
):
    if not wave_heights_m:
        return default_forecast_summary()

    wave_min = min(wave_heights_m)
    wave_max = max(wave_heights_m)
    wave_peak_index = wave_heights_m.index(wave_max)

    if current_speeds_mps:
        current_max_mps = max(current_speeds_mps)
        current_peak_index = current_speeds_mps.index(current_max_mps)
        current_max_kn = round(current_max_mps * MPS_TO_KNOTS, 1)
        current_peak_time = times[current_peak_index]
    else:
        current_max_kn = None
        current_peak_time = "N/A"

    hourly = []
    for index, time in enumerate(times):
        row = {
            "time": time,
            "wave_m": round(wave_heights_m[index], 1),
        }
        if time_utc_values and index < len(time_utc_values):
            row["time_utc"] = time_utc_values[index]
        if wave_directions_deg and index < len(wave_directions_deg):
            row["wave_direction_deg"] = round(wave_directions_deg[index], 1)
        if index < len(current_speeds_mps):
            row["current_mps"] = round(current_speeds_mps[index], 3)
            row["current_kn"] = round(current_speeds_mps[index] * MPS_TO_KNOTS, 1)
        if current_directions_deg and index < len(current_directions_deg):
            row["current_direction_deg"] = round(current_directions_deg[index], 1)
        hourly.append(row)

    return {
        "wave_min_m": round(wave_min, 1),
        "wave_max_m": round(wave_max, 1),
        "wave_peak_time": times[wave_peak_index],
        "wave_peak_direction_deg": round(wave_directions_deg[wave_peak_index], 1) if wave_directions_deg else None,
        "current_max_kn": current_max_kn,
        "current_peak_time": current_peak_time,
        "hourly": hourly,
    }


def summarize_route_point_series(
    times,
    wave_points_by_time,
    current_points_by_time,
    wave_direction_points_by_time=None,
    current_direction_points_by_time=None,
    time_utc_values=None,
):
    wave_heights = []
    wave_directions = []
    for index, points in enumerate(wave_points_by_time):
        wave_heights.append(max_valid(points))
        if wave_direction_points_by_time:
            exposed_index = index_of_max_valid(points)
            wave_directions.append(wave_direction_points_by_time[index][exposed_index])
    current_speeds = []
    current_directions = []
    for index, points in enumerate(current_points_by_time):
        current_speeds.append(max_valid(points))
        if current_direction_points_by_time:
            exposed_index = index_of_max_valid(points)
            current_directions.append(current_direction_points_by_time[index][exposed_index])
    summary = summarize_forecast_series(
        times,
        wave_heights,
        current_speeds,
        wave_directions or None,
        current_directions or None,
        time_utc_values,
    )
    summary["sampling_method"] = "route_exposed_max"
    return summary


def max_valid(values):
    valid = [value for value in values if value == value]
    if not valid:
        return float("nan")
    return max(valid)


def index_of_max_valid(values):
    valid_indexes = [index for index, value in enumerate(values) if value == value]
    if not valid_indexes:
        return 0
    return max(valid_indexes, key=lambda index: values[index])


def forecast_summary_from_files(waves_path, currents_path, route=None):
    try:
        import xarray as xr
    except ImportError:
        return default_forecast_summary()

    waves_file = Path(waves_path)
    currents_file = Path(currents_path)
    if not waves_file.exists() or not currents_file.exists():
        return default_forecast_summary()

    with xr.open_dataset(waves_file) as waves, xr.open_dataset(currents_file) as currents:
        times = [str(value) for value in waves["time"].dt.strftime("%H:%M").values]
        time_utc_values = [str(value) for value in waves["time"].dt.strftime("%Y-%m-%d %H:%M UTC").values]
        current_speed = (currents["uo"] ** 2 + currents["vo"] ** 2) ** 0.5
        wave_points_by_time = []
        wave_direction_points_by_time = []
        current_points_by_time = []
        current_direction_points_by_time = []
        for point in route_sample_points(route or load_route(DEFAULT_ROUTE_ID)):
            wave_point = waves["VHM0"].sel(
                longitude=point["longitude"],
                latitude=point["latitude"],
                method="nearest",
            )
            current_point = current_speed.sel(
                longitude=point["longitude"],
                latitude=point["latitude"],
                method="nearest",
            )
            u_point = currents["uo"].sel(
                longitude=point["longitude"],
                latitude=point["latitude"],
                method="nearest",
            )
            v_point = currents["vo"].sel(
                longitude=point["longitude"],
                latitude=point["latitude"],
                method="nearest",
            )
            wave_direction_point = waves["VMDR"].sel(
                longitude=point["longitude"],
                latitude=point["latitude"],
                method="nearest",
            )
            wave_points_by_time.append([float(value) for value in wave_point.values])
            wave_direction_points_by_time.append([float(value) for value in wave_direction_point.values])
            current_points_by_time.append([float(value) for value in current_point.values])
            current_direction_points_by_time.append(
                [
                    current_direction_deg(float(u), float(v))
                    for u, v in zip(u_point.values, v_point.values)
                ]
            )

    wave_by_time = transpose_points(wave_points_by_time)
    wave_direction_by_time = transpose_points(wave_direction_points_by_time)
    current_by_time = transpose_points(current_points_by_time)
    current_direction_by_time = transpose_points(current_direction_points_by_time)
    return summarize_route_point_series(
        times,
        wave_by_time,
        current_by_time,
        wave_direction_by_time,
        current_direction_by_time,
        time_utc_values,
    )


def current_direction_deg(u_east_mps, v_north_mps):
    return (math.degrees(math.atan2(u_east_mps, v_north_mps)) + 360.0) % 360.0


def transpose_points(points_by_series):
    if not points_by_series:
        return []
    return [list(values) for values in zip(*points_by_series)]
