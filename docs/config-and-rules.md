# Config-driven generation: rules & measures

synthpediatric is driven by a single declarative config that says **which rules apply,
with what parameters, and how strict**. This page specifies that config and the
formalism behind it. For copy-and-run recipes, see the [cookbook](cookbook.md).

## The formalism: select → measure → generate

Matching a target distribution (e.g. "keep the real age distribution: 0 yrs 36%,
1–4 yrs 17%, …") is a **marginal constraint** (a *target marginal* / survey
*calibration margin*). The established framework for turning a set of such constraints
into data is **select–measure–generate**: (1) *select* a collection of low-order
marginals and cross-tabs to preserve, (2) *measure* them on the real data, (3)
*generate* data that preserves them. See the marginal-based / graphical-model
literature, e.g. [McKenna et al., scalable DP synthetic data](https://arxiv.org/abs/2108.04978)
and the [`dpmm` library (PrivBayes/MST/AIM)](https://arxiv.org/abs/2506.00322). *(We
skip the DP noise step: we use already-published, disclosure-controlled aggregates.)*

The principled way to combine many (possibly interacting) marginals into one coherent
joint is **maximum entropy / iterative proportional fitting (IPF)** — which is exactly
what synthpediatric's calibration does. A single marginal is matched by direct
categorical sampling; multiple interacting marginals (age **and** age×ICCC) require
IPF to find the max-entropy joint satisfying all of them.

## Two rule classes

| Class | Example | Nature | Mechanism |
|---|---|---|---|
| **targets** (distributional) | keep age marginal; keep age×ICCC; survival curve by group | soft / statistical | sampling · IPF (max-entropy) |
| **constraints** (logical) | prostate markers are male-only; retinoblastoma is pediatric | hard / deterministic | repair (consistency rules) |

Validation measures (fidelity / utility / privacy) are declared separately as the
output report. See `../additional decisions` for the full measure list.

## config.yaml

A config is YAML (comments allowed) or JSON. Both load through the same code path and
normalize to one canonical form, so equivalent YAML and JSON produce the same resolved
config and the same hash. Run it with `synthpediatric run config.yaml`.

```yaml
name: Pediatric ALL cohort
metadata: remote              # remote | path/to.ttl | path/to.json
source: CTC                   # required for NCCR metadata (remote / .ttl)
n: 50000
seed: 42
profile: standard             # marginals_only | standard | full   (default: full)
value_mode: label             # label | code
no_frequency: uniform         # uniform (default) | nullify | suppress
missingness: none             # none (default) | realistic (reserved, not implemented)
strict: true                  # true (default) | false: unknown names are errors | warnings

rules:                        # optional per-rule toggles over the profile
  oversample: false           # name: true|false

cohort:                       # restrict to a sub-population
  name: ALL
  filters:                    # equals -> values; min / max -> threshold
    - {variable: icccMajor, op: equals, values: ["I. Leukemias..."]}

targets:                      # distributional rules (soft)
  marginals:                  # inline 1-way targets: "keep this distribution"
    ageRecode19Groups:
      "00 years": 0.36
      "01-04 years": 0.17     # proportions or counts
    sex: {Male: 0.51, Female: 0.49}
  overrides:                  # authoritative marginals from files
    tables: input/freqs/      # a .json/.yaml file, or a directory of them
  joints:                     # one cross-tab calibrated to the marginals (IPF)
    cliques:
      - [sex, ageRecode19Groups, icccMajor]
    crosstabs: input/sex_age_iccc.csv   # columns: the clique variables + count
    smoothing: 0.0            # optional; also max_iter (100), tol (1e-8)
  survival:                   # time/event columns by group
    group_col: icccMajor
    specs: input/survival_by_iccc.json  # or an inline mapping group -> spec
                              # key __default__: the spec for groups not listed (else 0.80)
    horizon_months: 120       # optional; also time_col (months), event_col (event)

oversample:                   # boost categories; one mapping or a list of them
  variable: icccMajor
  values: ["V. Retinoblastoma"]
  factor: 10                  # default 10

constraints:                  # logical rules (hard, coherence)
  file: rules/ctc_consistency_rules.json   # or inline: {rules: [...], max_iterations: 10}

validate:                     # reserved: parsed, shape-checked, recorded; not evaluated yet
  fidelity: [tvd, ks, correlation_difference, km_concordance]
  utility:  [pmse, "specific:survival_by_treatment"]
  privacy:  [nn_distance, membership_inference]
  suppression_min: 16         # default 16

outputs: {dir: out/all_cohort, format: csv}
```

Paths are relative to the working directory. Quote category labels that YAML would read
as booleans (`"Yes"`, `"No"`, `"On"`); an unquoted one is rejected with a message saying so.

Differences from the first draft of this spec: `targets.joints` is a mapping
(`cliques` + `crosstabs`), because a YAML list cannot carry sibling keys; `oversample`
is its own top-level section; `crosstabs` is a CSV file, not a directory.

Pre-YAML JSON recipes still run unchanged. Their flat keys map as follows:
`override_marginals` -> `targets.marginals`, `survival` -> `targets.survival`,
`rules: "file.json"` -> `constraints: {file: ...}`. A legacy key and its new spelling
cannot both be given. Note that `rules:` is a string path in a legacy recipe and a
toggle mapping in a new config; the type tells them apart. `no_frequency: exclude`
is accepted as an alias of `suppress`. An empty section (`{}`, `[]`, `null`) means "not
configured", as before.

## The rule registry

Each pipeline step is a named rule: it has a parameter schema (validated up front, with
errors that name the key and list the valid choices), an `apply` step, and for `survival`
a `preflight` check that runs before sampling (see "Validation against the data"). The registry
lives in `synthpediatric/rules.py`; the file formats and top-level schema live in
`synthpediatric/config.py`.

| Order | Rule | Config key | Stage | What it does |
|---|---|---|---|---|
| 10 | `marginals` | `targets.marginals` | dictionary | replace the marginal of named variables with inline frequencies |
| 20 | `overrides` | `targets.overrides` | dictionary | same, from files (a directory is merged in name order) |
| 30 | `cohort` | `cohort` | dictionary | keep only the categories a cohort definition allows |
| 40 | `oversample` | `oversample` | dictionary | multiply the weight of chosen categories (rare-cancer boost) |
| 50 | `joints` | `targets.joints` | generate | IPF-calibrate a cross-tab to the marginals; sample the backbone jointly |
| 60 | `constraints` | `constraints` | generate | repair logically impossible records (hard) |
| 80 | `survival` | `targets.survival` | post | add time and event columns by group |

Sampling sits between 60 and 80: independent marginals, or the calibrated backbone when
`joints` ran. Two steps are not rules because they are settings: `no_frequency` and
`missingness` (below).

### Execution order and precedence

The order is fixed and listed above; it is not configurable. A later rule sees the output
of earlier ones, which gives the precedence:

- `overrides` beat `marginals` for the same variable.
- `cohort` restricts the final marginals, so its weights are the within-cohort ones.
- `oversample` reweights the within-cohort marginals.
- `joints` calibrate to those final marginals.
- `constraints` are hard: they repair whatever sampling produced, so they win over a
  sampled or joint-drawn value. The repair cost shows in the fidelity report.
- `survival` is conditioned on the repaired group column.

A rule runs at most once. Where several items of one kind are needed, the rule takes a
list and applies the items in the listed order (`cohort.filters`, and `oversample` as a
list; factors on the same variable compound). Order is therefore explicit and testable.

### Profiles: the "how many rules" dial

`profile` chooses which rules are on by default. The bundles are one table,
`PROFILES` in `synthpediatric/rules.py`:

| Profile | Rules enabled | Intent |
|---|---|---|
| `marginals_only` | marginals, overrides, cohort | fastest, least input, strongest privacy |
| `standard` | + joints, constraints | adds the backbone cross-tab and coherence repairs |
| `full` | + oversample, survival | adds the rare-cancer boost and survival times |

A rule is *applied* when it is enabled and has parameters. Each rule ends in one of three
states, recorded in the manifest with a reason:

- `applied`: enabled and configured.
- `skipped`: enabled by the profile but the config has no section for it (not an error).
- `disabled`: left out by the profile, or switched off in `rules:`.

So one config can be run at all three tiers by changing only `profile:`; sections for
rules outside the profile are kept and just not applied. Toggle a single rule with
`rules: {name: true|false}`. Switching a rule on without giving it a section is an error.
With no `profile`, the default is `full`, which is what recipes meant before profiles
existed (every configured rule runs).

### Variables with no published frequency

`no_frequency` decides what happens to variables whose metadata has permissible values but
no published counts:

- `uniform` (default): sample uniformly over the permissible values.
- `nullify`: keep the column in the schema but leave every value blank. The variable is
  still sampled first, so other columns and the random stream are identical to `uniform`.
  It is excluded from conformance and fidelity scoring, and marked `nullified` in
  `coverage.csv`.
- `suppress`: drop the column.

### Missingness

`missingness: none` is the only implemented value. `realistic` is reserved for modeling
real-world missing values and currently stops the run with an error rather than being
ignored.

### Validation against the data, and `strict`

The schema checks (above) only look at the shape of the config. A second set of checks
compares what the config names with the resolved dictionary: variables, category labels,
survival groups, constraint columns. They produce errors of the form

```text
config error: targets.marginals.age_group: unknown category '05-9'. Did you mean '05-09'? Valid categories: 00-04, 05-09, ...
```

with the dotted key, the offending value, the closest valid name (`difflib`) when there is
one, and the valid names (the first 15 and the total when the list is longer). The real
messages for each case are in the [cookbook](cookbook.md#mistakes-the-checks-catch).

**Timing.** The checks run after the metadata is loaded and before any record is sampled
or file written (`run_recipe` raises before `write_run` is reached). Rules run in
execution order, so each is checked against the dictionary as the rules before it left it:
a cohort filter sees marginals and overrides, an oversample sees the cohort. A category an
earlier rule removed gets its own message ("exists in the dictionary but an earlier rule
... removed it"). Three things are checked against the dictionary *as loaded* instead,
because they are legitimately independent of earlier rules: `targets.marginals`,
`targets.overrides` (a table replaces the variable's whole distribution, so it may name
categories a previous table dropped) and the labels in the `joints` cross-tab (the
calibration drops rows for a category the cohort removed). "As loaded" also means before
`no_frequency: suppress` drops variables, so a marginals or overrides table can still supply
the frequencies of a suppressed variable (the column is added back, as before the checks).
`survival` runs after sampling,
so its section is checked in a preflight step that runs before sampling: `group_col`, the
group names in `specs` (a group is known if the loaded or the final dictionary has it, so
one specs file can serve several cohorts), and the shape of each spec.

**What is checked:**

| Section | Checked |
|---|---|
| `targets.marginals`, `targets.overrides` files | variable, each category label |
| `cohort.filters` | variable, `equals` labels (each filter against what the filters before it left), `min`/`max` on non-numeric variables, a filter that leaves no categories |
| `oversample` | variable, labels |
| `targets.joints` | clique variables, cross-tab labels |
| `targets.survival` | `group_col`, group names in `specs`, spec shape, `__default__` |
| `constraints` | the columns each constraint names; a malformed constraint (missing field) |

**`strict` (choice made here).** `strict: true` is the default: a reference to
something the dictionary does not have is a `ConfigError`. `strict: false` turns the
references that can be skipped into warnings, stored in `warnings` and printed by the CLI,
and the run does what it did before the checks existed: a marginals or overrides entry is
used as written, a cohort filter on an unknown variable is skipped, unknown `equals`
values are ignored, an oversample label gets no factor (and appears in `unmatched_values`
in the manifest, as before), an unknown survival group is ignored, a constraint on an
absent column is skipped, and cross-tab rows with an unknown label get no mass. Mistakes
with nothing sensible to run stay errors: a filter that leaves no categories, an unknown
`oversample` variable, `survival.group_col` or `joints` clique variable, an invalid
survival spec. Rationale: a typo that silently changes the output is worse than a
stopped run, and `strict: false` stays available for partial specs (such as one rules
file shared across datasets). The effective value is written to `manifest.json`
(`strict`); `config.strict` appears only when the config sets it, so the config hash of
every existing config is unchanged.

**Legacy recipes.** A config that uses a pre-YAML flat key (`override_marginals`, a
top-level `survival`, `rules: path.json`) is treated as `strict: false` unless it sets
`strict` itself, so these keep their exact output, including the oversample
`unmatched_values` warning that `test_legacy_recipe_output_unchanged` relies on. The
existing fixture needed no change. A legacy recipe with none of those keys (only `cohort`
or `oversample`) cannot be told from a new config and is strict. Because the lenient
default is inferred from the keys, the canonical `config` in a legacy run's manifest does
not carry it: add `strict: false` to re-run that config with the old leniency.

**`__default__` (choice made here).** In `targets.survival.specs`, `__default__` is
the spec for every group that is not listed, any valid spec (`0.8`, `{s5: ...}`,
`{points: ...}`). Without it, unlisted groups keep the built-in 5-year survival of 0.80, so
configs without the key give the same output as before, and `__default__: 0.80` gives the
same output as omitting it. `examples/profiles/full.yaml` already assumed this.

**Not covered:** the `allowed_values` / `trigger_values` labels inside constraints (a
repair target such as `Not applicable` is legitimately not in the dictionary), a
`time_col` / `event_col` that overwrites an existing column, and the `generate --rules` CLI
command (not config driven). Only the first mistake is reported per run.

### The reserved `validate:` block

`fidelity`, `utility` and `privacy` are lists of metric names; `suppression_min` is an
integer >= 1 (default 16). The shape is checked, unknown keys are rejected, defaults are
filled in, and the block is copied to the manifest. Metric names are not checked against
any list and no metric is computed; that is separate work.

## Manifest

`manifest.json` is written next to the cohort. To reproduce a run from the manifest alone,
feed its `config` back to `run_recipe` / save it as a file: the canonical config is itself
a valid config and gives the same hash.

| Key | Contents |
|---|---|
| `config` | the canonical resolved config (defaults filled, legacy keys moved, profile resolved) |
| `config_sha256` | SHA-256 of `config` plus the resolved rule list; `recipe_sha256` carries the same value for older readers |
| `recipe` | the config exactly as given, after parsing |
| `profile` | the resolved profile name |
| `rules` | every rule in execution order: `name`, `order`, `stage`, `status`, `reason`, `params`, and `details` for applied rules (for `joints`: iterations, deviation, convergence) |
| `oversampling` | one entry per oversample step: `variable`, `factor`, `factors_applied` (per category), `unmatched_values` (always empty when `strict` is true, because a non-matching label is an error), `proportions_before`, `proportions_after` |
| `no_frequency` | the mode, and the variables that had no published frequency |
| `missingness` | `none` |
| `validate` | the normalized `validate:` block, or null |
| `input_files` | SHA-256 of each file the config referenced (rule files, tables, survival specs, cross-tabs) |
| `strict` | whether unknown names were errors (`true`) or warnings (`false`) in this run |
| `warnings` | with `strict: false`, every unknown name that was tolerated; also IPF non-convergence |
| `n_records`, `seed`, `repairs`, `overall_tv_distance`, `coverage` | as before; `coverage` also counts `nullified` |

Oversampling still renames the dictionary with a `[reweighted: ...]` tag; the factors and
effective proportions now live in the manifest.

## Examples

- `examples/recipe_ctc.json` (legacy keys) and `examples/recipe_ctc.yaml` (this layout)
  describe the same run and produce an identical cohort for the same seed.
- `examples/profiles/marginals_only.yaml`, `standard.yaml`, `full.yaml` each run offline
  against `examples/nccr_ctc_dictionary.json`, adding the rules of their tier.

## How it maps to the engine

| Config section | Module |
|---|---|
| `metadata`/`source` | `nccr_rdf` (full-coverage loader) |
| `targets.marginals` / `overrides` | `inputs.override_marginals` |
| `targets.joints` | `calibrate` (`JointDistribution.from_counts`, `raking_ipf`, `generate_calibrated`) |
| `targets.survival` | `survival_gen.sample_survival` |
| `constraints` | `constraints.RuleSet` |
| `cohort` | `inputs.apply_cohort` |
| `oversample` | `resample.oversample_with_report` |
| `validate` | reserved; `conformance` + `evaluate` (fidelity) cover today's scorecard, privacy suite planned |

## Design notes: open points and choices made

These were left open and are easy to change.

- **Rule names.** Named after their config section: `marginals`, `overrides`, `cohort`,
  `oversample`, `joints`, `constraints`, `survival`. The spec's "consistency rules" are the
  `constraints` rule.
- **Profile contents.** Per the table above. `cohort` is in every tier because it defines
  the population rather than adding fidelity. `oversample` is in `full` only because it
  moves the cohort away from natural proportions. To change a bundle, edit `PROFILES`;
  tests assert the documented bundles and nesting.
- **Default profile.** `full`, so a config with no `profile` and every pre-YAML recipe run
  all configured rules. Dropping to a lower tier is explicit.
- **Repeats.** A rule runs at most once; multi-item rules take lists applied in order.
- **One clique.** `joints` calibrates a single cross-tab. Several overlapping cliques need
  multi-clique IPF and are rejected with an error for now.
- **`nullify` vs `suppress`.** `nullify` keeps the schema with blank values; `suppress`
  drops the column (the old `exclude`).
- **Hash scope.** The hash covers the canonical config and resolved rule list, not file
  contents; `input_files` fingerprints those separately.
- **PyYAML.** Optional extra (`pip install 'synthpediatric[yaml]'`), pinned to 6.0.3, also
  in `dev`. JSON configs need no extra. Without it, a `.yaml` config fails with the install
  command.
- **Strictness.** `strict: true` by default, `false` downgrades skippable bad references to
  warnings, legacy recipes default to `false`. Change the default in
  `config.effective_strict`; which mistakes are downgradable is decided at each `_flag(...)`
  call in `rules.py` (a call that raises directly is never downgraded).
- **`__default__`.** Works as the fallback survival spec (`DEFAULT_GROUP` in `rules.py`).
- **Not built (out of scope).** The Bayesian-network `network:` rule, scenario mode, the
  consistency battery content, validation metrics, and `missingness: realistic`.
