from __future__ import annotations

import numpy as np
import pytest

from scripts.prepare_swan_run import (
    _circular_mean_degrees,
    _computational_timestep_minutes,
    _swan_time,
)


def test_circular_mean_handles_north_wraparound():
    result = _circular_mean_degrees(np.array([359.0, 1.0]))
    assert result < 1.0 or result > 359.0


def test_swan_time_is_utc_style_compact_timestamp():
    assert _swan_time(np.datetime64("2026-07-16T03:00:00")) == "20260716.030000"


def test_swan_timestep_must_divide_output_interval():
    region = {
        "output_interval_hours": 1,
        "models": {"swan": {"computational_timestep_minutes": 5}},
    }
    assert _computational_timestep_minutes(region) == 5

    region["models"]["swan"]["computational_timestep_minutes"] = 7
    with pytest.raises(ValueError, match="divide"):
        _computational_timestep_minutes(region)
