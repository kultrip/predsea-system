#!/usr/bin/env bash
set -euo pipefail

WPS_DIR="${WPS_DIR:-/opt/WPS}"
WRF_DIR="${WRF_DIR:-/opt/WRF}"
PREDSEA_BIN="${PREDSEA_BIN:-/opt/predsea/bin}"
GRIB_DIR="${GRIB_DIR:-/data}"
RUN_DIR="${RUN_DIR:-/workspace/run}"
NAMELIST_WPS="${NAMELIST_WPS:-/workspace/namelist.wps}"
if [[ -f "/data/Vtable.ECMWF_grib2" ]]; then
  Vtable="/data/Vtable.ECMWF_grib2"
elif [[ -f "/data/Vtable.ECMWF" ]]; then
  Vtable="/data/Vtable.ECMWF"
else
  Vtable="${WPS_DIR}/ungrib/Variable_Tables/Vtable.ECMWF"
fi
MPI_PROCS="${MPI_PROCS:-4}"

mkdir -p "${RUN_DIR}"
cd "${RUN_DIR}"

if [[ ! -f "${NAMELIST_WPS}" ]]; then
  python3 /opt/predsea/setup_domain.py \
    --output "${NAMELIST_WPS}" \
    --start-date "${START_DATE:-2026-05-04_00:00:00}" \
    --end-date "${END_DATE:-2026-05-05_00:00:00}"
fi

cp "${NAMELIST_WPS}" "${WPS_DIR}/namelist.wps"
cd "${WPS_DIR}"

# Ensure required WPS output directories exist
mkdir -p ./geo_em
mkdir -p ./met_em

ln -sf "${Vtable}" Vtable
./link_grib.csh "${GRIB_DIR}"/*.grib2

echo "Running ungrib..."
"${PREDSEA_BIN}/ungrib.exe" > ungrib_stdout.log 2>&1 || true
cp ungrib.log ungrib_stdout.log "${RUN_DIR}/" || true

echo "Running geogrid..."
"${PREDSEA_BIN}/geogrid.exe" > geogrid_stdout.log 2>&1 || true
cp geogrid.log geogrid_stdout.log "${RUN_DIR}/" || true

echo "Running metgrid..."
"${PREDSEA_BIN}/metgrid.exe" > metgrid_stdout.log 2>&1 || true
cp metgrid.log metgrid_stdout.log "${RUN_DIR}/" || true

# Re-enable strict error checking
set -e

cd "${RUN_DIR}"
cp "${WPS_DIR}"/met_em/met_em.d0*.nc .
cp "${WRF_DIR}/run"/* . || true
python3 /opt/predsea/setup_domain.py \
  --start-date "${START_DATE:-2026-05-04_00:00:00}" \
  --end-date "${END_DATE:-2026-05-05_00:00:00}" \
  --patch-namelist-input namelist.input
cp "${PREDSEA_BIN}/real.exe" .
cp "${PREDSEA_BIN}/wrf.exe" .

mpirun --allow-run-as-root -np "${MPI_PROCS}" "${PREDSEA_BIN}/real.exe"
mpirun --allow-run-as-root -np "${MPI_PROCS}" "${PREDSEA_BIN}/wrf.exe"

echo "WRF output files:"
ls -1 wrfout_d0*
