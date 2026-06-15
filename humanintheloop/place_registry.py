from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from math import atan2, cos, radians, sin, sqrt
from tempfile import gettempdir
import logging


DEFAULT_TRAVEL_SPEED_KN = 15.0
DEFAULT_COPERNICUS_GCS_PREFIX = "gs://predsea-daily-outputs/copernicus"
DEFAULT_WAVES_BLOB = "waves_latest.nc"
DEFAULT_CURRENTS_BLOB = "currents_latest.nc"
GRAPH_FALLBACK_SPEED_KN = 15.0

logger = logging.getLogger(__name__)


def _haversine_nm(lat1, lon1, lat2, lon2):
    radius_nm = 3440.065
    phi1 = radians(lat1)
    phi2 = radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2.0) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2.0) ** 2
    return 2.0 * radius_nm * atan2(sqrt(a), sqrt(1.0 - a))


PLACE_CATALOG = {
    "ibiza": {
        "name": "Ibiza",
        "latitude": 38.92,
        "longitude": 1.49,
        "kind": "main_place",
        "parent_place_id": None,
        "children": (),
        "aliases": ("ibiza", "ibiza island"),
        "observation_candidates": ("canal_de_ibiza", "puertos_ibiza", "ibiza"),
    },
    "palma": {
        "name": "Palma",
        "latitude": 39.52,
        "longitude": 2.58,
        "kind": "main_port",
        "parent_place_id": None,
        "children": ("port_de_palma", "port_adriano", "can_pastilla"),
        "aliases": ("palma", "palma de mallorca"),
        "observation_candidates": ("bahia_de_palma", "puertos_mallorca", "mallorca", "palma"),
    },
    "port_de_palma": {
        "name": "Port de Palma",
        "latitude": 39.55,
        "longitude": 2.63,
        "kind": "sub_port",
        "parent_place_id": "palma",
        "children": (),
        "aliases": ("port de palma", "port of palma"),
        "observation_candidates": ("bahia_de_palma", "puertos_mallorca", "mallorca", "palma"),
    },
    "port_adriano": {
        "name": "Port Adriano",
        "latitude": 39.50,
        "longitude": 2.48,
        "kind": "sub_port",
        "parent_place_id": "palma",
        "children": (),
        "aliases": ("port adriano",),
        "observation_candidates": ("bahia_de_palma", "puertos_mallorca", "mallorca", "palma"),
    },
    "can_pastilla": {
        "name": "Can Pastilla",
        "latitude": 39.53,
        "longitude": 2.71,
        "kind": "sub_port",
        "parent_place_id": "palma",
        "children": (),
        "aliases": ("can pastilla", "can pastilla palma"),
        "observation_candidates": ("bahia_de_palma", "puertos_mallorca", "mallorca", "palma"),
    },
    "formentera": {
        "name": "Formentera",
        "latitude": 38.68,
        "longitude": 1.49,
        "kind": "main_place",
        "parent_place_id": None,
        "children": (),
        "aliases": ("formentera",),
        "observation_candidates": ("formentera", "puertos_formentera", "canal_de_ibiza"),
    },
    "menorca": {
        "name": "Menorca",
        "latitude": 40.02,
        "longitude": 4.12,
        "kind": "main_place",
        "parent_place_id": None,
        "children": ("ciutadella",),
        "aliases": ("menorca",),
        "observation_candidates": ("mahon", "puertos_mahon"),
    },
    "cabrera": {
        "name": "Cabrera",
        "latitude": 39.14,
        "longitude": 2.92,
        "kind": "main_place",
        "parent_place_id": None,
        "children": (),
        "aliases": ("cabrera",),
        "observation_candidates": ("canal_de_ibiza", "puertos_mallorca", "mallorca"),
    },
    "ciutadella": {
        "name": "Ciutadella",
        "latitude": 40.02,
        "longitude": 3.82,
        "kind": "main_port",
        "parent_place_id": "menorca",
        "children": (),
        "aliases": ("ciutadella", "ciutadella de menorca"),
        "observation_candidates": ("mahon", "puertos_mahon", "menorca"),
    },
    "alcudia": {
        "name": "Alcudia",
        "latitude": 39.84,
        "longitude": 3.14,
        "kind": "main_port",
        "parent_place_id": "palma",
        "children": (),
        "aliases": ("alcudia", "alcudia de mallorca"),
        "observation_candidates": ("alcudia", "puertos_alcudia", "mallorca", "puertos_mallorca"),
    },
    "soller": {
        "name": "Soller",
        "latitude": 39.81,
        "longitude": 2.74,
        "kind": "main_port",
        "parent_place_id": "palma",
        "children": (),
        "aliases": ("soller", "port de soller"),
        "observation_candidates": ("bahia_de_palma", "puertos_mallorca", "mallorca", "palma"),
    },
    "barcelona": {
        "name": "Barcelona",
        "latitude": 41.32,
        "longitude": 2.22,
        "kind": "main_place",
        "parent_place_id": None,
        "children": (),
        "aliases": ("barcelona",),
        "observation_candidates": ("barcelona", "puertos_barcelona"),
    },
    "valencia": {
        "name": "Valencia",
        "latitude": 39.38,
        "longitude": -0.28,
        "kind": "main_place",
        "parent_place_id": None,
        "children": (),
        "aliases": ("valencia",),
        "observation_candidates": ("valencia", "puertos_valencia"),
    },
    "portocolom": {
        "name": "Portocolom",
        "latitude": 39.41,
        "longitude": 3.27,
        "kind": "main_port",
        "parent_place_id": "palma",
        "children": (),
        "aliases": ("portocolom", "porto colom", "port de portocolom"),
        "observation_candidates": ("porto_colom", "puertos_mallorca", "mallorca", "puertos_alcudia", "alcudia"),
    },
}


DEFAULT_PLACE_BY_QUERY = {
    "palma": "palma",
    "palma de mallorca": "palma",
    "port de palma": "port_de_palma",
    "port of palma": "port_de_palma",
    "port adriano": "port_adriano",
    "can pastilla": "can_pastilla",
    "ibiza": "ibiza",
    "ibiza island": "ibiza",
    "formentera": "formentera",
    "menorca": "menorca",
    "cabrera": "cabrera",
    "ciutadella": "ciutadella",
    "ciutadella de menorca": "ciutadella",
    "alcudia": "alcudia",
    "alcudia de mallorca": "alcudia",
    "soller": "soller",
    "port de soller": "soller",
    "barcelona": "barcelona",
    "valencia": "valencia",
    "portocolom": "portocolom",
    "porto colom": "portocolom",
    "port de portocolom": "portocolom",
}


PAIR_METRICS = {}
STATIC_METRICS_COMPUTED_AT_UTC = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
FIXED_DISTANCE_TABLE = {
    ("palma", "ibiza"): 100.0,
    ("ibiza", "palma"): 100.0,
    ("ibiza", "formentera"): 15.0,
    ("formentera", "ibiza"): 15.0,
    ("palma", "portocolom"): 35.0,
    ("portocolom", "palma"): 35.0,
    ("palma", "alcudia"): 26.0,
    ("alcudia", "palma"): 26.0,
    ("alcudia", "ciutadella"): 30.0,
    ("ciutadella", "alcudia"): 30.0,
    ("palma", "port_de_palma"): 3.0,
    ("port_de_palma", "palma"): 3.0,
    ("palma", "port_adriano"): 15.0,
    ("port_adriano", "palma"): 15.0,
    ("palma", "can_pastilla"): 6.0,
    ("can_pastilla", "palma"): 6.0,
    ("palma", "soller"): 18.0,
    ("soller", "palma"): 18.0,
}


class PlaceDistanceResolver:
    def __init__(
        self,
        gcs_prefix: str = DEFAULT_COPERNICUS_GCS_PREFIX,
        waves_blob: str = DEFAULT_WAVES_BLOB,
        currents_blob: str = DEFAULT_CURRENTS_BLOB,
    ):
        self.gcs_prefix = gcs_prefix
        self.waves_blob = waves_blob
        self.currents_blob = currents_blob
        self._solver = None
        self._solver_loaded_at = None
        self._graph_metrics_cache = {}

    def resolve(self, origin_place_id: str, destination_place_id: str) -> dict:
        key = (origin_place_id, destination_place_id)
        fixed = FIXED_DISTANCE_TABLE.get(key)
        if fixed is not None:
            return self._fixed_metrics(origin_place_id, destination_place_id, fixed)
        if key not in self._graph_metrics_cache:
            self._graph_metrics_cache[key] = self._graph_metrics(origin_place_id, destination_place_id)
        return dict(self._graph_metrics_cache[key])

    def _fixed_metrics(self, origin_place_id: str, destination_place_id: str, distance_nm: float) -> dict:
        origin = place_definition(origin_place_id)
        destination = place_definition(destination_place_id)
        typical_travel_time_minutes = int(round((float(distance_nm) / DEFAULT_TRAVEL_SPEED_KN) * 60.0))
        return {
            "origin_place_id": origin_place_id,
            "origin_place_name": origin["name"],
            "destination_place_id": destination_place_id,
            "destination_place_name": destination["name"],
            "distance_nm": float(distance_nm),
            "typical_speed_kn": DEFAULT_TRAVEL_SPEED_KN,
            "typical_travel_time_minutes": typical_travel_time_minutes,
            "computed_at_utc": STATIC_METRICS_COMPUTED_AT_UTC,
            "source_tag": "place_distance_table_v1",
        }

    def _graph_metrics(self, origin_place_id: str, destination_place_id: str) -> dict:
        origin = place_definition(origin_place_id)
        destination = place_definition(destination_place_id)
        solver = self._route_solver()
        result = solver.solve(
            origin_lat=float(origin["latitude"]),
            origin_lon=float(origin["longitude"]),
            destination_lat=float(destination["latitude"]),
            destination_lon=float(destination["longitude"]),
            origin_place_id=origin_place_id,
            destination_place_id=destination_place_id,
            vessel_speed_kn=GRAPH_FALLBACK_SPEED_KN,
            forecast_run_utc="",
            computed_at_utc=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        )
        if result is None:
            raise ValueError(
                f"No navigable graph route found for '{origin_place_id}' -> '{destination_place_id}'"
            )
        return {
            "origin_place_id": result.origin_place_id,
            "origin_place_name": origin["name"],
            "destination_place_id": result.destination_place_id,
            "destination_place_name": destination["name"],
            "distance_nm": float(result.distance_nm),
            "typical_speed_kn": GRAPH_FALLBACK_SPEED_KN,
            "typical_travel_time_minutes": int(round(result.estimated_time_h * 60.0)),
            "computed_at_utc": result.computed_at_utc or STATIC_METRICS_COMPUTED_AT_UTC,
            "source_tag": "graph_sea_route_v1",
        }

    def _route_solver(self):
        if self._solver is not None:
            return self._solver
        waves_path = self._download_gcs_blob(self.waves_blob)
        currents_path = self._download_gcs_blob(self.currents_blob)
        from route_graph import MaritimeGrid
        from route_solver import RouteSolver

        grid = MaritimeGrid.from_netcdf(waves_path, currents_path)
        grid.build_vertex_index()
        grid.build_graph(
            priority="time",
            vessel_class="medium",
            vessel_speed_kn=GRAPH_FALLBACK_SPEED_KN,
        )
        self._solver = RouteSolver(grid)
        self._solver_loaded_at = datetime.now(timezone.utc).isoformat()
        logger.info("Loaded graph fallback solver at %s", self._solver_loaded_at)
        return self._solver

    def _download_gcs_blob(self, blob_name: str) -> str:
        bucket_name, prefix = self.gcs_prefix[5:].split("/", 1)
        full_blob_name = f"{prefix}/{blob_name}".lstrip("/")
        local_path = Path(gettempdir()) / full_blob_name.replace("/", "_")
        if local_path.exists():
            return str(local_path)
        try:
            from google.cloud import storage

            client = storage.Client()
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(full_blob_name)
            blob.download_to_filename(str(local_path))
            logger.info("Downloaded %s -> %s", f"{self.gcs_prefix}/{blob_name}", local_path)
            return str(local_path)
        except Exception as error:
            logger.error("Unable to download %s: %s", f"{self.gcs_prefix}/{blob_name}", error)
            raise


PLACE_DISTANCE_RESOLVER = PlaceDistanceResolver()


def available_place_ids():
    return sorted(PLACE_CATALOG)


def place_definition(place_id):
    try:
        return PLACE_CATALOG[place_id]
    except KeyError as error:
        available = ", ".join(available_place_ids())
        raise ValueError(f"Unknown place '{place_id}'. Available places: {available}") from error


def default_place_id_for_query(query):
    if query is None:
        return None
    normalized = " ".join(str(query).strip().lower().split())
    return DEFAULT_PLACE_BY_QUERY.get(normalized)


def station_candidates_for_place(place_id):
    place = place_definition(place_id)
    return list(place.get("observation_candidates") or ())


def place_pair_metrics(origin_place_id, destination_place_id):
    key = (origin_place_id, destination_place_id)
    if key not in PAIR_METRICS:
        PAIR_METRICS[key] = PLACE_DISTANCE_RESOLVER.resolve(origin_place_id, destination_place_id)
    return dict(PAIR_METRICS[key])


def coordinates_connection_metrics(
    *,
    origin_place_id,
    origin_place_name,
    origin_latitude,
    origin_longitude,
    destination_place_id,
    destination_place_name,
    destination_latitude,
    destination_longitude,
    typical_speed_kn=DEFAULT_TRAVEL_SPEED_KN,
):
    distance_nm = round(
        _haversine_nm(
            float(origin_latitude),
            float(origin_longitude),
            float(destination_latitude),
            float(destination_longitude),
        ),
        1,
    )
    typical_speed_kn = float(typical_speed_kn or DEFAULT_TRAVEL_SPEED_KN)
    typical_travel_time_minutes = int(round((distance_nm / typical_speed_kn) * 60.0))
    return {
        "origin_place_id": origin_place_id,
        "origin_place_name": origin_place_name,
        "destination_place_id": destination_place_id,
        "destination_place_name": destination_place_name,
        "distance_nm": distance_nm,
        "typical_speed_kn": typical_speed_kn,
        "typical_travel_time_minutes": typical_travel_time_minutes,
        "computed_at_utc": STATIC_METRICS_COMPUTED_AT_UTC,
        "source_tag": "place_registry_v1",
    }


def place_family(place_id):
    place = place_definition(place_id)
    parent_place_id = place.get("parent_place_id")
    if parent_place_id is None:
        return {
            "place_id": place_id,
            "place_name": place["name"],
            "parent_place_id": None,
            "children": list(place.get("children") or ()),
        }
    parent = place_definition(parent_place_id)
    return {
        "place_id": place_id,
        "place_name": place["name"],
        "parent_place_id": parent_place_id,
        "parent_place_name": parent["name"],
        "children": list(place.get("children") or ()),
    }
