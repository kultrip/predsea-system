from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Observation:
    source_id: str
    time: str
    lat: float
    lon: float
    wind_knots: float | None = None
    wind_direction_deg: float | None = None
    pressure_hpa: float | None = None


def load_observations_csv(path: str | Path) -> list[Observation]:
    """Load normalized station observations from a CSV export."""

    with Path(path).open(newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        return [_observation_from_row(row) for row in reader]


def _observation_from_row(row: dict[str, str]) -> Observation:
    return Observation(
        source_id=row.get("station_id") or row.get("source_id") or row.get("id") or "unknown",
        time=row["time"],
        lat=float(row["lat"]),
        lon=float(row["lon"]),
        wind_knots=_optional_float(row.get("wind_knots")),
        wind_direction_deg=_optional_float(row.get("wind_direction_deg")),
        pressure_hpa=_optional_float(row.get("pressure_hpa")),
    )


def _optional_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    return float(value)
