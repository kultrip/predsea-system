from pathlib import Path

import pytest

from scripts.run_marine_simulation import require_one, resolve_swan_tools
from scripts.submit_gcp_batch_simulation import (
    build_batch_job_json,
    default_timeout_seconds,
)


def test_require_one_rejects_missing_and_ambiguous_products(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="Missing SWAN boundary"):
        require_one(tmp_path, ("cmems_swan_boundary.nc",), "SWAN boundary")

    (tmp_path / "one.nc").write_text("one")
    (tmp_path / "two.nc").write_text("two")
    with pytest.raises(RuntimeError, match="Ambiguous SWAN boundary"):
        require_one(tmp_path, ("*.nc",), "SWAN boundary")


def test_require_one_returns_the_exact_product(tmp_path: Path):
    expected = tmp_path / "cmems_swan_boundary.nc"
    expected.write_text("boundary")
    assert require_one(
        tmp_path, ("cmems_swan_boundary.nc",), "SWAN boundary"
    ) == expected.resolve()


def test_resolve_swan_tools_handles_minimal_batch_path(tmp_path: Path, monkeypatch):
    for name in ("swan.exe", "swanrun"):
        executable = tmp_path / name
        executable.write_text("#!/bin/sh\n")
        executable.chmod(0o755)
    monkeypatch.setenv("PATH", "")
    swan_exe, swanrun = resolve_swan_tools(tmp_path)
    assert swan_exe == str(tmp_path / "swan.exe")
    assert swanrun == str(tmp_path / "swanrun")


def test_long_horizon_timeout_is_not_the_old_four_hour_constant():
    assert default_timeout_seconds(24) == 4 * 3600
    assert default_timeout_seconds(120) == 8 * 3600


def test_batch_manifest_carries_immutable_run_identity_and_timeout():
    image = "europe-west1-docker.pkg.dev/p/model/swan@sha256:" + "a" * 64
    manifest = build_batch_job_json(
        project_id="predsea-api",
        region_id="balearic_1km",
        model_type="swan",
        forecast_hours=120,
        gcs_bucket="predsea-daily-outputs-test",
        machine_type="c2d-highcpu-8",
        cpu_milli=8000,
        memory_mib=16384,
        mpi_ranks=4,
        image_uri=image,
        run_date="2026-07-20",
        run_id="run-123",
        timeout_seconds=28800,
    )
    task = manifest["taskGroups"][0]["taskSpec"]
    runnable = task["runnables"][0]
    assert task["maxRunDuration"] == "28800s"
    assert runnable["container"]["imageUri"] == image
    assert runnable["environment"]["variables"]["PREDSEA_RUN_ID"] == "run-123"


def test_batch_manifest_exposes_copernicus_service_environment_names():
    manifest = build_batch_job_json(
        project_id="predsea-api",
        region_id="balearic_1km",
        model_type="swan",
        forecast_hours=24,
        gcs_bucket="predsea-daily-outputs-test",
        machine_type="c2d-highcpu-4",
        cpu_milli=4000,
        memory_mib=8192,
        mpi_ranks=2,
        image_uri="example.invalid/swan@sha256:" + "a" * 64,
        run_date="2026-07-20",
        run_id="run-credentials",
        timeout_seconds=14400,
        copernicus_username="user",
        copernicus_password="password",
    )
    variables = manifest["taskGroups"][0]["taskSpec"]["runnables"][0][
        "environment"
    ]["variables"]
    assert variables["COPERNICUSMARINE_SERVICE_USERNAME"] == "user"
    assert variables["COPERNICUSMARINE_SERVICE_PASSWORD"] == "password"


def test_batch_manifest_supports_deadline_critical_standard_vm():
    manifest = build_batch_job_json(
        project_id="predsea-api",
        region_id="balearic_1km",
        model_type="swan",
        forecast_hours=24,
        gcs_bucket="predsea-daily-outputs-test",
        machine_type="c2d-highcpu-16",
        cpu_milli=16000,
        memory_mib=32768,
        mpi_ranks=8,
        image_uri="example.invalid/swan@sha256:" + "a" * 64,
        run_date="2026-07-20",
        run_id="run-standard-16",
        timeout_seconds=14400,
        provisioning_model="STANDARD",
    )

    policy = manifest["allocationPolicy"]["instances"][0]["policy"]
    task = manifest["taskGroups"][0]["taskSpec"]
    command = task["runnables"][0]["container"]["commands"][1]
    assert policy == {
        "machineType": "c2d-highcpu-16",
        "provisioningModel": "STANDARD",
    }
    assert task["computeResource"] == {"cpuMilli": "16000", "memoryMib": "32768"}
    assert "--mpi-ranks 8" in command
