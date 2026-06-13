from __future__ import annotations

import json
import time
from pathlib import Path

import requests

try:  # pragma: no cover - optional dependency during lightweight tests
    import xarray as xr
except Exception:  # pragma: no cover
    xr = None


def _ensure_cache_dir(cache_dir):
    if cache_dir is None:
        return None
    path = Path(cache_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cache_path(cache_dir, cache_key, suffix):
    if cache_dir is None or not cache_key:
        return None
    cache_dir = _ensure_cache_dir(cache_dir)
    return cache_dir / f"{cache_key}{suffix}"


def cache_json(cache_dir, cache_key, payload):
    path = _cache_path(cache_dir, cache_key, ".json")
    if path is None:
        return None
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def fetch_text(
    url,
    *,
    timeout=60,
    max_retries=3,
    backoff_seconds=2,
    session=None,
    cache_dir=None,
    cache_key=None,
):
    cache_path = _cache_path(cache_dir, cache_key, ".html")
    if cache_path and cache_path.exists():
        return {"text": cache_path.read_text(encoding="utf-8"), "cache_path": cache_path, "from_cache": True}

    session = session or requests.Session()
    last_error = None
    for attempt in range(max_retries):
        try:
            response = session.get(url, timeout=timeout)
            response.raise_for_status()
            if cache_path is not None:
                cache_path.write_text(response.text, encoding="utf-8")
            return {"text": response.text, "cache_path": cache_path, "from_cache": False}
        except Exception as error:  # pragma: no cover - network retry path
            last_error = error
            if attempt >= max_retries - 1:
                raise
            time.sleep(backoff_seconds * (2 ** attempt))
    raise last_error  # pragma: no cover


def open_dataset(
    url,
    *,
    timeout=60,
    max_retries=3,
    backoff_seconds=2,
):
    if xr is None:  # pragma: no cover - import guard
        raise RuntimeError("xarray is required to read Puertos del Estado NetCDF datasets")

    last_error = None
    for attempt in range(max_retries):
        try:
            # xarray handles the OPeNDAP request directly.
            return xr.open_dataset(url, decode_times=True)
        except Exception as error:  # pragma: no cover - network retry path
            last_error = error
            if attempt >= max_retries - 1:
                raise
            time.sleep(backoff_seconds * (2 ** attempt))
    raise last_error  # pragma: no cover

