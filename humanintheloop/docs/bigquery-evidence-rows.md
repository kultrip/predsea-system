# PredSea BigQuery evidence rows

PredSea now exports the normalized validation rows that already exist in the ETL:

- `validation/observation_samples.jsonl`
- `validation/forecast_index.jsonl`

Those rows are combined into one BigQuery fact table:

- dataset: `predsea_validation`
- table: `evidence_rows`

## What goes into the table

One row per normalized sample.

Forecast rows contain:

- `run_date`
- `run_id`
- `route_id`
- `route_name`
- `variable`
- `value`
- `units`
- `sample_time_utc`
- `forecast_created_at_utc`
- `target_time_utc`
- `lead_time_hours`
- `resolution_km`
- `forecast_source_id`
- `ocean_source`
- `truth_station_id`

Observation rows contain:

- `run_date`
- `run_id`
- `station_id`
- `station_name`
- `variable`
- `value`
- `units`
- `sample_time_utc`
- `observed_at_utc`

Every row also has:

- `schema_version`
- `record_type`
- `row_hash`
- `ingested_at_utc`
- `source_system`
- `reference_station_id`
- `reference_station_name`

## How it is populated

### Daily ETL

`../scripts/generate_daily_briefing.py` now exports the day’s validation archive to BigQuery after the validation JSONL files are written.
In GitHub Actions, Google Cloud authentication must happen before that script runs so the export can create and write the table.

### Backfill

`../scripts/backfill_validation_archive.py` exports the in-memory backfill rows to the same table when `--apply` is used.
You can pass the same BigQuery settings explicitly on the command line:

```bash
python scripts/backfill_validation_archive.py \
  --bucket predsea-daily-outputs \
  --prefix predictions \
  --auth gcloud \
  --apply \
  --bigquery-project predsea-api \
  --bigquery-dataset predsea_validation \
  --bigquery-table evidence_rows \
  --bigquery-location europe-west1
```

## Configuration

Set these environment variables:

- `PREDSEA_BIGQUERY_PROJECT`
- `PREDSEA_BIGQUERY_DATASET`  
- `PREDSEA_BIGQUERY_TABLE`
- `PREDSEA_BIGQUERY_LOCATION`

If the dataset/table variables are missing, the export is skipped and the ETL continues.

## Notes

- The export is best-effort. BigQuery problems should not break the maritime ETL.
- The table is partitioned by `run_date` and clustered by `record_type`, `route_id`, `variable`, and `source_system`.
- The table is intentionally normalized. No raw JSON payloads are stored.
