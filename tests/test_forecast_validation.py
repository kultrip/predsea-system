from pathlib import Path

from ingestion.observations_client import Observation
from processing.forecast_validation import compare_forecast_distributions


D01_FIXTURE = Path("processing/fixtures/wrfout_d01_sample.nc")
D02_FIXTURE = Path("processing/fixtures/wrfout_d02_sample.nc")
D03_FIXTURE = Path("processing/fixtures/wrfout_d03_sample.nc")


def test_compare_forecast_distributions_scores_each_domain_against_observations():
    observations = [
        Observation("socib-a", "2026-04-29T18:00:00Z", 39.30, 3.00, wind_knots=8.0),
        Observation("socib-b", "2026-04-29T18:00:00Z", 39.50, 3.20, wind_knots=7.0),
        Observation("socib-c", "2026-04-29T18:00:00Z", 39.70, 3.45, wind_knots=4.0),
    ]

    comparison = compare_forecast_distributions(
        observations=observations,
        wrfout_paths=[D01_FIXTURE, D02_FIXTURE, D03_FIXTURE],
        time="2026-04-29T18:00:00Z",
        variable="wind_knots",
    )

    assert comparison["variable"] == "wind_knots"
    assert comparison["observation_count"] == 3
    assert comparison["observed_distribution"]["mean"] > 0
    assert [domain["domain"] for domain in comparison["domains"]] == ["d01", "d02", "d03"]
    assert all(domain["matched_count"] == 3 for domain in comparison["domains"])
    assert all(domain["mae"] >= 0 for domain in comparison["domains"])
    assert all(domain["rmse"] >= 0 for domain in comparison["domains"])
    assert all(0 <= domain["ks_statistic"] <= 1 for domain in comparison["domains"])
    assert comparison["best_domain"]["domain"] in {"d01", "d02", "d03"}
