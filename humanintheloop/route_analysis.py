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
        "wave_peak_sea_state": None,
        "wave_peak_relative_angle_deg": None,
        "route_bearing_deg": None,
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
    route_bearing_deg=None,
    component_series=None,
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
            if route_bearing_deg is not None:
                sea_state = relative_sea_state(wave_directions_deg[index], route_bearing_deg)
                row["wave_relative_angle_deg"] = sea_state["relative_angle_deg"]
                row["wave_sea_state"] = sea_state["label"]
        if index < len(current_speeds_mps):
            row["current_mps"] = round(current_speeds_mps[index], 3)
            row["current_kn"] = round(current_speeds_mps[index] * MPS_TO_KNOTS, 1)
        if current_directions_deg and index < len(current_directions_deg):
            row["current_direction_deg"] = round(current_directions_deg[index], 1)
        if component_series:
            for component_name, component in component_series.items():
                heights = component.get("height") or []
                directions = component.get("direction") or []
                if index < len(heights) and heights[index] == heights[index]:
                    row[f"{component_name}_height_m"] = round(heights[index], 1)
                if index < len(directions) and directions[index] == directions[index]:
                    row[f"{component_name}_direction_deg"] = round(directions[index], 1)
        hourly.append(row)

    result = {
        "wave_min_m": round(wave_min, 1),
        "wave_max_m": round(wave_max, 1),
        "wave_peak_time": times[wave_peak_index],
        "wave_peak_direction_deg": round(wave_directions_deg[wave_peak_index], 1) if wave_directions_deg else None,
        "current_max_kn": current_max_kn,
        "current_peak_time": current_peak_time,
        "hourly": hourly,
    }
    if route_bearing_deg is not None:
        result["route_bearing_deg"] = round(route_bearing_deg, 1)
    if wave_directions_deg and route_bearing_deg is not None:
        peak_sea_state = relative_sea_state(wave_directions_deg[wave_peak_index], route_bearing_deg)
        result["wave_peak_sea_state"] = peak_sea_state["label"]
        result["wave_peak_relative_angle_deg"] = peak_sea_state["relative_angle_deg"]
    if component_series:
        for component_name, component in component_series.items():
            heights = component.get("height") or []
            directions = component.get("direction") or []
            if wave_peak_index < len(heights) and heights[wave_peak_index] == heights[wave_peak_index]:
                result[f"{component_name}_height_m"] = round(heights[wave_peak_index], 1)
            if wave_peak_index < len(directions) and directions[wave_peak_index] == directions[wave_peak_index]:
                result[f"{component_name}_direction_deg"] = round(directions[wave_peak_index], 1)
    return result


def summarize_route_point_series(
    times,
    wave_points_by_time,
    current_points_by_time,
    wave_direction_points_by_time=None,
    current_direction_points_by_time=None,
    time_utc_values=None,
    component_points_by_time=None,
    route=None,
):
    wave_heights = []
    wave_directions = []
    component_series = initialize_component_series(component_points_by_time)
    for index, points in enumerate(wave_points_by_time):
        wave_heights.append(max_valid(points))
        exposed_index = index_of_max_valid(points)
        if wave_direction_points_by_time:
            wave_directions.append(wave_direction_points_by_time[index][exposed_index])
        append_component_values(component_series, component_points_by_time, index, exposed_index)
    current_speeds = []
    current_directions = []
    for index, points in enumerate(current_points_by_time):
        current_speeds.append(max_valid(points))
        if current_direction_points_by_time:
            exposed_index = index_of_max_valid(points)
            current_directions.append(current_direction_points_by_time[index][exposed_index])
    route_bearing_deg = route_bearing(route) if route else None
    summary = summarize_forecast_series(
        times,
        wave_heights,
        current_speeds,
        wave_directions or None,
        current_directions or None,
        time_utc_values,
        route_bearing_deg=route_bearing_deg,
        component_series=component_series or None,
    )
    summary["sampling_method"] = "route_exposed_max"
    summary["route_segments"] = build_route_segments(
        times,
        wave_points_by_time,
        current_points_by_time,
        wave_direction_points_by_time,
        route_bearing_deg,
        route or load_route(DEFAULT_ROUTE_ID),
    )
    return summary


def build_route_segments(times, wave_points_by_time, current_points_by_time=None, wave_direction_points_by_time=None, route_bearing_deg=None, route=None):
    sample_points = route_sample_points(route or {})
    if not sample_points or not wave_points_by_time:
        return {}

    segment_indexes = operational_segment_indexes(len(sample_points))
    segments = {}
    for segment_id, point_index in segment_indexes.items():
        point = sample_points[point_index]
        wave_series = series_for_point(wave_points_by_time, point_index)
        current_series = series_for_point(current_points_by_time or [], point_index)
        direction_series = series_for_point(wave_direction_points_by_time or [], point_index)
        segments[segment_id] = summarize_route_segment(
            segment_id,
            point.get("name", segment_id.replace("_", " ")),
            times,
            wave_series,
            current_series,
            direction_series,
            route_bearing_deg,
        )

    worst_id = max(
        segments,
        key=lambda segment_id: comparable_segment_wave(segments[segment_id]),
    )
    best_window = best_route_departure_window(times, wave_points_by_time)
    segments["worst_segment"] = {"id": worst_id, **segments[worst_id]}
    segments["best_departure_window"] = best_window
    return segments


def operational_segment_indexes(point_count):
    if point_count <= 1:
        return {"departure_conditions": 0, "open_water_conditions": 0, "arrival_conditions": 0}
    return {
        "departure_conditions": 0,
        "open_water_conditions": point_count // 2,
        "arrival_conditions": point_count - 1,
    }


def series_for_point(values_by_time, point_index):
    series = []
    for values in values_by_time:
        if point_index < len(values):
            series.append(values[point_index])
    return series


def summarize_route_segment(segment_id, name, times, wave_series, current_series=None, direction_series=None, route_bearing_deg=None):
    peak_index = index_of_max_valid(wave_series)
    max_wave = wave_series[peak_index] if peak_index < len(wave_series) else float("nan")
    direction = direction_series[peak_index] if direction_series and peak_index < len(direction_series) else None
    sea_state = relative_sea_state(direction, route_bearing_deg)["label"] if direction is not None and route_bearing_deg is not None else None
    current = current_series[peak_index] if current_series and peak_index < len(current_series) else None
    segment = {
        "name": name,
        "max_wave_m": round(max_wave, 1) if max_wave == max_wave else None,
        "peak_time": times[peak_index] if peak_index < len(times) else None,
        "wave_direction_deg": round(direction, 1) if direction is not None and direction == direction else None,
        "sea_state": sea_state,
    }
    if current is not None and current == current:
        segment["current_kn"] = round(current * MPS_TO_KNOTS, 1)
    return segment


def comparable_segment_wave(segment):
    value = segment.get("max_wave_m")
    return float(value) if isinstance(value, (int, float)) else -1.0


def best_route_departure_window(times, wave_points_by_time):
    candidates = []
    for index, values in enumerate(wave_points_by_time):
        route_max = max_valid(values)
        if route_max == route_max and index < len(times):
            candidates.append({"time": times[index], "wave_m": round(route_max, 1)})
    if not candidates:
        return {"time": None, "wave_m": None}
    return min(candidates, key=lambda candidate: candidate["wave_m"])


def initialize_component_series(component_points_by_time):
    if not component_points_by_time:
        return {}
    return {
        component_name: {"height": [], "direction": []}
        for component_name in component_points_by_time
    }


def append_component_values(component_series, component_points_by_time, time_index, exposed_index):
    if not component_series or not component_points_by_time:
        return
    for component_name, component in component_points_by_time.items():
        for field in ("height", "direction"):
            values_by_time = component.get(field) or []
            if time_index < len(values_by_time) and exposed_index < len(values_by_time[time_index]):
                component_series[component_name][field].append(values_by_time[time_index][exposed_index])
            else:
                component_series[component_name][field].append(float("nan"))


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


def route_bearing(route):
    if not route:
        return None
    origin = route.get("origin") or {}
    destination = route.get("destination") or {}
    if not all(key in origin and key in destination for key in ("longitude", "latitude")):
        return None

    lon1 = math.radians(float(origin["longitude"]))
    lat1 = math.radians(float(origin["latitude"]))
    lon2 = math.radians(float(destination["longitude"]))
    lat2 = math.radians(float(destination["latitude"]))
    delta_lon = lon2 - lon1
    x = math.sin(delta_lon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(delta_lon)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def relative_sea_state(wave_from_direction_deg, route_bearing_deg):
    angle = relative_angle_deg(wave_from_direction_deg, route_bearing_deg)
    abs_angle = abs(angle)
    if abs_angle <= 30:
        label = "head sea"
    elif abs_angle < 70:
        label = "bow quartering sea"
    elif abs_angle <= 110:
        label = "beam sea"
    elif abs_angle < 150:
        label = "stern quartering sea"
    else:
        label = "following sea"
    return {
        "label": label,
        "relative_angle_deg": round(abs_angle, 1),
        "signed_relative_angle_deg": round(angle, 1),
    }


def relative_angle_deg(wave_from_direction_deg, route_bearing_deg):
    return ((float(wave_from_direction_deg) - float(route_bearing_deg) + 540.0) % 360.0) - 180.0


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
        component_series_by_name = {
            "swell_1": {"height": [], "direction": []},
            "swell_2": {"height": [], "direction": []},
            "wind_wave": {"height": [], "direction": []},
        }
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
            append_wave_component_point_values(waves, component_series_by_name, point)
            current_points_by_time.append([float(value) for value in current_point.values])
            current_direction_points_by_time.append(
                [
                    current_direction_deg(float(u), float(v))
                    for u, v in zip(u_point.values, v_point.values)
                ]
            )

    wave_by_time = transpose_points(wave_points_by_time)
    wave_direction_by_time = transpose_points(wave_direction_points_by_time)
    component_by_time = transpose_component_points(component_series_by_name)
    current_by_time = transpose_points(current_points_by_time)
    current_direction_by_time = transpose_points(current_direction_points_by_time)
    return summarize_route_point_series(
        times,
        wave_by_time,
        current_by_time,
        wave_direction_by_time,
        current_direction_by_time,
        time_utc_values,
        component_by_time or None,
        route=route or load_route(DEFAULT_ROUTE_ID),
    )


WAVE_COMPONENT_VARIABLES = {
    "swell_1": {"height": "VHM0_SW1", "direction": "VMDR_SW1"},
    "swell_2": {"height": "VHM0_SW2", "direction": "VMDR_SW2"},
    "wind_wave": {"height": "VHM0_WW", "direction": "VMDR_WW"},
}


def append_wave_component_point_values(waves, component_series_by_name, point):
    for component_name, variables in WAVE_COMPONENT_VARIABLES.items():
        for field, variable_name in variables.items():
            if variable_name not in waves:
                continue
            component_point = waves[variable_name].sel(
                longitude=point["longitude"],
                latitude=point["latitude"],
                method="nearest",
            )
            component_series_by_name[component_name][field].append(
                [float(value) for value in component_point.values]
            )


def transpose_component_points(component_series_by_name):
    result = {}
    for component_name, component in component_series_by_name.items():
        transposed = {}
        for field, points_by_series in component.items():
            if points_by_series:
                transposed[field] = transpose_points(points_by_series)
        if transposed:
            result[component_name] = transposed
    return result


def current_direction_deg(u_east_mps, v_north_mps):
    return (math.degrees(math.atan2(u_east_mps, v_north_mps)) + 360.0) % 360.0


def transpose_points(points_by_series):
    if not points_by_series:
        return []
    return [list(values) for values in zip(*points_by_series)]
