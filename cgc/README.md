# synthpediatric in CGC: start here

This folder is the entry point for the Jamboree teams who work in CGC.
The **Input team** runs `synthpediatric measure` on the real NCCR data inside CGC and exports only disclosure-controlled aggregates.
The **Output team** takes those aggregates, builds synthetic cohorts with `synthpediatric run`, and checks them against the real data with `synthpediatric validate`.

**Read this first.** VERIFIED means the command was run and seen to work, on macOS arm64, on 2026-11-16, with the Python versions named, against commit `baddbea` of `main`. NOT VERIFIED means it was not run as written. Nothing has been run on Linux or in a CGC workspace yet, so check your first install there and report problems.

Files in this folder:

* [INSTALL.md](INSTALL.md): detailed install notes and the offline (no internet) recipe.
* [templates/measure_config.template.yaml](templates/measure_config.template.yaml) and [templates/measure_config.template.json](templates/measure_config.template.json): measure configs to copy and edit.
* [templates/extract_ctc_example.py](templates/extract_ctc_example.py): an example of writing the flat extract file.
* Reference docs: [../docs/measure.md](../docs/measure.md) (all measure keys and output formats), [../docs/validation.md](../docs/validation.md), [../docs/cookbook.md](../docs/cookbook.md) (generator recipes).

## Start here: install

You need Python 3.9 or newer (tested: 3.9, 3.10, 3.12; check with `python3 --version`) and, for the GitHub routes, access to github.com and pypi.org and the `git` program installed and on the PATH.

Python 3.14 caveat: the `[validate]` extra cannot be installed on 3.14, because it pins scikit-learn 1.5.2, which has no 3.14 wheel. `measure` needs only the core and `[yaml]`, which work on 3.14. Use Python 3.10 to 3.13 if you also need `validate`.

| You want to | Install |
|---|---|
| Run `measure` with a JSON config | `synthpediatric` (no extra) |
| Run `measure` or `run` with a YAML config | `synthpediatric[yaml]` |
| Also run `validate` (discriminator AUC) | `synthpediatric[yaml,validate]` |

Make a virtual environment first:

```bash
python3 -m venv ~/sp-env && source ~/sp-env/bin/activate      # NOT VERIFIED (made with uv here)
```

**Route A, straight from GitHub (no examples on disk).** Installs the latest `main`:

```bash
pip install "synthpediatric[yaml,validate] @ git+https://github.com/cloudr-solutions/synthpediatric.git"
```

VERIFIED with uv on Python 3.9, 3.10 and 3.12. To pin a version so both teams run the same code, add `@<ref>` after `.git`, where `<ref>` is a commit sha or a release tag:

```bash
pip install "synthpediatric[yaml,validate] @ git+https://github.com/cloudr-solutions/synthpediatric.git@jamboree-2026-11-16"
```

`jamboree-2026-11-16` is the release tag for the version the Jamboree teams share (the nine-source fixes, `measure`, the core `validate`, and this folder). Newer tags will be announced; use the tag your team lead names. Pinning to a commit sha (`baddbea`) was VERIFIED with pip 26.3 on Python 3.10 and 3.12. Pinning to a tag uses the same syntax, but it was not run as written before the tag existed.

**Route B, clone, then install (examples and docs included).**

```bash
git clone https://github.com/cloudr-solutions/synthpediatric.git     # VERIFIED
pip install "./synthpediatric[yaml,validate]"                         # VERIFIED with uv pip, 3.10 and 3.12
```

To pin the clone, run `git checkout jamboree-2026-11-16` (or a commit sha) inside `synthpediatric/` before the `pip install` line. NOT VERIFIED.

Check the install:

```bash
synthpediatric --version          # VERIFIED: prints "synthpediatric 0.0.1"
synthpediatric measure --help     # VERIFIED
synthpediatric validate --help    # VERIFIED
```

The first command after an install can take 10 to 15 s. After that each command starts in 1 to 2 s. After Route A there is no `examples/` folder; use the templates in this folder instead. If CGC cannot reach GitHub or PyPI, see [INSTALL.md](INSTALL.md).

## Input team in 5 steps

1. Install (above), with `[yaml]` if you use the YAML template.
2. In a CGC notebook, write one flat file for one NCCR source table (for example Consolidated Tumor Case): one row per participant, only the columns you need, as CSV or parquet, saved in the workspace. See [templates/extract_ctc_example.py](templates/extract_ctc_example.py). Table and column names in your workspace may differ, so check them.
3. Copy [templates/measure_config.template.yaml](templates/measure_config.template.yaml) (or the `.json` one) next to the extract and edit it: the `data` file name, the variable names (use `rename:` and `labels:` if your columns or codes differ from the NCCR names) and the survival columns. Leave `threshold: 16` alone unless you have approval.
4. Run it from that folder: `synthpediatric measure measure_config.template.yaml`. It must end with `Audit passed on N files. Manifest: measure_manifest.json`. If the audit fails, no output is kept.
5. Export the output folder (see below) and nothing else.

VERIFIED on macOS: this flow with a stand-in extract, for both templates (YAML with the `[yaml]` extra, JSON with no extra). The templates use stand-in variable names. They have not been checked against the real NCCR labels or in CGC.

## Output team in 5 steps

1. Install (above), with `[yaml,validate]` if you will run `validate`.
2. Get the Input team's `measure_out/` folder and put it in your workspace.
3. Write a generator config that points at it, as in `examples/measure/generate_from_measured.yaml` in a clone (`targets.overrides.tables`, `targets.joints.crosstabs`, `targets.survival.specs`). The formats are in [../docs/measure.md](../docs/measure.md) and the recipes in [../docs/cookbook.md](../docs/cookbook.md).
4. Generate: `synthpediatric run your_config.yaml` (VERIFIED with the example config on a stand-in cohort).
5. Compare with the real extract, inside CGC: `synthpediatric validate extract_ctc.csv cohort.csv --label v0 --out-dir validate_out` (VERIFIED on a stand-in, Python 3.12 with `[validate]`, 40 s). Only the report files leave CGC. See [../docs/validation.md](../docs/validation.md).

## What to export from CGC

Export only the `measure` output folder:

```text
measure_out/
  freqs/<variable>.json             one-way counts, each at least 16
  crosstabs/<name>.csv              cross-tab counts, each at least 16
  survival/<name>.json              survival specs for the generator
  survival/<name>_summary.csv       the same, for people (blank = withheld)
  measure_manifest.json             tool version, config and input hashes, suppression counts
```

Do not export the extract or any other file. The stand-in run gave 9 files, 36 KB.
