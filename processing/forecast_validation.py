from __future__ import annotations

from math import sqrt
from pathlib import Path
from statistics import mean, median, pstdev
from typing import Any

from ingestion.observations_client import Observation
from processing.mariner_interpreter import get_captain_summary


SUPPORTED_VARIABLES = {
    "wind_knots": ("wind_knots",),
    "pressure_hpa": ("metrics", "pressure_hpa"),
}


def compare_forecast_distributions(
    observations: list[Observation],
    wrfout_paths: list[str | Path],
    time: str | None,
    variable: str = "wind_knots",
) -> dict[str, Any]:
    if variable not in SUPPORTED_VARIABLES:
        supported = ", ".join(sorted(SUPPORTED_VARIABLES))
        raise ValueError(f"Unsupported validation variable {variable!r}. Supported: {supported}.")

    observed_values = [_observation_value(observation, variable) for observation in observations]
    observed_values = [value for value in observed_values if value is not None]
    if not observed_values:
        raise ValueError(f"No observations contain {variable!r}.")

    domains = [
        _score_domain(
            observations=observations,
            wrfout_path=Path(wrfout_path),
            time=time,
            variable=variable,
        )
        for wrfout_path in wrfout_paths
    ]
    best = min(domains, key=lambda domain: (domain["rmse"], domain["mae"]))

    return {
        "variable": variable,
        "observation_count": len(observed_values),
        "observed_distribution": _distribution(observed_values),
        "domains": domains,
        "best_domain": {
            "domain": best["domain"],
            "mae": best["mae"],
            "rmse": best["rmse"],
            "bias": best["bias"],
            "ks_statistic": best["ks_statistic"],
        },
    }


def _score_domain(
    observations: list[Observation],
    wrfout_path: Path,
    time: str | None,
    variable: str,
) -> dict[str, Any]:
    pairs = []
    matches = []
    for observation in observations:
        observed = _observation_value(observation, variable)
        if observed is None:
            continue

        summary = get_captain_summary(
            lat=observation.lat,
            lon=observation.lon,
            time=time,
            wrfout_path=wrfout_path,
        )
        forecast = _forecast_value(summary, variable)
        error = forecast - observed
        nearest = summary["location"]["nearest_grid"]
        pairs.append((observed, forecast))
        matches.append(
            {
                "source_id": observation.source_id,
                "lat": observation.lat,
                "lon": observation.lon,
                "observed": round(observed, 3),
                "forecast": round(forecast, 3),
                "error": round(error, 3),
                "nearest_grid": nearest,
            }
        )

    observed_values = [pair[0] for pair in pairs]
    forecast_values = [pair[1] for pair in pairs]
    errors = [forecast - observed for observed, forecast in pairs]

    return {
        "domain": _domain_label(wrfout_path),
        "source": str(wrfout_path),
        "matched_count": len(pairs),
        "forecast_distribution": _distribution(forecast_values),
        "error_distribution": _distribution(errors),
        "bias": round(mean(errors), 3),
        "mae": round(mean(abs(error) for error in errors), 3),
        "rmse": round(sqrt(mean(error**2 for error in errors)), 3),
        "ks_statistic": round(_ks_statistic(observed_values, forecast_values), 3),
        "matches": matches,
    }


def _observation_value(observation: Observation, variable: str) -> float | None:
    return getattr(observation, variable)


def _forecast_value(summary: dict[str, Any], variable: str) -> float:
    path = SUPPORTED_VARIABLES[variable]
    value: Any = summary
    for key in path:
        value = value[key]
    return float(value)


def _distribution(values: list[float]) -> dict[str, float]:
    if not values:
        raise ValueError("Cannot calculate a distribution from no values.")

    sorted_values = sorted(values)
    return {
        "min": round(sorted_values[0], 3),
        "p25": round(_quantile(sorted_values, 0.25), 3),
        "median": round(median(sorted_values), 3),
        "mean": round(mean(sorted_values), 3),
        "p75": round(_quantile(sorted_values, 0.75), 3),
        "max": round(sorted_values[-1], 3),
        "std": round(pstdev(sorted_values), 3),
    }


def _quantile(sorted_values: list[float], fraction: float) -> float:
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = fraction * (len(sorted_values) - 1)
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = position - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def _ks_statistic(observed: list[float], forecast: list[float]) -> float:
    observed_sorted = sorted(observed)
    forecast_sorted = sorted(forecast)
    thresholds = sorted(set(observed_sorted + forecast_sorted))
    max_delta = 0.0
    for threshold in thresholds:
        observed_cdf = _cdf(observed_sorted, threshold)
        forecast_cdf = _cdf(forecast_sorted, threshold)
        max_delta = max(max_delta, abs(observed_cdf - forecast_cdf))
    return max_delta


def _cdf(sorted_values: list[float], threshold: float) -> float:
    count = 0
    for value in sorted_values:
        if value <= threshold:
            count += 1
    return count / len(sorted_values)


def _domain_label(path: Path) -> str:
    for label in ("d01", "d02", "d03"):
        if label in path.name:
            return label
    return path.stem
