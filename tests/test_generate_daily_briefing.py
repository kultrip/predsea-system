import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "generate_daily_briefing.py"


def load_runner():
    spec = importlib.util.spec_from_file_location("generate_daily_briefing", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeRouteAnalysis:
    DEFAULT_ROUTE_ID = "palma_ibiza"
    VESSEL_PROFILES = {"medium": {}, "small": {}, "large": {}}

    def load_routes(self):
        return {
            "palma_ibiza": {"id": "palma_ibiza", "name": "Palma -> Ibiza"},
            "palma_cabrera": {"id": "palma_cabrera", "name": "Palma -> Cabrera"},
        }

    def forecast_summary_from_files(self, waves_path, currents_path, route):
        return {
            "wave_min_m": 0.5,
            "wave_max_m": 1.1,
            "wave_peak_time": "14:00",
            "current_max_kn": 0.4,
            "current_peak_time": "15:00",
        }

    def build_route_snapshot(self, observations, forecast, route, vessel_class):
        return {
            "route_id": route["id"],
            "route": route["name"],
            "vessel_class": vessel_class,
            "observations": observations,
            "forecast": forecast,
            "recommendation": {"confidence": "medium"},
        }


class FakeBriefing:
    def load_observations(self):
        return {"canal_de_ibiza": {"wave_height_m": 0.9}}

    def write_outputs(self, snapshot, output_dir, question=None, location_label="Palma Marina", current_time=None, route=None):
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        (output_path / "daily_snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
        (output_path / "evidence.json").write_text(json.dumps({"decision_context": snapshot}), encoding="utf-8")
        (output_path / "briefing_linkedin.txt").write_text("linkedin", encoding="utf-8")
        (output_path / "briefing_whatsapp.txt").write_text("whatsapp", encoding="utf-8")
        (output_path / "briefing_whatsapp_screenshot_script.txt").write_text(
            "Captain: [Shared live location]\nPredSea: route read",
            encoding="utf-8",
        )


class UnavailableSocibBriefing(FakeBriefing):
    def load_observations(self):
        raise TimeoutError("SOCIB DataDiscovery timed out")


class FakeFetchData:
    OUTPUT_DIR = "./mvp_data"

    def __init__(self):
        self.calls = 0

    def get_balearic_forecast(self, dry_run=False):
        self.calls += 1


class FakeForecastSources:
    def __init__(self, sources):
        self.sources = sources

    def fetch_available_forecasts(self, fetch_data, output_dir=None, dry_run=False):
        return self.sources

    def source_manifest_entry(self, source):
        entry = {
            "id": source.get("id"),
            "label": source.get("label"),
            "available": bool(source.get("available")),
            "preferred": bool(source.get("preferred")),
        }
        if source.get("error"):
            entry["error"] = source["error"]
        return entry


class FakeChatFigure:
    def __init__(self):
        self.logo_paths = []

    def generate_chat_figure(self, script_path, logo_path, output_path, platform="WhatsApp"):
        self.logo_paths.append(Path(logo_path))
        Path(output_path).write_text("fake image", encoding="utf-8")


class FakeMapGenerator:
    def __init__(self):
        self.calls = []

    def generate_route_decision_map(self, waves_path, currents_path, route, snapshot, output_path):
        self.calls.append((Path(waves_path), Path(currents_path), route["id"], snapshot["route_id"]))
        Path(output_path).write_text("fake route map", encoding="utf-8")


def write_fake_map_indexes(output_dir, waves_path=None, currents_path=None, skip_maps=False):
    if skip_maps:
        return None
    maps_dir = Path(output_dir) / "maps"
    for variable, units, bounds in (
        ("wave_height", "m", [[38.5, 1.0], [40.5, 4.5]]),
        ("current_speed", "m/s", [[38.5, 1.0], [40.5, 4.5]]),
    ):
        variable_dir = maps_dir / variable
        variable_dir.mkdir(parents=True, exist_ok=True)
        (variable_dir / "index.json").write_text(
            json.dumps(
                {
                    "variable": variable,
                    "units": units,
                    "color_scale": {"min": 0, "max": 2.5, "palette": "turbo"},
                    "opacity": 0.698,
                    "overlays": [
                        {
                            "time": "2026-06-04T14:00:00Z",
                            "filename": f"{variable}_20260604_140000Z.png",
                            "grid_filename": f"{variable}_20260604_140000Z.grid.json",
                            "bounds": bounds,
                        },
                        {
                            "time": "2026-06-04T15:00:00Z",
                            "filename": f"{variable}_20260604_150000Z.png",
                            "grid_filename": f"{variable}_20260604_150000Z.grid.json",
                            "bounds": bounds,
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
    return {"wave_height": maps_dir / "wave_height", "current_speed": maps_dir / "current_speed"}


def test_generate_daily_briefings_writes_dated_route_artifacts_once_per_route(tmp_path, monkeypatch):
    runner = load_runner()
    fake_fetch = FakeFetchData()
    fake_map_generator = FakeMapGenerator()
    monkeypatch.setattr(runner, "maybe_generate_leaflet_overlays", lambda *args, **kwargs: None)
    def fake_route_map(map_generator, route_dir, route, snapshot, waves_path, currents_path, skip_maps=False, **kwargs):
        fake_map_generator.calls.append((Path(waves_path), Path(currents_path), route["id"], snapshot["route_id"]))
        output_path = Path(route_dir) / "route_decision_map.png"
        output_path.write_text("fake route map", encoding="utf-8")
        return output_path

    monkeypatch.setattr(runner, "maybe_generate_route_map", fake_route_map)
    monkeypatch.setattr(
        runner,
        "load_mvp_modules",
        lambda: SimpleNamespace(
            route_analysis=FakeRouteAnalysis(),
            briefing=FakeBriefing(),
            fetch_data=fake_fetch,
            chat_figure=FakeChatFigure(),
            map_generator=fake_map_generator,
        ),
    )
    monkeypatch.setattr(runner, "HUMANINTHELOOP_DIR", tmp_path)

    logo = tmp_path / "logo.png"
    logo.write_text("logo", encoding="utf-8")

    result = runner.generate_daily_briefings(
        output_root=tmp_path / "outputs",
        run_date="2026-05-10",
        route_ids=["palma_ibiza", "palma_cabrera"],
        vessel_class="medium",
        current_time="09:30",
        logo_path=logo,
    )

    assert fake_fetch.calls == 1
    assert result.routes == ["palma_ibiza", "palma_cabrera"]
    assert (result.output_dir / "palma_ibiza" / "daily_snapshot.json").exists()
    assert (result.output_dir / "palma_cabrera" / "briefing_whatsapp.txt").exists()
    assert (result.output_dir / "palma_ibiza" / "predsea_whatsapp_figure.png").exists()
    assert (result.output_dir / "palma_ibiza" / "route_decision_map.png").exists()
    assert [call[2] for call in fake_map_generator.calls] == ["palma_ibiza", "palma_cabrera"]
    manifest = json.loads((result.output_dir / "run_manifest.json").read_text())
    assert manifest["route_count"] == 2
    assert manifest["routes"] == ["palma_ibiza", "palma_cabrera"]


def test_generate_daily_briefings_writes_regional_evidence_for_location_questions(tmp_path, monkeypatch):
    runner = load_runner()
    monkeypatch.setattr(runner, "maybe_generate_leaflet_overlays", write_fake_map_indexes)
    monkeypatch.setattr(
        runner,
        "maybe_generate_route_map",
        lambda map_generator, route_dir, route, snapshot, waves_path, currents_path, skip_maps=False, **kwargs: (
            Path(route_dir) / "route_decision_map.png"
        ).write_text("fake route map", encoding="utf-8"),
    )
    monkeypatch.setattr(
        runner,
        "load_mvp_modules",
        lambda: SimpleNamespace(
            route_analysis=FakeRouteAnalysis(),
            briefing=FakeBriefing(),
            fetch_data=FakeFetchData(),
            chat_figure=FakeChatFigure(),
            map_generator=FakeMapGenerator(),
        ),
    )
    monkeypatch.setattr(runner, "HUMANINTHELOOP_DIR", tmp_path)

    result = runner.generate_daily_briefings(
        output_root=tmp_path / "outputs",
        run_date="2026-06-04",
        run_id="2026-06-04T1200Z",
        route_ids=["palma_ibiza"],
        vessel_class="medium",
        current_time="09:30",
        skip_figures=True,
    )

    regional = json.loads((result.output_dir / "regional_evidence.json").read_text(encoding="utf-8"))
    manifest = json.loads((result.output_dir / "run_manifest.json").read_text(encoding="utf-8"))

    assert regional["region_id"] == "balearics"
    assert regional["run_date"] == "2026-06-04"
    assert regional["run_id"] == "2026-06-04T1200Z"
    assert regional["supported_modes"] == ["route_question", "location_question", "map_inspect"]
    assert regional["available_variables"]["wave_height"]["units"] == "m"
    assert regional["available_variables"]["wave_height"]["time_count"] == 2
    assert regional["available_variables"]["wave_height"]["bounds"] == [[38.5, 1.0], [40.5, 4.5]]
    assert regional["available_variables"]["current_speed"]["units"] == "m/s"
    assert "No seabed type" in regional["limitations"]
    assert manifest["regional_evidence"]["path"] == "regional_evidence.json"
    assert manifest["regional_evidence"]["supported_modes"] == regional["supported_modes"]


def test_generate_daily_briefings_writes_parallel_source_evidence_and_keeps_preferred_route_outputs(tmp_path, monkeypatch):
    runner = load_runner()
    source_paths = {}
    for source_id in ("copernicus", "socib"):
        source_dir = tmp_path / "forecasts" / source_id
        source_dir.mkdir(parents=True)
        waves_path = source_dir / "waves.nc"
        currents_path = source_dir / "currents.nc"
        waves_path.write_text("waves", encoding="utf-8")
        currents_path.write_text("currents", encoding="utf-8")
        source_paths[source_id] = (waves_path, currents_path)

    sources = [
        {
            "id": "copernicus",
            "label": "Copernicus Marine Mediterranean forecast",
            "available": True,
            "preferred": True,
            "waves_path": source_paths["copernicus"][0],
            "currents_path": source_paths["copernicus"][1],
        },
        {
            "id": "socib",
            "label": "SOCIB WMOP/SAPO forecast",
            "available": True,
            "preferred": False,
            "waves_path": source_paths["socib"][0],
            "currents_path": source_paths["socib"][1],
        },
    ]
    monkeypatch.setattr(runner, "maybe_generate_leaflet_overlays", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        runner,
        "maybe_generate_route_map",
        lambda map_generator, route_dir, route, snapshot, waves_path, currents_path, skip_maps=False, **kwargs: (
            Path(route_dir) / "route_decision_map.png"
        ).write_text("fake route map", encoding="utf-8"),
    )
    monkeypatch.setattr(
        runner,
        "load_mvp_modules",
        lambda: SimpleNamespace(
            route_analysis=FakeRouteAnalysis(),
            briefing=FakeBriefing(),
            fetch_data=FakeFetchData(),
            forecast_sources=FakeForecastSources(sources),
            chat_figure=FakeChatFigure(),
            map_generator=FakeMapGenerator(),
        ),
    )
    monkeypatch.setattr(runner, "HUMANINTHELOOP_DIR", tmp_path)

    result = runner.generate_daily_briefings(
        output_root=tmp_path / "outputs",
        run_date="2026-06-04",
        route_ids=["palma_ibiza"],
        vessel_class="medium",
        current_time="09:30",
        skip_figures=True,
    )

    preferred_snapshot = json.loads(
        (result.output_dir / "palma_ibiza" / "daily_snapshot.json").read_text(encoding="utf-8")
    )
    copernicus_snapshot = json.loads(
        (result.output_dir / "sources" / "copernicus" / "palma_ibiza" / "daily_snapshot.json").read_text(encoding="utf-8")
    )
    socib_snapshot = json.loads(
        (result.output_dir / "sources" / "socib" / "palma_ibiza" / "daily_snapshot.json").read_text(encoding="utf-8")
    )
    manifest = json.loads((result.output_dir / "run_manifest.json").read_text(encoding="utf-8"))

    assert preferred_snapshot["forecast_source"]["id"] == "copernicus"
    assert copernicus_snapshot["forecast_source"]["id"] == "copernicus"
    assert socib_snapshot["forecast_source"]["id"] == "socib"
    assert manifest["forecast_sources"] == [
        {"id": "copernicus", "label": "Copernicus Marine Mediterranean forecast", "available": True, "preferred": True},
        {"id": "socib", "label": "SOCIB WMOP/SAPO forecast", "available": True, "preferred": False},
    ]


def test_generate_daily_briefings_records_unavailable_parallel_source_without_failing_available_source(tmp_path, monkeypatch):
    runner = load_runner()
    waves_path = tmp_path / "waves.nc"
    currents_path = tmp_path / "currents.nc"
    waves_path.write_text("waves", encoding="utf-8")
    currents_path.write_text("currents", encoding="utf-8")
    sources = [
        {
            "id": "copernicus",
            "label": "Copernicus Marine Mediterranean forecast",
            "available": False,
            "preferred": False,
            "error": "Copernicus authentication service timed out",
        },
        {
            "id": "socib",
            "label": "SOCIB WMOP/SAPO forecast",
            "available": True,
            "preferred": True,
            "waves_path": waves_path,
            "currents_path": currents_path,
        },
    ]
    monkeypatch.setattr(runner, "maybe_generate_leaflet_overlays", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        runner,
        "load_mvp_modules",
        lambda: SimpleNamespace(
            route_analysis=FakeRouteAnalysis(),
            briefing=FakeBriefing(),
            fetch_data=FakeFetchData(),
            forecast_sources=FakeForecastSources(sources),
            chat_figure=FakeChatFigure(),
            map_generator=FakeMapGenerator(),
        ),
    )
    monkeypatch.setattr(runner, "HUMANINTHELOOP_DIR", tmp_path)

    result = runner.generate_daily_briefings(
        output_root=tmp_path / "outputs",
        run_date="2026-06-04",
        route_ids=["palma_ibiza"],
        vessel_class="medium",
        current_time="09:30",
        skip_figures=True,
        skip_maps=True,
    )

    manifest = json.loads((result.output_dir / "run_manifest.json").read_text(encoding="utf-8"))
    snapshot = json.loads((result.output_dir / "palma_ibiza" / "daily_snapshot.json").read_text(encoding="utf-8"))

    assert not (result.output_dir / "sources" / "copernicus" / "palma_ibiza").exists()
    assert (result.output_dir / "sources" / "socib" / "palma_ibiza" / "daily_snapshot.json").exists()
    assert snapshot["forecast_source"]["id"] == "socib"
    assert manifest["forecast_sources"][0]["error"] == "Copernicus authentication service timed out"


def test_generate_daily_briefings_reuses_cached_forecast_bundle_when_all_live_sources_fail(tmp_path, monkeypatch):
    runner = load_runner()
    cached_dir = tmp_path / "mvp_data"
    cached_dir.mkdir(parents=True)
    waves_path = cached_dir / "balearic_waves.nc"
    currents_path = cached_dir / "balearic_currents.nc"
    waves_path.write_text("cached waves", encoding="utf-8")
    currents_path.write_text("cached currents", encoding="utf-8")
    (cached_dir / "forecast_source.json").write_text(
        json.dumps(
            {
                "id": "copernicus",
                "label": "Cached Copernicus Marine Mediterranean forecast",
                "available": True,
                "forecast_source_status": "cached",
                "forecast_run_date": "2026-06-04",
                "waves_path": str(waves_path),
                "currents_path": str(currents_path),
                "metadata": {"source_type": "cached_bundle", "cache_dir": str(cached_dir)},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(runner, "maybe_generate_leaflet_overlays", lambda *args, **kwargs: None)
    monkeypatch.setattr(runner, "maybe_generate_route_map", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        runner,
        "load_mvp_modules",
        lambda: SimpleNamespace(
            route_analysis=FakeRouteAnalysis(),
            briefing=FakeBriefing(),
            fetch_data=type("FetchData", (), {"OUTPUT_DIR": str(cached_dir)}),
            forecast_sources=FakeForecastSources([]),
            chat_figure=FakeChatFigure(),
            map_generator=FakeMapGenerator(),
        ),
    )
    monkeypatch.setattr(runner, "HUMANINTHELOOP_DIR", tmp_path)

    result = runner.generate_daily_briefings(
        output_root=tmp_path / "outputs",
        run_date="2026-06-04",
        route_ids=["palma_ibiza"],
        vessel_class="medium",
        current_time="09:30",
        skip_figures=True,
        skip_maps=True,
    )

    manifest = json.loads((result.output_dir / "run_manifest.json").read_text(encoding="utf-8"))
    snapshot = json.loads((result.output_dir / "palma_ibiza" / "daily_snapshot.json").read_text(encoding="utf-8"))

    assert snapshot["forecast_source"]["id"] == "copernicus"
    assert snapshot["forecast_source"]["cached"] is True
    assert manifest["forecast_sources"][-1]["metadata"]["source_type"] == "cached_bundle"
    assert manifest["forecast_sources"][-1]["available"] is True


def test_generate_daily_briefings_fails_when_required_artifact_is_missing(tmp_path, monkeypatch):
    runner = load_runner()
    monkeypatch.setattr(runner, "maybe_generate_leaflet_overlays", lambda *args, **kwargs: None)

    class BrokenBriefing(FakeBriefing):
        def write_outputs(self, snapshot, output_dir, **kwargs):
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            (Path(output_dir) / "daily_snapshot.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        runner,
        "load_mvp_modules",
        lambda: SimpleNamespace(
            route_analysis=FakeRouteAnalysis(),
            briefing=BrokenBriefing(),
            fetch_data=FakeFetchData(),
            chat_figure=FakeChatFigure(),
            map_generator=FakeMapGenerator(),
        ),
    )
    monkeypatch.setattr(runner, "HUMANINTHELOOP_DIR", tmp_path)

    with pytest.raises(RuntimeError, match="missing required artifact"):
        runner.generate_daily_briefings(
            output_root=tmp_path / "outputs",
            run_date="2026-05-10",
            route_ids=["palma_ibiza"],
            vessel_class="medium",
                current_time="09:30",
                skip_figures=True,
                skip_maps=True,
            )


def test_generate_daily_briefings_fails_when_forecast_layer_is_unavailable(tmp_path, monkeypatch):
    runner = load_runner()
    monkeypatch.setattr(runner, "maybe_generate_leaflet_overlays", lambda *args, **kwargs: None)

    class UnavailableForecastRouteAnalysis(FakeRouteAnalysis):
        def forecast_summary_from_files(self, waves_path, currents_path, route):
            return {
                "wave_min_m": None,
                "wave_max_m": None,
                "wave_peak_time": "N/A",
                "current_max_kn": None,
                "current_peak_time": "N/A",
            }

    monkeypatch.setattr(
        runner,
        "load_mvp_modules",
        lambda: SimpleNamespace(
            route_analysis=UnavailableForecastRouteAnalysis(),
            briefing=FakeBriefing(),
            fetch_data=FakeFetchData(),
            chat_figure=FakeChatFigure(),
            map_generator=FakeMapGenerator(),
        ),
    )
    monkeypatch.setattr(runner, "HUMANINTHELOOP_DIR", tmp_path)

    with pytest.raises(RuntimeError, match="Forecast layer unavailable"):
        runner.generate_daily_briefings(
            output_root=tmp_path / "outputs",
            run_date="2026-05-10",
            route_ids=["palma_ibiza"],
            vessel_class="medium",
            current_time="09:30",
            skip_figures=True,
        )


def test_generate_daily_briefings_continues_when_socib_observations_timeout(tmp_path, monkeypatch):
    runner = load_runner()
    fake_fetch = FakeFetchData()
    monkeypatch.setattr(runner, "maybe_generate_leaflet_overlays", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        runner,
        "load_mvp_modules",
        lambda: SimpleNamespace(
            route_analysis=FakeRouteAnalysis(),
            briefing=UnavailableSocibBriefing(),
            fetch_data=fake_fetch,
            chat_figure=FakeChatFigure(),
            map_generator=FakeMapGenerator(),
        ),
    )
    monkeypatch.setattr(runner, "HUMANINTHELOOP_DIR", tmp_path)

    result = runner.generate_daily_briefings(
        output_root=tmp_path / "outputs",
        run_date="2026-05-10",
        route_ids=["palma_ibiza"],
        vessel_class="medium",
        current_time="09:30",
        skip_figures=True,
        skip_maps=True,
    )

    snapshot = json.loads(
        (result.output_dir / "palma_ibiza" / "daily_snapshot.json").read_text(encoding="utf-8")
    )
    assert fake_fetch.calls == 1
    assert snapshot["observations"] == {}
    assert snapshot["recommendation"]["confidence"] == "medium"


def test_relative_logo_path_resolves_from_project_root_after_chdir(tmp_path, monkeypatch):
    runner = load_runner()
    fake_chat = FakeChatFigure()
    monkeypatch.setattr(runner, "maybe_generate_leaflet_overlays", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        runner,
        "maybe_generate_route_map",
        lambda map_generator, route_dir, route, snapshot, waves_path, currents_path, skip_maps=False, **kwargs: (
            Path(route_dir) / "route_decision_map.png"
        ).write_text("fake route map", encoding="utf-8"),
    )
    project_root = tmp_path / "repo"
    human_dir = project_root / "humanintheloop"
    assets_dir = project_root / "assets"
    human_dir.mkdir(parents=True)
    assets_dir.mkdir()
    logo = assets_dir / "predsea_logo.png"
    logo.write_text("logo", encoding="utf-8")

    monkeypatch.setattr(runner, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(runner, "HUMANINTHELOOP_DIR", human_dir)
    monkeypatch.setattr(
        runner,
        "load_mvp_modules",
        lambda: SimpleNamespace(
            route_analysis=FakeRouteAnalysis(),
            briefing=FakeBriefing(),
            fetch_data=FakeFetchData(),
            chat_figure=fake_chat,
            map_generator=FakeMapGenerator(),
        ),
    )

    result = runner.generate_daily_briefings(
        output_root=tmp_path / "outputs",
        run_date="2026-05-10",
        route_ids=["palma_ibiza"],
        vessel_class="medium",
        current_time="09:30",
        logo_path="assets/predsea_logo.png",
    )

    assert fake_chat.logo_paths == [logo]
    assert (result.output_dir / "palma_ibiza" / "predsea_whatsapp_figure.png").exists()
