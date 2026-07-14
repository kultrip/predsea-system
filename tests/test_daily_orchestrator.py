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

    selected = orchestrator.launch_vm_with_fallback(
        ["python", "gcp_orchestrator.py"],
        ["europe-west1-b", "europe-west1-c", "europe-west1-d"],
        ["c2d-standard-56", "c2d-standard-32"],
    )

    assert selected == ("europe-west1-d", "c2d-standard-56", "SPOT")
    assert len(commands) == 3
    assert all("--machine-type=c2d-standard-56" in command for command in commands)


def test_spot_vm_fallback_uses_smaller_machine_after_all_zones(monkeypatch):
    commands = []

    def fake_run(command, dry_run=False):
        commands.append(command)
        return 0 if "--machine-type=c2d-standard-32" in command else 1

    monkeypatch.setattr(orchestrator, "run_subprocess", fake_run)

    selected = orchestrator.launch_vm_with_fallback(
        ["python", "gcp_orchestrator.py"],
        ["europe-west1-b", "europe-west1-c"],
        ["c2d-standard-56", "c2d-standard-32"],
    )

    assert selected == ("europe-west1-b", "c2d-standard-32", "SPOT")
    assert len(commands) == 3


def test_vm_fallback_uses_regular_vm_after_all_spot_candidates(monkeypatch):
    commands = []

    def fake_run(command, dry_run=False):
        commands.append(command)
        return 0 if "--provisioning-model=STANDARD" in command else 1

    monkeypatch.setattr(orchestrator, "run_subprocess", fake_run)

    selected = orchestrator.launch_vm_with_fallback(
        ["python", "gcp_orchestrator.py"],
        ["europe-west1-b", "europe-west1-c"],
        ["c2d-standard-16", "c2-standard-16"],
    )

    assert selected == ("europe-west1-b", "c2-standard-16", "STANDARD")
    assert len(commands) == 5
    assert "--provisioning-model=STANDARD" in commands[-1]


def test_default_machine_fallbacks_include_16_vcpu_options():
    assert "c2d-standard-16" in orchestrator.DEFAULT_FALLBACK_MACHINE_TYPES
    assert "c2-standard-16" in orchestrator.DEFAULT_FALLBACK_MACHINE_TYPES


def test_was_instance_preempted_reads_compute_audit_event(monkeypatch):
    class Result:
        stdout = "Instance was preempted.\n"
        stderr = ""

    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        return Result()

    monkeypatch.setattr(orchestrator.subprocess, "run", fake_run)

    assert orchestrator.was_instance_preempted(
        "predsea-sim-test",
        "europe-west1-c",
        "predsea-api",
    )
    assert commands[0][:3] == ["gcloud", "logging", "read"]
