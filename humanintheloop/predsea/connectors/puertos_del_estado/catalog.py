from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from urllib.parse import urljoin

from .client import fetch_json, fetch_text
from .common import NETWORK_LABELS, clean_station_name, normalize_text, station_id_from_label, station_key_from_label


ROOT_CATALOG_URL = "https://opendap.puertos.es/thredds/catalog.xml"
THREDDS_BASE_URL = "https://opendap.puertos.es/thredds"
PORTUSCOPIA_API_BASE = "https://portuscopia.puertos.es/portuscopiasvr/api"

# Updated pattern to capture tide gauges, buoys, weather stations, and other observation types
# Matches: tidegauge_*, boya_*, weather_*, meteo_*, etc.
STATION_FOLDER_PATTERN = re.compile(
    r'href="(?P<href>/thredds/catalog/(?P<catalog_id>(?:tidegauge|boya|weather|meteo|buoy|station)[^"/]*)/catalog\.html)"[^>]*><code>(?P<label>[^<]+)</code>',
    re.IGNORECASE,
)
YEAR_PATTERN = re.compile(r'href="(?P<href>\d{4}/catalog\.html)"', re.IGNORECASE)
MONTH_PATTERN = re.compile(r'href="(?P<href>\d{2}/catalog\.html)"', re.IGNORECASE)
DATASET_PATTERN = re.compile(
    r'href="(?:/thredds/)?catalog\.html\?dataset=(?P<dataset>[^"]+\.nc4)"',
    re.IGNORECASE,
)
SUPPORTED_NETWORKS = {"redext", "redcos", "redmar"}


def _absolute_thredds_url(href):
    if not href:
        return None
    if href.startswith("http://") or href.startswith("https://"):
        return href
    return urljoin("https://opendap.puertos.es/", href.lstrip("/"))


def _discover_root_catalog_refs(*, session=None, timeout=60, max_retries=3, backoff_seconds=2, cache_dir=None):
    result = fetch_text(
        ROOT_CATALOG_URL,
        session=session,
        timeout=timeout,
        max_retries=max_retries,
        backoff_seconds=backoff_seconds,
        cache_dir=cache_dir,
        cache_key="puertos_root_catalog",
    )
    xml = result["text"]
    root = ET.fromstring(xml)
    ns = {"t": "http://www.unidata.ucar.edu/namespaces/thredds/InvCatalog/v1.0"}
    refs = []
    for ref in root.findall(".//t:catalogRef", ns):
        name = ref.attrib.get("name")
        href = ref.attrib.get("{http://www.w3.org/1999/xlink}href")
        if not name or not href:
            continue
        absolute = _absolute_thredds_url(href)
        if absolute:
            refs.append({"name": name, "href": href, "catalog_url": absolute})
    return refs


def _root_ref_index(refs, *, prefix=None):
    grouped = defaultdict(list)
    for ref in refs:
        if prefix and not ref["href"].split("/")[-2].startswith(prefix):
            continue
        grouped[normalize_text(ref["name"])].append(ref)
    return grouped


def _score_catalog_match(station_name, candidate_name):
    station_key = normalize_text(clean_station_name(station_name))
    candidate_key = normalize_text(clean_station_name(candidate_name))
    if not station_key or not candidate_key:
        return -10
    if station_key == candidate_key:
        return 100
    station_tokens = set(station_key.split("_"))
    candidate_tokens = set(candidate_key.split("_"))
    overlap = len(station_tokens & candidate_tokens)
    score = overlap * 10
    if station_key in candidate_key or candidate_key in station_key:
        score += 30
    score -= abs(len(station_key) - len(candidate_key)) // 4
    return score


def _best_catalog_ref(name, refs, *, prefix=None):
    if not refs:
        return None
    candidates = [ref for ref in refs if prefix is None or ref["href"].split("/")[-2].startswith(prefix)]
    if not candidates:
        candidates = list(refs)
    best = None
    best_score = None
    for ref in candidates:
        score = _score_catalog_match(name, ref["name"])
        if best is None or score > best_score:
            best = ref
            best_score = score
    return best


def _entry_network(entry):
    categories = entry.get("categories") or {}
    device = normalize_text(categories.get("device"))
    station_name = entry.get("Name") or ""
    if device in {"tide_gaude", "tide_gauge"}:
        return "redmar"
    if device == "buoy":
        if "costera" in normalize_text(station_name):
            return "redcos"
        return "redext"
    return None


def _portuscopia_catalogs_for_device(device, *, session=None, timeout=60, max_retries=3, backoff_seconds=2, cache_dir=None):
    payload = {"dataType": ["measure"], "device": [device], "variable": [], "scale": []}
    result = fetch_json(
        f"{PORTUSCOPIA_API_BASE}/tree/catalogs",
        method="post",
        json_data=payload,
        session=session,
        timeout=timeout,
        max_retries=max_retries,
        backoff_seconds=backoff_seconds,
        cache_dir=cache_dir,
        cache_key=f"puertos_tree_catalogs_{device}",
    )
    return result["json"]


def _merge_catalog_entries(entries):
    merged = {}
    for entry in entries:
        catalog_id = entry.get("catalogRefID") or entry.get("Xlink") or entry.get("Name")
        if not catalog_id:
            continue
        current = merged.setdefault(
            catalog_id,
            {
                **entry,
                "variablesInfo": [],
                "categories": {},
            },
        )
        current["Name"] = entry.get("Name") or current.get("Name")
        current["Xlink"] = entry.get("Xlink") or current.get("Xlink")
        current["portusLink"] = entry.get("portusLink") or current.get("portusLink")
        current["coords"] = entry.get("coords") or current.get("coords")
        current["bounds"] = entry.get("bounds") or current.get("bounds")
        current["dateFrom"] = entry.get("dateFrom") or current.get("dateFrom")
        current["dateTo"] = entry.get("dateTo") or current.get("dateTo")
        current["isPoint"] = entry.get("isPoint") if entry.get("isPoint") is not None else current.get("isPoint")
        current["availableMean"] = entry.get("availableMean") or current.get("availableMean")
        current["hourStep"] = entry.get("hourStep") or current.get("hourStep")
        current["netcdf4"] = entry.get("netcdf4") if entry.get("netcdf4") is not None else current.get("netcdf4")
        current.setdefault("variablesInfo", [])
        current["variablesInfo"].extend(entry.get("variablesInfo") or [])
        current.setdefault("categories", {})
        current["categories"].update(entry.get("categories") or {})
    return list(merged.values())


def _catalog_url_for_station(entry, network, root_refs):
    xlink = entry.get("Xlink")
    if isinstance(xlink, str) and xlink.startswith("/thredds/catalog/"):
        return _absolute_thredds_url(xlink)
    if isinstance(xlink, str) and xlink.startswith("https://opendap.puertos.es/thredds/catalog/"):
        return xlink
    name = entry.get("Name") or ""
    prefix = {
        "redmar": "tidegauge_",
        "redext": "wave_local_",
        "redcos": "wave_coast_",
    }.get(network)
    ref = _best_catalog_ref(name, root_refs, prefix=prefix)
    if ref:
        return ref["catalog_url"]
    return None


def discover_station_catalogs(
    *,
    session=None,
    timeout=60,
    max_retries=3,
    backoff_seconds=2,
    cache_dir=None,
):
    refs = _discover_root_catalog_refs(
        session=session,
        timeout=timeout,
        max_retries=max_retries,
        backoff_seconds=backoff_seconds,
        cache_dir=cache_dir,
    )
    entries = []
    for device in ("buoy", "tide_gaude", "radar"):
        try:
            entries.extend(
                _portuscopia_catalogs_for_device(
                    device,
                    session=session,
                    timeout=timeout,
                    max_retries=max_retries,
                    backoff_seconds=backoff_seconds,
                    cache_dir=cache_dir,
                )
            )
        except Exception:
            continue

    merged = _merge_catalog_entries(entries)
    stations = []
    for entry in merged:
        network = _entry_network(entry)
        if network not in SUPPORTED_NETWORKS:
            continue
        station_name = entry.get("Name") or "Unknown"
        station_id = station_id_from_label(station_name)
        coords = entry.get("coords") or {}
        thredds_catalog_url = _catalog_url_for_station(entry, network, refs)
        if not thredds_catalog_url:
            continue
        station = {
            "source_system": "puertos_del_estado",
            "source_label": NETWORK_LABELS[network],
            "network": network,
            "catalog_id": entry.get("catalogRefID") or entry.get("Xlink") or station_name,
            "catalog_url": thredds_catalog_url,
            "portus_link": entry.get("portusLink"),
            "station_id": station_id,
            "station_name": station_name,
            "station_key": station_key_from_label(station_name),
            "latitude": coords.get("lat"),
            "longitude": coords.get("lon"),
            "variables_info": entry.get("variablesInfo") or [],
            "categories": entry.get("categories") or {},
            "is_point": entry.get("isPoint"),
        }
        stations.append(station)
    return sorted(stations, key=lambda item: (item["network"], item["station_name"].lower()))


def discover_latest_dataset_url(
    station_catalog_url,
    *,
    session=None,
    timeout=60,
    max_retries=3,
    backoff_seconds=2,
    cache_dir=None,
    _visited=None,
):
    if not station_catalog_url:
        return None
    visited = set(_visited or ())
    if station_catalog_url in visited:
        return None
    visited.add(station_catalog_url)

    fetched = fetch_text(
        station_catalog_url,
        session=session,
        timeout=timeout,
        max_retries=max_retries,
        backoff_seconds=backoff_seconds,
        cache_dir=cache_dir,
        cache_key=f"puertos_catalog_{normalize_text(station_catalog_url)}",
    )
    xml_text = fetched["text"]
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        root = None
    if root is not None:
        ns = {"t": "http://www.unidata.ucar.edu/namespaces/thredds/InvCatalog/v1.0"}
        dataset_urls = sorted(
            {
                dataset.attrib.get("urlPath")
                for dataset in root.findall(".//t:dataset", ns)
                if dataset.attrib.get("urlPath")
            }
        )
        if dataset_urls:
            raw_links = [link for link in dataset_urls if "_analysis" not in link.lower()]
            chosen = (raw_links or dataset_urls)[-1]
            return urljoin(THREDDS_BASE_URL.rstrip("/") + "/dodsC/", chosen)

        child_links = []
        for ref in root.findall(".//t:catalogRef", ns):
            href = ref.attrib.get("{http://www.w3.org/1999/xlink}href") or ref.attrib.get("xlink:href")
            if not href:
                continue
            if href.startswith("http://") or href.startswith("https://"):
                child_links.append(href)
            elif href.startswith("/thredds/"):
                child_links.append(_absolute_thredds_url(href))
            else:
                child_links.append(urljoin(station_catalog_url, href))
        child_links = sorted({link for link in child_links if link})
    else:
        html = xml_text
        dataset_links = sorted(
            set(
                match.group("dataset")
                for match in re.finditer(
                    r'href="(?:/thredds/)?catalog\.html\?dataset=(?P<dataset>[^"]+\.(?:nc4?|nc))"',
                    html,
                    re.IGNORECASE,
                )
            )
        )
        if dataset_links:
            raw_links = [link for link in dataset_links if "_analysis" not in link.lower()]
            chosen = (raw_links or dataset_links)[-1]
            return urljoin(THREDDS_BASE_URL.rstrip("/") + "/dodsC/", chosen)

        child_links = []
        for match in re.finditer(r'href="(?P<href>[^"]+/catalog\.xml)"', html, re.IGNORECASE):
            href = match.group("href")
            if href.startswith("http://") or href.startswith("https://"):
                child_links.append(href)
            elif href.startswith("/thredds/"):
                child_links.append(_absolute_thredds_url(href))
            else:
                child_links.append(urljoin(station_catalog_url, href))
        child_links = sorted({link for link in child_links if link})

    for child_url in reversed([link for link in child_links if link]):
        latest = discover_latest_dataset_url(
            child_url,
            session=session,
            timeout=timeout,
            max_retries=max_retries,
            backoff_seconds=backoff_seconds,
            cache_dir=cache_dir,
            _visited=visited,
        )
        if latest:
            return latest
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
