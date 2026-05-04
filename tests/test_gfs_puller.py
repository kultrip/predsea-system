from datetime import datetime, timezone
from pathlib import Path

from ingestion.gfs_puller import (
    WESTERN_MEDITERRANEAN_BBOX,
    GfsPullConfig,
    build_s3_prefix,
    choose_latest_cycle,
    format_cycle,
    grib_filter_expression,
    list_grib_keys,
)


def test_choose_latest_cycle_uses_completed_six_hour_cycle():
    assert choose_latest_cycle(datetime(2026, 5, 4, 1, 30, tzinfo=timezone.utc)) == "00"
    assert choose_latest_cycle(datetime(2026, 5, 4, 7, 0, tzinfo=timezone.utc)) == "06"
    assert choose_latest_cycle(datetime(2026, 5, 4, 13, 0, tzinfo=timezone.utc)) == "12"
    assert choose_latest_cycle(datetime(2026, 5, 4, 23, 59, tzinfo=timezone.utc)) == "18"


def test_format_cycle_and_s3_prefix_match_noaa_gfs_layout():
    run_time = datetime(2026, 5, 4, 13, 0, tzinfo=timezone.utc)

    assert format_cycle(run_time, "12") == "gfs.20260504/12/atmos"
    assert build_s3_prefix(run_time, "12") == "gfs.20260504/12/atmos/"


def test_list_grib_keys_filters_025_degree_grib2_files():
    class FakePaginator:
        def paginate(self, Bucket, Prefix):
            assert Bucket == "noaa-gfs-bdp-pds"
            assert Prefix == "gfs.20260504/12/atmos/"
            return [
                {
                    "Contents": [
                        {"Key": "gfs.20260504/12/atmos/gfs.t12z.pgrb2.0p25.f000"},
                        {"Key": "gfs.20260504/12/atmos/gfs.t12z.pgrb2.0p25.f003.idx"},
                        {"Key": "gfs.20260504/12/atmos/gfs.t12z.pgrb2.1p00.f000"},
                        {"Key": "gfs.20260504/12/atmos/gfs.t12z.pgrb2.0p25.f003"},
                    ]
                }
            ]

    class FakeClient:
        def get_paginator(self, name):
            assert name == "list_objects_v2"
            return FakePaginator()

    config = GfsPullConfig(run_date=datetime(2026, 5, 4, 13, tzinfo=timezone.utc), cycle="12")

    assert list_grib_keys(FakeClient(), config) == [
        "gfs.20260504/12/atmos/gfs.t12z.pgrb2.0p25.f000",
        "gfs.20260504/12/atmos/gfs.t12z.pgrb2.0p25.f003",
    ]


def test_grib_filter_expression_describes_western_mediterranean_bbox():
    expression = grib_filter_expression(WESTERN_MEDITERRANEAN_BBOX)

    assert "lon>=-6.0" in expression
    assert "lon<=10.0" in expression
    assert "lat>=34.0" in expression
    assert "lat<=45.5" in expression


def test_config_uses_partitioned_output_directory(tmp_path):
    config = GfsPullConfig(
        run_date=datetime(2026, 5, 4, 13, tzinfo=timezone.utc),
        cycle="12",
        output_dir=tmp_path,
    )

    assert config.cycle_output_dir == Path(tmp_path) / "gfs.20260504" / "12"
