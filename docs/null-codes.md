# Null codes and the not-applicable fraction

Two parts. The null-code map says which permissible values of each NCCR variable mean "not
applicable", "unknown", "no data" or "not performed". The not-applicable fraction uses the map
to stop giving every synthetic row a value for variables that only exist for part of the
records (Gleason score and PSA exist for prostate cancers, not for every tumor).

## Why

The generator normalizes each variable's published counts to 1, so every row gets a value.
For a sub-population variable that is wrong: the CTC Gleason and PSA variables have published
counts totalling about 1,859 of 1,614,685 records (0.1%), and the old generator gave a
Gleason score to every female and every non-prostate cancer. 16 CTC variables have counts
that cover less than half of the records (17 in the metadata; `scope9802Public` is dropped
because its labels collide, see [sources.md](sources.md)).

## The null-code map

### What the metadata gives

Each permissible value is a code and a description. The raw export has `{Value, Description}`
and nothing else; `nccr_instances.ttl` has `skos:notation`, `skos:prefLabel`,
`nccr:codeDescription` and, when published, `nccr:recordCount`. There is no null flag. The
meaning is in the description ("Not applicable: Information not collected for this case"),
so the classifier reads the description. The code is used only for per-code overrides.

### Kinds

| Kind | Meaning | Typical codes |
|---|---|---|
| `not_applicable` | the question does not apply to this record | X8, 8, 88, `Blank`, 8888888 |
| `unknown` | an answer exists but is not known or not documented | X9, 9, 99 |
| `no_data` | the source has no data for the record | Missing, Not available, Not coded, 7777, 9999 |
| `not_performed` | a procedure or test was not done | X7, "No prostatectomy done" |
| `real` | an actual answer; everything no rule recognizes | |

`unknown` is a real answer for a record that was tested but not documented, so it is never
used to fill the not-applicable share.

### How it is built

`nullcodes.RULES` is an ordered list of rules (id, kind, regular expression, borderline flag,
note); the first rule whose pattern matches the description wins. The first rules keep
false positives real, then mixed descriptions, then not applicable, no data, unknown and not
performed. Rules matching a description that is not a clear case carry `borderline: true`.
Run `python -c "from synthpediatric.nullcodes import RULES; [print(r.id, r.kind, r.pattern) for r in RULES]"`
or read the `rules` list in the map file.

Per-code **overrides** beat the rules. The shipped file is
`src/synthpediatric/data/null_code_overrides.json` (empty today: the rules cover every
published code). Format:

```json
{"overrides": {
  "CTC.psaLabValueRecode.9": {"kind": "unknown", "reason": "tested, not documented"},
  "*.*.77": {"kind": "real", "reason": "the code 77 is an age"}
}}
```

A key is `SOURCE.variable.code`; `*` can stand for the source or the variable; the most
specific key wins. Add a file of your own with `na_fraction.overrides: path` in a config or
`--overrides path` on the command.

### The command and the shipped map

```
synthpediatric nullcodes <metadata.ttl|remote> [--source S] [--overrides file] -o map.json [--summary summary.md]
```

The shipped map is `src/synthpediatric/data/null_code_map.json`, built from the published
snapshot; its readable summary (counts per source and kind, the borderline classifications
for review, the false positives) is [null-code-map-summary.md](null-code-map-summary.md).
Regenerate after the metadata changes. The map file holds only the null-type codes of each
variable; a variable's `n_real` says how many values were left real.

Counts on the snapshot (3,978 permissible values, one per source/variable/code):

| source | values | not_applicable | unknown | no_data | not_performed | real |
|---|---:|---:|---:|---:|---:|---:|
| ABM | 22 | 0 | 0 | 9 | 0 | 13 |
| CCDI | 74 | 0 | 0 | 0 | 0 | 74 |
| COG | 33 | 0 | 0 | 7 | 0 | 26 |
| CTC | 2,169 | 25 | 64 | 40 | 23 | 2,017 |
| MCD | 65 | 0 | 0 | 1 | 0 | 64 |
| MCE | 1,093 | 347 | 0 | 385 | 0 | 361 |
| MCP | 65 | 0 | 0 | 1 | 0 | 64 |
| PHARM | 133 | 0 | 0 | 2 | 0 | 131 |
| RO | 324 | 0 | 3 | 12 | 0 | 309 |
| all | 3,978 | 372 | 67 | 457 | 23 | 3,059 |

919 values are null-type. On the raw export (`RAW-JSON`, 2,376 values) the same rules give 904
(MCE 732, CTC 139, RO 13, ABM 9, COG 7, PHARM 2, MCD 1, MCP 1) in 100 distinct descriptions. The figure
of 777 mentioned for this work is not reproduced by either basis; no count here is forced to
it. The count depends on what is a value (the TTL lists every code of every variable) and on
how borderline cases are decided (37 distinct descriptions are flagged for review).

False positives kept real (51 values): ICCC group names with "unspecified" in them (`Ie
Unspecified and other specified leukemias`, `XII OTHER AND UNSPECIFIED MALIGNANT NEOPLASMS`),
`Not classified by SEER or in situ`, partial Gleason answers (`Primary pattern 3, secondary
pattern unknown`), `Non-Hispanic American Indian/Alaska Native`, `Refused (1988+)`, and
clinical sentences that contain "unknown" only in a clause.

## The not-applicable fraction

### The rule

For each variable with published counts in an NCCR source:

- covered share = sum of its published counts / the source's `totalRecordCount`;
- gap = records minus summed counts;
- **suppression ceiling** = 15 x the number of the variable's values with no count. Counts
  below 16 are omitted, so suppressed cells can hide at most that many records;
- the gap is **material** when it is larger than the suppression ceiling and its share of
  the records is at least `min_share` (default 0.005). A smaller gap is suppression, not a
  sub-population, and is left alone (`suppression_only`, `below_min_share`).

For a material gap the uncovered share of rows is set to the variable's not-applicable code
or blank. The counted values are still sampled from the normalized counts, among the rows
that keep a value. Choice of the fill:

1. a `not_applicable` value with no published count (best match: "Not applicable ...");
2. else the `not_applicable` value with the largest count (its share is part of the covered
   share, so the uncovered share is added to the same code once, not twice);
3. else blank. `unknown`, `no_data` and `not_performed` values are never used.

Rows are chosen at random with an exact count (`round(share x n)`), from a random stream of
its own: the sampled counted values and the stream the consistency rules use do not change.
The default is on for every NCCR metadata source. A JSON dictionary has no source policy, no
record total and no fraction, so the legacy golden output and legacy-key recipes are
unchanged. The `generate` command does not apply it; `run` does.

### Settings

```yaml
na_fraction: false            # whole setting off (YAML: use true/false; 'off' parses as false)
na_fraction:
  mode: on                    # on | off; default on (supplied_by: default)
  min_share: 0.005
  variables:                  # per variable: on | off | auto (default auto)
    psaLabValueRecode: off
    regionalNodesPositive: on     # on skips the materiality tests
  overrides: my_overrides.json
```

A per-variable `on` or `off` beats the global mode. Variable names are checked with a
did-you-mean message. `na_fraction` is not part of a rule profile.

### Order against the rules

1. `marginals`, `overrides`, `cohort`, `oversample` change the dictionary. A variable whose
   distribution one of them changed is skipped (`set_by_rule`): the published counts no
   longer describe it.
2. `joints` and `conditional` run as before. Their variables are skipped (`rule_target`):
   for `conditional` the group, the targets, and the derived age and hierarchy variables;
   for `joints` the dimensions. The age and sex targets are fully covered anyway.
3. The sampled table receives the not-applicable share.
4. `constraints` repair the result. Gleason repaired to the variable's X8 for female records,
   and a `repair_to_null` rule, therefore see the fraction already in place: a repair only
   changes the rows still holding a counted value, and rows already X8 or blank stay.
5. `post` rules (survival).
6. `no_frequency: nullify` blanks its columns.

The fraction is not conditional on sex or site: which rows are not applicable is random.
Use a constraint to tie it to a trigger.

### Reporting

`manifest.json` gets `na_fraction`: `settings` (mode, `mode_supplied_by`, `min_share`,
per-variable settings) and for every variable with a gap: `covered_share`,
`uncovered_share`, `gap_records`, `max_suppressed_records`, `status` (`applied` or
`skipped`), `reason`, `code` (the value used, `null` with `blank: true` for blank),
`code_counted`, `generated_rows`, `generated_share`, `code_share_target`,
`code_share_generated`, `setting` and `supplied_by`. `target_share` and `generated_share`
are the rows set to the code. When the code also has a published count (`code_counted`),
the rows that held it already stay, so the share of the code in the table is higher:
`code_share_target` is `uncovered_share` plus the code's published share, and
`code_share_generated` is the share found after the fraction was set (null for blank).
Compare the column in the CSV with these two, not with `target_share`. For a `code_counted`
column the rows the fraction set cannot be told from the rows that held the code already, so
a recomputation of `fidelity.csv` from the CSV alone differs from it in these columns (the
manifest figure leaves the set rows out, a CSV recomputation keeps them). Conformance
and fidelity use the null-aware functions: blank is not out of vocabulary and is counted in
`n_null` of `conformance.csv` and `coverage_null_counts` of the manifest. Fidelity compares
the counted values among the rows that received them; the generated not-applicable rows are
reported only in the manifest. Configured `validate:` metrics leave the affected columns out.

## Results on the real metadata snapshot

CTC, n = 20,000, seed 42, defaults, 0 out-of-vocabulary values. The 17 low-coverage
variables (16 in the table; the 17th, `scope9802Public`, is dropped by the loader) and the six
prostate variables:

| variable | covered | generated not-applicable share | code used |
|---|---:|---:|---|
| esophagusAndEgjTumorEpicenter | 0.011% | 99.990% | blank |
| gleasonTertiaryPattern | 0.079% | 99.920% | X8 label |
| psaLabValueRecode | 0.085% | 99.915% | blank |
| gleasonPatternClinicalRecode | 0.115% | 99.885% | X8 label |
| gleasonScoreClinicalRecode | 0.117% | 99.885% | X8 label |
| gleasonPatternPathologicRecode | 0.121% | 99.880% | X8 label |
| gleasonScorePathologicRecode | 0.122% | 99.880% | X8 label |
| p16Recode | 0.376% | 99.625% | Not applicable for this case |
| microsatelliteInstability | 0.918% | 99.080% | X8 label |
| ldhPretreatmentLabValue | 2.092% | 97.910% | X8 label |
| brainMolecularMarkers | 2.386% | 97.615% | X8 label |
| lymphVasInvasionPublic | 3.167% | 96.835% | Not Applicable |
| rxSummSurgPrimSite2023 | 4.477% | 95.525% | Diagnosed prior to 2023 |
| breslowDepthRecode | 4.831% | 95.170% | X8 label (this schema) |
| reasonForNoRadiation | 25.252% | 74.750% | blank |
| cocAccreditedFlag | 25.318% | 74.680% | Not applicable; DCO |

Sixteen more variables with coverage between 55% and 99.1% also get a share (for example
`rxSummSystemicSurSeq` 34%, `rxSummHormone` 3.8%, `regionalNodesPositive` 2.2%). Switch one
off with `na_fraction.variables`, or raise `min_share`. The full list is in the manifest.
