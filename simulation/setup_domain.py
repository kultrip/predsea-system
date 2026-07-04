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
    d03_e_we: int = 151
    d03_e_sn: int = 151
    d02_i_parent_start: int = 40
    d02_j_parent_start: int = 20
    d03_i_parent_start: int = 34
    d03_j_parent_start: int = 35
    forcing_prefix: str = "ECMWF"


def render_namelist(domain: BalearicDomain) -> str:
    return f"""&share
 wrf_core = 'ARW',
 max_dom = 3,
 start_date = '{domain.start_date}', '{domain.start_date}', '{domain.start_date}',
 end_date = '{domain.end_date}', '{domain.end_date}', '{domain.end_date}',
 interval_seconds = {domain.interval_seconds},
 io_form_geogrid = 2,
 opt_output_from_geogrid_path = './geo_em',
 debug_level = 0,
/

&geogrid
 parent_id = 1, 1, 2,
 parent_grid_ratio = 1, 3, 3,
 i_parent_start = 1, {domain.d02_i_parent_start}, {domain.d03_i_parent_start},
 j_parent_start = 1, {domain.d02_j_parent_start}, {domain.d03_j_parent_start},
 e_we = {domain.d01_e_we}, {domain.d02_e_we}, {domain.d03_e_we},
 e_sn = {domain.d01_e_sn}, {domain.d02_e_sn}, {domain.d03_e_sn},
 geog_data_res = 'modis_lakes+5m', 'modis_lakes+5m', 'modis_lakes+5m',
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


def patch_namelist_input(path: Path, start_date_str: str, end_date_str: str) -> None:
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
        r"(\bstart_year\s*=)[^,/;\n]+": f"\\1 {s_yr}, {s_yr}, {s_yr}",
        r"(\bstart_month\s*=)[^,/;\n]+": f"\\1 {s_mo}, {s_mo}, {s_mo}",
        r"(\bstart_day\s*=)[^,/;\n]+": f"\\1 {s_dy}, {s_dy}, {s_dy}",
        r"(\bstart_hour\s*=)[^,/;\n]+": f"\\1 {s_hr}, {s_hr}, {s_hr}",
        r"(\bend_year\s*=)[^,/;\n]+": f"\\1 {e_yr}, {e_yr}, {e_yr}",
        r"(\bend_month\s*=)[^,/;\n]+": f"\\1 {e_mo}, {e_mo}, {e_mo}",
        r"(\bend_day\s*=)[^,/;\n]+": f"\\1 {e_dy}, {e_dy}, {e_dy}",
        r"(\bend_hour\s*=)[^,/;\n]+": f"\\1 {e_hr}, {e_hr}, {e_hr}",
    }
    
    new_content = content
    for pattern, replacement in replacements.items():
        new_content = re.sub(pattern, replacement, new_content, flags=re.IGNORECASE)
        
    path.write_text(new_content)
    print(f"Successfully patched {path} with start_date={start_date_str} and end_date={end_date_str}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a WPS namelist for the Balearic Sea nest.")
    parser.add_argument("--output", type=Path, default=Path("simulation/namelist.wps"))
    parser.add_argument("--start-date", default=BalearicDomain.start_date)
    parser.add_argument("--end-date", default=BalearicDomain.end_date)
    parser.add_argument("--geog-data-path", default=BalearicDomain.geog_data_path)
    parser.add_argument("--forcing-prefix", default=BalearicDomain.forcing_prefix)
    parser.add_argument("--patch-namelist-input", type=Path, help="Path to namelist.input to dynamically patch run dates.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    domain = BalearicDomain(
        start_date=args.start_date,
        end_date=args.end_date,
        geog_data_path=args.geog_data_path,
        forcing_prefix=args.forcing_prefix,
    )
    output = write_namelist(args.output, domain)
    print(output)
    if args.patch_namelist_input:
        patch_namelist_input(args.patch_namelist_input, args.start_date, args.end_date)


if __name__ == "__main__":
    main()
