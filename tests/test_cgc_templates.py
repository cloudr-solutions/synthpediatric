"""The CGC measure config templates load and pass the measure audit on a stand-in extract."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from synthpediatric.measure import read_structured, run_measure

TEMPLATES = Path(__file__).resolve().parents[1] / "cgc" / "templates"


def _extract(n: int = 3000) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    return pd.DataFrame({
        "iccc_category": rng.choice(["I Leukemias", "III CNS"], size=n),
        "sex": rng.choice(["Male", "Female"], size=n),
        "age_group": rng.choice(["00-04", "05-09", "10-14"], size=n),
        "diagnosis_year_group": rng.choice(["2001-2005", "2006-2010"], size=n),
        "vital_status": rng.choice(["Alive", "Dead"], size=n),
        "months": rng.uniform(1, 150, size=n),
        "event": rng.integers(0, 2, size=n),
    })


@pytest.mark.parametrize("name", ["measure_config.template.yaml", "measure_config.template.json"])
def test_template_runs_on_a_stand_in_extract(tmp_path, name):
    if name.endswith(".yaml"):
        pytest.importorskip("yaml")
    _extract().to_csv(tmp_path / "extract_ctc.csv", index=False)
    cfg = read_structured(TEMPLATES / name)
    cfg["data"] = str(tmp_path / "extract_ctc.csv")  # the only change a user makes: the path
    cfg["outputs"] = {"dir": str(tmp_path / "measure_out")}
    manifest = run_measure(cfg)
    assert manifest
    assert (tmp_path / "measure_out" / "measure_manifest.json").exists()
