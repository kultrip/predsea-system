#!/usr/bin/env python3
"""Validate canonical PredSea SWAN or CROCO NetCDF before publication."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import xarray as xr


MODEL_SPECS = {
    "swan": {
        "time": ("time",),
        "latitude": ("latitude", "lat"),
        "longitude": ("longitude", "lon"),
        "variables": {
            "hs": (0.0, 25.0),
            "tps": (0.0, 40.0),
            "dir": (0.0, 360.0),
        },
    },
    "croco": {
        "time": ("ocean_time", "time"),
        "latitude": ("lat_rho", "latitude", "lat"),
        "longitude": ("lon_rho", "longitude", "lon"),
        "variables": {
            "zeta": (-15.0, 15.0),
            "temp": (-5.0, 45.0),
            "salt": (0.0, 50.0),
            "u": (-10.0, 10.0),
            "v": (-10.0, 10.0),
        },
    },
}


def _first_existing(dataset: xr.Dataset, names: tuple[str, ...]) -> str | None:
    return next((name for name in names if name in dataset), None)


def _coordinate_bounds(values: np.ndarray) -> tuple[float, float]:
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        raise ValueError("coordinate contains no finite values")
    return float(finite.min()), float(finite.max())


def validate_dataset(
    dataset: xr.Dataset,
    *,
    model: str,
    expected_timestamps: int,
    minimum_finite_fraction: float = 0.9,
    expected_bbox: tuple[float, float, float, float] | None = None,
) -> dict:
    """Return a machine-readable validation report for a native model product."""
    spec = MODEL_SPECS[model]
    errors: list[str] = []

    time_name = _first_existing(dataset, spec["time"])
    lat_name = _first_existing(dataset, spec["latitude"])
    lon_name = _first_existing(dataset, spec["longitude"])
    if time_name is None:
        errors.append(f"missing time coordinate ({', '.join(spec['time'])})")
    if lat_name is None:
        errors.append(f"missing latitude coordinate ({', '.join(spec['latitude'])})")
    if lon_name is None:
        errors.append(f"missing longitude coordinate ({', '.join(spec['longitude'])})")

    timestamp_count = int(dataset.sizes.get(time_name, 0)) if time_name else 0
    if timestamp_count != expected_timestamps:
        errors.append(
            f"expected {expected_timestamps} timestamps, found {timestamp_count}"
        )

    bbox = None
    if lat_name and lon_name:
        try:
            lat_min, lat_max = _coordinate_bounds(dataset[lat_name].values)
            lon_min, lon_max = _coordinate_bounds(dataset[lon_name].values)
            bbox = [lon_min, lat_min, lon_max, lat_max]
            if expected_bbox is not None:
                west, south, east, north = expected_bbox
                if lon_min > west or lat_min > south or lon_max < east or lat_max < north:
                    errors.append(
                        "output does not cover expected bbox "
                        f"{list(expected_bbox)}; actual bbox is {bbox}"
                    )
        except ValueError as exc:
            errors.append(str(exc))

    variables = {}
    for variable, (minimum, maximum) in spec["variables"].items():
        if variable not in dataset:
            errors.append(f"missing required variable {variable}")
            variables[variable] = {"status": "missing"}
            continue
        values = np.asarray(dataset[variable].values, dtype=float)
        finite_mask = np.isfinite(values)
        finite_fraction = float(finite_mask.mean()) if values.size else 0.0
        finite_values = values[finite_mask]
        observed_min = float(finite_values.min()) if finite_values.size else None
        observed_max = float(finite_values.max()) if finite_values.size else None
        status = "valid"
        if finite_fraction < minimum_finite_fraction:
            errors.append(
                f"{variable} finite fraction {finite_fraction:.4f} is below "
                f"{minimum_finite_fraction:.4f}"
            )
            status = "invalid"
        if finite_values.size and (
            observed_min < minimum or observed_max > maximum
        ):
            errors.append(
                f"{variable} range [{observed_min}, {observed_max}] exceeds "
                f"[{minimum}, {maximum}]"
            )
            status = "invalid"
        variables[variable] = {
            "status": status,
            "finite_fraction": finite_fraction,
            "minimum": observed_min,
            "maximum": observed_max,
            "physical_range": [minimum, maximum],
        }

    return {
        "schema_version": "predsea.native_marine_validation.v1",
        "model": model,
        "status": "passed" if not errors else "failed",
        "timestamp_count": timestamp_count,
        "expected_timestamp_count": expected_timestamps,
        "bbox": bbox,
        "minimum_finite_fraction": minimum_finite_fraction,
        "variables": variables,
        "errors": errors,
    }


def _parse_bbox(text: str | None) -> tuple[float, float, float, float] | None:
    if not text:
        return None
    values = tuple(float(value) for value in text.split(","))
    if len(values) != 4:
        raise argparse.ArgumentTypeError("bbox must be west,south,east,north")
    return values


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=sorted(MODEL_SPECS), required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--expected-timestamps", type=int, required=True)
    parser.add_argument("--expected-bbox")
    parser.add_argument("--minimum-finite-fraction", type=float, default=0.9)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)

    with xr.open_dataset(args.input) as dataset:
        report = validate_dataset(
            dataset,
            model=args.model,
            expected_timestamps=args.expected_timestamps,
            minimum_finite_fraction=args.minimum_finite_fraction,
            expected_bbox=_parse_bbox(args.expected_bbox),
        )
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(payload)
    print(payload, end="")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
