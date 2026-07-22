from __future__ import annotations

import numpy as np
from pathlib import Path

from scripts.prepare_croco_forcing import croco_climatology_times


def test_climatology_uses_croco_ssh_variable_contract():
    source = Path("scripts/prepare_croco_forcing.py").read_text()

    assert '"SSH": (("ssh_time", "eta_rho", "xi_rho"), zeta_clm)' in source
    assert '"zeta": (("ssh_time", "eta_rho", "xi_rho"), zeta_clm)' not in source


def test_builds_named_elapsed_day_axes_required_by_croco():
    source = np.array(
        ["2026-07-16T00:00:00", "2026-07-16T01:00:00", "2026-07-16T06:00:00"],
        dtype="datetime64[s]",
    )

    axes = croco_climatology_times(source)

    assert set(axes) == {"ssh_time", "uclm_time", "tclm_time", "sclm_time"}
    for name, (dimension, values) in axes.items():
        assert dimension == name
        np.testing.assert_allclose(values, [0.0, 1.0 / 24.0, 0.25])


def test_rejects_non_increasing_climatology_time():
    source = np.array(
        ["2026-07-16T00:00:00", "2026-07-16T00:00:00"], dtype="datetime64[s]"
    )

    try:
        croco_climatology_times(source)
    except ValueError as exc:
        assert "increasing" in str(exc)
    else:
        raise AssertionError("duplicate CROCO forcing timestamps must be rejected")
