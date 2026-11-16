# Validation: compare a synthetic cohort with a real one

`synthpediatric validate` compares one or more synthetic cohorts with a real cohort and
writes a similarity report. The headline number is the **real-vs-synthetic discriminator
AUC**: a classifier tries to tell real rows from synthetic rows, and an AUC near 0.5
means it cannot. Track that number across versions (v0, v1, v2, v3) to show progress.

This is the first tier of the scorecard adopted for the Jamboree (read-ahead, accepted
Oct 28): univariate fidelity, dependency fidelity, the discriminator, a replicate envelope
and an iteration history. Privacy gates (identifiability, attribute inference,
nearest-neighbour distance), specific utility and temporal metrics come later.

The tool is meant to run **inside the CGC workspace**, where the real participant-level
NCCR data lives. Only the report files leave CGC; see [What the report contains](#what-the-report-contains).

## Install

```bash
pip install -e ".[validate]"     # adds scikit-learn==1.5.2, needed for the discriminator only
```

Everything else in the package, including the univariate and dependency measures of this
module, imports and runs without scikit-learn. Asking for the discriminator without it
fails with: `The discriminator AUC needs scikit-learn. Install it with: pip install
"synthpediatric[validate]"`.

## Run it

```bash
synthpediatric validate real.parquet syn_seed1.parquet syn_seed2.parquet syn_seed3.parquet \
    --dictionary examples/nccr_ctc_dictionary.json \
    --label v0 --out-dir out/validation
```

| Argument | Meaning |
|---|---|
| `real` | real cohort, `.csv` or `.parquet` |
| `synthetic ...` | one or more synthetic cohorts. Two or more files are treated as replicates (same config, different seeds) |
| `--dictionary` | optional context for column types: a dictionary JSON, a generation config (`.yaml`/`.json`), a `.ttl` file or `remote` (with `--source`) |
| `--label` | run label, e.g. `v0`; letters, digits, `.`, `_`, `-` (max 64) |
| `--out-dir` | where the report files go |
| `--history` | history CSV to append to (default `<out-dir>/history.csv`) |
| `--min-count` | disclosure threshold: category counts below it are suppressed (default 16) |
| `--seed` | seed for the discriminator's sampling, folds and forest (default 0) |
| `--folds` | cross-validation folds for the discriminator (default 5) |
| `--metrics` | comma-separated subset of the metric names below (default: all) |
| `--exclude` | comma-separated columns to leave out, such as participant IDs or dates |

Leave out identifier columns with `--exclude`. They would not leak (no values are
written), but they make the discriminator meaningless.

### Output files

- `report_<label>.json`: the machine-readable report (schema below).
- `summary_<label>.txt`: a short human-readable summary, also printed to the terminal.
- `history.csv`: one row per run with the headline numbers, appended in run order. A
  repeated label is appended again with a warning; the last row for a label is the latest.

From Python:

```python
from synthpediatric.validate import validate_cohorts, write_report, read_history
report = validate_cohorts(real_df, [syn1, syn2, syn3], label="v1", dictionary=d, seed=0)
write_report(report, "out/validation")
read_history("out/validation/history.csv")[["label", "auc"]]
```

## Metric names (closed list)

These are the only names accepted by `--metrics` and, once wired, by the `fidelity:` list
of the `validate:` config block. `synthpediatric.validate.METRIC_NAMES` holds the list
and `check_metric_names` / `check_validate_block` reject anything else. The `utility`
and `privacy` lists are empty for now. Wiring the block into `config.py` and the run
pipeline is deferred to a later change.

| Name | What it computes |
|---|---|
| `tvd` | total variation distance per categorical variable |
| `ks` | Kolmogorov-Smirnov distance per numeric variable |
| `assoc_diff` | pairwise association difference, real vs synthetic |
| `discriminator_auc` | cross-validated real-vs-synthetic classifier AUC (headline) |
| `replicate_envelope` | share of real statistics inside the replicate range |

## The measures

**Univariate fidelity.** For each shared column: total variation distance (TVD, half the
sum of absolute differences in category proportions, 0 to 1) for categorical columns, and
the two-sample Kolmogorov-Smirnov statistic (largest gap between the two empirical CDFs,
0 to 1) for numeric columns. Missing values count as their own category; for KS they are
dropped. The summary gives the mean, the max and the worst variables.

**Dependency fidelity.** For every pair of shared columns, the same association measure is
computed in the real and the synthetic cohort, and the report gives the absolute
difference. All measures run from 0 (no association) to 1:

- categorical x categorical: bias-corrected Cramer's V (Bergsma 2013). The correction
  keeps V near 0 for independent variables in finite samples, so sampling noise does not
  look like dependence;
- categorical x numeric: correlation ratio (eta), with the same kind of small-sample
  adjustment;
- numeric x numeric: absolute Spearman rank correlation.

Categories are those of the real cohort, top 50 by frequency; rarer levels share one
code. The summary gives the mean and max difference and the worst pairs with both values.
Because the corrected V is clipped at 0, two independent variables still show a small
positive V by chance, larger in smaller cohorts: about 0.01 to 0.02 at 5,000 rows. Treat
differences of that size as noise; the replicate envelope tells you which ones are not.

**Discriminator AUC (headline).** A random forest is trained to label rows real (0) or
synthetic (1); the report gives the mean held-out AUC over stratified K folds (default 5),
the per-fold values and their standard deviation, and the columns that drive it. Column
importance is permutation importance: how much the held-out AUC drops when that column is
shuffled (up to 2,000 held-out rows per fold, 3 repeats). The top columns are where to
look next. With several synthetic replicates, one discriminator runs per replicate (seed
`seed + i`); the report gives the mean AUC, each replicate's AUC, and the mean importance.

**Replicate envelope.** Generate K synthetic cohorts with the same config and different
seeds. For each statistic (the proportion of every real category with at least
`min-count` rows, mean/SD/median of numeric columns, and every pairwise association), the
check asks whether the real value lies inside the [min, max] range of the K replicate
values. If the generator were unbiased, the real value would be exchangeable with the
replicates and fall inside the range with probability (K - 1)/(K + 1): 0.6 for K = 4,
about 0.82 for K = 10. The report gives that expected share beside the observed share,
per family (univariate, dependency), and lists the statistics furthest outside. An
observed share well below the expected one means real bias. A large univariate distance
whose statistic still sits inside the envelope is sampling noise. The envelope needs at
least 2 replicates; with one, it is reported as not available. Use K of at least 5 for a
readable result.

**Iteration history.** Each run appends one row to `history.csv`: label, time, sizes,
AUC and its fold SD, univariate mean/max, dependency mean/max, envelope share, threshold,
seed and package version. `read_history` loads it for the v0 to v3 trend at the report-out.

## What the report contains

The report is designed to be exported from CGC under the disclosure rule that cells under
16 are suppressed. It contains **only aggregate statistics**:

- run metadata: label, timestamp, package version, settings;
- row counts of each cohort, the shared column names, the detected type of each column,
  and the names of columns found in only one cohort or excluded;
- distances (TVD, KS) per column, association values and differences per column pair,
  AUCs per fold and replicate, permutation importances per column;
- envelope results: counts of statistics inside/outside, and for the worst statistics the
  real value, the replicate range and the gap (proportions only for real categories with
  at least `min-count` rows);
- `category_detail`: for the worst categorical variables (up to 10), counts per category
  in the real cohort and in the first synthetic cohort, at most 25 levels each.

It never contains a row, a row index, an identifier, or a value from a free-text or
numeric column. Disclosure control on category-level content:

- a category level is named only if its real or synthetic count is at least `min-count`;
  all other levels are pooled into one row, `(other levels, each below the threshold in
  both cohorts)`;
- every count below `min-count` (including 0) is replaced by `null`;
- complementary suppression: if exactly one count in a variable's list is suppressed, the
  next smallest is suppressed too, so the total cannot reveal it;
- envelope proportions are given only for real levels with at least `min-count` rows, and
  if the remaining rows add up to between 1 and `min-count - 1`, the smallest listed
  level is also left out, so the small remainder cannot be worked out as 1 minus the rest;
- before writing, `audit_report` walks the whole report and refuses to write it if any
  count is below the threshold or any list is longer than 1,000 items.

Labels of synthetic-only levels come from the published dictionary. The threshold is set
with `--min-count` (or `min_count=` in Python) and is recorded in the report. The real
cohort itself must have at least `min-count` rows.

The disclosure reviewer should still look at the report before release: association
values and AUCs are aggregates over the whole cohort, but this tool does not apply any
rule beyond the ones listed above.

## Decisions on the open points

**Classifier and encoding: scikit-learn `RandomForestClassifier`, integer-coded
categories, new optional extra `validate` (`scikit-learn==1.5.2`).** A model with only
main effects, such as logistic regression on one-hot columns, cannot see a broken
relationship when each marginal is still right; a shuffled column changes no marginal.
Trees see interactions. We tried scikit-learn's `HistGradientBoostingClassifier` first;
on the development Mac it took about 2 s per fit against 0.14 s for a 100-tree forest
(OpenMP thread overhead), with the same detection power in our tests. The forest uses
`n_estimators=100`, `min_samples_leaf=5`, `max_features="sqrt"`, `n_jobs=1` and a fixed
`random_state`, so it is reproducible for a given seed. Categories are integer-coded by
pooled frequency (top 50 levels; rarer levels share one code; missing is a level), which
trees split well without a one-hot blow-up on wide NCCR tables. Numeric missing values
become a sentinel value (-1e12) that trees can isolate. scikit-learn is BSD-licensed, so
it fits the open-release goal (unlike SDV, which is BSL). The pin follows the existing
`pyyaml==6.0.3` style; 1.5.2 supports Python 3.9 (the package minimum) through 3.13 and
NumPy 2. It is also in the `dev` extra so CI runs the discriminator tests.

**Numeric vs categorical.** The dictionary decides when it lists the column: a `vtype`
such as `numeric`, `integer` or `continuous` makes it numeric, anything else categorical.
Without a dictionary entry, a column is numeric if it has a numeric dtype in every cohort
and more than 20 distinct values in the real cohort; otherwise categorical. A column that
is text in any cohort is categorical. This matches the generator, which is
categorical-heavy and stores codes such as stage or age group as small sets of values.
Integral floats (a CSV integer column with missing values) are compared as integers, so
`1` and `1.0` are the same category.

**Unequal sizes.** The larger cohort is down-sampled at random, without replacement and
with the run seed, to the size of the smaller one, then both are capped at 20,000 rows
per class (`max_rows_per_class`). Balanced classes keep the AUC's 0.5 baseline
meaningful and give each cohort equal weight. The univariate, dependency and envelope
measures use all rows, since they are proportions and do not depend on class balance.

**Report formats.** JSON for the machine-readable report (nested, keeps per-fold and
per-pair detail, readable from R with `jsonlite`), plain text for the summary, and CSV for
the history (one flat row per run, easy to plot or open in a spreadsheet).

**Where the replicates come from.** The caller generates them and passes them in: on the
CLI as several synthetic files, in Python as a list of DataFrames. `generate_replicates(fn,
k, seed)` calls a generator function with seeds `seed+1 ... seed+k` for convenience,
for example `lambda s: generate(d, n=5000, rng=s).data` or a `run_recipe` call with the
config's seed overridden. The tool does not run the generator itself, because inside CGC
the cohorts are usually produced elsewhere and brought in as files, and because a
validation run should not depend on network access to the NCCR metadata.

## Reproducibility and platforms

With the same inputs, seed and package versions, the report is the same apart from the
timestamp. Floating-point results can differ in the last digits between macOS and Linux,
so the tests check ranges (for example AUC between 0.4 and 0.6 for two seeds of the same
generator, AUC above 0.6 after a shuffled column), never exact values.
