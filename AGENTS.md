## Imported Claude Cowork project instructions

First please read all the documentation ideally ordered by date of change, so you can have an idea about the project. Then share with me what you understand so I will know if you understood it correctly or not.

## Canonical CROCO grid safety

Never copy a CROCO grid directly into
`gs://*/static/native-marine/<region_id>/croco-grid/`. In particular, never
promote a file from `failure-diagnostics` with `gsutil cp` or
`gcloud storage cp`.

The only supported promotion pathway is
`scripts/promote_croco_grid.py`. It downloads or opens the candidate locally,
calls `validate_grid_matches_region()` for the target `region_id`, and only
then constructs and writes the canonical destination.
