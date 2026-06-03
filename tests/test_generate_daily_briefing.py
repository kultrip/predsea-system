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


def test_generate_daily_briefings_writes_dated_route_artifacts_once_per_route(tmp_path, monkeypatch):
    runner = load_runner()
    fake_fetch = FakeFetchData()
    fake_map_generator = FakeMapGenerator()
    monkeypatch.setattr(runner, "maybe_generate_leaflet_overlays", lambda *args, **kwargs: None)
    def fake_route_map(map_generator, route_dir, route, snapshot, waves_path, currents_path, skip_maps=False):
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
        lambda map_generator, route_dir, route, snapshot, waves_path, currents_path, skip_maps=False: (
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
