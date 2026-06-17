import json
import os
import subprocess
import sys
from pathlib import Path


COPERNICUS_SOURCE = {
    "id": "copernicus",
    "label": "Copernicus Marine Mediterranean forecast",
}
SOCIB_SOURCE = {
    "id": "socib",
    "label": "SOCIB WMOP/SAPO forecast",
}
SOURCE_TIMEOUT_SECONDS = int(os.getenv("PREDSEA_SOURCE_TIMEOUT_SECONDS", "900"))
SOURCE_ATTEMPTS = int(os.getenv("PREDSEA_SOURCE_ATTEMPTS", "1"))


def fetch_available_forecasts(fetch_data, output_dir=None, dry_run=False):
    """Fetch all configured forecast sources without letting one source block another."""
    output_dir = Path(output_dir or fetch_data.OUTPUT_DIR)
    timeout_seconds = int(os.getenv("PREDSEA_SOURCE_TIMEOUT_SECONDS", str(SOURCE_TIMEOUT_SECONDS)))
    attempts = int(os.getenv("PREDSEA_SOURCE_ATTEMPTS", str(SOURCE_ATTEMPTS)))
    source_configs = [
        (source_id, source_output_dir(source_id, output_dir))
        for source_id in configured_source_ids()
    ]
    sources = []
    for source_id, output_path in source_configs:
        print(f"Fetching forecast source: {source_id}", flush=True)
        print(f"  Output directory: {output_path}", flush=True)
        source = fetch_source_with_attempts(
            source_id,
            output_path,
            timeout_seconds=timeout_seconds,
            attempts=attempts,
            dry_run=dry_run,
        )
        if source.get("available"):
            waves_path = source.get("waves_path")
            currents_path = source.get("currents_path")
            print(
                f"Forecast source ready: {source_id} "
                f"(waves={waves_path}, currents={currents_path})",
                flush=True,
            )
        else:
            print(f"Forecast source unavailable: {source_id} ({source.get('error')})", flush=True)
        sources.append(source)
    mark_preferred_source(sources)
    return sources


def configured_source_ids():
    return ["copernicus"]


def source_output_dir(source_id, output_dir):
    output_dir = Path(output_dir)
    if source_id == "socib":
        return output_dir / "socib_thredds"
    return output_dir / source_id


def fetch_source_with_attempts(source_id, output_dir, timeout_seconds, attempts=1, dry_run=False):
    attempts = max(1, int(attempts))
    last_source = None
    for attempt in range(1, attempts + 1):
        if attempt > 1:
            print(f"Retrying forecast source: {source_id} (attempt {attempt}/{attempts})", flush=True)
        source = fetch_source_via_subprocess(
            source_id,
            output_dir,
            timeout_seconds=timeout_seconds,
            dry_run=dry_run,
        )
        if source.get("available"):
            if attempt > 1:
                source.setdefault("metadata", {})["fetch_attempt"] = attempt
            return source
        last_source = source
    if last_source is not None and attempts > 1:
        last_source["error"] = f"failed after {attempts} attempt(s): {last_source.get('error')}"
    return last_source or source_template(source_id)


def fetch_source_via_subprocess(source_id, output_dir, timeout_seconds, dry_run=False):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    source = source_template(source_id)
    metadata_path = output_dir / "forecast_source.json"
    command = [
        sys.executable,
        str(Path(__file__).with_name("fetch_forecast_source.py")),
        "--source",
        source_id,
        "--output-dir",
        str(output_dir),
    ]
    if dry_run:
        command.append("--dry-run")

    try:
        completed = subprocess.run(
            command,
            cwd=Path(__file__).parent,
            timeout=timeout_seconds,
            check=False,
            text=True,
            capture_output=True,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
    except subprocess.TimeoutExpired:
        source.update(available=False, error=f"{source_id} fetch timed out after {timeout_seconds}s")
        return source
    except Exception as error:
        source.update(available=False, error=str(error))
        return source

    if completed.stdout:
        print(completed.stdout.rstrip(), flush=True)
    if completed.stderr:
        print(completed.stderr.rstrip(), flush=True)

    if completed.returncode != 0:
        source.update(
            available=False,
            error=source_error_from_process(source_id, completed),
        )
        return source

    if not metadata_path.exists():
        source.update(available=False, error=f"{source_id} did not write {metadata_path.name}")
        return source

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["waves_path"] = Path(metadata["waves_path"])
    metadata["currents_path"] = Path(metadata["currents_path"])
    return metadata


def source_template(source_id):
    if source_id == "copernicus":
        return dict(COPERNICUS_SOURCE)
    if source_id == "socib":
        return dict(SOCIB_SOURCE)
    return {"id": source_id, "label": source_id}


def source_error_from_process(source_id, completed):
    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
    if not output:
        return f"{source_id} fetch exited with code {completed.returncode}"
    return output[-1000:]


def fetch_copernicus_forecast(fetch_data, dry_run=False):
    source = dict(COPERNICUS_SOURCE)
    try:
        result = fetch_data.get_balearic_forecast(dry_run=dry_run) or {}
        output_dir = Path(fetch_data.OUTPUT_DIR)
        source.update(
            available=True,
            waves_path=Path(result.get("waves_path") or output_dir / "balearic_waves.nc"),
            currents_path=Path(result.get("currents_path") or output_dir / "balearic_currents.nc"),
        )
    except Exception as error:
        source.update(available=False, error=str(error))
    return source


def fetch_socib_forecast(fetch_data, output_dir=None, dry_run=False):
    source = dict(SOCIB_SOURCE)
    try:
        import socib_thredds

        target_dir = Path(output_dir or fetch_data.OUTPUT_DIR) / "socib_thredds"
        result = socib_thredds.get_balearic_forecast(output_dir=target_dir, dry_run=dry_run)
        source.update(
            available=True,
            waves_path=Path(result["waves_path"]),
            currents_path=Path(result["currents_path"]),
            metadata=result.get("metadata", {}),
        )
    except Exception as error:
        source.update(available=False, error=str(error))
    return source


def mark_preferred_source(sources, preferred_source_id="copernicus"):
    available = [source for source in sources if source.get("available")]
    for source in sources:
        source["preferred"] = False
    if not available:
        return sources

    preferred = next(
        (source for source in available if source.get("id") == preferred_source_id),
        available[0],
    )
    preferred["preferred"] = True
    return sources


def source_manifest_entry(source):
    entry = {
        "id": source.get("id"),
        "label": source.get("label"),
        "available": bool(source.get("available")),
        "preferred": bool(source.get("preferred")),
    }
    if source.get("error"):
        entry["error"] = source["error"]
    if source.get("metadata"):
        entry["metadata"] = source["metadata"]
    if source.get("waves_path"):
        entry["waves_path"] = str(source["waves_path"])
    if source.get("currents_path"):
        entry["currents_path"] = str(source["currents_path"])
    return entry
