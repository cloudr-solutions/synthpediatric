# Config-driven generation: rules & measures

synthpediatric is driven by a single declarative config that says **which rules apply,
with what parameters, and how strict**. This page specifies that config and the
formalism behind it.

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

```yaml
name: Pediatric ALL cohort
metadata: remote              # remote | path/to.ttl | path/to.json
source: CTC
n: 50000
seed: 42
profile: standard             # marginals_only | standard | full  (expands the rules below)

cohort:                       # optional: restrict to a sub-population
  filters:
    - {variable: icccMajor, op: equals, values: ["I. Leukemias..."]}

targets:                      # distributional rules (soft)
  marginals:                  # a 1-way marginal target == "keep this distribution"
    ageRecode19Groups:
      "00 years": 0.36
      "01-04 years": 0.17
      # ... (proportions or counts)
    sex: {Male: 0.51, Female: 0.49}
  overrides:                  # authoritative marginals from the Input team (SEER*Stat)
    tables: input/freqs/      # per-variable frequency tables
  joints:                     # low-order cross-tabs (cliques) -> IPF / max-entropy
    - [sex, ageRecode19Groups, icccMajor]
    - [icccMajor, combinedSummaryStage]
    crosstabs: input/crosstabs/
  survival:                   # survival curves by group
    group_col: icccMajor
    specs: input/survival_by_iccc.json
    horizon_months: 120

constraints:                  # logical rules (hard, coherence)
  file: rules/ctc_consistency_rules.json

validate:                     # Output-team report
  fidelity: [tvd, ks, correlation_difference, km_concordance]
  utility:  [pmse, "specific:survival_by_treatment"]
  privacy:  [nn_distance, membership_inference]
  suppression_min: 16

outputs: {dir: out/all_cohort, format: csv}
```

### "How many rules apply" — the fidelity dial

`profile` expands to a rule bundle; individual rules can be toggled/overridden:

- `marginals_only` — fastest, lowest fidelity, least input needed, strongest privacy.
- `standard` — + consistency constraints + backbone joints.
- `full` — + survival + conditionals (+ oversampling as needed).

More rules → higher fidelity, but more required input statistics, slower, and a larger
privacy surface — so the dial lets us pick the tier empirically (simpler often wins).

## How it maps to the engine (today)

| Config section | Module |
|---|---|
| `metadata`/`source` | `nccr_rdf` (full-coverage loader) |
| `targets.marginals` / `overrides` | `inputs.dictionary_from_frequencies`, `inputs.override_marginals` |
| `targets.joints` | `calibrate` (IPF; `JointDistribution.from_counts` for cross-tabs) |
| `targets.survival` | `survival_gen.sample_survival` |
| `constraints` | `constraints.RuleSet` |
| `cohort` | `inputs.apply_cohort` |
| `validate` | `conformance` + `evaluate` (fidelity), privacy suite (planned) |

The config is also the **reproducibility artifact**: the recipe runner hashes it into a
run manifest. `recipe.py` implements the JSON form today; YAML input, a formal rule
registry, and the `profile` bundles are the in-progress evolution of this spec.
