from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BalearicDomain:
    start_date: str = "2026-05-04_00:00:00"
    end_date: str = "2026-05-05_00:00:00"
    interval_seconds: int = 10800
    geog_data_path: str = "/opt/WPS_GEOG"
    ref_lat: float = 40.0
    ref_lon: float = 5.0
    d01_dx_m: int = 9000
    d01_dy_m: int = 9000
    d01_e_we: int = 160
    d01_e_sn: int = 120
    d02_e_we: int = 277
    d02_e_sn: int = 271
    # Emergency operational profile: retain all regional footprints at the
    # d02 resolution.  Each dimension preserves the corresponding 1 km nest
    # extent: (fine_dimension - 1) / 3 + 1.
    regional_dx_m: int = 3000
    d03_e_we: int = 51
    d03_e_sn: int = 51
    d04_e_we: int = 101
    d04_e_sn: int = 34
    d05_e_we: int = 51
    d05_e_sn: int = 134
    d06_e_we: int = 51
    d06_e_sn: int = 68
    d07_e_we: int = 85
    d07_e_sn: int = 101

    d02_i_parent_start: int = 40
    d02_j_parent_start: int = 20
    d03_i_parent_start: int = 34
    d03_j_parent_start: int = 35
    d04_i_parent_start: int = 10
    d04_j_parent_start: int = 180
    d05_i_parent_start: int = 110
    d05_j_parent_start: int = 60
    d06_i_parent_start: int = 160
    d06_j_parent_start: int = 180
    d07_i_parent_start: int = 160
    d07_j_parent_start: int = 10

    forcing_prefix: str = "ECMWF"

    @classmethod
    def ultra_1km(cls, **kwargs) -> "BalearicDomain":
        """Return the preserved seven-domain 1 km regional configuration."""
        return cls(
            regional_dx_m=1000,
            d03_e_we=151,
            d03_e_sn=151,
            d04_e_we=301,
            d04_e_sn=100,
            d05_e_we=151,
            d05_e_sn=400,
            d06_e_we=151,
            d06_e_sn=202,
            d07_e_we=253,
            d07_e_sn=301,
            **kwargs,
        )

    @property
    def regional_parent_ratio(self) -> int:
        d02_dx_m = self.d01_dx_m // 3
        if d02_dx_m % self.regional_dx_m:
            raise ValueError("regional resolution must divide the d02 resolution exactly")
        ratio = d02_dx_m // self.regional_dx_m
        if ratio < 1:
            raise ValueError("regional resolution cannot be coarser than d02")
        return ratio


def render_namelist(domain: BalearicDomain) -> str:
    regional_ratio = domain.regional_parent_ratio
    return f"""&share
 wrf_core = 'ARW',
 max_dom = 7,
 start_date = '{domain.start_date}', '{domain.start_date}', '{domain.start_date}', '{domain.start_date}', '{domain.start_date}', '{domain.start_date}', '{domain.start_date}',
 end_date = '{domain.end_date}', '{domain.end_date}', '{domain.end_date}', '{domain.end_date}', '{domain.end_date}', '{domain.end_date}', '{domain.end_date}',
 interval_seconds = {domain.interval_seconds},
 io_form_geogrid = 2,
 opt_output_from_geogrid_path = './geo_em',
 debug_level = 0,
/

&geogrid
 parent_id = 1, 1, 2, 2, 2, 2, 2,
 parent_grid_ratio = 1, 3, {regional_ratio}, {regional_ratio}, {regional_ratio}, {regional_ratio}, {regional_ratio},
 i_parent_start = 1, {domain.d02_i_parent_start}, {domain.d03_i_parent_start}, {domain.d04_i_parent_start}, {domain.d05_i_parent_start}, {domain.d06_i_parent_start}, {domain.d07_i_parent_start},
 j_parent_start = 1, {domain.d02_j_parent_start}, {domain.d03_j_parent_start}, {domain.d04_j_parent_start}, {domain.d05_j_parent_start}, {domain.d06_j_parent_start}, {domain.d07_j_parent_start},
 e_we = {domain.d01_e_we}, {domain.d02_e_we}, {domain.d03_e_we}, {domain.d04_e_we}, {domain.d05_e_we}, {domain.d06_e_we}, {domain.d07_e_we},
 e_sn = {domain.d01_e_sn}, {domain.d02_e_sn}, {domain.d03_e_sn}, {domain.d04_e_sn}, {domain.d05_e_sn}, {domain.d06_e_sn}, {domain.d07_e_sn},
 geog_data_res = 'modis_landuse_20class_30s_with_lakes+default', 'modis_landuse_20class_30s_with_lakes+default', 'modis_landuse_20class_30s_with_lakes+default', 'modis_landuse_20class_30s_with_lakes+default', 'modis_landuse_20class_30s_with_lakes+default', 'modis_landuse_20class_30s_with_lakes+default', 'modis_landuse_20class_30s_with_lakes+default',
 dx = {domain.d01_dx_m},
 dy = {domain.d01_dy_m},
 map_proj = 'lambert',
 ref_lat = {domain.ref_lat:.4f},
 ref_lon = {domain.ref_lon:.4f},
 truelat1 = 37.0,
 truelat2 = 43.0,
 stand_lon = {domain.ref_lon:.4f},
 geog_data_path = '{domain.geog_data_path}',
/

&ungrib
 out_format = 'WPS',
 ordered_by_date = .true.,
 prefix = '{domain.forcing_prefix}',
/

&metgrid
 fg_name = '{domain.forcing_prefix}',
 io_form_metgrid = 2,
 opt_output_from_metgrid_path = './met_em',
/
"""


def write_namelist(path: Path, domain: BalearicDomain) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_namelist(domain))
    return path


def validate_mpi_decomposition(
    domain: BalearicDomain,
    nproc_x: int = 4,
    nproc_y: int = 3,
    minimum_patch_cells: int = 10,
) -> None:
    grids = (
        (domain.d01_e_we, domain.d01_e_sn),
        (domain.d02_e_we, domain.d02_e_sn),
        (domain.d03_e_we, domain.d03_e_sn),
        (domain.d04_e_we, domain.d04_e_sn),
        (domain.d05_e_we, domain.d05_e_sn),
        (domain.d06_e_we, domain.d06_e_sn),
        (domain.d07_e_we, domain.d07_e_sn),
    )
    invalid = []
    for domain_id, (e_we, e_sn) in enumerate(grids, start=1):
        patch_x = e_we // nproc_x
        patch_y = e_sn // nproc_y
        if patch_x < minimum_patch_cells or patch_y < minimum_patch_cells:
            invalid.append(f"d{domain_id:02d}={e_we}x{e_sn} -> {patch_x}x{patch_y} cells")
    if invalid:
        raise ValueError(
            f"Invalid WRF MPI decomposition {nproc_x}x{nproc_y}; "
            f"minimum patch dimension is {minimum_patch_cells}: {'; '.join(invalid)}"
        )


def patch_namelist_input(path: Path, start_date_str: str, end_date_str: str, domain: BalearicDomain) -> None:
    nproc_x = 4
    nproc_y = 3
    validate_mpi_decomposition(domain, nproc_x=nproc_x, nproc_y=nproc_y)
    regional_ratio = domain.regional_parent_ratio
    try:
        parts_start = start_date_str.split("_")
        date_start = parts_start[0].split("-")
        time_start = parts_start[1].split(":")
        
        parts_end = end_date_str.split("_")
        date_end = parts_end[0].split("-")
        time_end = parts_end[1].split(":")
        
        s_yr, s_mo, s_dy = date_start[0], date_start[1], date_start[2]
        s_hr = time_start[0]
        
        e_yr, e_mo, e_dy = date_end[0], date_end[1], date_end[2]
        e_hr = time_end[0]
    except Exception as e:
        print(f"Error parsing dates for namelist.input patch: {e}")
        return

    if not path.exists():
        print(f"Warning: {path} does not exist. Cannot patch.")
        return
        
    content = path.read_text()
    
    import re
    replacements = {
        # Time control
        r"(\bstart_year\s*=)[^!\n/]+": f"\\1 {s_yr}, {s_yr}, {s_yr}, {s_yr}, {s_yr}, {s_yr}, {s_yr},",
        r"(\bstart_month\s*=)[^!\n/]+": f"\\1 {s_mo}, {s_mo}, {s_mo}, {s_mo}, {s_mo}, {s_mo}, {s_mo},",
        r"(\bstart_day\s*=)[^!\n/]+": f"\\1 {s_dy}, {s_dy}, {s_dy}, {s_dy}, {s_dy}, {s_dy}, {s_dy},",
        r"(\bstart_hour\s*=)[^!\n/]+": f"\\1 {s_hr}, {s_hr}, {s_hr}, {s_hr}, {s_hr}, {s_hr}, {s_hr},",
        r"(\bend_year\s*=)[^!\n/]+": f"\\1 {e_yr}, {e_yr}, {e_yr}, {e_yr}, {e_yr}, {e_yr}, {e_yr},",
        r"(\bend_month\s*=)[^!\n/]+": f"\\1 {e_mo}, {e_mo}, {e_mo}, {e_mo}, {e_mo}, {e_mo}, {e_mo},",
        r"(\bend_day\s*=)[^!\n/]+": f"\\1 {e_dy}, {e_dy}, {e_dy}, {e_dy}, {e_dy}, {e_dy}, {e_dy},",
        r"(\bend_hour\s*=)[^!\n/]+": f"\\1 {e_hr}, {e_hr}, {e_hr}, {e_hr}, {e_hr}, {e_hr}, {e_hr},",
        r"(\bhistory_interval\s*=)[^!\n/]+": f"\\1 60, 60, 60, 60, 60, 60, 60,",
        r"(\bframes_per_outfile\s*=)[^!\n/]+": f"\\1 1, 1, 1, 1, 1, 1, 1,",
        r"(\binput_from_file\s*=)[^!\n/]+": f"\\1 .true., .true., .true., .true., .true., .true., .true.,",
        # WRF recommends no more than roughly 6 seconds per kilometre for the
        # parent domain. 45 seconds leaves margin for the 9 km grid and divides
        # cleanly through the 3:1 nested-domain time-step ratios.
        r"(\btime_step\s*=)[^!\n/]+": f"\\1 45,",
        r"(\btime_step_fract_num\s*=)[^!\n/]+": f"\\1 0,",
        r"(\btime_step_fract_den\s*=)[^!\n/]+": f"\\1 1,",
        
        # Domains
        r"(\bmax_dom\s*=)[^!\n/]+": f"\\1 7,",
        r"(\be_we\s*=)[^!\n/]+": f"\\1 {domain.d01_e_we}, {domain.d02_e_we}, {domain.d03_e_we}, {domain.d04_e_we}, {domain.d05_e_we}, {domain.d06_e_we}, {domain.d07_e_we},",
        r"(\be_sn\s*=)[^!\n/]+": f"\\1 {domain.d01_e_sn}, {domain.d02_e_sn}, {domain.d03_e_sn}, {domain.d04_e_sn}, {domain.d05_e_sn}, {domain.d06_e_sn}, {domain.d07_e_sn},",
        r"(\be_vert\s*=)[^!\n/]+": f"\\1 45, 45, 45, 45, 45, 45, 45,",
        r"(\bnum_metgrid_levels\s*=)[^!\n/]+": f"\\1 13,",
        r"(\bnum_metgrid_soil_levels\s*=)[^!\n/]+": f"\\1 4,",
        r"(\bdx\s*=)[^!\n/]+": f"\\1 {domain.d01_dx_m}, {domain.d01_dx_m // 3}, {domain.regional_dx_m}, {domain.regional_dx_m}, {domain.regional_dx_m}, {domain.regional_dx_m}, {domain.regional_dx_m},",
        r"(\bdy\s*=)[^!\n/]+": f"\\1 {domain.d01_dy_m}, {domain.d01_dy_m // 3}, {domain.regional_dx_m}, {domain.regional_dx_m}, {domain.regional_dx_m}, {domain.regional_dx_m}, {domain.regional_dx_m},",
        r"(\bgrid_id\s*=)[^!\n/]+": f"\\1 1, 2, 3, 4, 5, 6, 7,",
        r"(\bparent_id\s*=)[^!\n/]+": f"\\1 0, 1, 2, 2, 2, 2, 2,",
        r"(\bi_parent_start\s*=)[^!\n/]+": f"\\1 1, {domain.d02_i_parent_start}, {domain.d03_i_parent_start}, {domain.d04_i_parent_start}, {domain.d05_i_parent_start}, {domain.d06_i_parent_start}, {domain.d07_i_parent_start},",
        r"(\bj_parent_start\s*=)[^!\n/]+": f"\\1 1, {domain.d02_j_parent_start}, {domain.d03_j_parent_start}, {domain.d04_j_parent_start}, {domain.d05_j_parent_start}, {domain.d06_j_parent_start}, {domain.d07_j_parent_start},",
        r"(\bparent_grid_ratio\s*=)[^!\n/]+": f"\\1 1, 3, {regional_ratio}, {regional_ratio}, {regional_ratio}, {regional_ratio}, {regional_ratio},",
        r"(\bparent_time_step_ratio\s*=)[^!\n/]+": f"\\1 1, 3, {regional_ratio}, {regional_ratio}, {regional_ratio}, {regional_ratio}, {regional_ratio},",
        r"(\bnproc_x\s*=)[^!\n/]+": f"\\1 {nproc_x},",
        r"(\bnproc_y\s*=)[^!\n/]+": f"\\1 {nproc_y},",
        
        # Physics arrays
        r"(\bmp_physics\s*=)[^!\n/]+": f"\\1 -1, -1, -1, -1, -1, -1, -1,",
        r"(\bcu_physics\s*=)[^!\n/]+": f"\\1 -1, -1, -1, -1, -1, -1, -1,",
        r"(\bra_lw_physics\s*=)[^!\n/]+": f"\\1 -1, -1, -1, -1, -1, -1, -1,",
        r"(\bra_sw_physics\s*=)[^!\n/]+": f"\\1 -1, -1, -1, -1, -1, -1, -1,",
        r"(\bbl_pbl_physics\s*=)[^!\n/]+": f"\\1 -1, -1, -1, -1, -1, -1, -1,",
        r"(\bsf_sfclay_physics\s*=)[^!\n/]+": f"\\1 -1, -1, -1, -1, -1, -1, -1,",
        r"(\bsf_surface_physics\s*=)[^!\n/]+": f"\\1 -1, -1, -1, -1, -1, -1, -1,",
        r"(\bradt\s*=)[^!\n/]+": f"\\1 15, 15, 15, 15, 15, 15, 15,",
        r"(\bbldt\s*=)[^!\n/]+": f"\\1 0, 0, 0, 0, 0, 0, 0,",
        r"(\bcudt\s*=)[^!\n/]+": f"\\1 0, 0, 0, 0, 0, 0, 0,",
        r"(\bsf_urban_physics\s*=)[^!\n/]+": f"\\1 0, 0, 0, 0, 0, 0, 0,",
        
        # Dynamics arrays
        r"(\bzdamp\s*=)[^!\n/]+": f"\\1 5000., 5000., 5000., 5000., 5000., 5000., 5000.,",
        r"(\bdampcoef\s*=)[^!\n/]+": f"\\1 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2,",
        r"(\bkhdif\s*=)[^!\n/]+": f"\\1 0, 0, 0, 0, 0, 0, 0,",
        r"(\bkvdif\s*=)[^!\n/]+": f"\\1 0, 0, 0, 0, 0, 0, 0,",
        r"(\bnon_hydrostatic\s*=)[^!\n/]+": f"\\1 .true., .true., .true., .true., .true., .true., .true.,",
        r"(\bmoist_adv_opt\s*=)[^!\n/]+": f"\\1 1, 1, 1, 1, 1, 1, 1,",
        r"(\bscalar_adv_opt\s*=)[^!\n/]+": f"\\1 1, 1, 1, 1, 1, 1, 1,",
        r"(\bgwd_opt\s*=)[^!\n/]+": f"\\1 1, 0, 0, 0, 0, 0, 0,",
    }
    
    new_content = content
    for pattern, replacement in replacements.items():
        new_content = re.sub(pattern, replacement, new_content, flags=re.IGNORECASE)

    domains_match = re.search(r"(?ms)^\s*&domains\b.*?^\s*/", new_content)
    if domains_match:
        domains_block = domains_match.group(0)
        additions = []
        if not re.search(r"(?m)^\s*nproc_x\s*=", domains_block):
            additions.append(f" nproc_x = {nproc_x},")
        if not re.search(r"(?m)^\s*nproc_y\s*=", domains_block):
            additions.append(f" nproc_y = {nproc_y},")
        if additions:
            patched_block = domains_block.rsplit("/", 1)[0] + "\n" + "\n".join(additions) + "\n/"
            new_content = new_content[:domains_match.start()] + patched_block + new_content[domains_match.end():]
        
    path.write_text(new_content)
    print(f"Successfully patched {path} for domain starting {start_date_str}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a WPS namelist for the Balearic Sea nest.")
    parser.add_argument("--output", type=Path, default=Path("simulation/namelist.wps"))
    parser.add_argument("--start-date", default=BalearicDomain.start_date)
    parser.add_argument("--end-date", default=BalearicDomain.end_date)
    parser.add_argument("--geog-data-path", default=BalearicDomain.geog_data_path)
    parser.add_argument("--forcing-prefix", default=BalearicDomain.forcing_prefix)
    parser.add_argument(
        "--resolution-profile",
        choices=("operational-3km", "ultra-1km"),
        default="operational-3km",
        help="Regional nest resolution profile (default: fast operational 3 km).",
    )
    parser.add_argument("--patch-namelist-input", type=Path, help="Path to namelist.input to dynamically patch run dates.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    domain_factory = BalearicDomain.ultra_1km if args.resolution_profile == "ultra-1km" else BalearicDomain
    domain = domain_factory(
        start_date=args.start_date,
        end_date=args.end_date,
        geog_data_path=args.geog_data_path,
        forcing_prefix=args.forcing_prefix,
    )
    output = write_namelist(args.output, domain)
    print(output)
    if args.patch_namelist_input:
        patch_namelist_input(args.patch_namelist_input, args.start_date, args.end_date, domain)


if __name__ == "__main__":
    main()
