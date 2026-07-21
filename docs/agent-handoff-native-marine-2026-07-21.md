# PredSea Native Marine Forecast — Agent Handoff

Last updated: **2026-07-21 11:10 Europe/Madrid**  
Repository: `/Users/charles.santana/Kultrip/predsea-system`  
Google Cloud project: `predsea-api`  
Primary GCP location: `europe-west1`  
Development branch pushed to origin: `codex/wrf-curvilinear-publication`

This is the authoritative operational handoff for continuing the native PredSea
marine forecast project. Read it before changing code or cloud resources. Older
handoffs remain useful history, but their run IDs, digests, and status may be
stale.

## 1. Mission

Build a reliable, repeatable forecast system in which PredSea runs its own
numerical models:

```text
ECMWF atmosphere forcing
        |
        +--> WPS/WRF --> PredSea atmospheric forecast
        |
        +--> SWAN wind forcing

Copernicus Marine wave boundary conditions --> SWAN --> PredSea wave forecast
Copernicus Marine ocean initial/boundary data --> CROCO --> PredSea ocean forecast

PredSea WRF + SWAN + CROCO
        --> validated canonical NetCDF
        --> immutable staging bundle
        --> staging API / Relay products
        --> guarded production promotion
```

Provider terminology is important:

- ECMWF is forcing for WRF and SWAN. It is not a PredSea marine forecast.
- Copernicus Marine is initial/open-boundary forcing, comparison baseline, and
  fallback. It is not the native PredSea output.
- SWAN output computed by PredSea is the native PredSea wave forecast.
- CROCO output computed by PredSea will be the native PredSea ocean forecast.
- Observations are ground truth where quality-controlled observations exist.

## 2. Non-negotiable safety boundary

Current native marine work is **staging only**.

Do not modify any of the following until explicit production promotion gates
pass:

- production Cloud Run service `predsea-api`;
- production Cloud Run job `daily-orchestrator`;
- production scheduler;
- production bucket `predsea-daily-outputs`;
- production `latest` pointers;
- production traffic or IAM.

The native marine staging bucket is:

```text
gs://predsea-daily-outputs-test
```

A successful model run is not automatic permission to promote. A staging
success must first pass output-content, lineage, API, repeatability, runtime,
disk, and cost gates.

Never:

- print, document, or commit credential values;
- copy `.env` files into build contexts;
- report a forecast as successful because a process returned zero;
- call Copernicus data a PredSea native forecast;
- update a customer-visible pointer before immutable artifacts validate;
- infer that a missing success marker means preemption;
- delete diagnostic or cloud resources without authorization;
- deploy from an unreviewed dirty workspace;
- mix staging and production buckets, services, datasets, or run IDs.

Some credentials were previously exposed in terminal output. Treat them as
compromised and rotate them as a separate security task. Do not repeat their
values in issues, commits, logs, or agent messages.

## 3. Repository operating constraints

The main workspace contains many unrelated user modifications and untracked
files. Preserve them. Stage only files intentionally changed for the current
task.

At this handoff the worktree is on a detached `HEAD`, while commits are pushed
explicitly to:

```text
origin/codex/wrf-curvilinear-publication
```

Recent relevant commits, in order:

```text
28c902b fix: adapt ECMWF SWAN winds to hourly timeline
5bd908a fix: pass Copernicus service credentials to Batch
2a61b42 fix: interpolate SWAN winds without SciPy
2444709 fix: resolve native SWAN tools in Batch
edc8ea2 build: reduce SWAN Cloud Build context
4c64a40 fix: make SWAN runner executable in Batch
6b41421 fix: allow SWAN MPI launch in Batch
```

Before editing:

1. read repository `AGENTS.md`;
2. inspect `git status --short --branch`;
3. inspect the relevant files and tests;
4. preserve unrelated changes;
5. use `apply_patch` for edits;
6. run focused tests and `git diff --check`;
7. stage only explicit paths;
8. commit with a narrow message;
9. push detached commits with:

   ```bash
   git push origin HEAD:codex/wrf-curvilinear-publication
   ```

Do not use `git reset --hard`, `git checkout --`, broad cleanup commands, or
bulk staging.

## 4. Mandatory GCP command discipline

Before **every** `gcloud` command:

1. read `.agents/skills/gcloud/SKILL.md` completely;
2. run `gcloud help <exact leaf command>`;
3. execute one `gcloud` command at a time;
4. provide `--project=predsea-api` explicitly;
5. provide `--region=europe-west1`, `--location=europe-west1`, or an exact zone;
6. provide `--quiet`;
7. reduce output using `--format`, filters, freshness, and limits;
8. do not use pipes, redirection, shell substitution, or chained gcloud calls.

Dry-run any state-changing command when supported. Pin deployed Batch images by
immutable digest, never only by tag.

For Batch application logs, the useful resource is:

```text
resource.type="batch.googleapis.com/Job"
```

The `resource.labels.job_id` value observed in logging is the Batch **UID**, not
always the friendly job name. Obtain it from `gcloud batch jobs describe`.

## 5. Current cloud state

Current staging-only Batch job:

```text
Friendly job: predsea-sim-balearic-1km-swan-f8b64f3c
Run ID:       2026-07-20T0000Z-swan-current-r10
Region:       balearic_1km
Model:        SWAN 41.51
Horizon:      24 hours
Output:       hourly, 25 timestamps including hour 0
Machine:      c2d-highcpu-4 Spot
MPI ranks:    2
GCP location: europe-west1
Bucket:       predsea-daily-outputs-test
Image digest: sha256:9f1ae044a4e00cf08e10e51d66a8dae8df75a9f6aebcb3d703d063ba390174ac
```

Last observed state at approximately 2026-07-21 11:00 Europe/Madrid:

```text
SCHEDULED — waiting for a Spot VM allocation
```

This status is time-sensitive. The next agent must re-query it before making any
claim or submitting another job. Do not submit a duplicate while r10 is active.

Cloud Build for the r10 image:

```text
Build ID: 762e5621-f295-4c2a-a559-5f5a8bb6b86f
Status: SUCCESS
Tag: europe-west1-docker.pkg.dev/predsea-api/predsea-simulations/swan-batch:mpi-6b41421
Digest: sha256:9f1ae044a4e00cf08e10e51d66a8dae8df75a9f6aebcb3d703d063ba390174ac
```

The running heartbeat/monitor is named:

```text
complete-predsea-july-20-swan-staging-run
```

Delete that monitor only after terminal success or a genuinely external blocker.

## 6. Current product configuration

The authority tile is:

```text
simulation/marine/regions/balearic_1km.json
```

Current grid and time configuration:

| Property | Value |
|---|---:|
| Approximate bounds | 0.5°E–5.5°E, 37.5°N–41.5°N |
| Grid | 501 × 401 |
| Nominal resolution | 1 km |
| Grid spacing in SWAN input | approximately 0.01° × 0.01° |
| Forecast window | 2026-07-20 00:00 UTC to 2026-07-21 00:00 UTC |
| Published interval | 1 hour |
| Expected timestamps | 25 |
| Internal SWAN timestep | 5 minutes |
| Wind source | ECMWF Open Data 10u/10v |
| Wind source cadence | available 3-hour steps, 0–24 h |
| SWAN wind cadence | interpolated to exact hourly states |
| Wave boundary source | Copernicus Mediterranean wave parameters |
| Boundary formulation | hourly parametric JONSWAP from VHM0/VTPK/VMDR |
| Native parallel output | structured VTK/PVD |
| Canonical publication output | PredSea NetCDF |

Do not change the internal timestep back to ten minutes: SWAN rejected that
configuration because the geographic propagation CFL exceeded its limit.

## 7. Proven evidence from recent staging attempts

The following are verified facts, not guesses.

### 7.1 ECMWF wind behavior

The ECMWF Open Data source does not provide a separate object for every desired
one-hour step in this workflow. The implemented contract is:

1. download available 3-hour 10u/10v steps 0, 3, 6, ..., 24;
2. validate exactly nine source times and finite 10u/10v values;
3. linearly interpolate them to 25 exact hourly states for SWAN;
4. validate the prepared SWAN wind timeline independently.

Do not assume “hourly product” means ECMWF publishes 25 hourly source objects.
Do not reintroduce SciPy as a hidden runtime dependency; interpolation is
implemented explicitly with NumPy/xarray.

Observed valid wind ranges in the July 20 test were finite and plausible:

```text
10u approximately -32.49 to 27.91 m/s
10v approximately -22.77 to 25.63 m/s
```

### 7.2 Copernicus/CMEMS boundary behavior

The authenticated current boundary product was downloaded and validated. A
validated cache exists at:

```text
gs://predsea-daily-outputs-test/forcing/cmems/2026-07-20/cmems_swan_boundary.nc
```

It contains the required 25-hour boundary timeline for this experiment.
Copernicus credentials must be passed using both supported name families because
client versions differ:

```text
COPERNICUS_USERNAME
COPERNICUS_PASSWORD
COPERNICUSMARINE_SERVICE_USERNAME
COPERNICUSMARINE_SERVICE_PASSWORD
```

Never print passwords in a dry-run manifest. The submission helper redacts both
password fields; preserve that behavior.

### 7.3 Full input preparation

The pipeline has successfully prepared:

- the 501 × 401 bathymetry/grid;
- `bottom.bot`;
- `wind.dat` with 25 hourly states;
- four-boundary TPAR/JONSWAP inputs with 25 timestamps;
- a versioned SWAN command file;
- an input manifest containing hashes and lineage.

Therefore the current unresolved gate is not basic forcing acquisition or SWAN
input creation.

### 7.4 Failures found and fixed

| Attempt | Evidence | Root cause | Fix |
|---|---|---|---|
| Earlier runs | cached ECMWF wind malformed | cache accepted by name, not content | fail-closed payload/time validation and fresh fetch |
| Earlier runs | hourly ECMWF objects absent | wrong source cadence assumption | download 3-hour steps and interpolate hourly |
| Earlier runs | missing SciPy during xarray interpolation | implicit optional dependency | explicit NumPy/xarray interpolation |
| r8 | `swan.exe/swanrun are not installed` | Batch supplied a minimal PATH and `swanrun` executable bit was not guaranteed | prepend `/usr/local/bin`, `chmod 0755`, assert both executables in image build |
| r9 | OpenMPI refused root; no `swan_output.pvd` | Batch container runs as root and OpenMPI requires explicit acknowledgement | set both OpenMPI root acknowledgement variables and fail if PVD is absent |

The required OpenMPI environment variables are:

```text
OMPI_ALLOW_RUN_AS_ROOT=1
OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1
```

Do not remove them unless the container is intentionally changed to a non-root
runtime user and that new contract is tested.

The SWAN `swanrun` wrapper returned success even when `mpirun` refused to start.
This is why output existence/content validation is mandatory after execution.

## 8. Exact next actions

### Gate A — monitor r10

1. Describe `predsea-sim-balearic-1km-swan-f8b64f3c`.
2. If scheduled, wait; do not submit duplicates merely because Spot allocation
   is delayed.
3. When running, obtain its UID and inspect Batch logs.
4. Confirm these stages in order:
   - VM allocation and pinned digest pull;
   - cached forcing sync;
   - malformed cache rejection if applicable;
   - ECMWF source validation: nine 3-hour states;
   - SWAN wind preparation validation: 25 hourly states;
   - CMEMS boundary validation: 25 timestamps;
   - native `swanrun` invocation with two MPI ranks;
   - real numerical progress and normal SWAN termination;
   - `swan_output.pvd` and referenced parallel VTK pieces exist;
   - VTK-to-NetCDF canonicalization;
   - canonical NetCDF content validation;
   - upload to the immutable staging run prefix;
   - staging `SUCCESS` marker upload;
   - Batch terminal `SUCCEEDED`.

Expected output prefix:

```text
gs://predsea-daily-outputs-test/predictions/2026-07-20/runs/2026-07-20T0000Z-swan-current-r10/balearic_1km/
```

### Gate B — if r10 fails

Do not guess and do not immediately alter physics.

1. Preserve the exact job UID, timestamps, image digest, and final logs.
2. Identify the first failing stage and first causal error, not only the final
   Python exception.
3. Classify it as infrastructure, forcing, preparation, MPI/runtime, numerical,
   canonicalization, validation, or upload.
4. Change one attributable variable whenever practical.
5. Add a regression check at the cheapest boundary that would have caught it.
6. Run focused tests.
7. Commit and push only the intended files.
8. Build a new image with `.gcloudignore.swan`.
9. Require Cloud Build to pass its runtime assertions.
10. pin the new digest;
11. dry-run the next unique run ID;
12. submit once and monitor.

Mechanical staging issues are authorized for autonomous repair. Production is
still out of scope.

### Gate C — after r10 succeeds

Success requires all of the following, not merely Batch `SUCCEEDED`:

- exactly 25 timestamps from hour 0 through hour 24;
- full expected geographic coverage;
- mandatory wave variables present;
- at least 90% finite values, with land-mask handling documented;
- physical wave-height, period, and direction ranges;
- no constant or empty fields masquerading as output;
- lineage identifying ECMWF as wind forcing and Copernicus as boundary forcing;
- native provider identified as PredSea SWAN;
- immutable artifact hashes and manifest;
- measured runtime, disk, output size, machine type, and estimated compute cost;
- no writes to production.

Then connect the validated native bundle to the staging publication/API path.
Test route/place JSON and maps using native SWAN values. Keep the existing
Copernicus-backed production response live as fallback.

## 9. Build and submission workflow

Use the reduced build context:

```text
.gcloudignore.swan
```

It exists because the local disk was full and the repository contained many
gigabytes of unrelated outputs, temporary data, environments, and Git objects.
The reduced context is about 30 MiB and intentionally retains:

- `scripts/`;
- `simulation/marine/swan/`;
- `simulation/marine/regions/`;
- `assets/static_grids/balearic_bathymetry_swan.nc`.

Do not solve local disk pressure by deleting user data. Do not silently expand
the build context to include outputs, scratch data, credentials, or virtual
environments.

Representative build shape, after mandatory skill/help validation:

```bash
gcloud builds submit . \
  --config=simulation/marine/swan/cloudbuild.batch.yaml \
  --substitutions=_IMAGE=europe-west1-docker.pkg.dev/predsea-api/predsea-simulations/swan-batch:<unique-tag> \
  --ignore-file=.gcloudignore.swan \
  --project=predsea-api \
  --region=europe-west1 \
  --async \
  '--format=value(id)' \
  --quiet
```

After success, extract `results.images[].digest` and submit using the digest.
Always dry-run `scripts/submit_gcp_batch_simulation.py` first. Use a unique run
ID for each attempt; never reuse an old failed run ID.

## 10. Validation philosophy

Every stage is fail-closed and content-based.

Bad validation patterns to avoid:

- file exists;
- command returned zero;
- logs contain no obvious error;
- object count is nonzero;
- API returned HTTP 200 but values are `None`;
- time coordinate endpoints look right but intermediate times are missing;
- a baseline provider name appears in metadata without real baseline rows;
- a model smoke test is treated as a regional forecast.

Required validation dimensions:

- exact timestamps, cadence, start, and end;
- required variables and dimensions;
- finite fraction and fill values;
- physical value bounds;
- spatial coverage and coordinate orientation;
- ocean/land mask behavior;
- source/model/run/grid lineage;
- hash, size, and immutability;
- observed runtime/disk/cost;
- explicit failure reason.

## 11. Roadmap after the first native SWAN success

Proceed in this order while production remains live:

| Order | Deliverable | Promotion condition |
|---:|---|---|
| 1 | Balearic SWAN 1 km, 24 h | one fully validated staging run |
| 2 | Repeatable unattended SWAN run | at least a second clean cycle; interruption behavior understood |
| 3 | Staging API consumes native waves | route/place/map values prove native lineage and non-null data |
| 4 | SWAN 96 h benchmark | forcing, stability, disk, runtime, cost margin pass |
| 5 | SWAN 120 h benchmark | only if operational window retains margin; otherwise retain 96 h |
| 6 | Balearic CROCO 1 km, initially 6 h then 24 h | real 3-D ocean forcing, native output, content validation |
| 7 | Coupled staging bundle | WRF + SWAN + CROCO manifests align in time/space/lineage |
| 8 | Forecast quality ETL | asynchronous matchups against observations and baselines |
| 9 | Guarded production promotion | unattended repeatability, rollback, API and customer gates |
| 10 | Additional regions | introduce one versioned tile at a time |

Do not jump directly to 120 hours before measuring the 24-hour run. Project
runtime, disk, and cost from evidence, then test 96 hours if five days lacks
margin. Four days is an acceptable operational product; a late five-day failure
is not.

## 12. CROCO constraints not to forget

The existing surface-current Copernicus file is not sufficient to initialize
CROCO. A valid native ocean run requires at least:

- 3-D temperature;
- 3-D salinity;
- 3-D currents;
- sea-surface height;
- depth/vertical coordinates;
- complete initial conditions;
- complete open-boundary conditions;
- atmospheric surface forcing;
- a versioned regional grid and vertical configuration.

Do not claim a CROCO forecast based on `uo`/`vo` surface fields alone. CROCO
must first pass a bounded six-hour regional benchmark, then 24 hours, before
longer horizons.

## 13. Atmospheric/WRF constraints retained from earlier work

Do not regress these already-discovered invariants:

- derive WRF duration from start/end dates rather than independent hardcoding;
- verify forcing covers the entire requested duration;
- order ECMWF GRIB messages chronologically across pressure and surface data;
- validate WPS timestamps plus mandatory soil/snow field inventory;
- reject `parent_grid_ratio=1` for active child domains;
- reject MPI decompositions that create undersized patches;
- distinguish `met_em` inputs from `wrfout` outputs using names and content;
- size disk from measured output volume with margin;
- set runtime timeout from measured throughput with margin;
- use bounded early stability/throughput gates;
- preserve checkpoints and reuse downloaded forcing after infrastructure failure;
- use Spot only for retryable stages and retain a Standard fallback strategy.

The stable emergency atmosphere topology was two domains at 3 km, not seven
same-resolution nested domains. A 3 km/24 h success does not prove a 1 km/5-day
forecast.

## 14. Forecast quality and observations

Quality evaluation is a separate asynchronous ETL and must never block daily
forecast publication.

Required comparison structure:

```text
PredSea raw forecast
Copernicus/ECMWF baseline sampled at identical point/time
quality-controlled observation sampled at identical point/time
        --> matchup with spatial/time offsets and rejection reason
        --> metrics by model, variable, region, station, lead band, and regime
```

Observations, not Copernicus, are ground truth. Compare all models on identical
matched samples. Never silently drop a missing sample for only one model.

Minimum metrics:

- bias, MAE, RMSE, correlation, centered RMSE, sample count;
- circular direction bias/MAE;
- detection, false-alarm ratio, critical success index, Brier score where valid;
- peak-condition error, threshold-crossing timing, best-window agreement, and
  unsafe false negatives for route products;
- availability, latency, coverage, and rejection counts.

Stratify at least by lead bands 0–24, 25–48, 49–72, 73–96, and 97–120 hours.
Preserve raw output. Compute verification before bias correction. Train any
correction only on earlier cycles and evaluate on later untouched cycles.

New observation locations must be registry/config driven where possible. A new
provider needs a connector, normalization/QC tests, and a registry entry; it
must not require changes to WRF/SWAN/CROCO physics.

## 15. Multi-region expansion

After Balearic success and repeatability, add one independent tile at a time:

1. `balearic_1km` — eastern Spain and Balearics;
2. `alboran_1km` — southern Spain and Gibraltar;
3. `gulf_of_lion_1km` — southern France;
4. `tyrrhenian_1km` — western Italy, Corsica, Sardinia;
5. `algerian_1km` — southern western Mediterranean.

Each region needs versioned bounds, grid, bathymetry, timestep, forcing
coverage, observation registry, runtime/disk/cost measurements, and an
independent promotion decision. Inland destinations must not enlarge marine
compute domains.

Do not assume a configuration stable for one coastline is stable for another.
Bathymetry, open boundaries, winds, numerical timestep, observations, and cost
must be validated per region.

## 16. Definition of done

The overall project is not done until:

1. native SWAN waves run unattended and repeatably;
2. native CROCO ocean runs unattended and repeatably;
3. WRF/SWAN/CROCO produce aligned, validated, immutable PredSea bundles;
4. staging API and Relay outputs use real non-null native values with lineage;
5. quality ETL compares PredSea, external baselines, and observations fairly;
6. runtime, disk, cost, quota, retry, and rollback behavior are measured;
7. production promotion is atomic, reversible, and does not remove fallback;
8. additional regions can be added through versioned profiles and bounded
   validation rather than bespoke production edits.

Until then, label all native marine output as staging/experimental and preserve
the current production fallback.

## 17. Related documents

Read these for deeper history and design context:

- `docs/native-marine-forecast-plan.md`
- `docs/etl-definitive-solution-plan.md`
- `docs/ai-agent-master-handoff-2026-07-16.md`
- `docs/etl-agent-handoff-2026-07-16.md`
- `docs/real-validation-runbook.md`

When facts conflict, prefer current GCP evidence, current code/tests, and this
dated handoff. Update this document after every terminal run or material design
decision so the next agent does not inherit stale assumptions.
