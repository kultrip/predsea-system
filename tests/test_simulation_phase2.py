from pathlib import Path

from simulation.setup_domain import BalearicDomain, render_namelist


def test_render_namelist_defines_one_km_balearic_nested_domain():
    namelist = render_namelist(BalearicDomain())

    assert "max_dom = 7" in namelist
    assert "parent_id = 1, 1, 2, 2, 2, 2, 2" in namelist
    assert "parent_grid_ratio = 1, 3, 3, 3, 3, 3, 3" in namelist
    assert "dx = 9000" in namelist
    assert "dy = 9000" in namelist
    assert "ref_lat = 40.0000" in namelist
    assert "ref_lon = 5.0000" in namelist
    assert "stand_lon = 5.0000" in namelist
    assert "geog_data_res = 'modis_landuse_20class_30s_with_lakes+default', 'modis_landuse_20class_30s_with_lakes+default', 'modis_landuse_20class_30s_with_lakes+default', 'modis_landuse_20class_30s_with_lakes+default', 'modis_landuse_20class_30s_with_lakes+default', 'modis_landuse_20class_30s_with_lakes+default', 'modis_landuse_20class_30s_with_lakes+default'" in namelist
    assert "i_parent_start = 1, 40, 34, 10, 110, 160, 160" in namelist
    assert "j_parent_start = 1, 20, 35, 180, 60, 180, 10" in namelist
    assert "e_we = 160, 277, 151, 301, 151, 151, 253" in namelist
    assert "e_sn = 120, 271, 151, 100, 400, 202, 301" in namelist
    assert "ordered_by_date = .true." in namelist



def test_render_namelist_allows_dates_and_geog_path_override():
    namelist = render_namelist(
        BalearicDomain(
            start_date="2026-05-04_00:00:00",
            end_date="2026-05-05_00:00:00",
            geog_data_path="/opt/wps_geog",
        )
    )

    assert (
        "start_date = '2026-05-04_00:00:00', '2026-05-04_00:00:00', '2026-05-04_00:00:00', '2026-05-04_00:00:00', '2026-05-04_00:00:00', '2026-05-04_00:00:00', '2026-05-04_00:00:00'"
        in namelist
    )
    assert (
        "end_date = '2026-05-05_00:00:00', '2026-05-05_00:00:00', '2026-05-05_00:00:00', '2026-05-05_00:00:00', '2026-05-05_00:00:00', '2026-05-05_00:00:00', '2026-05-05_00:00:00'"
        in namelist
    )
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
    assert "libeccodes-tools" in dockerfile
    assert "libjasper-dev" not in dockerfile
    assert "jasper-software/jasper" in dockerfile
    assert "CMAKE_INSTALL_PREFIX=/usr/local" in dockerfile
    assert "linux/amd64" in dockerfile
    assert "mpirun" in dockerfile
    assert "test -x run/wrf.exe" in dockerfile
    assert "test -x geogrid.exe" in dockerfile
    assert "COPY --from=wrf-builder /opt/WRF/run/wrf.exe" in dockerfile
    assert "COPY --from=wrf-builder /opt/WPS/geogrid.exe" in dockerfile

    assert "link_grib.csh" in pipeline
    assert "run_wps_stage ungrib" in pipeline
    assert "run_wps_stage metgrid" in pipeline
    assert "grib_copy -B 'dataDate:i,dataTime:i'" in pipeline
    assert "ungrib created the complete WPS intermediate time sequence" in pipeline
    assert pipeline.index("run_wps_stage ungrib") < pipeline.index("missing_intermediate_times=()")
    assert pipeline.index("missing_intermediate_times=()") < pipeline.index("run_wps_stage metgrid")
    assert '"${exe}" > "${stdout_log}" 2>&1' in pipeline
    assert 'PREDSEA_BIN="${PREDSEA_BIN:-/opt/predsea/bin}"' in pipeline
    assert '"${PREDSEA_BIN}/real.exe"' in pipeline
    assert '"${PREDSEA_BIN}/wrf.exe"' in pipeline
