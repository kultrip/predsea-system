from scripts import daily_orchestrator as orchestrator


def test_ordered_unique_keeps_primary_and_removes_duplicates():
    assert orchestrator.ordered_unique(
        "europe-west1-c",
        "europe-west1-b,europe-west1-c,europe-west1-d",
        orchestrator.DEFAULT_FALLBACK_ZONES,
    ) == ["europe-west1-c", "europe-west1-b", "europe-west1-d"]


def test_spot_vm_fallback_checks_zones_before_smaller_machine(monkeypatch):
    commands = []

    def fake_run(command, dry_run=False):
        commands.append(command)
        return 0 if "--zone=europe-west1-d" in command else 1

    monkeypatch.setattr(orchestrator, "run_subprocess", fake_run)

    selected = orchestrator.launch_spot_vm_with_fallback(
        ["python", "gcp_orchestrator.py"],
        ["europe-west1-b", "europe-west1-c", "europe-west1-d"],
        ["c2d-standard-56", "c2d-standard-32"],
    )

    assert selected == ("europe-west1-d", "c2d-standard-56")
    assert len(commands) == 3
    assert all("--machine-type=c2d-standard-56" in command for command in commands)


def test_spot_vm_fallback_uses_smaller_machine_after_all_zones(monkeypatch):
    commands = []

    def fake_run(command, dry_run=False):
        commands.append(command)
        return 0 if "--machine-type=c2d-standard-32" in command else 1

    monkeypatch.setattr(orchestrator, "run_subprocess", fake_run)

    selected = orchestrator.launch_spot_vm_with_fallback(
        ["python", "gcp_orchestrator.py"],
        ["europe-west1-b", "europe-west1-c"],
        ["c2d-standard-56", "c2d-standard-32"],
    )

    assert selected == ("europe-west1-b", "c2d-standard-32")
    assert len(commands) == 3
