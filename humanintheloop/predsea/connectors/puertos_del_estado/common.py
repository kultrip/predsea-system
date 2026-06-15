from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone

import numpy as np
import pandas as pd


SOURCE_SYSTEM = "puertos_del_estado"
NETWORK_LABELS = {
    "redext": "REDEXT",
    "redcos": "REDCOS",
    "redmar": "REDMAR",
}


def strip_accents(text):
    normalized = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def normalize_text(text):
    text = strip_accents(str(text or "")).strip().lower()
    text = re.sub(r"\s*\(.*?\)", "", text)
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def clean_station_name(label):
    text = strip_accents(str(label or "")).strip()
    text = re.sub(r"^Boya Costera de\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^Boya de\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^Boya\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^Estacion\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*\(.*?\)", "", text)
    return text.strip()


def station_key_from_label(label):
    return normalize_text(clean_station_name(label))


def station_id_from_label(label):
    key = station_key_from_label(label)
    return f"puertos_{key}" if key else None


def parse_utc_timestamp(value):
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    try:
        parsed = pd.to_datetime(value, utc=True)
    except Exception:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except Exception:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    if pd.isna(parsed):
        return None
    if isinstance(parsed, pd.Timestamp):
        return parsed.to_pydatetime().astimezone(timezone.utc)
    return parsed


def timestamp_text(value):
    parsed = parse_utc_timestamp(value)
    if parsed is None:
        return None
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")


def to_float(value):
    try:
        if value is None:
            return None
        if isinstance(value, (list, tuple)) and value:
            value = value[0]
        if isinstance(value, np.ndarray) and value.size:
            value = value.reshape(-1)[0]
        return float(value)
    except Exception:
        return None


def _time_dim_name(da):
    for dim in da.dims:
        if dim.lower() in {"time", "time_counter", "datetime"}:
            return dim
    return None


def _spatial_dims(da):
    dims = [dim for dim in da.dims if dim.lower() != "time" and da.sizes.get(dim, 0) > 1]
    return dims


def _coordinate_values(coord):
    try:
        values = np.asarray(coord.values)
    except Exception:
        values = np.asarray(coord)
    return values


def select_spatial_point(da, latitude, longitude):
    lat_coord = da.coords.get("latitude")
    lon_coord = da.coords.get("longitude")
    if lat_coord is None or lon_coord is None:
        return da

    lat_values = _coordinate_values(lat_coord)
    lon_values = _coordinate_values(lon_coord)

    if lat_values.ndim == 1 and lon_values.ndim == 1:
        try:
            return da.sel(latitude=latitude, longitude=longitude, method="nearest")
        except Exception:
            return da

    if lat_values.shape == lon_values.shape and lat_values.ndim >= 2:
        distance = ((lat_values - float(latitude)) ** 2) + ((lon_values - float(longitude)) ** 2)
        flat_index = int(np.nanargmin(distance))
        unravelled = np.unravel_index(flat_index, distance.shape)
        spatial_dims = _spatial_dims(da)
        if len(spatial_dims) >= len(unravelled):
            selections = {dim: idx for dim, idx in zip(spatial_dims[: len(unravelled)], unravelled)}
            try:
                return da.isel(selections)
            except Exception:
                return da

    return da


def latest_value_from_dataarray(da, *, latitude=None, longitude=None):
    candidate = da
    if latitude is not None and longitude is not None:
        candidate = select_spatial_point(candidate, latitude, longitude)
    time_dim = _time_dim_name(candidate)
    if time_dim is None:
        return None, None
    for dim in list(candidate.dims):
        if dim != time_dim and candidate.sizes.get(dim, 0) == 1:
            candidate = candidate.isel({dim: 0}, drop=True)
    candidate = candidate.where(candidate.notnull(), drop=True)
    if candidate.size == 0:
        return None, None
    latest = candidate.isel({time_dim: -1}).squeeze(drop=True)
    value = to_float(getattr(latest, "values", latest))
    if value is None:
        return None, None
    time_value = timestamp_text(candidate[time_dim].values[-1])
    parsed_time = parse_utc_timestamp(time_value)
    if parsed_time is not None and parsed_time > datetime.now(timezone.utc):
        return None, None
    return value, time_value


def variable_keyword(text):
    return normalize_text(" ".join(part for part in [text] if part))
