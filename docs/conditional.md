# Conditional distributions by group (`targets.conditional`)

Use this rule when a published table gives, for each group (for example each ICCC major
group), the distribution of other variables (age, sex). The rule draws the group from a mix,
then draws each target given the group. The generated cohort reproduces each group's
conditional distributions, not only the overall marginals.

The rule is `conditional` (order 55, stage `generate`). It is on in the `standard` and `full`
profiles. It needs an NCCR snapshot when the group is an ICCC variable, because the ICCC and
age variables come from the metadata.

Examples (all in `examples/conditional/`, run from the repository root with `run_example.py`):

| File | What it shows |
|---|---|
| `age_sex_by_iccc_placeholder.yaml` | the annotated placeholder config, inline rows |
| `age_by_iccc_crosstab_placeholder.yaml` | the same, with the numbers in CSV cross-tabs (`crosstabs/`) |
| `age_sex_by_iccc_refusal_placeholder.yaml` | a table with a cell below 16: the run is refused |
| `one_registry_age_sex_by_iccc.yaml` | real aggregate table of one state registry, age and sex by ICCC group |
| `nccr_age_by_iccc_0_19.yaml` | real aggregate table of all NCCR, age by ICCC group, with a sex-by-ICCC target |

The placeholder files hold invented numbers. The two real configs hold real aggregate numbers
that the team lead cleared for public use as synthesis inputs on 2026-11-16, and their
provenance block says so.

## The annotated config

This is `age_sex_by_iccc_placeholder.yaml` (PLACEHOLDER numbers, illustrative only):

```yaml
name: PLACEHOLDER conditional - age and sex by ICCC group
metadata: nccr_instances.ttl
source: CTC
n: 50000
seed: 7
profile: standard
cohort:                        # 3 covered groups plus 1 the table does not cover
  name: PLACEHOLDER four groups
  filters:
    - variable: icccMajor
      op: equals
      values:
        - "I. Leukemias, Myeloproliferative And Myelodysplastic Diseases"
        - "II. Lymphomas and reticuloendothelial neoplasms"
        - "III. CNS and Miscellaneous Intracranial and Intraspinal Neoplasms"
        - "V. Retinoblastoma"
targets:
  conditional:
    provenance:
      source: PLACEHOLDER table name
      date: "2000-01-01"
      origin: assumption       # cgc_aggregate | seer_stat | literature | assumption
      note: Invented numbers for documentation only.
      # min_cell: 16
      # override_reason: ...   # required when min_cell is 0
    group:
      variable: icccMajor
      labels:                  # short names for dictionary labels
        Leukemias: "I. Leukemias, Myeloproliferative And Myelodysplastic Diseases"
        Lymphomas: "II. Lymphomas and reticuloendothelial neoplasms"
        CNS: "III. CNS and Miscellaneous Intracranial and Intraspinal Neoplasms"
        Retinoblastoma: "V. Retinoblastoma"
      mix:
        basis: counts          # counts | percent | published_marginal
        values: {Leukemias: 300, Lymphomas: 200, CNS: 250}
    scope:
      age_years: [0, 19]
    age:
      anchor: ageRecode19Groups
      bins:
        "0-4": {years: [0, 4]}
        "5-9": {years: [5, 9]}
        "10-14": {years: [10, 14]}
        "15-19": {years: [15, 19]}
      # split:
      #   "0-4": {"00 years": 1, "01-04 years": 4}
    targets:
      - variable: ageRecode19Groups
        basis: percent
        by_group:
          Leukemias: {"0-4": 40, "5-9": 20, "10-14": 20, "15-19": 20}
          Lymphomas: {"0-4": 10, "5-9": 20, "10-14": 30, "15-19": 40}
          CNS: {"0-4": 30, "5-9": 30, "10-14": 20, "15-19": 20}
      - variable: sex
        basis: counts
        by_group:
          Leukemias: {Male: 170, Female: 130}
          Lymphomas: {Male: 110, Female: 90}
          CNS: {Male: 120, Female: 130}
    uncovered:
      groups:
        Retinoblastoma:
          share: 40
          targets:
            ageRecode19Groups: published_age_mix
            sex: same_as_covered_total
outputs: {dir: out/conditional/age_sex_by_iccc}
```

## Keys

`targets.conditional` takes these keys. Unknown keys are errors.

| Key | Meaning |
|---|---|
| `provenance.source`, `date`, `origin` | required. `origin` is `cgc_aggregate`, `seer_stat`, `literature` or `assumption` |
| `provenance.note`, `min_cell`, `override_reason` | optional. See "Minimum cell check" |
| `group.variable` | the grouping variable (one per config) |
| `group.labels` | optional map from your label to the dictionary label. Labels you do not list must be exact dictionary labels |
| `group.mix.basis`, `values` | how many records each group gets: `counts`, `percent`, or `published_marginal` (the group variable's own marginal; `values` is not allowed then) |
| `scope.age_years` | `[lo, hi]`, the age range the table covers. Needs `age` |
| `age.anchor` | the age variable that is sampled. It must also be in `targets` |
| `age.bins` | your age groups, each `{years: [lo, hi]}` (must start and end on anchor band edges) or a list of anchor labels |
| `age.split` | optional weights that divide a union bin between its anchor bands |
| `targets[]` | `variable`, `basis` (`counts` or `percent`), and exactly one of `by_group` (inline rows) or `file` (a CSV) |
| `uncovered.groups` | one entry per group that is in scope but not in the table. See below |

Every label and variable name is checked against the dictionary before any record is
generated, with a did-you-mean suggestion.

## Percentages, counts and CSV files

- `percent` rows are distributions: each row must sum to 100 within one point. They are
  normalised.
- `counts` rows are normalised too, so counts act as ratios. For a target such as sex, the
  counts give the ratio Male / (Male + Female) in each group. If the rows do not add up to the
  group size (with mix basis `counts`), the difference is recorded in the manifest under
  `details.provenance_notes`, and the run goes on.
- A `file` target is a CSV with the group-variable column, the target-variable column and
  `count` (the format of `synthpediatric measure`). A cell absent from the file is a zero and
  is listed in the manifest. File paths are relative to the directory you run from. For the age
  target, the file lists anchor labels, so the counts give the union split and no default is
  needed. `age.split` together with an age file is an error.
- Only the categories you list are generated. `Unknown` is never generated unless you list it.

## Union bins and the split

A bin such as `0-4` can be a union of anchor bands (`00 years` and `01-04 years`). Inside a
union the default split is the anchor's published weights from the metadata, restricted to the
union and renormalised (uniform if all are zero). Give `age.split` to override it. Each bin's
split and its source (`config`, `published_restricted`, `uniform`) are in the manifest.

## Uncovered groups

A group that is in scope (after the cohort filter) but not in the table needs an entry under
`uncovered.groups`, or the run stops and lists the missing groups. Each entry has a `share`
(a number in the unit of the mix, or `exclude`) and, unless the share is `exclude`, one
treatment for every target:

| Target | Treatment | Meaning |
|---|---|---|
| age anchor | `published_age_mix` | the metadata's age weights, restricted to the scope and renormalised |
| age anchor or other | `{values: {category: number}}` | your own ratio |
| other | `same_as_covered_total` | the pooled distribution of the covered groups |
| other | `published_marginal` | the metadata's marginal, restricted to the categories you list |

`published_age_mix` is an assumption. The metadata has no age distribution per group, so the
rule applies the overall published age weights to the uncovered group. Every treatment is
recorded in the manifest as an assumption. With `share: exclude` the group is left out of the
dataset, and no treatment is needed. `one_registry_age_sex_by_iccc.yaml` excludes its two
uncovered groups this way, because they are not reported for that registry.

With mix basis `published_marginal`, the share of an uncovered group is `exclude` or a percent
of the total, and the covered groups get the published weights rescaled to the remainder.

## Minimum cell check

Aggregate counts from CGC can disclose small groups, so the rule checks every count before
sampling. The check sits in `provenance`:

- the default minimum is 16 for `origin: cgc_aggregate`; other origins have no check unless
  you set `min_cell`;
- a count is refused when it is above 0 and below the minimum. A zero is not flagged, because
  it does not disclose a small group;
- the check covers counted cells (your counts) and implied cells (percent times the group
  count, at bin level) when the group size is known. With percent rows and no group size, the
  manifest says `implied counts not checkable: group size unknown`;
- `min_cell: 0` switches the check off and needs a non-empty `override_reason`. The manifest
  records the value, who supplied it, and the reason, so the decision stays visible.

A refused run raises `DisclosureRefusal` (a `ConfigError`) that lists every offending cell as
`group | target | category | value | counted|implied`, the threshold and the origin, and ends
with "Nothing was generated." No file is written. The threshold is never adjusted silently.

Individual-level data in CGC is not size restricted. The threshold concerns aggregates
exported from CGC, such as the tables in the real examples. Those examples contain cells below
16 and set `min_cell: 0` with the release decision as the reason.

## Derived variables stay consistent

The rule samples the age anchor and derives everything that depends on it.

- Age variables are found by name (`age*`) in the dictionary and listed in the manifest under
  `details.age_variables`. For the CTC source they are `ageRecode19Groups`,
  `ageRecode20Groups`, `ageRecodeSingle85p` and `ageRecodeSingle90p`. A variable whose label is
  one band is derived directly. A variable whose labels split the band is sampled inside it
  with its published weights. An age-named variable with an unparsable label is an error.
  When several variables split the same band (the single-year recodes `ageRecodeSingle85p`
  and `ageRecodeSingle90p`), the one with the most labels is drawn and the others take the
  label that contains that year, so a record has one single-year age in every variable. The
  manifest lists them under `details.age_links`; where the labels of a variable do not nest
  inside the reference variable's, it keeps its own draw.
- When the group is an ICCC variable, `iccc2017Recode` and `iccc2017ExtendedRecode` are
  derived from the major group (child label drawn from its published weights within the
  major). The extended recode is finer than the recode (`Ia1`, `Ia2` inside `Ia`), so it is
  drawn inside the label of `iccc2017Recode`, matched by Roman numeral and letter; the
  manifest lists this under `details.hierarchy.nested`. If the labels do not match one to
  one, both are drawn from the major group independently, as before. The extended recode's
  own headings (for example `IX SOFT TISSUE...`) belong to the headings of the recode, which
  has no published count, so they are not drawn. These two are the only subgroup-level ICCC
  variables. `nccrSiteMorphRecodeLevel1` to
  `5` are site and morphology recodes, not ICCC, so they are not derived. For any other group
  variable the manifest says `hierarchy: none detected`.
- `conditional_derivation.csv` lists every derivation (source label, variable, derived label,
  method, probability).

## Order, outputs and the manifest

The rule runs at order 55: after `joints`, before `constraints`. The base sampler produces the
other columns first. The rule then overwrites the group, target and derived columns, and the
`constraints` ruleset repairs the final records. Constraints can therefore change conditional
columns, so the achieved tables are measured after them. `targets.joints` and
`targets.conditional` cannot use the same variable.

Extra files next to the cohort:

| File | Contents |
|---|---|
| `conditional_group_mix.csv` | target and achieved share per group, with the expected standard error and z |
| `conditional_targets_vs_generated.csv` | per group, target and category: target and generated share, difference, expected standard error, z (age at user-bin level) |
| `conditional_derivation.csv` | the derivation tables |

`manifest.json` has the rule's `details` under `rules[]`: provenance, the minimum-cell
decision, age bins and splits, `age_variables`, `hierarchy`, `dropped_by_cohort`, `uncovered`
assumptions, `provenance_notes`, and `achieved` (from `conditional.verification_summary`:
largest difference, largest z, and the noise expected from chance alone).

## Decisions

- **YAML shape.** One `conditional` block under `targets`, with `group`, `age`, a list of
  `targets`, and `uncovered`. Each target names its own variable, so one group can drive age,
  sex and other variables in one rule.
- **Cohort filter on the group variable.** The mix is restricted to the surviving groups and
  renormalised. Table groups the cohort removed are dropped and listed in
  `details.dropped_by_cohort`; this is not an error. With mix basis `published_marginal`, the
  post-cohort marginal is used.
- **One grouping variable per config.** A second group variable needs a second config.
- **Sex as a ratio.** Counts that do not add up to the group size are used as printed, as a
  ratio, and the difference is recorded.
- **Uncovered groups.** They need an explicit share and treatments. Nothing is filled in
  silently.

## Limits

- There is no age-by-sex cross inside a group: age and sex are independent given the group.
- `fidelity.csv` shows the TVD against the published marginals. The rule replaces those
  marginals on purpose, so a higher TVD on the group and target columns is expected. Use
  `conditional_targets_vs_generated.csv` to judge the fit.
- `config_sha256` changes for every config after upgrading, because the resolved rule list now
  includes `conditional`. Rerun and record the new hash.
