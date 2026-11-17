# R is not added to CI; this test must be run manually with Rscript 4.5.1 available.
"""cgc/R/synth_heatmap.R gives the same numbers as synthpediatric.validate.

Every test skips when ``Rscript`` is not on the PATH.
"""
from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from synthpediatric import validate as V

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "cgc" / "R" / "synth_heatmap.R"
SELF_CHECK = ROOT / "cgc" / "R" / "test_synth_heatmap.R"
RSCRIPT = shutil.which("Rscript")
if RSCRIPT is None:
    pytestmark = pytest.mark.skip(reason="Rscript is not installed")

ICCC = ["I(a) Lymphoid leukemias", "II(a) Hodgkin lymphomas", "III(b) Astrocytomas",
        "IV Neuroblastoma,\nand other peripheral nervous cell tumors", "VI(a) Nephroblastoma"]
AGES = ["00 years", "01-04 years", "05-09 years", "10-14 years", "15-19 years"]
TINY = (ICCC[0], "15-19 years")  # the deliberately small real cell


def make_cohort(seed: int, n: int = 3000, tiny: bool = False) -> pd.DataFrame:
    """A cohort shaped like the CTC extract: ICCC group by age group, sex, a stage with
    missing values, and two numeric columns. ``tiny`` leaves 5 records in cell TINY."""
    rng = np.random.default_rng(seed)
    iccc = rng.choice(ICCC, size=n, p=[0.35, 0.2, 0.2, 0.15, 0.1])
    shift = pd.Series(iccc).map({g: i for i, g in enumerate(ICCC)}).to_numpy()
    age_idx = np.clip(rng.integers(0, 5, size=n) + (shift >= 3) * -2 + (shift == 1) * 2, 0, 4)
    age = np.array(AGES)[age_idx]
    sex = rng.choice(["Male", "Female"], size=n, p=[0.53, 0.47])
    stage = rng.choice(["Localized", "Regional", "Distant", None], size=n, p=[0.4, 0.3, 0.2, 0.1])
    years = age_idx * 4 + rng.integers(0, 4, size=n)
    survival = np.round(rng.exponential(60 + 10 * shift, size=n), 1)
    survival[rng.random(n) < 0.05] = np.nan
    df = pd.DataFrame({"icccMajor": iccc, "ageRecode19Groups": age, "sex": sex,
                       "stage": stage, "ageYears": years, "survivalMonths": survival})
    if tiny:
        in_cell = (df.icccMajor == TINY[0]) & (df.ageRecode19Groups == TINY[1])
        extra = df.iloc[:5].copy()
        extra["icccMajor"], extra["ageRecode19Groups"] = TINY
        df = pd.concat([df[~in_cell], extra], ignore_index=True)
    return df


def run_r(real: Path, synth: Path, out: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [RSCRIPT, str(SCRIPT), "--real", str(real), "--synth", str(synth), "--out", str(out)],
        capture_output=True, text=True, timeout=300,
    )


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    d = tmp_path_factory.mktemp("r_heatmap")
    real, syn = d / "real.csv", d / "synth.csv"
    make_cohort(1, tiny=True).to_csv(real, index=False)
    make_cohort(2).to_csv(syn, index=False)
    zpath = d / "synth.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.write(syn, "cohort.csv")
    out = d / "out"
    res = run_r(real, zpath, out)  # the zip route
    assert res.returncode == 0, res.stdout + res.stderr
    assert "Audit passed: no disclosure violation found" in res.stdout
    return real, syn, out


def python_numbers(real_csv: Path, syn_csv: Path):
    real, syn = V.read_frame(real_csv), V.read_frame(syn_csv)
    cols = list(real.columns)
    types = V.detect_types([real, syn], cols)
    rc, sc = V._Cohort(real, cols, types), V._Cohort(syn, cols, types)
    levels = {c: V._levels(rc.cat[c], 50) for c in rc.cat}
    return types, rc, sc, levels


def test_r_self_check():
    res = subprocess.run([RSCRIPT, str(SELF_CHECK)], capture_output=True, text=True, timeout=300)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "all checks passed" in res.stdout


def test_cramers_v_matches_validate(run):
    real, syn, out = run
    types, rc, sc, levels = python_numbers(real, syn)
    m_real = pd.read_csv(out / "cramersv_real.csv", index_col=0)
    m_syn = pd.read_csv(out / "cramersv_synth.csv", index_col=0)
    cats = [c for c in types if types[c] == "categorical"]
    assert sorted(m_real.index) == sorted(cats)
    assert list(m_real.index) == list(m_real.columns)
    for i, a in enumerate(cats):
        for b in cats[i + 1:]:
            ka, kb = len(levels[a]) + 1, len(levels[b]) + 1
            for cohort, mat in ((rc, m_real), (sc, m_syn)):
                v = V.cramers_v(V._codes(cohort.cat[a], levels[a]), ka,
                                V._codes(cohort.cat[b], levels[b]), kb)
                assert abs(mat.loc[a, b] - v) < 0.01, (a, b)


def test_tvd_matches_validate(run):
    real, syn, out = run
    types, rc, sc, _ = python_numbers(real, syn)
    uni = pd.read_csv(out / "univariate_fidelity.csv").set_index("variable")
    assert list(uni.columns) == ["type", "measure", "distance"]
    for c, t in types.items():
        if t == "categorical":
            assert uni.loc[c, "measure"] == "tvd"
            assert abs(uni.loc[c, "distance"] - V.tv_distance(rc.cat[c], sc.cat[c])) < 0.01, c
        else:
            assert uni.loc[c, "measure"] == "ks"
            assert abs(uni.loc[c, "distance"] - V.ks_distance(rc.num[c], sc.num[c])) < 0.01, c


def test_tiny_cell_and_complement_are_suppressed(run):
    real, _, out = run
    share = pd.read_csv(out / "cell_real_share.csv", index_col=0)
    assert ICCC[3] in share.index  # the label with a comma and a line break is one level
    assert pd.isna(share.loc[TINY[0], TINY[1]])
    # complementary suppression: one more blank cell in the tiny cell's row and column
    assert share.loc[TINY[0]].isna().sum() >= 2
    assert share[TINY[1]].isna().sum() >= 2
    for name in ("cell_synth_share.csv", "cell_diff.csv"):
        other = pd.read_csv(out / name, index_col=0)
        assert (other.isna().to_numpy() == share.isna().to_numpy()).all(), name
    # every shown real share is a cell of at least 16 records; no counts are written
    r = pd.read_csv(real)
    for row in share.index:
        for col in share.columns:
            v = share.loc[row, col]
            if pd.notna(v) and row != "(other levels)" and col != "(other levels)":
                n = ((r.icccMajor == row) & (r.ageRecode19Groups == col)).sum()
                assert n >= 16 and abs(v - n / len(r)) < 1e-12
    assert ((share.stack() >= 0) & (share.stack() <= 1)).all()


def test_figures_exist(run):
    _, _, out = run
    for f in ["heatmap_cramersv_real", "heatmap_cramersv_synth", "heatmap_cramersv_diff",
              "heatmap_univariate", "heatmap_cell_real_share", "heatmap_cell_synth_share",
              "heatmap_cell_diff"]:
        assert (out / f"{f}.png").stat().st_size > 0, f
        assert (out / f"{f}.pdf").stat().st_size > 0, f
    assert "Top 10 worst pairs" in (out / "summary.txt").read_text()
