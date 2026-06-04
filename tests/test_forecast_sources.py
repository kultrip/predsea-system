import json
import subprocess
import sys
from pathlib import Path

import pytest


HUMANINTHELOOP_DIR = Path(__file__).resolve().parents[1] / "humanintheloop"
if str(HUMANINTHELOOP_DIR) not in sys.path:
    sys.path.insert(0, str(HUMANINTHELOOP_DIR))

import forecast_sources


def test_fetch_source_via_subprocess_marks_timeout_unavailable(tmp_path, monkeypatch):
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=12)

    monkeypatch.setattr(forecast_sources.subprocess, "run", fake_run)

    result = forecast_sources.fetch_source_via_subprocess(
        "socib",
        tmp_path / "socib",
        timeout_seconds=12,
    )

    assert result["id"] == "socib"
    assert result["available"] is False
    assert "timed out after 12s" in result["error"]


def test_fetch_source_via_subprocess_reads_metadata_from_successful_source(tmp_path, monkeypatch):
    source_dir = tmp_path / "copernicus"
    source_dir.mkdir()
    metadata_path = source_dir / "forecast_source.json"
    metadata_path.write_text(
        json.dumps(
            {
                "id": "copernicus",
                "label": "Copernicus Marine Mediterranean forecast",
                "available": True,
                "waves_path": str(source_dir / "balearic_waves.nc"),
                "currents_path": str(source_dir / "balearic_currents.nc"),
            }
        ),
        encoding="utf-8",
    )

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="ok\n", stderr="")

    monkeypatch.setattr(forecast_sources.subprocess, "run", fake_run)

    result = forecast_sources.fetch_source_via_subprocess(
        "copernicus",
        source_dir,
        timeout_seconds=30,
    )

    assert result["available"] is True
    assert result["waves_path"] == source_dir / "balearic_waves.nc"
    assert result["currents_path"] == source_dir / "balearic_currents.nc"


def test_fetch_available_forecasts_runs_sources_independently(tmp_path, monkeypatch, capsys):
    calls = []

    def fake_fetch(source_id, output_dir, timeout_seconds, dry_run=False):
        calls.append((source_id, Path(output_dir), timeout_seconds, dry_run))
        return {
            "id": source_id,
            "label": source_id,
            "available": source_id == "socib",
            "waves_path": Path(output_dir) / "balearic_waves.nc",
            "currents_path": Path(output_dir) / "balearic_currents.nc",
        }

    monkeypatch.setattr(forecast_sources, "fetch_source_via_subprocess", fake_fetch)
    monkeypatch.setenv("PREDSEA_SOURCE_TIMEOUT_SECONDS", "77")

    class FetchData:
        OUTPUT_DIR = str(tmp_path / "mvp_data")

    results = forecast_sources.fetch_available_forecasts(FetchData())

    assert [call[0] for call in calls] == ["copernicus", "socib"]
    assert all(call[2] == 77 for call in calls)
    assert results[0]["available"] is False
    assert results[1]["available"] is True
    assert results[1]["preferred"] is True
    output = capsys.readouterr().out
    assert "Fetching forecast source: copernicus" in output
    assert "Forecast source unavailable: copernicus" in output
    assert "Forecast source ready: socib" in output
