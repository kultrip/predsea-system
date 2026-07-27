import ast
from pathlib import Path

import pytest

from scripts.run_marine_simulation import stage_cmems_forcing


RUNNER = Path(__file__).parents[1] / "scripts" / "run_marine_simulation.py"


def test_runner_never_imports_shutil_inside_a_function():
    tree = ast.parse(RUNNER.read_text(encoding="utf-8"))
    offenders = []
    for function in (
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ):
        for node in ast.walk(function):
            if isinstance(node, ast.Import) and any(
                alias.name == "shutil" for alias in node.names
            ):
                offenders.append((function.name, node.lineno))
            if isinstance(node, ast.ImportFrom) and node.module == "shutil":
                offenders.append((function.name, node.lineno))
    assert offenders == []


def test_stage_cmems_forcing_copies_nonempty_artifact(tmp_path: Path):
    inputs_dir = tmp_path / "inputs"
    croco_work = tmp_path / "outputs" / "croco_alboran_1km"
    inputs_dir.mkdir()
    croco_work.mkdir(parents=True)
    staged = inputs_dir / "cmems_ocean_forcing.nc"
    staged.write_bytes(b"CDF\x01validated-cmems-test-payload")

    destination = stage_cmems_forcing(staged, croco_work)

    assert destination == croco_work / "cmems_ocean_forcing.nc"
    assert destination.read_bytes() == staged.read_bytes()


def test_stage_cmems_forcing_rejects_empty_artifact(tmp_path: Path):
    staged = tmp_path / "cmems_ocean_forcing.nc"
    staged.touch()
    croco_work = tmp_path / "croco_alboran_1km"
    croco_work.mkdir()

    with pytest.raises(ValueError, match="Pre-staged CMEMS forcing is empty"):
        stage_cmems_forcing(staged, croco_work)
