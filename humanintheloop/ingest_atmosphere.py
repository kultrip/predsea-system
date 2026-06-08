BALEARIC_BBOX = {
    "south": 38.0,
    "north": 40.5,
    "west": 1.0,
    "east": 4.5,
}


ATMOSPHERIC_PROVIDERS = [
    {
        "id": "meteo_france_arome",
        "label": "Meteo-France AROME 0.01 degree",
        "tier": 1,
        "resolution_km": 1.3,
        "variables": ["u10", "v10", "wind_gust"],
    },
    {
        "id": "aemet_harmonie_arome",
        "label": "AEMET HARMONIE-AROME",
        "tier": 2,
        "resolution_km": 2.5,
        "variables": ["u10", "v10", "wind_gust"],
    },
    {
        "id": "ecmwf_open_data",
        "label": "ECMWF Open Data",
        "tier": 3,
        "resolution_km": 25.0,
        "variables": ["u10", "v10", "wind_gust"],
    },
]


def select_wind_forecast(fetchers, bbox=BALEARIC_BBOX):
    errors = {}
    for provider in ATMOSPHERIC_PROVIDERS:
        fetcher = fetchers.get(provider["id"])
        if fetcher is None:
            errors[provider["id"]] = "fetcher not configured"
            continue
        try:
            result = fetcher(provider)
        except Exception as error:
            errors[provider["id"]] = str(error)
            continue
        if result.get("available"):
            return normalize_wind_result(result, provider, bbox, errors)
        errors[provider["id"]] = result.get("error", "provider unavailable")

    return {
        "available": False,
        "source": None,
        "resolution_km": None,
        "tier": None,
        "bbox": dict(bbox),
        "errors": errors,
    }


def normalize_wind_result(result, provider, bbox, errors=None):
    normalized = dict(result)
    normalized.update(
        {
            "available": True,
            "source": provider["id"],
            "label": provider["label"],
            "tier": provider["tier"],
            "resolution_km": provider["resolution_km"],
            "bbox": dict(bbox),
            "variables": list(provider["variables"]),
        }
    )
    if errors:
        normalized["fallback_errors"] = errors
    return normalized


def lineage_for_wind_result(result):
    if not result.get("available"):
        return {
            "source": None,
            "resolution_km": None,
            "status": "unavailable",
            "tier": None,
        }
    return {
        "source": result.get("source"),
        "resolution_km": result.get("resolution_km"),
        "status": "active",
        "tier": result.get("tier"),
    }
