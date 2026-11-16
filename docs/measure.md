# Measure: export disclosure-controlled aggregates from CGC

`synthpediatric measure` is for the Input team. You run it inside the CGC workspace on the
real participant-level NCCR data. It writes only aggregates, in the file formats the
generator already reads, so the output goes into a generator config unchanged. Only cells
with a count of 16 or more leave CGC.

```text
real extract (CGC) --measure--> freqs/ crosstabs/ survival/ + manifest --run--> synthetic cohort
```

It does one source table at a time and links nothing across sources. Validation measures
(TVD, discriminator and so on) live in [validation.md](validation.md), not here.

## Quick start

```bash
synthpediatric run examples/measure/standin_generate.yaml      # a stand-in "real" cohort
synthpediatric measure examples/measure/measure_config.yaml    # writes out/measure/aggregates/
synthpediatric run examples/measure/generate_from_measured.yaml
```

`measure` options: `--out-dir DIR` (beats `outputs.dir`) and `--overwrite` (replace the
results of an earlier measure run; a directory without `measure_manifest.json` is never
replaced). From Python: `synthpediatric.measure.run_measure(config, out_dir=None)` returns
the manifest, and `audit_outputs(dir, threshold)` audits any directory in the layout below.

## 1. Produce the extract in CGC

The tool reads a flat table with one row per participant, as `.csv` or `.parquet`. Give
one file or a list (the files must have the same columns; they are stacked).

How to make it in CGC (a notebook or a script in the workspace):

1. Export or query the approved NCCR table for one source (for example the Consolidated
   Tumor Case table) into a data frame.
2. Keep only the columns you will measure: the variables for frequency tables and
   cross-tabs, and for survival the group, the follow-up time in months and the event.
3. Save it inside the workspace, for example `extract_ctc.parquet`. The extract stays in
   CGC. Only the `measure` output folder is exported.

Run `synthpediatric measure` in the same workspace. Nothing else needs a network.

## 2. The measure config (YAML or JSON)

```yaml
name: CTC measures, Jamboree day 1
data: extract_ctc.parquet          # file, or list of files
rename:                            # extract column -> NCCR variable name (optional)
  SEX_CODE: sex
labels:                            # extract value -> NCCR label, per variable (optional)
  sex: {"1": Male, "2": Female}
bins:                              # continuous variable -> categories (optional)
  age_years: {edges: [0, 5, 10, 15, 20, 40], labels: ["00-04", "05-09", "10-14", "15-19", "20-39"]}
dictionary: examples/nccr_ctc_dictionary.json   # optional: check names and labels
strict: true                       # true (default): a label not in the dictionary is an error
cohort:                            # optional filter, same shape as the generator's
  name: Leukemias
  filters:
    - {variable: iccc_category, op: equals, values: ["I Leukemias"]}
threshold: 16                      # default 16
max_levels: 200                    # default 200: more distinct values than this is an error
frequencies: [iccc_category, sex, age_years]
crosstabs:
  - {name: sex_age, variables: [sex, age_years]}     # or just a list: [sex, age_years]
survival:
  - name: survival_by_iccc
    group: iccc_category
    time: months                   # follow-up in months
    event: event                   # 0/1 or true/false
    # event_values: [Dead]         # when the column is text: which values count as the event
    horizon_months: 120            # default 120, like the generator
    time_points: [12, 36, 60]      # survival at these months
    s5: true                       # 5-year (60-month) survival, default true
    median: false                  # median survival where defined
    form: points                   # what survival/<name>.json holds: points | s5 | median_months
    time_resolution_months: 1      # times are rounded down to this step before the KM fit
outputs: {dir: out/measure}
```

Required: `data` and at least one of `frequencies`, `crosstabs`, `survival`. Unknown keys are
errors with the list of valid keys.

### Choices made (open points)

| Point | Choice | Why |
|---|---|---|
| Input shapes | One flat CSV or parquet table, or several with the same columns | What CGC exports easily. No joins. |
| Name mapping | Use `rename` (extract column to NCCR name) and `labels` (extract value to NCCR label). Everything else in the config uses the NCCR names. | The generator matches variables and categories by exact name and label. |
| Name and label checks | With `dictionary:` set, an unknown variable or label is an error with a "Did you mean" hint. Without it, nothing is checked against NCCR (a typo in a column name is still caught). `strict: false` turns label errors into counted warnings. | Same style as the generator's config validation. Without metadata inside CGC there is nothing to check against. |
| Missing requested variable | Error: `frequencies: unknown variable 'sexx'. Did you mean 'sex'? Valid variables: ...` | |
| Missing values | Participants with a missing value are left out of that table (and of that cross-tab). Nothing about them is exported. | The generator has no count-less category. |
| Continuous variables | Categorical only for now. A column with non-integer numbers must be listed under `bins` (edges, one label per interval, left-closed). Integer columns are treated as categories. A column with more than `max_levels` values is refused (it is probably an ID). | Binning with labels that match NCCR's bands keeps the output in the generator's label space. |
| Filter | Applied to the raw extract values, after `rename`, before `labels` and `bins`. `min` and `max` are numeric. | |

## 3. Output files and how to plug them in

Everything goes under the output directory:

```text
freqs/<variable>.json
crosstabs/<name>.csv
survival/<name>.json
survival/<name>_summary.csv
measure_manifest.json
```

### freqs/<variable>.json: one-way frequency table

Plug in: `targets.overrides.tables: out/measure/freqs/` (the directory is merged in name
order; or point at one file).

```json
{"sex": {"Female": 1520, "Male": 1480}}
```

A mapping `variable -> {label: count}`. Counts are whole numbers of at least 16. A
suppressed category has no count, so it is not listed. Note that an override replaces the
variable's whole distribution, so a suppressed category gets no records in the generated
cohort.

### crosstabs/<name>.csv: cross-tab

Plug in: `targets.joints: {cliques: [[sex, age_group]], crosstabs: out/measure/crosstabs/sex_age.csv}`.
The clique must list the same variables as the CSV columns. The generator supports one
clique per config.

```text
sex,age_group,count
Male,00-04,320
Male,05-09,180
```

Header: the variables, then `count`. One row per observed cell with a count of at least 16.
A suppressed cell has no row (the generator reads a missing cell as 0 mass, as for any
cell absent from the table).

### survival/<name>.json: survival specs by group

Plug in: `targets.survival: {group_col: iccc_category, horizon_months: 120, specs: out/measure/survival/survival_by_iccc.json}`.
Use the same `horizon_months` as in the measure config.

```json
{
  "I Leukemias": {"points": [[12, 0.9709], [36, 0.925], [60, 0.8791]]},
  "V Retinoblastoma": {"s5": 0.97}
}
```

One spec per group, in the form chosen by `form`:

* `points`: `[[month, survival], ...]`, Kaplan-Meier survival at the `time_points`.
* `s5`: 5-year survival, `{"s5": 0.88}`.
* `median_months`: `{"median_months": 150}`, only for groups where the median is defined.

Points are written as pairs, not as `{"12": 0.97}`. JSON keys are text, and the generator
sorts a `points` mapping by key, so `"120"` would sort before `"60"`. A list of pairs
avoids that. (YAML mappings with integer keys are fine.)

The estimator is `synthpediatric.analyze.kaplan_meier`. Follow-up beyond `horizon_months`
is censored at the horizon. Times are rounded down to `time_resolution_months` (default 1,
the usual NCCR unit) before fitting, which makes a large cohort fast.

### survival/<name>_summary.csv

For people: `group,n,s5,s12,s36,s60,median_months`. The same suppression rules as the spec
file; a blank means the value was withheld or is undefined. The generator does not read it.

### measure_manifest.json

Tool version, UTC time, the SHA-256 of the measure config and of each input file, the
threshold, the cohort filter, per output: kind, variables, file, SHA-256, cells written,
number of primary and complementary suppressed cells (counts, never the values) and for
survival the groups exported, dropped and the values withheld. It has no participant-level
data, no suppressed category names, and no table totals or participant count (a total would
let a reader recover a suppressed cell).

## 4. Disclosure control

The threshold defaults to 16. Lowering it is allowed and recorded in the manifest; do not do
that without approval.

1. **Primary suppression.** A table cell with a count below the threshold is not written.
   This is how the published NCCR metadata shows a suppressed value: a value that has no
   count.
2. **Complementary suppression.** Whenever a line of a table has exactly one suppressed cell,
   the smallest other cell in that line is suppressed too, using the same helper as the
   validation report (`validate._suppress`). A line is a whole 1-way table, or for a
   cross-tab every row and column (for every axis and every setting of the other axes). The
   check repeats until every line has no single hidden cell. This also protects a cell from
   being derived from the 1-way tables of the same variables.
3. **Small survival groups.** A group with fewer than `threshold` participants is not
   exported. A survival value (a point, 5-year survival or the median) is exported only if
   at least `threshold` participants are still at risk at that time, and the number of events
   up to that time is 0 or at least `threshold`. Groups left with no exportable value are not
   exported. The manifest counts the groups dropped and the values withheld. For rare groups
   with very high survival, this rule withholds values (for example 3 deaths among 96
   participants).
4. **Audit before anything is kept.** Results are built in a staging directory next to the
   output directory. `audit_outputs` then checks every file: allowed locations only, counts
   are whole numbers of at least the threshold, crosstab rows and survival summary `n` are at
   least the threshold, every survival group has a summary row, the manifest holds no
   participant fields, and no list is long enough to be a record dump
   (`validate.audit_report`). On any failure the staging directory is deleted, the command
   exits with `audit failed, no output was kept` and the output directory is never created.
   Only audited results are moved into place.

What is not covered: an analyst's judgement. Aggregates over the suppression floor can
still be sensitive in small populations; follow the data use agreement.

## 5. SEER*Stat, R or any other tool: make the files by hand

The generator only needs the file formats above. You can produce them in SEER*Stat, R, SAS
or a spreadsheet. If you do, apply the same rules yourself: no cell below 16, complementary
suppression, no small survival groups. You can check your folder with
`synthpediatric.measure.audit_outputs("my_folder", 16)`, which accepts the layout above
without a manifest.

Frequency table (`freqs/sex.json`; a mapping, labels exactly as in the NCCR metadata):

```json
{"sex": {"Male": 1480, "Female": 1520}}
```

Cross-tab (`crosstabs/sex_age.csv`; any file name, `count` last):

```text
sex,age_group,count
Male,00-04,320
Female,00-04,290
```

Survival specs (`survival/by_iccc.json`; group names exactly as in the group column):

```json
{
  "I Leukemias": {"s5": 0.88},
  "III CNS": {"median_months": 150},
  "VII Hepatic": {"points": [[12, 0.90], [60, 0.70], [120, 0.60]]},
  "__default__": {"s5": 0.85}
}
```

`__default__` is the spec for groups not listed. Points must not increase over time.

In R, for example:

```r
tab <- as.data.frame(table(sex = df$sex))
jsonlite::write_json(list(sex = setNames(as.list(tab$Freq), tab$sex)), "freqs/sex.json",
                     auto_unbox = TRUE)
```

## 6. Limits of this first version

* One clique per cross-tab file and one clique per generator config.
* Survival is observed (Kaplan-Meier) survival from time and event columns. Relative, net
  and cause-specific survival need SEER*Stat; write their values into the spec files by
  hand.
* The generator draws independent random censoring (uniform from 12 months to the horizon),
  so the measured censoring distribution is not reproduced, only the survival curve.
* A dictionary check needs a JSON dictionary or a generation config (anything
  `validate --dictionary` accepts that does not need `--source`).
* The validation measures of the plan (Tiers 7 to 9) belong to `synthpediatric validate`.
