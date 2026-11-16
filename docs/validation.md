# Validation: compare a synthetic cohort with a real one

`synthpediatric validate` compares one or more synthetic cohorts with a real cohort and
writes a similarity report. The headline number is the **real-vs-synthetic discriminator
AUC**: a classifier tries to tell real rows from synthetic rows, and an AUC near 0.5
means it cannot. Track that number across versions (v0, v1, v2, v3) to show progress.

This is the first tier of the scorecard adopted for the Jamboree (read-ahead, accepted
Oct 28): univariate fidelity, dependency fidelity, the discriminator, a replicate envelope
and an iteration history. The privacy tier (identifiability, attribute inference,
nearest-neighbour distance ratio, membership inference) is described in
[Privacy tier](#privacy-tier), and a recipe can request validation through its
`validate:` block ([Validation from a config](#validation-from-a-config)). Specific
utility and temporal metrics come later.

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

**Python 3.14.** The `[validate]` extra cannot be installed on Python 3.14: it pins
scikit-learn 1.5.2, which has no wheel for 3.14. Use Python 3.10 to 3.13 for the
discriminator. The rest of this module, including the privacy tier, needs only numpy and
pandas and runs on 3.14.

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

These are the only names accepted by `--metrics` and `--privacy` and by the `fidelity:` and
`privacy:` lists of the `validate:` config block. `synthpediatric.validate.METRIC_NAMES`
holds the list and `check_metric_names` / `check_validate_block` reject anything else. The
`utility` list is empty: no utility metric is built yet.

| Group | Name | What it computes |
|---|---|---|
| fidelity | `tvd` | total variation distance per categorical variable |
| fidelity | `ks` | Kolmogorov-Smirnov distance per numeric variable |
| fidelity | `assoc_diff` | pairwise association difference, real vs synthetic |
| fidelity | `discriminator_auc` | cross-validated real-vs-synthetic classifier AUC (headline) |
| fidelity | `replicate_envelope` | share of real statistics inside the replicate range |
| privacy | `nn_distance_ratio` | nearest-neighbour distance, synthetic-to-real over real-to-real |
| privacy | `identifiability` | ADS-GAN identifiability score (Yoon et al. 2020), the proposed release gate |
| privacy | `attribute_inference` | accuracy of predicting a sensitive field from the synthetic data, against a marginal-only baseline |
| privacy | `membership_inference` | AUC of a nearest-synthetic-record attack, members against a holdout |

**Names that older docs and examples used.** The Jamboree planning notes listed
`correlation_difference`, `km_concordance`, `pmse`, `specific:survival_by_treatment`,
`nn_distance` and `membership_inference`. We kept the closed list as built and changed the
examples instead: `correlation_difference` is `assoc_diff`, `nn_distance` is
`nn_distance_ratio`, and `membership_inference` keeps its name. `km_concordance`, `pmse`
and `specific:...` are specific-utility metrics, out of scope for now, so they are not
accepted yet and the shipped examples no longer list them (their `utility:` list is
empty). An unknown name is an error with a did-you-mean hint; see
[Validation from a config](#validation-from-a-config).

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

## Privacy tier

Generating from published frequencies uses no individual-level records, so privacy holds
by design. The tier still measures it, because reviewers and release boards ask for a
number. All four measures compare a **real participant-level cohort** with the synthetic
cohort, so they run inside CGC, where the real data lives.

```bash
synthpediatric validate real.csv syn.csv --label p0 --out-dir out/validation \
    --metrics tvd --privacy all --holdout holdout.csv --sensitive vital_status
```

| Argument | Meaning |
|---|---|
| `--privacy` | comma-separated privacy metrics, or `all` (default: none) |
| `--holdout` | real records that were **not** used to build the synthetic data; needed for `membership_inference` |
| `--sensitive` | comma-separated categorical fields to attack in `attribute_inference`; no default |
| `--max-records` | sampling cap per cohort for the distance work (default 2,000) |

Python: `validate_cohorts(real, syn, privacy=[...], holdout=df, sensitive=[...],
thresholds={...}, max_records=2000)`. The result is under `report["privacy"]`.

### Distance

All distance-based measures use a weighted **Gower distance**, which suits records that
mix categorical and numeric fields. A categorical field contributes 0 when the two values
are equal and 1 otherwise (a missing value is a value of its own). A numeric field
contributes `|a - b| / range`, with the range taken from the real cohort and the result
capped at 1; one missing value contributes 1 and two missing values 0. The distance is the
weighted mean over fields, so it lies between 0 and 1. A Hamming distance is the special
case with only categorical fields and equal weights. Fields are weighted equally, except in
`identifiability` (below).

### The four measures

**Nearest-neighbour distance ratio** (`nn_distance_ratio`). For each synthetic record the
distance to its nearest real record, averaged; divided by the same average for each real
record and its nearest *other* real record. Both cohorts are sampled to the same size so
the ratio is fair.

- About 1: synthetic records are no closer to real individuals than real individuals are
  to each other. Near 0: synthetic records sit on top of real ones (copying).
- Also reported: the share of synthetic records identical to a real record, and the share
  of real records identical to another real record. The second is the natural background
  rate for a categorical-heavy cohort with few fields.
- It does not mean: a ratio far above 1 only says the cohorts are far apart, which is a
  fidelity matter, not a privacy gain.

**Identifiability score** (`identifiability`; Yoon et al. 2020, the ADS-GAN paper). For each
real record, `d` is the distance to its nearest other real record and `d_hat` the distance
to its nearest synthetic record. The score is the share of real records with `d_hat < d`
(strict). Fields are weighted by the inverse of their entropy (computed on the real
cohort, numeric fields in 10 bins), as in the paper, so a field with rare values counts
more; a field that never varies gets weight 0. This is the read-ahead's "release gate".
The wording in the notes ("probability that a synthetic record is closer to a real
individual than real individuals are to each other") is the paper's definition seen from
the real record's side; we follow the paper's per-real-record form.

- **The neutral value is about 0.5, not 0.** If the synthetic cohort is an independent draw
  from the same distribution as the real one, a real record's nearest neighbour among
  `n - 1` other real and `n` synthetic records is synthetic with probability about
  `n / (2n - 1)`. The report shows this reference beside the score. A perfect generator
  therefore scores about 0.5, and scores toward 1 mean synthetic records sit closer to
  individuals than other individuals do (copying).
- Ties (distance equal, for example identical categorical records) do not count as
  closer; their share is reported as `share_ties`. With few categorical fields, many
  real records are identical to another real record, which pushes the score down. Read the
  score together with `share_ties` and the identical-record shares above.
- It does not mean: a score below the reference is not a proof of safety, only that no
  unusual closeness to individuals was found by this distance.

**Attribute-inference risk** (`attribute_inference`; after Achterberg 2024). The attacker
knows every field of a real participant except one sensitive field, finds the participant's
5 nearest synthetic records (unweighted Gower distance over the known fields), and predicts
the sensitive field by a vote weighted by `1 / (distance + 0.001)`, so an exact match
dominates. The report gives the accuracy over the real records, the **baseline accuracy**
(always guess the most common value of the field in the synthetic marginal, with no other
knowledge) and the `lift`, accuracy minus baseline. Only categorical fields can be
attacked.

- A lift near 0 means the other fields add nothing beyond the marginal. A strongly
  positive lift means the synthetic data lets an attacker learn the field.
- It does not mean: a positive lift is not automatically a leak. If the synthetic data
  correctly reproduces a population-level relationship (age group and diagnosis, say), an
  attacker learns it legitimately. A lift also depends on how much the other fields
  predict the sensitive one in the real population. For an independent field the voting
  attack is usually a little *less* accurate than the mode guess (negative lift).
- Which fields count as sensitive is a policy decision; see the decisions below.

**Membership-inference AUC** (`membership_inference`). The attacker scores each record by
minus its distance to the nearest synthetic record and guesses "member" for high scores.
The AUC compares a group of **members** (the real cohort given as `real`) with a group of
**non-members** (the holdout), sampled to the same size. About 0.5 means the attacker
cannot tell them apart; toward 1 means the synthetic data sits closer to the members.

- It needs a holdout: real records the generator did not use. Without one, the metric is
  skipped and the report says so.
- It does not mean: for synthetic data made only from published frequencies, nothing in
  the generator depends on any individual, so a value near 0.5 is expected by
  construction. The number is a check, not a discovery.

### Release gate and thresholds

The read-ahead proposes the identifiability score as the release gate, but **no threshold
has been agreed**, and this tool does not invent one. Thresholds are configurable and
**unset by default**:

| Config key (under `validate.thresholds`) | Passes when |
|---|---|
| `identifiability_max` | identifiability score <= the value |
| `nn_distance_ratio_min` | ratio >= the value |
| `membership_auc_max` | membership AUC <= the value |
| `attribute_inference_lift_max` | the largest lift over the sensitive fields <= the value |

The report has a `thresholds` list (one entry per metric) and a `release_gate` entry (the
identifiability row). Each shows the measured value, the threshold, and a status: `pass`,
`fail`, `not computed` (a threshold is set but the metric did not run) or `no threshold
configured`. **Until the release board agrees a threshold, the measured value is a
number to look at, not a pass.** The report prints the plain-language interpretation of
each measure next to its value. Thresholds are available from the config and from Python
(`thresholds=`); the `validate` command does not take them.

### Sampling cap

Distance work is quadratic in the number of records. Each cohort is sampled (seeded, without
replacement) to at most `max_records` rows, default 2,000; when cohorts differ in size,
both are cut to the smaller one, so real-to-real and synthetic-to-real distances are
computed against equally large reference sets (a bigger reference set always finds closer
neighbours). Sampling adds noise: the identifiability score from 2,000 records has a
standard error of about 0.01 to 0.02. A cohort under 30 records is not scored (the metric
is skipped with that reason). On a development Mac, 60 mixed fields at the cap took about 3
seconds for all four measures. Raise the cap with `--max-records` or `validate.max_records`
for a tighter estimate; the work grows with the square of it.

## Validation from a config

A recipe can request validation with a `validate:` block. `synthpediatric run` then
computes the metrics after generation, writes `validation_report.json` and
`validation_summary.txt` next to `manifest.json`, and records the headline numbers in the
manifest under `validation`. A config without `validate:`, or with all three lists empty,
behaves exactly as before and writes neither file.

```yaml
validate:
  fidelity: [tvd, ks, assoc_diff, discriminator_auc]
  privacy: [nn_distance_ratio, identifiability, attribute_inference, membership_inference]
  real: /cgc/data/extract_ctc.csv       # participant-level file, available inside CGC
  holdout: /cgc/data/extract_ctc_holdout.csv
  sensitive: [vital_status]
  exclude: [participant_id]
  thresholds: {identifiability_max: 0.6}   # unset by default; 0.6 is only an example
  suppression_min: 16
  max_records: 2000
```

| Key | Meaning |
|---|---|
| `fidelity`, `utility`, `privacy` | lists of metric names from the closed list above (`utility` has none yet) |
| `real` | path to a real participant-level `.csv` or `.parquet`. **Absent is the normal public situation**: no real data is present |
| `holdout` | optional path to real records not used to build the synthetic data (membership inference) |
| `sensitive` | categorical fields to attack in `attribute_inference`; none by default |
| `exclude` | columns left out of every comparison (identifiers, dates) |
| `thresholds` | optional gate limits, see [Release gate and thresholds](#release-gate-and-thresholds) |
| `max_records` | sampling cap for the privacy distances (default 2,000, minimum 30) |
| `suppression_min` | disclosure threshold (default 16) |

**Without `validate.real`** only the metrics that need no real data can run: `tvd`
becomes the marginal check against the published frequencies (mean TVD over the columns
that have published counts, and the worst columns). Every other requested metric is
listed in the report and the manifest under `skipped`, with the reason. The run also
prints how many metrics were skipped.

**With `validate.real`** the toolkit runs as for `synthpediatric validate`, with the run's
cohort as the single synthetic cohort. Two requested metrics can still be skipped, each
reported with its reason: `replicate_envelope` (it needs at least 2 replicates; use the
`validate` command with several seeds) and `discriminator_auc` when scikit-learn is not
installed. Columns blanked by `no_frequency: nullify` are left out of the comparison.
`membership_inference` is skipped without `holdout`, and `attribute_inference` without
`sensitive`. A named file that does not exist is an error before anything is generated; a
real file with fewer than `suppression_min` rows is an error too.

**Metric names** are checked against the closed list before any record is generated. An
unknown name raises a config error with a hint, for example `validate.privacy[0]: unknown
metric 'identifiabilty'. Did you mean 'identifiability'? Valid metrics: ...`. Strictness
follows the config's `strict` setting: with `strict: true` (the default for YAML configs)
it is an error; with `strict: false` the name is ignored and a warning is added to the
manifest.

**Manifest.** `manifest["validation"]` holds `report` and `summary` (file names), `mode`
(`dictionary_only` or `real_reference`), `requested`, `skipped` (metric and reason) and
`headline`: `mean_tvd_published` (without real data) or `univariate_mean`,
`dependency_mean_abs_diff`, `discriminator_auc`, and the privacy numbers
`identifiability`, `nn_distance_ratio`, `attribute_inference_max_lift`, `membership_auc`
and `release_gate_identifiability` (`pass`, `fail` or `no threshold configured`) when they
ran. The real file's content is not recorded; its path is in the manifest's `config`.

The reports follow the same disclosure rule as the rest of the module: aggregates only,
`audit_report` must pass before a file is written, and no category counts appear in the
privacy section at all.

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
- `privacy`: one number per measure (plus the sampling sizes and the interpretation text),
  the `thresholds` list and the `release_gate` entry; no category counts and no record
  values. `skipped` lists every requested metric that was not computed, with the reason.

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

### Decisions for the privacy tier and the config wiring

**Distance: weighted Gower** (see [Distance](#distance)). The generator's data is
categorical-heavy with a few numeric fields, so one distance has to treat both. Gower needs
no scaling choices beyond the real range, stays in [0, 1], and reduces to Hamming for
purely categorical records. Euclidean distance on one-hot columns would make a field with
many levels dominate. Identifiability uses inverse-entropy weights because the paper does;
the other measures use equal weights, which are easier to explain.

**Identifiability follows the paper's per-real-record form** (strict inequality, ties not
counted), and the report states the independent-draw reference of about 0.5. We did not
subtract the reference or rescale the score, so the number is the one other papers report.

**Sensitive fields: a config list with no default.** `validate.sensitive` (or
`--sensitive`) names the fields. With no list, `attribute_inference` is skipped and the
report says why. A built-in default would amount to a clinical or policy judgement about
which fields are sensitive (diagnosis, vital status, race, and so on), which this tool
should not make. The release board can fix the list in the shared config.

**Attacker model for attribute inference.** A weighted k-nearest-neighbour vote (k = 5)
over the known fields, using only numpy. It is a simple attacker, so a flat lift is a lower
bound on risk, not proof of none. A stronger attacker (a trained classifier) would need
scikit-learn and is not built.

**Membership inference needs a holdout, so it gets its own key, `validate.holdout`.** If
the generator only ever saw published frequencies, there is no set of members and
non-members to separate, and a random split of the one real file would give about 0.5
whatever the synthetic data looked like, which would be a number with no meaning. The
metric therefore runs only when real records known not to have been used are supplied,
and is otherwise reported as skipped. In the tests, the "leaky" generator is a copy of the
real file and the holdout a second real sample.

**`validate.real` is a path, absent means no real data.** It names one participant-level
file (`.csv` or `.parquet`) readable from where `run` executes; relative paths resolve
against the working directory, like other paths in the config. The config states a file
and never the data, and the manifest records the path but not the file's contents or hash.
Output files are `validation_report.json` (the full report) and `validation_summary.txt`
(the printable summary), written next to `manifest.json`. The `validate` command keeps its
own names (`report_<label>.json`, `summary_<label>.txt`, `history.csv`); a `run` does not
append to a history file, because one run is not an iteration series.

**Sampling caps.** Default 2,000 records per cohort for the quadratic distance work, set by
`validate.max_records` or `--max-records` (minimum 30), seeded, both cohorts cut to the
same size (see [Sampling cap](#sampling-cap)). The discriminator keeps its own cap of
20,000 rows per class.

**Thresholds.** Named by metric and direction (`identifiability_max`, and so on), unset by
default, with the report showing `no threshold configured` when unset. A pass or fail is
printed only when the user has chosen a threshold.

**Python 3.14 and the `[validate]` extra.** The extra pins scikit-learn 1.5.2, which has
no wheel for Python 3.14, so `pip install "synthpediatric[validate]"` cannot be installed
there. Use Python 3.10 to 3.13 for the discriminator. The privacy tier uses only numpy and
pandas, so it does not need the extra; asking for `discriminator_auc` in a config there skips that one
metric with the reason and records a skip, rather than failing the run.

## Reproducibility and platforms

With the same inputs, seed and package versions, the report is the same apart from the
timestamp. Floating-point results can differ in the last digits between macOS and Linux,
so the tests check ranges (for example AUC between 0.4 and 0.6 for two seeds of the same
generator, AUC above 0.6 after a shuffled column), never exact values.
