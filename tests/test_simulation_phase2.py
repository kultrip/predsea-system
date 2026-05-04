from pathlib import Path

from simulation.setup_domain import BalearicDomain, render_namelist


def test_render_namelist_defines_one_km_balearic_nested_domain():
    namelist = render_namelist(BalearicDomain())

    assert "max_dom = 2" in namelist
    assert "parent_grid_ratio = 1, 3" in namelist
    assert "dx = 3000" in namelist
    assert "dy = 3000" in namelist
    assert "ref_lat = 39.2000" in namelist
    assert "ref_lon = 2.7000" in namelist
    assert "stand_lon = 2.7000" in namelist
    assert "geog_data_res = 'default', 'default'" in namelist


def test_render_namelist_allows_dates_and_geog_path_override():
    namelist = render_namelist(
        BalearicDomain(
            start_date="2026-05-04_00:00:00",
            end_date="2026-05-05_00:00:00",
            geog_data_path="/opt/wps_geog",
        )
    )

    assert "start_date = '2026-05-04_00:00:00', '2026-05-04_00:00:00'" in namelist
    assert "end_date = '2026-05-05_00:00:00', '2026-05-05_00:00:00'" in namelist
    assert "geog_data_path = '/opt/wps_geog'" in namelist


def test_phase2_files_capture_wrf_wps_pipeline_contract():
    dockerfile = Path("simulation/Dockerfile").read_text()
    pipeline = Path("simulation/run_pipeline.sh").read_text()

    assert "FROM debian:bullseye AS wrf-builder" in dockerfile
    assert "FROM debian:bullseye-slim AS wrf-runtime" in dockerfile
    assert "WRF_VERSION=4.5" in dockerfile
    assert "WPS_VERSION=4.5" in dockerfile
    assert "gfortran" in dockerfile
    assert "libnetcdf-dev" in dockerfile
    assert "libnetcdff-dev" in dockerfile
    assert "libnetcdf15" not in dockerfile
    assert "netcdf-bin" in dockerfile
    assert "libjasper-dev" not in dockerfile
    assert "jasper-software/jasper" in dockerfile
    assert "CMAKE_INSTALL_PREFIX=/usr/local" in dockerfile
    assert "linux/amd64" in dockerfile
    assert "mpirun" in dockerfile

    assert "link_grib.csh" in pipeline
    assert "ungrib.exe" in pipeline
    assert "metgrid.exe" in pipeline
    assert "real.exe" in pipeline
    assert "wrf.exe" in pipeline
