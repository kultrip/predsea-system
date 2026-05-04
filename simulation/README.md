# Simulation

WRF/WPS build artifacts, domain setup scripts, namelists, and run automation live here.

Phase 2 includes:

- WRF v4.5 multi-stage Dockerfile
- WPS/WRF NetCDF-4 compilation support
- Balearic 1km nest generation
- GRIB2-to-`wrf.exe` pipeline automation

Generate the default Balearic WPS namelist:

```bash
python simulation/setup_domain.py --output simulation/namelist.wps
```

Build the WRF/WPS image:

```bash
docker build --platform linux/amd64 -t predsea-wrf:4.5 -f simulation/Dockerfile simulation
```

Run the pipeline inside the container with GRIB2 files mounted at `/data/gfs`.
