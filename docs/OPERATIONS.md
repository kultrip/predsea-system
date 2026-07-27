# PredSea Operations & Deployment Runbook

This runbook documents operational procedures, container deployment specifications, and post-mortem post-processing guidelines for **PredSea**.

---

## 1. Regional GCP Batch Deployment Specifications

PredSea operates 5 active regional forecast shards across the Western Mediterranean basin using GCP Batch SPOT instances with 16 vCPUs and 16 MPI ranks:

| Region ID | Physical Bounds (Lat, Lon) | Grid Points | Machine Type | Container Tag |
| :--- | :--- | :---: | :---: | :--- |
| **`balearic_1km`** | $[37.5^\circ\text{N}, 41.5^\circ\text{N}], [0.5^\circ\text{E}, 5.5^\circ\text{E}]$ | $200,901$ | `c2d-highcpu-16` | `croco-batch:20260726-v20` |
| **`alboran_1km`** | $[35.0^\circ\text{N}, 37.5^\circ\text{N}], [-6.0^\circ\text{E}, -1.0^\circ\text{E}]$ | $125,751$ | `c2d-highcpu-16` | `croco-batch:20260726-v20` |
| **`gulf_of_lion_1km`** | $[41.5^\circ\text{N}, 44.5^\circ\text{N}], [2.0^\circ\text{E}, 6.5^\circ\text{E}]$ | $135,751$ | `c2d-highcpu-16` | `croco-batch:20260726-v20` |
| **`tyrrhenian_1km`** | $[38.0^\circ\text{N}, 44.5^\circ\text{N}], [7.5^\circ\text{E}, 14.0^\circ\text{E}]$ | $423,150$ | `c2d-highcpu-16` | `croco-batch:20260726-v20` |
| **`algerian_1km`** | $[35.0^\circ\text{N}, 38.0^\circ\text{N}], [-1.0^\circ\text{E}, 8.5^\circ\text{E}]$ | $286,251$ | `c2d-highcpu-16` | `croco-batch:20260726-v20` |

The region profiles under `simulation/marine/regions/` are the source of truth
for these geographic bounds and compiled grid dimensions.

### Container Registry URIs
* **Primary Digest-Pinned URI**: `europe-west1-docker.pkg.dev/predsea-api/predsea-simulations/croco-batch@sha256:164c921bae33d23094a8f0103d4b6f6cec8c2112671a26d7700d4fe86d4ca31d`
* **Artifact Registry Tag**: `europe-west1-docker.pkg.dev/predsea-api/predsea-simulations/croco-batch:20260726-v20`
* **GCR Tag**: `gcr.io/predsea-api/predsea-croco-staging:20260726-gate8c-v20`

---

## 2. Multi-Region Launch Execution

To trigger all 5 Western Mediterranean shards in parallel:

```bash
bash run_all_regions.sh
```

### Batch Status Verification
```bash
gcloud batch jobs list --location=europe-west1 --project=predsea-api \
  --format="table(name.basename():label=JOB_ID, status.state:label=STATE, status.runDuration:label=DURATION)"
```

---

## 3. Post-Mortem Analysis & System Operational Guards

### Incident Summary: Staggered C-Grid Validation OOM
* **Symptom**: GCP Batch simulation runs failed during post-processing with `RuntimeError: CROCO content validation failed with exit code 1`.
* **Root Cause**: `scripts/validate_marine_output.py` applied `mask_rho` to staggered velocity fields (`u` on `eta_u, xi_u` and `v` on `eta_v, xi_v`). `xarray` attempted an outer join of unmatched dimensions on a 3D ocean domain ($401 \times 500 \times 32 \times 25$), resulting in an attempt to allocate 250+ TB of RAM.
* **Fix Implemented**: Integrated `_apply_matching_mask` in `scripts/validate_marine_output.py` to match mask grid dimensions (`mask_u` for `u`, `mask_v` for `v`, `mask_rho` for `temp/salt/zeta`).
* **Verification**: Validation execution dropped from an OOM hang to **1.8 seconds**, returning `"status": "succeeded"`.

### Local Footprint & In-Cloud Policy
1. **Zero Local Dataset Downloads**: Operators and developers MUST NOT download multi-gigabyte forecast NetCDF files to local workstations.
2. **Streaming Inspection**: Use `xarray` with `gcsfs` for remote metadata and slice inspection.
3. **Containerized Execution**: All pre-processing, model execution, and validation routines run inside GCP Batch containers.
