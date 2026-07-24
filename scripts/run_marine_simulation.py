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

import xarray as xr

try:
    from scripts.fetch_swan_wind import fetch_wind, validate_wind
except ModuleNotFoundError:  # Direct execution from the scripts directory.
    from fetch_swan_wind import fetch_wind, validate_wind


def log_step(name: str):
    print("\n" + "=" * 60)
    print(f"🌊 [RUNNER] {name}")
    print("=" * 60)


def resolve_swan_tools(
    install_dir: Path = Path("/usr/local/bin"),
) -> tuple[str | None, str | None]:
    """Resolve the native SWAN tools even when Batch supplies a minimal PATH."""
    current_path = os.environ.get("PATH", "")
    entries = current_path.split(os.pathsep) if current_path else []
    if str(install_dir) not in entries:
        os.environ["PATH"] = os.pathsep.join([str(install_dir), *entries])
    return shutil.which("swan.exe"), shutil.which("swanrun")


def run_subprocess(
    cmd: list[str], cwd: Path | None = None, log_path: Path | None = None
) -> int:
    print(f"Running: {' '.join(cmd)}")
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        cwd=str(cwd) if cwd else None
    )
    log_file = None
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_file = log_path.open("w", encoding="utf-8")
    try:
        if process.stdout:
            for line in process.stdout:
                print(line, end="", flush=True)
                if log_file is not None:
                    log_file.write(line)
                    log_file.flush()
    finally:
        if log_file is not None:
            log_file.close()
    return process.wait()


def run_checked(
    cmd: list[str], *, stage: str, cwd: Path | None = None,
    log_path: Path | None = None,
) -> None:
    return_code = run_subprocess(cmd, cwd=cwd, log_path=log_path)
    if return_code != 0:
        raise RuntimeError(f"{stage} failed with exit code {return_code}")


def upload_croco_failure_diagnostics(
    *, outputs_dir: Path, region_id: str, run_date: str, run_id: str,
    gcs_bucket: str, error: Exception,
) -> int:
    """Persist a failed CROCO run without turning upload failure into success."""
    failure_dir = outputs_dir / f"croco_{region_id}"
    failure_dir.mkdir(parents=True, exist_ok=True)
    (failure_dir / "FAILURE.txt").write_text(
        f"status=FAILED\nstage=croco\nerror={type(error).__name__}: {error}\n"
        f"timestamp={dt.datetime.now(dt.timezone.utc).isoformat()}\n",
        encoding="utf-8",
    )
    diagnostic_target = (
        f"gs://{gcs_bucket}/predictions/{run_date}/runs/{run_id}/"
        f"{region_id}/failure-diagnostics/"
    )
    return run_subprocess(
        ["gsutil", "-m", "cp", "-r", str(failure_dir), diagnostic_target]
    )


def croco_mpi_command(mpi_ranks: int, executable: Path, namelist: Path) -> list[str]:
    """Use every allocated vCPU, including SMT hardware threads, as an MPI slot."""
    return [
        "mpirun",
        "--allow-run-as-root",
        "--use-hwthread-cpus",
        "-np",
        str(mpi_ranks),
        str(executable),
        str(namelist),
    ]


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


def run_croco_simulation(*, project_root: Path, inputs_dir: Path, outputs_dir: Path,
                         region_id: str, run_date: str, run_id: str,
                         forecast_hours: int, mpi_ranks: int, gcs_bucket: str) -> None:
    """Run the bounded regional CROCO path from explicit real inputs."""
    if mpi_ranks != 16:
        raise ValueError(
            "the pinned Balearic CROCO binary is compiled for a 4x4 decomposition; "
            "--mpi-ranks must be 16"
        )
    grid_uri = os.environ.get("PREDSEA_CROCO_GRID_GCS_URI")
    wrf_uri = os.environ.get("PREDSEA_WRF_GCS_URI")
    if not grid_uri or not grid_uri.startswith("gs://"):
        raise ValueError("PREDSEA_CROCO_GRID_GCS_URI must identify an immutable staging grid object")
    if not wrf_uri or not wrf_uri.startswith("gs://"):
        raise ValueError("PREDSEA_WRF_GCS_URI must identify immutable staging WRF output")

    region_profile = project_root / "simulation" / "marine" / "regions" / f"{region_id}.json"
    template = project_root / "simulation" / "marine" / "croco" / "croco.in.balearic"
    croco_exe = Path("/usr/local/bin/croco_balearic")
    for required in (region_profile, template, croco_exe):
        if not required.is_file():
            raise FileNotFoundError(f"required CROCO runtime asset is missing: {required}")

    croco_work = outputs_dir / f"croco_{region_id}"
    croco_work.mkdir(parents=True, exist_ok=True)
    grid_path = croco_work / "croco_grid.nc"
    wrf_dir = inputs_dir / "wrf"
    wrf_dir.mkdir(parents=True, exist_ok=True)
    run_checked(["gsutil", "cp", grid_uri, str(grid_path)], stage="CROCO grid download")
    with xr.open_dataset(grid_path) as grid:
        actual_shape = (int(grid.sizes["xi_rho"]), int(grid.sizes["eta_rho"]))
        expected_shape = (
            int(os.environ.get("PREDSEA_CROCO_XI_RHO", "501")),
            int(os.environ.get("PREDSEA_CROCO_ETA_RHO", "401")),
        )
        if actual_shape != expected_shape:
            raise ValueError(
                "CROCO grid/binary dimension mismatch: "
                f"grid xi_rho/eta_rho={actual_shape}, binary expects {expected_shape}"
            )
    run_checked(["gsutil", "-m", "cp", "-r", wrf_uri, str(wrf_dir)], stage="WRF forcing download")

    with open(region_profile, "r", encoding="utf-8") as f:
        region_data = json.load(f)
    croco_spec = region_data.get("models", {}).get("croco", {})
    vertical_levels = int(croco_spec.get("vertical_levels", 32))

    log_step("2. Acquiring validated three-dimensional CMEMS ocean forcing")
    run_checked(
        [
            "python3", "/app/scripts/fetch_native_marine_forcing.py",
            "--run-date", run_date,
            "--forecast-hours", str(forecast_hours),
            "--region", str(region_profile),
            "--output-dir", str(croco_work),
            "--models", "croco",
            "--overwrite",
        ],
        stage="CROCO CMEMS acquisition and validation",
    )
    run_checked(
        [
            "python3", "/app/scripts/prepare_croco_forcing.py",
            "--grid", str(grid_path),
            "--forcing-dir", str(croco_work),
            "--output-dir", str(croco_work),
            "--vertical-levels", str(vertical_levels),
        ],
        stage="CROCO ocean forcing interpolation",
    )

    domain = os.environ.get("PREDSEA_WRF_DOMAIN", "d02")
    wrf_files = sorted(wrf_dir.rglob(f"wrfout_{domain}_*"))
    if len(wrf_files) < forecast_hours + 1:
        raise RuntimeError(
            f"WRF forcing is incomplete for {domain}: expected at least "
            f"{forecast_hours + 1} hourly files, found {len(wrf_files)}"
        )
    bulk_path = croco_work / "croco_blk.nc"
    run_checked(
        [
            "python3", "/app/scripts/prepare_croco_bulk_forcing.py",
            "--wrf", *[str(path) for path in wrf_files[: forecast_hours + 1]],
            "--grid", str(grid_path),
            "--output", str(bulk_path),
            "--start-time", f"{run_date}T00:00:00",
            "--forecast-hours", str(forecast_hours),
        ],
        stage="real WRF-to-CROCO bulk forcing conversion",
    )

    namelist = croco_work / "croco.in"
    croco_timestep_seconds = int(os.environ.get("PREDSEA_CROCO_TIMESTEP_SECONDS", "20"))
    run_checked(
        [
            "python3", "/app/simulation/marine/croco/prepare_croco_in.py",
            "--template", str(template),
            "--output", str(namelist),
            "--work-dir", str(croco_work),
            "--start-date", run_date,
            "--forecast-hours", str(forecast_hours),
            "--timestep-seconds", str(croco_timestep_seconds),
        ],
        stage="CROCO namelist rendering",
    )

    log_step("3. Running native CROCO ocean forecast")
    os.environ["OMPI_ALLOW_RUN_AS_ROOT"] = "1"
    os.environ["OMPI_ALLOW_RUN_AS_ROOT_CONFIRM"] = "1"
    run_checked(
        croco_mpi_command(mpi_ranks, croco_exe, namelist),
        stage="parallel CROCO execution",
        cwd=croco_work,
        log_path=croco_work / "croco.stdout.log",
    )
    history = croco_work / "croco_his.nc"
    if not history.is_file() or history.stat().st_size == 0:
        raise RuntimeError("CROCO returned without a non-empty croco_his.nc")
    run_checked(
        [
            "python3", "/app/scripts/validate_marine_output.py",
            "--output", str(history),
            "--model=croco",
            "--region", str(region_profile),
            "--forecast-hours", str(forecast_hours),
        ],
        stage="CROCO content validation",
    )

    log_step("4. Uploading validated native CROCO forecast")
    prefix = f"predictions/{run_date}/runs/{run_id}/{region_id}/"
    target = f"gs://{gcs_bucket}/{prefix}{region_id}_croco_forecast.nc"
    run_checked(["gsutil", "cp", str(history), target], stage="canonical CROCO upload")
    marker = outputs_dir / "CROCO_SUCCESS"
    marker.write_text(
        f"status=SUCCESS\nmodel=croco\nforcing=predsea_wrf+cmems\n"
        f"timestamp={dt.datetime.now(dt.timezone.utc).isoformat()}\n"
    )
    run_checked(
        ["gsutil", "cp", str(marker), f"gs://{gcs_bucket}/{prefix}CROCO_SUCCESS"],
        stage="CROCO success-marker upload",
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
    if args.model == "both":
        parser.error(
            "combined execution is intentionally disabled; submit SWAN and CROCO "
            "as separate parallel Batch jobs"
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

    if args.model == "croco":
        try:
            run_croco_simulation(
                project_root=project_root,
                inputs_dir=inputs_dir,
                outputs_dir=outputs_dir,
                region_id=args.region,
                run_date=run_date,
                run_id=run_id,
                forecast_hours=args.forecast_hours,
                mpi_ranks=args.mpi_ranks,
                gcs_bucket=args.gcs_bucket,
            )
        except Exception as exc:
            upload_rc = upload_croco_failure_diagnostics(
                outputs_dir=outputs_dir,
                region_id=args.region,
                run_date=run_date,
                run_id=run_id,
                gcs_bucket=args.gcs_bucket,
                error=exc,
            )
            if upload_rc != 0:
                print(
                    "WARNING: failed to upload CROCO failure diagnostics",
                    file=sys.stderr,
                    flush=True,
                )
            raise
        log_step("🏆 CROCO shard execution finished successfully!")
        return

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
    try:
        wave_boundary = require_one(
            inputs_dir,
            ("cmems_swan_boundary.nc", "cmems_wave_boundary.nc"),
            "CMEMS SWAN boundary NetCDF",
        )
    except FileNotFoundError:
        print(
            "📡 Validated CMEMS SWAN boundary is absent; fetching the exact "
            "regional hourly product directly in GCP."
        )
        run_checked(
            [
                "python3",
                "/app/scripts/fetch_native_marine_forcing.py",
                "--run-date",
                run_date,
                "--forecast-hours",
                str(args.forecast_hours),
                "--region",
                str(
                    project_root
                    / "simulation"
                    / "marine"
                    / "regions"
                    / f"{args.region}.json"
                ),
                "--output-dir",
                str(inputs_dir),
                "--models",
                "swan",
                "--overwrite",
            ],
            stage="CMEMS SWAN boundary acquisition and validation",
        )
        wave_boundary = require_one(
            inputs_dir,
            ("cmems_swan_boundary.nc",),
            "fresh CMEMS SWAN boundary NetCDF",
        )
        run_checked(
            [
                "gsutil",
                "cp",
                str(wave_boundary),
                f"{cmems_gcs_src}{wave_boundary.name}",
            ],
            stage="validated CMEMS SWAN boundary cache upload",
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
        swan_exe, swanrun = resolve_swan_tools()
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
        # GCP Batch containers run as root. OpenMPI requires both acknowledgements
        # before it will launch ranks in that environment.
        os.environ["OMPI_ALLOW_RUN_AS_ROOT"] = "1"
        os.environ["OMPI_ALLOW_RUN_AS_ROOT_CONFIRM"] = "1"
        run_checked(swan_run_cmd, stage="parallel SWAN execution", cwd=swan_work_dir)
        if not (swan_work_dir / "swan_output.pvd").is_file():
            raise RuntimeError(
                "parallel SWAN execution returned without producing swan_output.pvd"
            )

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
