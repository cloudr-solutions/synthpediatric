# Cookbook: writing a synthpediatric config

Short recipes you can copy, run and edit. Every recipe is a file in `examples/cookbook/`,
runs offline against `examples/nccr_ctc_dictionary.json`, and is run by
`tests/test_cookbook.py`, so what you read here still works. The full reference is
[config-and-rules.md](config-and-rules.md).

Setup, once: `pip install -e ".[yaml]"`. Run every command from the repository root. Each
run writes `cohort.csv`, `manifest.json`, `coverage.csv`, `conformance.csv`, `fidelity.csv`
and `dictionary.json` to `outputs.dir` (here `out/cookbook/<letter>`; `--out-dir` overrides it).

The numbers quoted under each recipe are what these exact files produced (seed 1).

Labels in this dictionary: `age_group` has 5-year bands (`00-04` ... `35-39`), `iccc_category`
has `I Leukemias` ... `XII Other` plus `Not classified`, `sex` is `Male`/`Female`,
`vital_status` is `Alive`/`Dead`. List a variable's labels with
`synthpediatric profile examples/nccr_ctc_dictionary.json` or open the JSON. Use the labels
exactly as written. With the remote NCCR metadata the same variables are `icccMajor` and
`ageRecode19Groups` (labels such as `00 years`, `01-04 years`), so check the names there.

## Which profile do I need?

`profile` is the "how many rules" dial. A rule runs when the profile includes it and your
config has a section for it. A section for a rule outside the profile is kept but not applied.

| Profile | Rules on | Inputs it uses | You get | Pick it when |
|---|---|---|---|---|
| `marginals_only` | marginals, overrides, cohort | metadata or dictionary; optional `targets.marginals`, `targets.overrides`, `cohort` | independent columns, each matching its distribution | you only have 1-way frequencies, or want the lowest-risk, fastest output |
| `standard` | + joints, constraints | + one cross-tab CSV (`targets.joints`), a rules file or inline `constraints` | related columns (the cross-tab) and no impossible combinations | you have a published cross-tab or clinical rules |
| `full` | + oversample, survival | + `oversample`, `targets.survival` | rare-cancer boost and `months` / `event` columns | you want a rare-cancer cohort or follow-up time |

No `profile` means `full`. Which rules actually ran is in the run output and in `manifest.json`
under `rules` (`applied`, `skipped` or `disabled`, with a reason).

---

## a. Keep a published age distribution

Use it when you have a published distribution (for example 36% / 17% / ...) and the cohort
must reproduce it.

```yaml
name: Cookbook a - published age distribution
metadata: examples/nccr_ctc_dictionary.json
n: 5000
seed: 1
profile: marginals_only
targets:
  marginals:
    age_group:
      "00-04": 0.36
      "05-09": 0.17
      "10-14": 0.15
      "15-19": 0.32
outputs: {dir: out/cookbook/a}
```

```bash
synthpediatric run examples/cookbook/a_age_distribution.yaml
```

Look for: the sampled shares in `cohort.csv`. We got 00-04 0.3708, 05-09 0.1716, 10-14 0.1482,
15-19 0.3094, close to the targets (sampling noise at n=5000).

How it behaves, checked by running it:

- Give proportions or counts. Values are normalized to sum to 1, so `36, 17, 15, 32` is the
  same as `0.36, 0.17, 0.15, 0.32`.
- The listed table replaces the variable's whole distribution. Categories you leave out are
  never generated. Here `20-24` to `35-39` do not appear at all (the cohort has 4 age groups).
  To keep a category, list it.
- `fidelity.csv` compares the cohort with the dictionary after your targets are applied, so
  `age_group` scores 0.0124 (TV distance) against the new table, not against the original data.
- Labels and variable names are checked against the dictionary before anything is generated:
  `"05-9"` instead of `"05-09"` stops the run with a suggestion. See "Mistakes the checks
  catch" below.

## b. Restrict to a sub-population

Use it to generate only the cases that match a cohort definition.

```yaml
name: Cookbook b - leukemias and lymphomas, diagnosed under 15
metadata: examples/nccr_ctc_dictionary.json
n: 3000
seed: 1
profile: marginals_only
cohort:
  name: Leukemia or lymphoma, under 15
  filters:
    - {variable: iccc_category, op: equals, values: ["I Leukemias", "II Lymphomas"]}
    - {variable: age_group, op: max, threshold: 14}
outputs: {dir: out/cookbook/b}
```

```bash
synthpediatric run examples/cookbook/b_cohort_filter.yaml
```

Look for: only the allowed categories in `cohort.csv`. We got 1,674 lymphomas and 1,326
leukemias, and age groups 00-04 (1,233), 05-09 (867) and 10-14 (900). `min` / `max` read the
first number in the label, so `15-19` counts as 15 and is dropped by `max: 14`.

## c. Oversample a rare cancer

Use it to get enough rare cases to analyse. It needs `profile: full`.

```yaml
name: Cookbook c - oversample retinoblastoma and hepatic tumors
metadata: examples/nccr_ctc_dictionary.json
n: 5000
seed: 1
profile: full
oversample:
  variable: iccc_category
  values: ["V Retinoblastoma", "VII Hepatic"]
  factor: 10
outputs: {dir: out/cookbook/c}
```

```bash
synthpediatric run examples/cookbook/c_oversample_rare.yaml
```

Look for: `oversampling` in `manifest.json`. It has `factors_applied` (10.0 for each category),
`unmatched_values` (empty when every label matched) and `proportions_before` / `proportions_after`.
We got retinoblastoma 0.0027 -> 0.0249 and hepatic 0.0065 -> 0.0600 in the weights, and 0.026
and 0.061 in the 5,000 records. The effective boost is a little under 10x because the other
categories shrink to keep the total at 1. A label that matches no category is an error
(`oversample.values: unknown category ...`), so `unmatched_values` is empty in a normal run. With
`strict: false` it is a warning again and is listed in `unmatched_values`.

## d. Survival times by group

Use it to add follow-up time and an event flag whose curves follow published survival by group.
It needs `profile: full`.

```yaml
name: Cookbook d - survival by ICCC category
metadata: examples/nccr_ctc_dictionary.json
n: 20000
seed: 1
profile: full
targets:
  survival:
    group_col: iccc_category
    horizon_months: 120
    specs:
      "V Retinoblastoma": {s5: 0.97}
      "I Leukemias": {median_months: 150}
      "VII Hepatic": {points: {12: 0.90, 60: 0.70, 120: 0.60}}
outputs: {dir: out/cookbook/d}
```

```bash
synthpediatric run examples/cookbook/d_survival_by_group.yaml
```

Look for: two new columns, `months` and `event` (1 = event seen, 0 = censored), in `cohort.csv`.
A spec is `s5` (5-year survival), `median_months`, or `points` (survival at given months);
a bare number means 5-year survival. Records are censored at `horizon_months` or earlier by
random dropout, so the share of events is lower than 1 minus survival. We got:

| Group | Records | Share with event |
|---|---|---|
| V Retinoblastoma (s5 0.97) | 49 | 0.020 |
| I Leukemias (median 150 months) | 1,554 | 0.233 |
| VII Hepatic (points) | 137 | 0.255 |
| III CNS (not listed) | 2,218 | 0.207 |

Groups you do not list get the spec under the key `__default__`. Without that key they get
the built-in 5-year survival of 0.80. Adding `__default__: 0.80` to this recipe leaves the
output unchanged. Changing it to `__default__: 0.20` moved the unlisted III CNS group
(2,218 records) from an event share of 0.207 to 0.768. A group name in `specs` that is not a
category of `group_col` is an error, so a typo cannot silently fall back to the default.

## e. A joint cross-tab with IPF calibration

Use it when you have a published cross-tab (for example sex by age) and want the relationship
kept, while still matching your marginals.

```yaml
name: Cookbook e - sex x age cross-tab with IPF
metadata: examples/nccr_ctc_dictionary.json
n: 5000
seed: 1
profile: standard
targets:
  marginals:
    sex: {Male: 0.52, Female: 0.48}
    age_group: {"00-04": 0.30, "05-09": 0.15, "10-14": 0.15, "15-19": 0.40}
  joints:
    cliques:
      - [sex, age_group]
    crosstabs: examples/profiles/crosstab_sex_age.csv
outputs: {dir: out/cookbook/e}
```

```bash
synthpediatric run examples/cookbook/e_joint_crosstab.yaml
```

The CSV has the clique columns plus `count`:

```text
sex,age_group,count
Male,00-04,320
Male,05-09,180
...
```

Look for: the `joints` entry under `rules` in `manifest.json`: `converged: true`,
`iterations: 5`, `max_deviation` about 7e-11. The cross-tab's own margins are different
from your targets; IPF reshapes it until both match. We got sex Male 0.5146 / Female 0.4854
and age 0.3032 / 0.1452 / 0.1478 / 0.4038. Only one clique per config is supported. The
variables in the clique must be in the dictionary, and the cross-tab labels must match its labels.

## f. Variables with no published frequency

Use it when the metadata lists a variable's permissible values but has no counts for them.
Choose how to treat it with `no_frequency`. This needs metadata that can mark a variable as
unpublished, so these three files read a small NCCR-style Turtle file,
`examples/cookbook/mini_nccr.ttl` (`sex` has counts, `race` has none; the race labels are
illustrative). A JSON dictionary cannot carry that flag, so `no_frequency` has no effect
with one.

The three files are identical except for `no_frequency` and `outputs.dir`:

```yaml
name: Cookbook f - no_frequency uniform      # nullify / suppress in the other two files
metadata: examples/cookbook/mini_nccr.ttl
source: CTC
n: 1000
seed: 1
profile: marginals_only
no_frequency: uniform                        # uniform | nullify | suppress
outputs: {dir: out/cookbook/f_uniform}
```

```bash
synthpediatric run examples/cookbook/f_no_frequency_uniform.yaml
synthpediatric run examples/cookbook/f_no_frequency_nullify.yaml
synthpediatric run examples/cookbook/f_no_frequency_suppress.yaml
```

Look for: the columns of `cohort.csv` and `coverage.csv`.

| `no_frequency` | Columns | `race` in `coverage.csv` | `manifest.json` coverage |
|---|---|---|---|
| `uniform` | sex, race (random values) | `uniform` | `{'published': 1, 'uniform': 1}` |
| `nullify` | sex, race (all blank) | `nullified` | `{'published': 1, 'nullified': 1}` |
| `suppress` | sex only | not listed | `{'published': 1}` |

In all three, `manifest.json` lists `race` under `no_frequency.variables`. Overall TV distance
was 0.0154 for `uniform` (race is scored against a uniform guess) and 0.0051 for the other two
(race is not scored). Pick `uniform` to keep the column usable, `nullify` to keep the schema
without inventing values, `suppress` to drop the column.

## g. Consistency rules (constraints)

Use it to stop impossible records, such as prostate markers on female patients. Needs
`profile: standard` or `full`.

```yaml
name: Cookbook g - consistency rules
metadata: examples/cookbook/ctc_mini_dictionary.json
n: 3000
seed: 1
profile: standard
constraints:
  file: examples/ctc_consistency_rules.json
outputs: {dir: out/cookbook/g}
```

```bash
synthpediatric run examples/cookbook/g_consistency_rules.yaml
```

`examples/ctc_consistency_rules.json` names CTC columns (`icccMajor`, `gleason...`, `psa...`).
`examples/nccr_ctc_dictionary.json` has none of them, so this recipe uses
`examples/cookbook/ctc_mini_dictionary.json`, a small dictionary with those columns. Its
ICCC counts are the real ones; the other frequencies are placeholders. With the offline
dictionary, use `examples/nccr_ctc_rules.json`, which matches its columns.

Look for: `Consistency repairs: 4,038` in the output and the per-rule counts in `repairs` in
`manifest.json` (for example `psa_is_male_only: 673`, `retinoblastoma_is_early_childhood: 16`).
In the cohort, all 1,354 female records have `Not applicable` for the Gleason score, and
retinoblastoma is only in `00 years`, `01-04 years` or `05-09 years`. Repairs cost fidelity:
overall TV distance was 0.155 here, which is the price of forcing those values.

You can also write rules inline: `constraints: {rules: [...], max_iterations: 10}` with the same
rule fields as the JSON file.

---

## Common errors

Config mistakes stop the run before anything is written, with `config error:` and the key
name. These are the real messages, from the commands above with one thing changed. Mistakes
in names and labels (a variable, category, group or column that the dictionary does not have)
are in the next section.

Unknown profile (`profile: ultra`):

```text
config error: profile: unknown value 'ultra'. Valid choices: marginals_only, standard, full
```

Unknown rule in `rules:` (a typo, `survivial: true`):

```text
config error: rules: unknown rule 'survivial'. Valid rules: marginals, overrides, cohort, oversample, joints, constraints, survival
```

Unknown top-level key (`target:` instead of `targets:`):

```text
config error: config: unknown key 'target'. Valid keys: name, metadata, source, n, seed, profile, value_mode, no_frequency, missingness, strict, rules, cohort, targets, oversample, constraints, validate, outputs, override_marginals, survival
```

Unquoted `Yes` / `No` (YAML turns them into true / false). In a cohort filter
(`values: [Yes, No]`):

```text
config error: cohort.filters[0].values: True was parsed as a YAML boolean; quote the value (e.g. "Yes" / "No") so it stays a text label
```

and as a marginal key (`{Yes: 0.5, No: 0.5}`):

```text
config error: targets.marginals.vital_status key: True was parsed as a YAML boolean; quote the value (e.g. "Yes" / "No") so it stays a text label
```

Fix: write `"Yes"` and `"No"` in quotes.

Switching a rule on without a section (`profile: marginals_only` with `rules: {survival: true}`):

```text
config error: rules.survival: switched on but no parameters given; add a 'targets.survival' section
```

Fix: add the section (`targets.survival`), or remove the toggle.

`missingness: realistic`:

```text
config error: missingness: 'realistic' is reserved but not implemented yet; use 'none' (records are generated without missing values)
```

Fix: use `none` or leave the key out.

## Mistakes the checks catch

Every name and label in a config is checked against the dictionary before any record is
generated or file written. A mistake stops the run with `config error:`, the dotted key, the
offending value, the closest valid name when there is one, and the valid names (the first 15
and the total when the list is long). These are the real messages, each from a recipe above
with one thing changed, using `examples/nccr_ctc_dictionary.json`.

Misspelled label in `targets.marginals` (`"05-9"` for `"05-09"`):

```text
config error: targets.marginals.age_group: unknown category '05-9'. Did you mean '05-09'? Valid categories: 00-04, 05-09, 10-14, 15-19, 20-24, 25-29, 30-34, 35-39
```

Misspelled variable in `targets.marginals` (`agegroup`):

```text
config error: targets.marginals: unknown variable 'agegroup'. Did you mean 'age_group'? Valid variables: iccc_category, sex, age_group, diagnosis_year_group, vital_status
```

Misspelled variable or label in `cohort.filters`:

```text
config error: cohort.filters[0].variable: unknown variable 'agegroup'. Did you mean 'age_group'? Valid variables: iccc_category, sex, age_group, diagnosis_year_group, vital_status
config error: cohort.filters[0].values: unknown category '05-9'. Did you mean '05-09'? Valid categories: 00-04, 05-09, 10-14, 15-19, 20-24, 25-29, 30-34, 35-39
```

Misspelled label in `oversample` (`"V Retinoblastom"`):

```text
config error: oversample.values: unknown category 'V Retinoblastom'. Did you mean 'V Retinoblastoma'? Valid categories: I Leukemias, II Lymphomas, III CNS, IV Neuroblastoma, V Retinoblastoma, VI Renal, VII Hepatic, VIII Bone, IX Soft tissue, X Germ cell, XI Epithelial/melanoma, XII Other, Not classified
```

Misspelled group in `targets.survival.specs`, and a misspelled `group_col`:

```text
config error: targets.survival.specs: unknown group 'V Retinoblastom'. Did you mean 'V Retinoblastoma'? Valid groups: I Leukemias, II Lymphomas, III CNS, IV Neuroblastoma, V Retinoblastoma, VI Renal, VII Hepatic, VIII Bone, IX Soft tissue, X Germ cell, XI Epithelial/melanoma, XII Other, Not classified
config error: targets.survival.group_col: unknown column 'icccategory'. Did you mean 'iccc_category'? Valid columns: iccc_category, sex, age_group, diagnosis_year_group, vital_status
```

A spec that is not one of the forms in recipe d (`{s6: 0.9}`):

```text
config error: targets.survival.specs.V Retinoblastoma: invalid survival spec {'s6': 0.9} (unrecognized survival spec keys: ['s6']). Use a number (5-year survival), {s5: ...}, {median_months: ...} or {points: ...}
```

A rules file that names a column the data does not have. Here recipe g's rules file
(`examples/ctc_consistency_rules.json`, CTC column names) is run against the offline
dictionary instead of `ctc_mini_dictionary.json`:

```text
config error: constraints.file[0].target_col: unknown column 'gleasonScoreClinicalRecode' in constraint 'gleason_clinical_score_is_male_only' of examples/ctc_consistency_rules.json. Valid columns: iccc_category, sex, age_group, diagnosis_year_group, vital_status
```

The same checks cover a table in a `targets.overrides` file, the variables of a `joints`
clique, and the labels in the cross-tab CSV:

```text
config error: targets.overrides.age_group: unknown category '05-9' (in ages.json). Did you mean '05-09'? Valid categories: 00-04, 05-09, 10-14, 15-19, 20-24, 25-29, 30-34, 35-39
config error: targets.joints.cliques[0]: unknown variable 'agegroup'. Did you mean 'age_group'? Valid variables: iccc_category, sex, age_group, diagnosis_year_group, vital_status
config error: targets.joints.crosstabs.age_group: unknown category '05-9' (in .scratch/x.csv). Did you mean '05-09'? Valid categories: 00-04, 05-09, 10-14, 15-19, 20-24, 25-29, 30-34, 35-39
```

A label that is in the dictionary but that an earlier rule removed (here a cohort that kept
only two ICCC categories, then an oversample of a third):

```text
config error: oversample.values: category 'V Retinoblastoma' exists in the dictionary but an earlier rule (marginals, overrides or cohort) removed it. Valid categories at this point: I Leukemias, II Lymphomas
```

Rules are checked in execution order, each against the categories left by the rules before it.
The exceptions are `targets.marginals`, `targets.overrides` and the `joints` cross-tab, which
are checked against the dictionary as loaded: a table replaces a variable's whole
distribution, and a cross-tab may keep rows for a category the cohort dropped.

### Working with partial specs: `strict: false`

By default (`strict: true`) these are errors. If you knowingly use a spec that names more than
the data has (for example one rules file shared by several datasets), add `strict: false`.
Each such reference then becomes a line in `warnings` (printed as `warning: ...`, saved in
`manifest.json`) and the run goes on as it did before the checks existed:

- a marginals or overrides variable or label is used as written (a new column or category appears);
- a cohort filter on an unknown variable is skipped, and unknown values in `equals` are ignored;
- an oversample value that matches nothing gets no factor, and is listed in `unmatched_values`;
- a survival group that matches nothing is ignored (those records use `__default__` or 0.80);
- a constraint that names an absent column is skipped;
- cross-tab rows with an unknown label get no mass.

Example (`strict: false`, `"V Retinoblastom"` in `oversample`):

```text
warning: oversample: values not found in 'iccc_category' (no factor applied): ['V Retinoblastom']
```

Some mistakes stay errors under `strict: false`, because there is nothing sensible to run: a
cohort filter that would leave no records, an unknown `oversample` variable, an unknown
`survival.group_col` or `joints` clique variable, and an invalid survival spec.

Old JSON recipes (those using `override_marginals`, a top-level `survival`, or `rules:
file.json`) are treated as `strict: false` unless they say otherwise, so they behave exactly as
before. Put `strict: true` in one to turn the checks on.

### Still not checked

- `allowed_values` and `trigger_values` labels inside a constraints file (a repair target such
  as `Not applicable` is legitimately not in the dictionary).
- A `time_col` / `event_col` that has the same name as an existing column overwrites it.
- Only the first mistake is reported per run; fix it and run again to see the next.
- Data values: a dictionary that is itself wrong (for example the wrong metadata `source`) is
  not detected.
