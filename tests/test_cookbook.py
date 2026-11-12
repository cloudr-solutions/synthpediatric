"""Run every cookbook recipe end to end, offline, so docs/cookbook.md cannot rot."""
import json
from pathlib import Path

import pytest

from synthpediatric.cli import main

RECIPES = sorted(Path("examples/cookbook").glob("*.yaml"))


def test_every_recipe_letter_is_present():
    assert {p.name[0] for p in RECIPES} >= set("abcdefg")


@pytest.mark.parametrize("recipe", RECIPES, ids=lambda p: p.stem)
def test_cookbook_recipe_runs_and_writes_manifest(recipe, tmp_path, capsys):
    assert main(["run", str(recipe), "--out-dir", str(tmp_path)]) == 0
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert (tmp_path / "cohort.csv").exists()
    assert manifest["n_records"] == manifest["config"]["n"]
    capsys.readouterr()
