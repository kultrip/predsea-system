# Runbook: getting a real WRF/ROMS/SWAN run validated (not simulated)

This is the part of the July 2 fix that can't be done from a sandboxed environment
without your GCP credentials — it has to run on your machine (or CI) with real
`gcloud`/`GOOGLE_APPLICATION_CREDENTIALS` access and will spend real credit. Steps 2–5
of the code fix (ingestion, comparison, cost reporting) are already done and tested in
this repo; this runbook is just Step 1 plus how to confirm the rest actually works
against real data.

## 0. Before you spend anything

- Confirm your project/billing account: `gcloud config get-value project` should show your real project (per `humanintheloop/docs/bigquery-evidence-rows.md`, the account used for backfills is `hello@predsea.com` — make sure you're not accidentally pointed at a different ADC identity).
- Confirm the WRF/WPS compile artifact from your June 23 Cloud Build run still exists (check whatever image/tag `scripts/vm_startup.sh` expects — `--image-tag latest` by default). If it's gone, you'll compile again before you can run.
- Decide scope for this first real run: **WRF + SWAN only** is the safer first attempt — ROMS compilation is referenced across multiple scripts but the production `simulation/Dockerfile` doesn't currently build it, so confirm your ROMS binary is actually wired into `vm_startup.sh` before expecting ROMS output. If it isn't, run WRF+SWAN first and add ROMS once its build path is confirmed.

## 1. Launch the real Spot VM run

```bash
python scripts/gcp_orchestrator.py \
  --project <your-project-id> \
  --zone europe-west1-b \
  --machine-type c2d-standard-32 \
  --gcs-bucket predsea-daily-outputs \
  --run-date 2026-07-0X \
  --execution-mode container
```

This prints the instance name and the exact GCS prefix it will write to
(`gs://<bucket>/predictions/<run-date>/runs/<run-id>/`) — write both down, you'll need
the run-id for every step below.

Monitor it (this is the exact command the script itself prints):

```bash
gcloud compute instances get-serial-port-output <instance-name> --zone=europe-west1-b --project=<your-project-id>
```

You already hit one real failure mode here once ("premature GCE Spot VM
termination", fixed June 25) — watch the serial log for early exits, not just the
final "instance deleted" state, since a Spot preemption or an early script exit both
end with the VM disappearing.

## 2. Confirm real output landed in GCS

```bash
gsutil ls -r gs://predsea-daily-outputs/predictions/<run-date>/runs/<run-id>/
```

You're looking for `.nc`/`.nc4` files whose names contain `d03` or `wrfout` (WRF),
`roms`/`his`/`avg` (ROMS), or `swan`/`wave` (SWAN) — those are the exact patterns
`scripts/*_forecast_ingestor.py` search for. If nothing matches those patterns, the
ingestors won't find anything to ingest even if the run technically succeeded —
check the actual filenames the model containers wrote and adjust the ingestor's
`download_*_file_from_gcs()` match patterns if they've drifted, rather than renaming
files by hand every time.

## 3. Ingest the real output

```bash
export PREDSEA_ENV=prod
export GOOGLE_CLOUD_PROJECT=<your-project-id>
export PREDSEA_BIGQUERY_DATASET=predsea_validation

python scripts/wrf_forecast_ingestor.py  --run-date <run-date> --run-id <run-id> --gcs-bucket predsea-daily-outputs
python scripts/swan_forecast_ingestor.py --run-date <run-date> --run-id <run-id> --gcs-bucket predsea-daily-outputs
# only if ROMS output actually landed in step 2:
python scripts/roms_forecast_ingestor.py --run-date <run-date> --run-id <run-id> --gcs-bucket predsea-daily-outputs
```

Add `--dry-run` first to sanity-check the parsed rows (including the new
`latitude`/`longitude` fields added 2026-07-02) before writing to BigQuery.

Confirm the rows actually landed:

```sql
SELECT provider, COUNT(*), MIN(target_time_utc), MAX(target_time_utc)
FROM `predsea_validation.evidence_rows`
WHERE record_type = 'forecast' AND run_date = '<run-date>'
GROUP BY provider
```

## 4. Run the real comparison (not the old synthetic one)

```bash
cd humanintheloop
python scripts/model_comparison.py --date <run-date> --project <your-project-id> --dataset predsea_validation
```

Expect one of a few honest outcomes, not automatically a win:
- `no_forecast_data` — step 3 didn't actually write rows for that date; check the BigQuery query above.
- `no_nearby_stations` — your forecast sampling points aren't within 25nm of a station in `station_metadata`; widen `--max-station-distance-nm` or check that table has real recent rows.
- A real report with some variables `"status": "compared"` and real RMSE/bias/correlation, and others `"status": "insufficient_sample_size"` if you don't have 5+ matched pairs yet for that variable. This is normal for a first run — one day of hourly data gives at most ~24 points per variable per station, and buoy coverage is uneven.

## 5. Regenerate the cost/status summary

```bash
python scripts/hpc_cost_summary.py --date <run-date>
```

If you didn't separately log `reports/<run-date>/{wrf,roms,swan}_cost.json` or
`_runtime.json` to GCS during the run, this will correctly say
`no_real_cost_recorded` rather than guess — if you want a real cost number, capture
the VM's actual runtime (start/end timestamps from the serial log in step 1) and drop
a small `{"vm_type": "...", "wallclock_minutes": ...}` JSON at
`gs://predsea-hpc-outputs/reports/<run-date>/wrf_runtime.json` (etc.) before rerunning
this script — it'll turn that into a labeled estimate automatically.

## 6. What "done" looks like

Not "12/12 wins" — a report you could hand to Google's engineer or your own team that
says, for however many variables had enough real data: real sample size, real RMSE,
real bias, which real station it was checked against, and an honest
`no_real_cost_recorded` or a clearly-labeled estimate for cost. That's a smaller
number than the old file claimed, and a far more useful one.
