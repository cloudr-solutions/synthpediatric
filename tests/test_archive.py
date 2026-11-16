import hashlib
import json
import zipfile

import pytest

from synthpediatric.cli import main
from synthpediatric.config import ConfigError, normalize_config
from synthpediatric.recipe import run_recipe, write_run

DICT = "examples/nccr_ctc_dictionary.json"
REPORTS = {"coverage.csv", "conformance.csv", "fidelity.csv", "manifest.json", "dictionary.json"}


def _cfg(**outputs):
    cfg = {"name": "My Run!", "metadata": DICT, "n": 200, "seed": 3}
    if outputs:
        cfg["outputs"] = outputs
    return cfg


def _names(path):
    return {p.name for p in path.iterdir()}


def test_zip_has_one_entry_and_reports_stay_plain(tmp_path):
    out = write_run(run_recipe(_cfg(archive="zip")), tmp_path)
    zips = [p for p in out.iterdir() if p.suffix == ".zip"]
    assert len(zips) == 1
    with zipfile.ZipFile(zips[0]) as zf:
        entries = zf.namelist()
    assert entries == [zips[0].stem + ".csv"]
    assert REPORTS <= _names(out)
    assert _names(out) == REPORTS | {zips[0].name}  # no bare CSV by default


def test_extracted_csv_identical_to_plain_run(tmp_path):
    plain = write_run(run_recipe(_cfg()), tmp_path / "plain")
    zipped = write_run(run_recipe(_cfg(archive="zip")), tmp_path / "zip")
    z = next(zipped.glob("*.zip"))
    with zipfile.ZipFile(z) as zf:
        data = zf.read(zf.namelist()[0])
    assert data == (plain / "cohort.csv").read_bytes()


def test_keep_csv_true_and_false(tmp_path):
    kept = write_run(run_recipe(_cfg(archive="zip", keep_csv=True)), tmp_path / "k")
    gone = write_run(run_recipe(_cfg(archive="zip")), tmp_path / "g")
    assert len(list(kept.glob("*.csv"))) == 4 and len(list(gone.glob("*.csv"))) == 3
    z = next(kept.glob("*.zip"))
    with zipfile.ZipFile(z) as zf:
        assert zf.read(zf.namelist()[0]) == (kept / (z.stem + ".csv")).read_bytes()


def test_archive_name(tmp_path):
    out = write_run(run_recipe(_cfg(archive="zip", archive_name="seer_ctc.zip")), tmp_path)
    assert (out / "seer_ctc.zip").exists()
    with zipfile.ZipFile(out / "seer_ctc.zip") as zf:
        assert zf.namelist() == ["seer_ctc.csv"]


def test_manifest_fields(tmp_path):
    out = write_run(run_recipe(_cfg(archive="zip", archive_name="a")), tmp_path)
    m = json.loads((out / "manifest.json").read_text())["archive"]
    with zipfile.ZipFile(out / "a.zip") as zf:
        raw = zf.read("a.csv")
    assert m["archive"] == "a.zip" and m["entry"] == "a.csv"
    assert m["csv_bytes"] == len(raw)
    assert m["zip_bytes"] == (out / "a.zip").stat().st_size
    assert m["csv_sha256"] == hashlib.sha256(raw).hexdigest()
    assert m["csv_kept"] is False


def test_plain_run_manifest_has_no_archive_key(tmp_path):
    out = write_run(run_recipe(_cfg()), tmp_path)
    assert "archive" not in json.loads((out / "manifest.json").read_text())


def test_parquet_with_zip_rejected(tmp_path):
    with pytest.raises(ConfigError, match="csv output only"):
        normalize_config(_cfg(archive="zip", format="parquet"))
    with pytest.raises(ConfigError, match="csv output only"):
        write_run(run_recipe(_cfg(archive="zip")), tmp_path, fmt="parquet")


def test_validation_errors():
    with pytest.raises(ConfigError, match="Valid choices"):
        normalize_config(_cfg(archive="tar"))
    with pytest.raises(ConfigError, match="keep_csv"):
        normalize_config(_cfg(archive="zip", keep_csv="yes"))
    with pytest.raises(ConfigError, match="archive_name"):
        normalize_config(_cfg(archive="zip", archive_name="a/b"))


def test_cli_archive_flag(tmp_path):
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps(_cfg()))
    out = tmp_path / "o"
    rc = main(["run", str(cfg), "--out-dir", str(out), "--archive", "zip"])
    assert rc == 0
    assert len(list(out.glob("*.zip"))) == 1
