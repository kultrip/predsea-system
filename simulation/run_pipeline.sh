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
if [[ -f "./metgrid/METGRID.TBL.ECMWF" ]]; then
  echo "Using METGRID.TBL.ECMWF..."
  (cd metgrid && ln -sf METGRID.TBL.ECMWF METGRID.TBL)
  ls -l metgrid/METGRID.TBL
fi

run_wps_stage() {
  local stage="$1"
  local exe="${PREDSEA_BIN}/${stage}.exe"
  local stdout_log="${stage}_stdout.log"
  local native_log="${stage}.log"

  echo "Running ${stage}..."
  set +e
  "${exe}" > "${stdout_log}" 2>&1
  local rc=$?
  set -e

  cp "${native_log}" "${stdout_log}" "${RUN_DIR}/" || true
  if [[ ${rc} -ne 0 ]]; then
    echo "❌ ${stage}.exe failed with exit code ${rc}."
    echo "Last lines from ${stdout_log}:"
    tail -n 80 "${stdout_log}" || true
    if [[ -f "${native_log}" ]]; then
      echo "Last lines from ${native_log}:"
      tail -n 80 "${native_log}" || true
    fi
    exit "${rc}"
  fi
}

# 3. Link GRIB files
echo "Linking GRIB files from ${GRIB_DIR}..."
if ls "${GRIB_DIR}"/ecmwf_*.grib2 1> /dev/null 2>&1; then
    ./link_grib.csh "${GRIB_DIR}"/ecmwf_*.grib2
else
    echo "❌ Error: No GRIB files found in ${GRIB_DIR}"
    exit 1
fi

run_wps_stage ungrib
run_wps_stage geogrid
run_wps_stage metgrid

# Set MPI environment variables for container stability
export OMPI_MCA_btl_vader_single_copy_mechanism=none
export OMPI_MCA_btl_tcp_if_include=lo,eth0

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

mpirun --oversubscribe --allow-run-as-root -np "${MPI_PROCS}" "${PREDSEA_BIN}/real.exe"
mpirun --oversubscribe --allow-run-as-root -np "${MPI_PROCS}" "${PREDSEA_BIN}/wrf.exe"

echo "WRF output files:"
ls -1 wrfout_d0*
