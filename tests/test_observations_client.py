from pathlib import Path

from ingestion.observations_client import Observation, load_observations_csv


def test_load_observations_csv_normalizes_common_station_columns(tmp_path):
    csv_path = tmp_path / "observations.csv"
    csv_path.write_text(
        "\n".join(
            [
                "station_id,time,lat,lon,wind_knots,wind_direction_deg,pressure_hpa",
                "socib-01,2026-04-29T18:00:00Z,39.30,3.00,8.5,90,1012.4",
                "socib-02,2026-04-29T18:00:00Z,39.50,3.20,6.0,85,1011.8",
            ]
        )
    )

    observations = load_observations_csv(csv_path)

    assert observations == [
        Observation(
            source_id="socib-01",
            time="2026-04-29T18:00:00Z",
            lat=39.30,
            lon=3.00,
            wind_knots=8.5,
            wind_direction_deg=90.0,
            pressure_hpa=1012.4,
        ),
        Observation(
            source_id="socib-02",
            time="2026-04-29T18:00:00Z",
            lat=39.50,
            lon=3.20,
            wind_knots=6.0,
            wind_direction_deg=85.0,
            pressure_hpa=1011.8,
        ),
    ]
