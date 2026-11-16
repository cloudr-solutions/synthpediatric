# synthpediatric in CGC: quick start

For the Input team (runs `measure` on the real data inside CGC) and the Output team (builds
synthetic cohorts from what the Input team exports). Code:
https://github.com/cloudr-solutions/synthpediatric.

**Read this first.** Labels: **VERIFIED** means the command was run and seen to work, on
macOS arm64, on 2026-11-16, with the Python versions named, against commit `baddbea` of
`main`. **NOT VERIFIED** means it was not run as written. Nothing has been run on Linux or
in a CGC workspace yet, so check the first install there.

## 1. What you need

* Python 3.9 or newer. Tested: 3.9, 3.10 and 3.12. Check with `python3 --version`.
* Python 3.14: the `validate` extra cannot be installed (it pins scikit-learn 1.5.2, which
  has no wheel for 3.14). `measure` only needs the core and `[yaml]`, which do have 3.14
  wheels. Use 3.10 to 3.13 if you also want `validate`.
* For the GitHub routes: access to github.com and pypi.org, and the `git` program must be
  installed and on the PATH (network access alone is not enough).
* Disk: about 200 MB for the core install, about 305 MB with `[yaml,validate]`.

Which extras to install:

| You want to | Install |
|---|---|
| Run `measure` with a JSON config | `synthpediatric` (no extra) |
| Run `measure` or `run` with a YAML config (all examples are YAML) | `synthpediatric[yaml]` |
| Also run `validate` (discriminator AUC) | `synthpediatric[yaml,validate]` |

Without `[yaml]`, a YAML config stops with `config error: YAML configs require PyYAML: pip
install 'synthpediatric[yaml]'`. Without `[validate]`, `validate` stops with `The
discriminator AUC needs scikit-learn`. Recommended: `[yaml,validate]`.

## 2. Install

Make a virtual environment first (the commands below assume it is active, or call
`~/sp-env/bin/pip` directly):

```bash
python3 -m venv ~/sp-env && source ~/sp-env/bin/activate      # NOT VERIFIED (made with uv here)
```

### Route A: straight from GitHub (no examples on disk)

```bash
pip install "synthpediatric[yaml,validate] @ git+https://github.com/cloudr-solutions/synthpediatric.git"
```

This installs the latest `main`. VERIFIED with uv on 3.9, 3.10 and 3.12. The same with uv,
if CGC has it:
`uv pip install "synthpediatric[yaml,validate] @ git+https://github.com/cloudr-solutions/synthpediatric.git"`
(VERIFIED, 3.9, 3.10, 3.12).

To pin to a specific commit or tag, add `@<ref>` after `.git`:

```bash
pip install "synthpediatric[yaml,validate] @ git+https://github.com/cloudr-solutions/synthpediatric.git@<TAG>"
```

`<TAG>` is a placeholder. A release tag will be named here later; until then use a commit
sha in its place. Pinning to a commit sha was VERIFIED with pip 26.3 on Python 3.10 (32 s)
and 3.12 (30 s), using `baddbea`. Pinning to a tag was not run, because no tag exists yet.
Use the same ref on every workspace so both teams run the same code.

This installs the program only. The `examples/` and `docs/` folders are **not** included,
so `examples/measure/*.yaml` does not exist after Route A. Write your own config
(section 4) or use Route B.

### Route B: clone, then install (examples and docs included)

```bash
git clone https://github.com/cloudr-solutions/synthpediatric.git     # VERIFIED (1.2 MB)
pip install "./synthpediatric[yaml,validate]"                         # VERIFIED with uv pip, 3.10 and 3.12
pip install -e "./synthpediatric[yaml,validate]"                      # editable; VERIFIED with uv pip, 3.12
```

To pin the clone, run `git checkout <TAG>` (or a commit sha) inside `synthpediatric/` before
the `pip install` line. NOT VERIFIED.

Check either route:

```bash
synthpediatric --version          # VERIFIED: prints "synthpediatric 0.0.1"
synthpediatric measure --help     # VERIFIED
synthpediatric validate --help    # VERIFIED
```

The first command after an install can take 10 to 15 s (Python compiles numpy and pandas
once). After that each command starts in 1 to 2 s.

## 3. Try it on a stand-in cohort (Route B)

Run these from the cloned `synthpediatric/` folder. The configs use paths relative to the
folder you run in, and they write under `out/`.

```bash
cd synthpediatric
synthpediatric run examples/measure/standin_generate.yaml        # 40,000 fake "real" records -> out/measure/standin/
synthpediatric measure examples/measure/measure_config.yaml      # aggregates -> out/measure/aggregates/
synthpediatric run examples/measure/generate_from_measured.yaml  # synthetic cohort from the aggregates
```

VERIFIED on 3.9, 3.10 and 3.12 (run in a folder holding a copy of `examples/`, which is
the same layout). Each step takes 1 to 2 s. `measure` must end with
`Audit passed on 9 files. Manifest: measure_manifest.json`. Running it again into the same
folder is refused; add `--overwrite` to replace an earlier measure result (VERIFIED).

## 4. Measure the real data (Input team)

1. In a CGC notebook, export one NCCR source table (for example Consolidated Tumor Case) to
   one flat CSV or parquet file, one row per participant, with only the columns you need.
   Save it in the workspace, for example `extract_ctc.csv`. It never leaves CGC.
2. Put a config next to it, `measure_ctc.yaml`:

```yaml
name: CTC measures, Jamboree day 1
data: extract_ctc.csv
threshold: 16                  # cells below 16 are suppressed; do not lower without approval
frequencies: [iccc_category, sex, age_group, diagnosis_year_group, vital_status]
crosstabs:
  - {name: sex_age, variables: [sex, age_group]}
survival:
  - name: survival_by_iccc
    group: iccc_category
    time: months               # follow-up in months
    event: event               # 0/1 or true/false
    horizon_months: 120
    time_points: [12, 36, 60, 120]
    s5: true
    median: true
    form: points
outputs: {dir: measure_out}
```

3. Run it from the same folder:

```bash
synthpediatric measure measure_ctc.yaml
```

VERIFIED with Route A installs (pip on 3.10 and 3.12, uv `[yaml]` on 3.10 and 3.12) on the
stand-in cohort. The same config as JSON (`measure_ctc.json`) works with no extra at all
(VERIFIED, 3.12). If your column names or codes differ from the NCCR names, add `rename:`
and `labels:`; for continuous columns add `bins:`. The full list of keys is in
[measure.md](measure.md) (in the clone, or on GitHub).

## 5. What comes out, and what to export

```text
measure_out/
  freqs/<variable>.json             one-way counts, each at least 16
  crosstabs/<name>.csv              cross-tab counts, each at least 16
  survival/<name>.json              survival specs for the generator
  survival/<name>_summary.csv       the same, for people (blank = withheld)
  measure_manifest.json             tool version, config and input hashes, suppression counts
```

The stand-in run gave 9 files, 36 KB. **Export only this `measure_out/` folder from CGC.**
Do not export the extract or any other file. If the audit fails, the command prints
`audit failed, no output was kept` and no output folder is created.

The Output team plugs the folder into a generator config, as in
`examples/measure/generate_from_measured.yaml` (`targets.overrides.tables`,
`targets.joints.crosstabs`, `targets.survival.specs`), and runs `synthpediatric run`.

## 6. If CGC cannot reach GitHub or PyPI

Build a wheelhouse on a machine with internet access, upload it to CGC, install with no
network:

```bash
# on a connected machine, in a Python 3.12 venv with pip:
git clone https://github.com/cloudr-solutions/synthpediatric.git
pip wheel --no-deps ./synthpediatric -w wheelhouse                     # VERIFIED (96 KB wheel)
pip download "synthpediatric[yaml,validate]" --find-links wheelhouse \
  --platform manylinux2014_x86_64 --platform manylinux_2_17_x86_64 --platform manylinux_2_28_x86_64 \
  --only-binary=:all: --python-version 3.12 --implementation cp -d wheelhouse   # VERIFIED (download only)

# in CGC, after uploading wheelhouse/:
pip install --no-index --find-links wheelhouse "synthpediatric[yaml,validate]"   # NOT VERIFIED on Linux
```

Set `--python-version` to the CGC Python (`python3 --version`). The wheels must match the
CGC Python version and Linux; Mac wheels do not work there. The offline install step was
VERIFIED on the Mac with Mac wheels (`uv pip install --offline --no-index --find-links`,
3.12), then `measure` passed its audit.

Measured bundle sizes (Linux x86_64):

| Python | Core only (JSON configs) | `[yaml]` | `[yaml,validate]` |
|---|---|---|---|
| 3.10 | 77 MB, 8 files | 78 MB | 127 MB, 14 files |
| 3.12 | 80 MB, 7 files | 81 MB | 127 MB, 13 files |
| 3.13 | | | 127 MB |
| 3.14 | | 81 MB | not possible (no scikit-learn 1.5.2) |

pyarrow is the largest file (48 to 53 MB). If the CGC image has an old glibc (below 2.28,
check with `ldd --version`), download with only `--platform manylinux2014_x86_64`: pip then
picks older wheels (pyarrow 20.0.0), 116 to 119 MB for `[yaml,validate]`. Every dependency
has a Linux wheel either way. To bring the examples too, upload the cloned folder (1.2 MB).
