import forecast_sources


class FakeFetchData:
    OUTPUT_DIR = "/tmp/predsea-test-output"


def test_configured_forecast_sources_default_to_copernicus_only():
    assert forecast_sources.configured_source_ids() == ["copernicus"]


def test_fetch_available_forecasts_calls_configured_sources_without_scoping_error(monkeypatch, tmp_path):
    result = forecast_sources.fetch_available_forecasts(
        FakeFetchData,
        output_dir=tmp_path,
        dry_run=True,
    )

    assert [source["id"] for source in result] == ["copernicus"]
    assert result[0]["available"] is True
