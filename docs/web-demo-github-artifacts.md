# PredSea Web Demo Artifacts

The daily GitHub Action generates route briefings and then exports a stable
web-demo bundle under:

```text
outputs/web-demo/
```

The uploaded artifact is named:

```text
predsea-daily-output
```

## Files For The Website

Use these stable paths from the downloaded artifact:

```text
web-demo/demo_manifest.json
web-demo/latest.json
web-demo/latest_map.png
web-demo/latest_chat.png
web-demo/latest_whatsapp.txt
```

For all generated routes:

```text
web-demo/routes/<route_id>/daily_snapshot.json
web-demo/routes/<route_id>/route_decision_map.png
web-demo/routes/<route_id>/predsea_whatsapp_figure.png
web-demo/routes/<route_id>/briefing_whatsapp.txt
```

## How To Download Manually

From GitHub:

1. Open the `predsea-system` repository.
2. Go to **Actions**.
3. Open the latest **PredSea Daily Briefing** run.
4. Download the `predsea-daily-output` artifact.
5. Use the files under `web-demo/`.

With the GitHub CLI:

```bash
gh run list --workflow "PredSea Daily Briefing" --limit 5
gh run download <RUN_ID> --name predsea-daily-output --dir /tmp/predsea-daily-output
```

The webpage should consume the small JSON/PNG files, not NetCDF or WRF output
files directly.
