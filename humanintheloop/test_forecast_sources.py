import forecast_sources


def test_configured_forecast_sources_default_to_copernicus_only(monkeypatch):
    monkeypatch.delenv("PREDSEA_ENABLE_SOCIB_MODEL_FORECASTS", raising=False)

    assert forecast_sources.configured_source_ids() == ["copernicus"]


def test_configured_forecast_sources_can_opt_into_socib_models(monkeypatch):
    monkeypatch.setenv("PREDSEA_ENABLE_SOCIB_MODEL_FORECASTS", "1")

    assert forecast_sources.configured_source_ids() == ["copernicus", "socib"]


def test_source_output_dir_uses_existing_socib_folder_name():
    assert forecast_sources.source_output_dir("socib", "/tmp/predsea").name == "socib_thredds"
