# PredSea Response Consistency and SOCIB Cutover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make PredSea answer like a stable co-captain, with one canonical operational stance in the API and a hard cutover from SOCIB DataDiscovery to the modern `api.socib.es` flow.

**Architecture:** We keep the existing flat-module Python ETL and FastAPI API. The API will own the canonical recommendation stance, cache the active route/run interpretation, and render captain-facing language in local time and window language. The ETL will keep the evidence layer richer and more factual, including daily briefing summaries, observation-vs-forecast alignment, route-relative sea state, and SOCIB API metadata/observations from `api.socib.es`.

**Tech Stack:** Python, FastAPI, Pydantic, requests, pandas, pytest, GitHub Actions, existing PredSea ETL modules.

---

### Task 1: API canonical stance, local time wording, and liability guardrails

**Files:**
- Modify: `decision_engine.py`
- Modify: `api/services.py`
- Modify: `api/app.py`
- Modify: `api/schemas.py`
- Modify: `briefing_renderers.py`
- Test: `test_decision_engine.py`
- Test: `test_api_app.py`

- [ ] **Step 1: Write the failing test**

```python
def test_question_response_uses_canonical_stance_and_local_time():
    response = client.post(
        "/routes/palma_ibiza/question",
        json={
            "run": "latest",
            "question": "Palma Ibiza tomorrow morning?",
            "vessel_class": "medium",
            "current_date": "2026-06-10",
            "current_time": "23:08",
        },
    ).json()

    assert response["operational_stance"]["decision"] in {"GO", "CAUTION", "HOLD"}
    assert response["operational_stance"]["confidence"] in {"High", "Medium", "Low"}
    assert "LT" in response["answer"]
    assert "UTC" not in response["answer"]
    assert "safe" not in response["answer"].lower()
    assert "guaranteed" not in response["answer"].lower()
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
./.venv/bin/python -m pytest -q test_api_app.py::test_question_response_uses_canonical_stance_and_local_time -v
```

Expected: fail because the API still emits minute-level or UTC wording, and some answer paths still rephrase instead of reading the canonical stance.

- [ ] **Step 3: Implement the minimal API wording change**

Add a shared formatter in `decision_engine.py` that renders the visible answer from one stance object and keeps times in local-time windows:

```python
def format_window_label(time_text):
    if not time_text:
        return "during daylight hours"
    hour = int(str(time_text).split(":", 1)[0])
    if hour < 10:
        return "before late morning"
    if hour < 13:
        return "through the morning"
    if hour < 18:
        return "during daylight hours"
    if hour < 22:
        return "this evening"
    return "overnight"
```

Use the canonical stance object to render:

- `Decision`
- `Best window`
- `Comfort`
- `Risk`
- `Why`
- `What could change`
- `Confidence`

and remove safety-language phrases like `safe`, `guaranteed`, `no issues`, and `you are good to go` from the API answer layer.

- [ ] **Step 4: Run the test to verify it passes**

Run:

```bash
./.venv/bin/python -m pytest -q test_decision_engine.py test_api_app.py -v
```

Expected: pass, with the API answer in local-time windows and the same shared stance reused across the response.

- [ ] **Step 5: Commit**

```bash
git add decision_engine.py api/services.py api/app.py api/schemas.py briefing_renderers.py test_decision_engine.py test_api_app.py
git commit -m "Add canonical operational stance to API wording"
```

---

### Task 2: Daily briefing anchor, recommendation cache, and explainability-on-demand

**Files:**
- Modify: `briefing.py`
- Modify: `briefing_renderers.py`
- Modify: `api/services.py`
- Modify: `evidence_package.py`
- Add: `recommendation_state.py`
- Test: `test_evidence_package.py`
- Test: `test_run_based_outputs.py`

- [ ] **Step 1: Write the failing test**

```python
from types import SimpleNamespace

def test_daily_briefing_anchor_and_explainability():
    snapshot = sample_snapshot()
    briefing = build_daily_marine_summary(snapshot)

    assert briefing["summary_type"] == "daily_marine_briefing"
    assert briefing["valid_for"] == "24h"
    assert "issued_at_utc" in briefing
    assert briefing["confidence"] in {"High", "Medium", "Low"}

    question_request = SimpleNamespace(
        question="why?",
        vessel_class="medium",
        run="latest",
        current_date="2026-06-10",
        current_time="12:00",
    )
    answer, adjusted, freshness = answer_question(snapshot, question_request)
    assert "wave" in answer["answer"].lower()
    assert "swell" in answer["answer"].lower()
    assert "forecast issue time" in answer["answer"].lower()
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
./.venv/bin/python -m pytest -q test_evidence_package.py::test_daily_briefing_anchor_and_explainability -v
```

Expected: fail because there is no shared daily briefing anchor and no explicit explainability-on-demand path yet.

- [ ] **Step 3: Implement the minimal cache and briefing layer**

Add `recommendation_state.py` with a small in-memory/session helper that stores the canonical stance per route/run/time window:

```python
def get_or_build_stance(route_id, run_id, snapshot, question=None):
    cached = load_cached_stance(route_id, run_id)
    if cached and not materially_changed(cached, snapshot):
        return cached
    stance = build_operational_stance(snapshot, question=question)
    save_cached_stance(route_id, run_id, stance)
    return stance
```

Then have `briefing.py` build the stable daily briefing summary once per run and reuse it for all briefing surfaces and `what changed?` style responses.

- [ ] **Step 4: Run the test to verify it passes**

Run:

```bash
./.venv/bin/python -m pytest -q test_evidence_package.py test_run_based_outputs.py -v
```

Expected: pass, with a shared briefing summary and on-demand explainability that exposes why the recommendation exists without dumping every internal number.

- [ ] **Step 5: Commit**

```bash
git add briefing.py briefing_renderers.py api/services.py evidence_package.py recommendation_state.py test_evidence_package.py test_run_based_outputs.py
git commit -m "Add daily briefing anchor and recommendation cache"
```

---

### Task 3: SOCIB hard cutover to `api.socib.es`

**Files:**
- Add: `socib_api.py`
- Add: `socib_api_client.py`
- Add: `socib_api_metadata.py`
- Add: `socib_api_parsers.py`
- Add: `socib_api_observations.py`
- Modify: `ingest_observations.py`
- Modify: `briefing.py`
- Test: `test_socib_api.py`
- Modify: `test_ingest_observations.py`
- Modify: `test_socib_scripts.py`

- [ ] **Step 1: Write the failing test**

```python
def test_socib_api_uses_api_socib_es_not_data_discovery():
    bundle = socib_api.fetch_socib_bundle(dry_run=True)
    assert bundle["base_url"] == "https://api.socib.es"
    assert "DataDiscovery" not in bundle["observation_endpoints"][0]
    assert bundle["platform_types"] == [
        "Coastal Station",
        "Oceanographic Buoy",
        "Sea Level",
        "Weather Station",
    ]
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
./.venv/bin/python -m pytest -q test_socib_api.py::test_socib_api_uses_api_socib_es_not_data_discovery -v
```

Expected: fail because the new `api.socib.es` client family does not exist yet.

- [ ] **Step 3: Implement the minimal SOCIB API client**

Create a `requests`-based client with retries, `timeout=120`, and `api_key` / `apikey` support:

```python
import time
import requests

def fetch_json(url, params=None, headers=None, timeout=120, retries=3, backoff_factor=2):
    session = requests.Session()
    last_error = None
    for attempt in range(retries):
        try:
            response = session.get(url, params=params, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as error:
            last_error = error
            if attempt + 1 >= retries:
                raise
            time.sleep(backoff_factor * (2 ** attempt))
    raise last_error
```

Build discovery helpers for:

- `/platforms/`
- `/data-sources/`
- `/data-sources/{id}/data/?latest=true`
- `/data-sources/{id}/data/?initial_datetime=...&end_datetime=...`

Then replace the existing `socib_public.py` observation path in `ingest_observations.py` with the new `socib_api` flow.

- [ ] **Step 4: Run the test to verify it passes**

Run:

```bash
./.venv/bin/python -m pytest -q test_socib_api.py test_ingest_observations.py -v
```

Expected: pass, and the old `apps.socib.es/DataDiscovery` path should no longer appear in the active SOCIB observation flow.

- [ ] **Step 5: Commit**

```bash
git add socib_api.py socib_api_client.py socib_api_metadata.py socib_api_parsers.py socib_api_observations.py ingest_observations.py briefing.py test_socib_api.py test_ingest_observations.py test_socib_scripts.py
git commit -m "Migrate SOCIB observations to api.socib.es"
```

---

### Task 4: Route intelligence, passage scenarios, and long-passage logic

**Files:**
- Modify: `route_analysis.py`
- Modify: `api/services.py`
- Modify: `api/app.py`
- Modify: `routes.json`
- Test: `test_route_analysis.py`
- Test: `test_api_app.py`

- [ ] **Step 1: Write the failing test**

```python
def test_long_route_passage_scenario_includes_night_arrival():
    route = route_analysis.load_route("palma_barcelona")
    snapshot = route_analysis.build_route_snapshot({}, route=route, vessel_class="medium")
    passage = snapshot["forecast"]["passage_evidence"]

    assert passage["available"] is True
    assert passage["segment_count"] >= 3
    assert passage["worst_segment"] is not None
    assert "arrival" in snapshot["forecast"]["route_segments"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
./.venv/bin/python -m pytest -q test_route_analysis.py::test_long_route_passage_scenario_includes_night_arrival -v
```

Expected: fail because long-route passage scenario logic is not yet captured for the new mainland routes.

- [ ] **Step 3: Implement the minimal route intelligence**

Extend `route_analysis.py` so it can:

- compute route bearing
- sample worst segments along the route
- estimate passage exposure for candidate departures
- label route-relative sea state from combined/swell/wind-wave directions
- keep route alternatives for Palma→Menorca style decisions

Use the same route-dependent outputs the API already consumes, rather than inventing a separate path.

- [ ] **Step 4: Run the test to verify it passes**

Run:

```bash
./.venv/bin/python -m pytest -q test_route_analysis.py test_api_app.py -v
```

Expected: pass, with route answers that can mention alternative approaches, long-passage implications, and updated route-relative sea state.

- [ ] **Step 5: Commit**

```bash
git add route_analysis.py api/services.py api/app.py routes.json test_route_analysis.py test_api_app.py
git commit -m "Add route intelligence for long passages and alternatives"
```

---

### Task 5: Daily workflow and documentation updates

**Files:**
- Modify: `.github/workflows/predsea-daily.yml`
- Modify: `.github/workflows/provider-release-monitor.yml`
- Modify: `docs/api-whatsapp.md`
- Modify: `docs/prediction-etl.md`
- Modify: `docs/superpowers/specs/2026-06-11-socib-api-migration-design.md` if implementation reveals a mismatch
- Test: `test_run_based_outputs.py`

- [ ] **Step 1: Write the failing test**

```python
def test_daily_generator_keeps_required_artifacts_and_lineage(tmp_path):
    generator = load_script_module(Path(__file__).resolve().parents[1] / "scripts" / "generate_daily_briefing.py")
    run_id = "2026-06-11T0600Z"
    day_dir = tmp_path / "outputs" / "2026-06-11"
    run_dir = day_dir / "runs" / run_id
    route_dir = run_dir / "palma_ibiza"
    route_dir.mkdir(parents=True)
    (day_dir / "latest_run.json").write_text(json.dumps({"run_id": run_id, "path": f"runs/{run_id}"}), encoding="utf-8")
    (run_dir / "run_manifest.json").write_text(json.dumps({"run_date": "2026-06-11", "run_id": run_id, "routes": ["palma_ibiza"]}), encoding="utf-8")
    (route_dir / "daily_snapshot.json").write_text(json.dumps({"route_id": "palma_ibiza", "data_lineage": {"ground_truth_validation": {"source": "socib_api"}}}), encoding="utf-8")
    (route_dir / "evidence.json").write_text(json.dumps({"decision_context": {"route_id": "palma_ibiza"}}), encoding="utf-8")
    (route_dir / "briefing_whatsapp.txt").write_text("daily_marine_briefing", encoding="utf-8")
    (route_dir / "briefing_linkedin.txt").write_text("daily_marine_briefing", encoding="utf-8")
    (route_dir / "briefing_whatsapp_screenshot_script.txt").write_text("daily_marine_briefing", encoding="utf-8")
    (route_dir / "decision_answer.txt").write_text("daily_marine_briefing", encoding="utf-8")

    assert generator.required_artifacts_for(skip_figures=True, skip_maps=True)[:5] == [
        "daily_snapshot.json",
        "evidence.json",
        "briefing_linkedin.txt",
        "briefing_whatsapp.txt",
        "briefing_whatsapp_screenshot_script.txt",
    ]
    assert json.loads((route_dir / "daily_snapshot.json").read_text(encoding="utf-8"))["data_lineage"]["ground_truth_validation"]["source"] == "socib_api"
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
./.venv/bin/python -m pytest -q test_run_based_outputs.py -v
```

Expected: fail until the workflow and docs reflect the new daily briefing anchor and the new SOCIB path.

- [ ] **Step 3: Update workflows and docs**

Ensure GitHub Actions continues to:

- authenticate before upload
- export the daily outputs to GCS
- retain the new SOCIB path
- keep the evidence bundle and validation artifact expectations current

Update the docs so the API and ETL docs describe:

- local time wording
- GO / CAUTION / HOLD language
- daily briefing anchor
- SOCIB API cutover
- route alternatives and passage scenarios

- [ ] **Step 4: Run the test to verify it passes**

Run:

```bash
./.venv/bin/python -m pytest -q test_run_based_outputs.py test_api_app.py test_evidence_package.py -v
```

Expected: pass, with workflows and docs aligned to the new API/ETL behavior.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/predsea-daily.yml .github/workflows/provider-release-monitor.yml docs/api-whatsapp.md docs/prediction-etl.md test_run_based_outputs.py
git commit -m "Align workflows and docs with SOCIB API migration"
```

---

## Self-Review Notes

- The plan covers the API stance layer, daily briefing anchor, SOCIB API hard cutover, route intelligence, and workflow/docs updates.
- There are no placeholder steps or vague “add validation” items.
- The file responsibilities stay aligned with the current flat-module repo style.
- The sequence is API-first, then ETL enrichment, which keeps the captain-facing behavior stable before the data migration widens.
