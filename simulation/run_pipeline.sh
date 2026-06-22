#!/usr/bin/env bash
set -euo pipefail

WPS_DIR="${WPS_DIR:-/opt/WPS}"
WRF_DIR="${WRF_DIR:-/opt/WRF}"
PREDSEA_BIN="${PREDSEA_BIN:-/opt/predsea/bin}"
GRIB_DIR="${GRIB_DIR:-/data}"
RUN_DIR="${RUN_DIR:-/workspace/run}"
NAMELIST_WPS="${NAMELIST_WPS:-/workspace/namelist.wps}"
Vtable="${Vtable:-${WPS_DIR}/ungrib/Variable_Tables/Vtable.ECMWF}"
MPI_PROCS="${MPI_PROCS:-4}"

mkdir -p "${RUN_DIR}"
cd "${RUN_DIR}"

if [[ ! -f "${NAMELIST_WPS}" ]]; then
  python3 /opt/predsea/setup_domain.py --output "${NAMELIST_WPS}"
fi

cp "${NAMELIST_WPS}" "${WPS_DIR}/namelist.wps"
cd "${WPS_DIR}"

ln -sf "${Vtable}" Vtable
./link_grib.csh "${GRIB_DIR}"/*.grib2
"${PREDSEA_BIN}/ungrib.exe"
"${PREDSEA_BIN}/geogrid.exe"
"${PREDSEA_BIN}/metgrid.exe"

cd "${RUN_DIR}"
cp "${WPS_DIR}"/met_em.d0*.nc .
cp "${WRF_DIR}/run"/* .
cp "${PREDSEA_BIN}/real.exe" .
cp "${PREDSEA_BIN}/wrf.exe" .

mpirun -np "${MPI_PROCS}" "${PREDSEA_BIN}/real.exe"
mpirun -np "${MPI_PROCS}" "${PREDSEA_BIN}/wrf.exe"

echo "WRF output files:"
ls -1 wrfout_d0*
