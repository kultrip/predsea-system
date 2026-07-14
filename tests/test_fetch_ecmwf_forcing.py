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


def test_validate_wps_reference_times_accepts_raw_valid_time_at_zero_lead(
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
                "dataTime": 300,
                "validityDate": 20260714,
                "validityTime": 300,
                "forecastTime": 0,
            },
        ]
    )
    monkeypatch.setattr(fetch_ecmwf_forcing, "eccodes", fake)

    fetch_ecmwf_forcing.validate_wps_reference_times(path)


def test_validate_wps_reference_times_rejects_old_cycle_hidden_by_validity_alias(
    monkeypatch, tmp_path
):
    path = tmp_path / "forcing.grib2"
    path.write_bytes(b"grib")
    fake = FakeEccodes(
        [
            {
                "dataDate": 20260713,
                "dataTime": 1200,
                "validityDate": 20260714,
                "validityTime": 0,
                "forecastTime": 12,
            }
        ]
    )
    monkeypatch.setattr(fetch_ecmwf_forcing, "eccodes", fake)

    with pytest.raises(RuntimeError, match="raw reference times"):
        fetch_ecmwf_forcing.validate_wps_reference_times(path)
