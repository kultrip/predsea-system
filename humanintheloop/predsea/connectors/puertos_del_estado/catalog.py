from __future__ import annotations

import re
import unicodedata
from urllib.parse import urljoin

from .client import fetch_text


ROOT_CATALOG_URL = "https://opendap.puertos.es/thredds/catalog.html"
CATALOG_BASE_URL = "https://opendap.puertos.es/thredds/catalog"
DODS_BASE_URL = "https://opendap.puertos.es/thredds/dodsC"

STATION_FOLDER_PATTERN = re.compile(
    r'href="(?P<href>/thredds/catalog/(?P<catalog_id>tidegauge_[^"/]+)/catalog\.html)"[^>]*><code>(?P<label>[^<]+)</code>',
    re.IGNORECASE,
)
YEAR_PATTERN = re.compile(r'href="(?P<href>\d{4}/catalog\.html)"', re.IGNORECASE)
MONTH_PATTERN = re.compile(r'href="(?P<href>\d{2}/catalog\.html)"', re.IGNORECASE)
DATASET_PATTERN = re.compile(
    r'href="(?:/thredds/)?catalog\.html\?dataset=(?P<dataset>[^"]+\.nc4)"',
    re.IGNORECASE,
)


def _strip_accents(text):
    normalized = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def station_key_from_label(label):
    base = re.sub(r"\s*\(.*?\)", "", str(label or "").strip())
    base = _strip_accents(base)
    base = re.sub(r"[^a-zA-Z0-9]+", "_", base.lower()).strip("_")
    return base


def station_id_from_label(label):
    key = station_key_from_label(label)
    return f"puertos_{key}" if key else None


def _absolute_catalog_url(href):
    if href.startswith("http://") or href.startswith("https://"):
        return href
    return urljoin("https://opendap.puertos.es", href)


def _fetch_html(url, *, session=None, timeout=60, max_retries=3, backoff_seconds=2, cache_dir=None, cache_key=None):
    result = fetch_text(
        url,
        session=session,
        timeout=timeout,
        max_retries=max_retries,
        backoff_seconds=backoff_seconds,
        cache_dir=cache_dir,
        cache_key=cache_key,
    )
    return result["text"], result.get("cache_path")


def discover_station_catalogs(
    *,
    session=None,
    timeout=60,
    max_retries=3,
    backoff_seconds=2,
    cache_dir=None,
):
    html, _ = _fetch_html(
        ROOT_CATALOG_URL,
        session=session,
        timeout=timeout,
        max_retries=max_retries,
        backoff_seconds=backoff_seconds,
        cache_dir=cache_dir,
        cache_key="puertos_root_catalog",
    )
    stations = []
    for match in STATION_FOLDER_PATTERN.finditer(html):
        catalog_id = match.group("catalog_id")
        label = match.group("label").strip()
        href = match.group("href")
        station_id = station_id_from_label(label)
        stations.append(
            {
                "source_system": "puertos_del_estado",
                "catalog_id": catalog_id,
                "catalog_url": _absolute_catalog_url(href),
                "station_id": station_id,
                "station_name": label,
                "station_key": station_key_from_label(label),
            }
        )
    return sorted(stations, key=lambda item: item["station_name"].lower())


def _latest_link(links):
    if not links:
        return None
    return sorted(links)[-1]


def discover_latest_dataset_url(
    station_catalog_url,
    *,
    session=None,
    timeout=60,
    max_retries=3,
    backoff_seconds=2,
    cache_dir=None,
    prefer_raw=True,
):
    station_html, _ = _fetch_html(
        station_catalog_url,
        session=session,
        timeout=timeout,
        max_retries=max_retries,
        backoff_seconds=backoff_seconds,
        cache_dir=cache_dir,
        cache_key=f"puertos_catalog_{station_catalog_url.rsplit('/', 2)[-2]}",
    )
    year_links = sorted({match.group("href") for match in YEAR_PATTERN.finditer(station_html)})
    for year_href in reversed(year_links):
        year_url = urljoin(station_catalog_url, year_href)
        year_html, _ = _fetch_html(
            year_url,
            session=session,
            timeout=timeout,
            max_retries=max_retries,
            backoff_seconds=backoff_seconds,
            cache_dir=cache_dir,
            cache_key=f"puertos_year_{year_href.replace('/', '_')}",
        )
        month_links = sorted({match.group("href") for match in MONTH_PATTERN.finditer(year_html)})
        for month_href in reversed(month_links):
            month_url = urljoin(year_url, month_href)
            month_html, _ = _fetch_html(
                month_url,
                session=session,
                timeout=timeout,
                max_retries=max_retries,
                backoff_seconds=backoff_seconds,
                cache_dir=cache_dir,
                cache_key=f"puertos_month_{month_href.replace('/', '_')}",
            )
            dataset_links = sorted({match.group("dataset") for match in DATASET_PATTERN.finditer(month_html)})
            if not dataset_links:
                continue
            raw_links = [link for link in dataset_links if "_analysis" not in link]
            chosen = _latest_link(raw_links or dataset_links)
            if chosen:
                return urljoin(DODS_BASE_URL + "/", chosen)
    return None


def discover_observation_stations(
    *,
    session=None,
    timeout=60,
    max_retries=3,
    backoff_seconds=2,
    cache_dir=None,
):
    stations = discover_station_catalogs(
        session=session,
        timeout=timeout,
        max_retries=max_retries,
        backoff_seconds=backoff_seconds,
        cache_dir=cache_dir,
    )
    discovered = []
    for station in stations:
        latest_dataset_url = discover_latest_dataset_url(
            station["catalog_url"],
            session=session,
            timeout=timeout,
            max_retries=max_retries,
            backoff_seconds=backoff_seconds,
            cache_dir=cache_dir,
        )
        if not latest_dataset_url:
            continue
        discovered.append(
            {
                **station,
                "latest_dataset_url": latest_dataset_url,
            }
        )
    return discovered

