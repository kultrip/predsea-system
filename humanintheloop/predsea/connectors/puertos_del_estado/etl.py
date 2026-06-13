from __future__ import annotations

from . import catalog, client, normalizer, parser


def fetch_puertos_observations(
    *,
    dry_run=False,
    timeout=60,
    max_retries=3,
    backoff_seconds=2,
    cache_dir=None,
    session=None,
):
    if dry_run:
        return {
            "observations": {},
            "measurements": {},
            "lineage": {
                "source": "puertos_del_estado",
                "status": "unavailable",
                "stations_matched": 0,
                "station_ids": [],
            },
            "errors": {},
            "source": "puertos_del_estado",
            "catalog_count": 0,
            "catalog_stations": [],
            "cache_paths": [],
        }
    discovered = catalog.discover_observation_stations(
        session=session,
        timeout=timeout,
        max_retries=max_retries,
        backoff_seconds=backoff_seconds,
        cache_dir=cache_dir,
    )
    observations = {}
    station_measurements = {}
    errors = {}
    matched_station_ids = []
    cache_paths = []

    for station in discovered:
        station_key = station["station_key"]
        if dry_run:
            observations[station_key] = {
                "source": "puertos_del_estado",
                "provider": "puertos_del_estado",
                "station_id": station["station_id"],
                "station_name": station["station_name"],
                "catalog_id": station["catalog_id"],
                "dry_run": True,
            }
            continue
        try:
            dataset = client.open_dataset(
                station["latest_dataset_url"],
                timeout=timeout,
                max_retries=max_retries,
                backoff_seconds=backoff_seconds,
            )
            try:
                measurements = parser.parse_station_dataset(
                    dataset,
                    station,
                    dataset_url=station["latest_dataset_url"],
                )
            finally:
                dataset.close()

            if not measurements:
                errors[station_key] = "no supported measurements found"
                continue

            record = normalizer.measurements_to_observation_record(station, measurements)
            observations[station_key] = record
            station_measurements[station_key] = measurements
            matched_station_ids.append(station["station_id"])
        except Exception as error:  # pragma: no cover - network path
            errors[station_key] = str(error)

    lineage = {
        "source": "puertos_del_estado",
        "status": "matched_successfully" if observations else "unavailable",
        "stations_matched": len(matched_station_ids),
        "station_ids": matched_station_ids,
    }
    return {
        "observations": observations,
        "measurements": station_measurements,
        "lineage": lineage,
        "errors": errors,
        "source": "puertos_del_estado",
        "catalog_count": len(discovered),
        "catalog_stations": discovered,
        "cache_paths": [path for path in cache_paths if path],
    }
