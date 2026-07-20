#!/usr/bin/env python3
"""
PredSea Marine Simulation Runner.
Orchestrates raw forcing download from GCS, pre-processing (SWAN preparation, CROCO forcing),
executes parallel simulations via MPI/OpenMP, converts outputs to NetCDF,
runs physical validations, and uploads results back to GCS.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

try:
    from scripts.fetch_swan_wind import fetch_wind, validate_wind
except ModuleNotFoundError:  # Direct execution from the scripts directory.
    from fetch_swan_wind import fetch_wind, validate_wind


def log_step(name: str):
    print("\n" + "=" * 60)
    print(f"🌊 [RUNNER] {name}")
    print("=" * 60)


def run_subprocess(cmd: list[str], cwd: Path | None = None) -> int:
    print(f"Running: {' '.join(cmd)}")
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        cwd=str(cwd) if cwd else None
    )
    if process.stdout:
        for line in process.stdout:
            print(line, end="")
    return process.wait()


def run_checked(cmd: list[str], *, stage: str, cwd: Path | None = None) -> None:
    return_code = run_subprocess(cmd, cwd=cwd)
    if return_code != 0:
        raise RuntimeError(f"{stage} failed with exit code {return_code}")


def require_one(directory: Path, patterns: tuple[str, ...], label: str) -> Path:
    """Resolve one explicit input product and reject ambiguous discovery."""
    matches: list[Path] = []
    for pattern in patterns:
        matches.extend(directory.glob(pattern))
    unique = sorted({path.resolve() for path in matches if path.is_file()})
    if not unique:
        raise FileNotFoundError(
            f"Missing {label} in {directory}; expected one of: {', '.join(patterns)}"
        )
    if len(unique) != 1:
        rendered = ", ".join(path.name for path in unique)
        raise RuntimeError(f"Ambiguous {label} in {directory}: {rendered}")
    return unique[0]


def resolve_project_file(container_path: Path, local_path: Path) -> Path:
    if container_path.exists():
        return container_path
    if local_path.exists():
        return local_path
    raise FileNotFoundError(f"Required project file is missing: {container_path}")


def resolve_swan_bathymetry(project_root: Path, region_id: str) -> Path:
    names = (
        f"{region_id}_bathymetry_swan.nc",
        "balearic_bathymetry_swan.nc" if region_id == "balearic_1km" else "",
    )
    for name in names:
        if not name:
            continue
        path = project_root / "simulation" / "inputs" / name
        if path.exists():
            return path
    raise FileNotFoundError(
        f"No versioned SWAN bathymetry is installed for {region_id}; "
        "generate and validate the regional grid before submitting compute"
    )


def main():
    parser = argparse.ArgumentParser(description="Run SWAN/CROCO simulation shard.")
    parser.add_argument("--region", required=True, help="Region ID (e.g., balearic_1km, alboran_1km)")
    parser.add_argument("--model", choices=["swan", "croco", "both"], default="both", help="Model to run")
    parser.add_argument("--forecast-hours", type=int, default=24, help="Forecast horizon hours")
    parser.add_argument("--mpi-ranks", type=int, default=4, help="MPI rank count")
    parser.add_argument("--gcs-bucket", required=True, help="Output GCS bucket")
    args = parser.parse_args()

    if args.forecast_hours <= 0 or args.forecast_hours > 120:
        parser.error("--forecast-hours must be between 1 and 120")
    if args.mpi_ranks <= 0:
        parser.error("--mpi-ranks must be positive")
    if args.model != "swan":
        parser.error(
            "CROCO Batch execution is not implemented yet; refusing to report "
            "success for --model=croco/both"
        )

    # Determine dates and run IDs from environment or fallback to today
    run_date = os.environ.get("PREDSEA_RUN_DATE")
    if not run_date:
        run_date = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")

    run_id = os.environ.get("PREDSEA_RUN_ID")
    if not run_id:
        run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H%MZ")

    log_step(f"Initializing simulation shard: region={args.region}, model={args.model}, hours={args.forecast_hours}")
    print(f"📅 Run Date: {run_date}")
    print(f"🆔 Run ID: {run_id}")
    print(f"🪣 GCS Bucket: {args.gcs_bucket}")
    print(f"🧵 MPI Ranks: {args.mpi_ranks}")

    project_root = Path("/app")
    if not (project_root / "scripts").exists():
        project_root = Path(__file__).resolve().parents[1]

    # Setup standard workspaces
    workspace_dir = Path("/workspace")
    workspace_dir.mkdir(parents=True, exist_ok=True)

    inputs_dir = workspace_dir / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)

    outputs_dir = workspace_dir / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    # 1. Sync boundary forcing down from GCS
    log_step("1. Syncing boundary forcing files from GCS")

    ecmwf_gcs_src = f"gs://{args.gcs_bucket}/forcing/ecmwf/{run_date}/"
    cmems_gcs_src = f"gs://{args.gcs_bucket}/forcing/cmems/{run_date}/"

    print(f"📥 Syncing ECMWF forcing from {ecmwf_gcs_src}...")
    ecmwf_sync_rc = run_subprocess(
        ["gsutil", "-m", "rsync", "-r", ecmwf_gcs_src, str(inputs_dir)]
    )
    if ecmwf_sync_rc != 0:
        print(
            "⚠️ Cached ECMWF forcing is unavailable; the runner will fetch "
            "the minimal SWAN wind product directly."
        )

    print(f"📥 Syncing CMEMS forcing from {cmems_gcs_src}...")
    run_checked(
        ["gsutil", "-m", "rsync", "-r", cmems_gcs_src, str(inputs_dir)],
        stage="CMEMS forcing download",
    )

    wind_candidates = sorted(inputs_dir.glob(f"ecmwf_sfc_{run_date}_*Z.grib2"))
    wind_candidates.extend(inputs_dir.glob("ecmwf_sfc.grib2"))
    wind_grib = inputs_dir / f"ecmwf_swan_wind_{run_date}_00Z.grib2"
    wind_error: Exception | None = None
    for candidate in dict.fromkeys(path.resolve() for path in wind_candidates):
        try:
            report = validate_wind(candidate, run_date, args.forecast_hours)
            print(f"✅ Cached ECMWF SWAN wind passed payload/time validation: {report}")
            wind_grib = candidate
            break
        except Exception as exc:
            wind_error = exc
            print(f"⚠️ Rejecting cached ECMWF wind {candidate.name}: {exc}")
    else:
        print(
            "📡 No cached wind passed validation; fetching a clean 10u/10v "
            "forecast directly from ECMWF Open Data in GCP."
        )
        if wind_error:
            print(f"   Last cached-wind validation error: {wind_error}")
        report = fetch_wind(run_date, args.forecast_hours, wind_grib)
        print(f"✅ Fresh ECMWF SWAN wind passed payload/time validation: {report}")
        run_checked(
            [
                "gsutil",
                "cp",
                str(wind_grib),
                f"{ecmwf_gcs_src}{wind_grib.name}",
            ],
            stage="validated ECMWF SWAN wind cache upload",
        )
    wave_boundary = require_one(
        inputs_dir,
        ("cmems_swan_boundary.nc", "cmems_wave_boundary.nc"),
        "CMEMS SWAN boundary NetCDF",
    )
    print(f"🔍 Resolved forcing: wind={wind_grib.name}, waves={wave_boundary.name}")

    # 2. Run SWAN simulation flow
    if args.model in ("swan", "both"):
        log_step("2. Running SWAN Wave Simulation")

        region_profile = resolve_project_file(
            project_root / "simulation" / "marine" / "regions" / f"{args.region}.json",
            Path(__file__).resolve().parents[1]
            / "simulation"
            / "marine"
            / "regions"
            / f"{args.region}.json",
        )
        bathymetry_path = resolve_swan_bathymetry(project_root, args.region)
        swan_work_dir = outputs_dir / f"swan_{args.region}"
        swan_work_dir.mkdir(parents=True, exist_ok=True)

        # Run prepare_swan_run.py
        prep_cmd = [
            "python3", "/app/scripts/prepare_swan_run.py",
            "--region", str(region_profile),
            "--bathymetry", str(bathymetry_path),
            "--wind-grib", str(wind_grib),
            "--wave-boundary", str(wave_boundary),
            "--output-dir", str(swan_work_dir),
            "--start-time", f"{run_date}T00:00:00",
            "--forecast-hours", str(args.forecast_hours)
        ]

        run_checked(prep_cmd, stage="SWAN input preparation")

        # Execute SWAN parallel run
        # Compile/run steps can be performed using native swan binary
        print(f"🚀 Executing parallel SWAN wave model on {args.mpi_ranks} MPI ranks...")
        # Note: In container, swan.exe or similar execution script is inside PATH or compiled in place
        swan_exe = shutil.which("swan.exe")
        swanrun = shutil.which("swanrun")
        if not swan_exe or not swanrun:
            raise FileNotFoundError(
                "swan.exe/swanrun are not installed in the Batch image; "
                "use the pinned native SWAN Batch image"
            )
        command_files = sorted(swan_work_dir.glob("predsea_*.swn"))
        if len(command_files) != 1:
            raise RuntimeError(
                f"Expected one SWAN command file, found {len(command_files)}"
            )
        input_stem = command_files[0].stem
        swan_run_cmd = [
            swanrun, "-input", input_stem, "-mpi", str(args.mpi_ranks)
        ]

        # We run the command inside the prepared swan workspace directory containing swan.cmd
        run_checked(swan_run_cmd, stage="parallel SWAN execution", cwd=swan_work_dir)

        # Convert parallel VTK outputs to NetCDF using the corrected vtk_to_netcdf script
        log_step("3. Converting SWAN parallel VTK XML output to NetCDF")
        netcdf_output_file = outputs_dir / f"{args.region}_swan_forecast.nc"

        convert_cmd = [
            "python3", "/app/scripts/vtk_to_netcdf.py",
            "--results-dir", str(swan_work_dir),
            "--output", str(netcdf_output_file),
        ]
        run_checked(convert_cmd, stage="SWAN canonicalization")

        # Run physics validation checks (fail-closed, land-mask aware)
        log_step("4. Validating output products")
        validate_cmd = [
            "python3", "/app/scripts/validate_marine_output.py",
            "--output", str(netcdf_output_file),
            "--model=swan",
            "--region", str(region_profile),
            "--forecast-hours", str(args.forecast_hours)
        ]
        run_checked(validate_cmd, stage="SWAN content validation")

        # Upload NetCDF to GCS
        log_step("5. Uploading output NetCDF and products to GCS")
        gcs_dest_path = f"predictions/{run_date}/runs/{run_id}/{args.region}/"
        netcdf_gcs_target = f"gs://{args.gcs_bucket}/{gcs_dest_path}{args.region}_swan_forecast.nc"

        print(f"☁️ Uploading {netcdf_output_file.name} to {netcdf_gcs_target}...")
        run_checked(
            ["gsutil", "cp", str(netcdf_output_file), netcdf_gcs_target],
            stage="canonical SWAN upload",
        )

        # Upload SUCCESS completion marker
        success_marker = outputs_dir / "SUCCESS"
        success_marker.write_text(f"status=SUCCESS\ntimestamp={dt.datetime.now(dt.timezone.utc).isoformat()}\n")

        success_gcs_target = f"gs://{args.gcs_bucket}/{gcs_dest_path}SUCCESS"
        print(f"☁️ Uploading SUCCESS marker to {success_gcs_target}...")
        run_checked(
            ["gsutil", "cp", str(success_marker), success_gcs_target],
            stage="SWAN success-marker upload",
        )

    log_step("🏆 Shard execution finished successfully!")


if __name__ == "__main__":
    main()
