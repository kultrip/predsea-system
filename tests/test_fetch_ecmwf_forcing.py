from pathlib import Path

import pytest

from scripts import fetch_ecmwf_forcing


class FakeEccodes:
    def __init__(self, messages):
        self.messages = messages
        self.index = 0

    def codes_grib_new_from_file(self, file_obj):
        if self.index >= len(self.messages):
            return None
        message = self.messages[self.index]
        self.index += 1
        return message

    @staticmethod
    def codes_get(message, key):
        return message[key]

    @staticmethod
    def codes_release(message):
        return None


def test_skip_if_exists_validates_forecast_metadata(monkeypatch, tmp_path):
    """Cached valid-time files must not bypass the WPS metadata check."""
    monkeypatch.setattr(
        fetch_ecmwf_forcing,
        "parse_args",
        lambda: type(
            "Args",
            (),
            {
                "run_date": "2026-07-14",
                "run_time": 0,
                "lead_hours": 3,
                "output_dir": tmp_path,
                "gcs_bucket": "",
                "dry_run": False,
                "skip_if_exists": True,
            },
        )(),
    )
    for kind in ("pl", "sfc"):
        (tmp_path / f"ecmwf_{kind}_2026-07-14_00Z.grib2").write_bytes(b"stale")

    monkeypatch.setattr(fetch_ecmwf_forcing, "validate_forcing_files", lambda *args: None)
    metadata_checks = []

    def reject_stale(path, *args):
        metadata_checks.append(path.name)
        raise RuntimeError("step-zero metadata")

    monkeypatch.setattr(fetch_ecmwf_forcing, "validate_forecast_metadata", reject_stale)

    def stop_after_cache_rejection(**kwargs):
        assert not (tmp_path / "ecmwf_pl_2026-07-14_00Z.grib2").exists()
        assert not (tmp_path / "ecmwf_sfc_2026-07-14_00Z.grib2").exists()
        raise RuntimeError("stop test")

    monkeypatch.setattr(fetch_ecmwf_forcing, "fetch_ecmwf_data", stop_after_cache_rejection)

    with pytest.raises(SystemExit):
        fetch_ecmwf_forcing.main()

    assert metadata_checks == ["ecmwf_pl_2026-07-14_00Z.grib2"]


def test_validate_forecast_metadata_accepts_cycle_and_forecast_leads(
    monkeypatch, tmp_path
):
    path = tmp_path / "forcing.grib2"
    path.write_bytes(b"grib")
    fake = FakeEccodes(
        [
            {
                "dataDate": 20260714,
                "dataTime": 0,
                "validityDate": 20260714,
                "validityTime": 0,
                "forecastTime": 0,
            },
            {
                "dataDate": 20260714,
                "dataTime": 0,
                "validityDate": 20260714,
                "validityTime": 300,
                "forecastTime": 3,
            },
        ]
    )
    monkeypatch.setattr(fetch_ecmwf_forcing, "eccodes", fake)

    fetch_ecmwf_forcing.validate_forecast_metadata(path, "2026-07-14", 0, [0, 3])


def test_validate_forecast_metadata_rejects_rewritten_step_zero_messages(
    monkeypatch, tmp_path
):
    path = tmp_path / "forcing.grib2"
    path.write_bytes(b"grib")
    fake = FakeEccodes(
        [
            {
                "dataDate": 20260714,
                "dataTime": 300,
                "validityDate": 20260714,
                "validityTime": 300,
                "forecastTime": 0,
            }
        ]
    )
    monkeypatch.setattr(fetch_ecmwf_forcing, "eccodes", fake)

    with pytest.raises(RuntimeError, match="preserve the ECMWF cycle reference"):
        fetch_ecmwf_forcing.validate_forecast_metadata(path, "2026-07-14", 0, [0, 3])
