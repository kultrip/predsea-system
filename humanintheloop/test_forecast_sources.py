import forecast_sources


class FakeFetchData:
    OUTPUT_DIR = "/tmp/predsea-test-output"


def test_configured_forecast_sources_default_to_copernicus_only(monkeypatch):
    monkeypatch.delenv("PREDSEA_ENABLE_SOCIB_MODEL_FORECASTS", raising=False)

    assert forecast_sources.configured_source_ids() == ["copernicus"]


def test_configured_forecast_sources_can_opt_into_socib_models(monkeypatch):
    monkeypatch.setenv("PREDSEA_ENABLE_SOCIB_MODEL_FORECASTS", "1")

    assert forecast_sources.configured_source_ids() == ["copernicus", "socib"]


def test_source_output_dir_uses_existing_socib_folder_name():
    assert forecast_sources.source_output_dir("socib", "/tmp/predsea").name == "socib_thredds"


def test_fetch_available_forecasts_calls_configured_sources_without_scoping_error(monkeypatch, tmp_path):
    monkeypatch.delenv("PREDSEA_ENABLE_SOCIB_MODEL_FORECASTS", raising=False)

    result = forecast_sources.fetch_available_forecasts(
        FakeFetchData,
        output_dir=tmp_path,
        dry_run=True,
    )

    assert [source["id"] for source in result] == ["copernicus"]
    assert result[0]["available"] is True
