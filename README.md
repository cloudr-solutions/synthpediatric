# synthpediatric

Generate **privacy-safe synthetic pediatric and AYA (ages 0–39) cancer cohorts**
from *published cancer-registry metadata* — the permissible-value frequencies that
registries publish as data dictionaries.

`synthpediatric` is source-agnostic. It works from a simple **marginals dictionary**
(the permissible values and their frequencies for each variable) and can ingest that
dictionary from any registry via a **source adapter**. It ships with an adapter for
the **National Childhood Cancer Registry (NCCR) Data Platform** metadata, and a plain
JSON dictionary format for any other source. From that dictionary it samples each
variable, repairs clinically incoherent records with a declarative consistency-rules
engine, and can optionally calibrate cross-variable structure to match the published
marginals.

Because the default path consumes only **aggregate published frequencies** and no
individual-level records, the synthetic output is privacy-safe by construction: there
is no training population to re-identify.

## How it works

```
published metadata ──(source adapter)──▶ marginals dictionary ──▶ generate ──▶ rules ──▶ (optional) joint calibration ──▶ cohort
```

- **Marginals dictionary** — the common interface: for each variable, its permissible
  values and their frequencies. Provide it as JSON, or produce it with an adapter.
- **Source adapters** — turn a published metadata source into a dictionary. An
  **NCCR adapter** (`synthpediatric.nccr_rdf`, reads the NCCR RDF/Turtle metadata) is
  included as the reference adapter; new registries can be added the same way.
- **Generation + consistency rules** — sample from the dictionary, then repair
  clinically impossible records (e.g. a prostate Gleason score on a female patient).
- **Joint calibration (optional)** — learn cross-variable structure from an
  individual-level proxy and rake it to the published marginals (see below).

## Install

```bash
pip install -e .            # core: numpy, pandas, pyarrow (Python 3.9+)
pip install -e ".[rdf]"     # + rdflib, for the NCCR RDF adapter
pip install -e ".[yaml]"    # + PyYAML, to run YAML configs (JSON configs need nothing extra)
```

## Quickstart — any source (JSON dictionary)

The source-agnostic path: hand the tool a marginals dictionary and generate.

```bash
synthpediatric generate examples/nccr_ctc_dictionary.json -n 5000 --evaluate
```

```json
{
  "name": "Example registry cohort",
  "n_records": 1474368,
  "variables": [
    {
      "name": "sex", "label": "Sex", "type": "categorical",
      "values": [
        {"value": "Female", "count": 900104},
        {"value": "Male",   "count": 574264}
      ]
    }
  ]
}
```

Frequencies may be given as `count`, `frequency`, or `proportion`.

## Quickstart — NCCR adapter (included)

The NCCR adapter reads the published NCCR metadata
(<https://github.com/NCI-DCCPS/nccr-metadata>) directly. Use `remote` to fetch it, or
pass a local `.ttl` file.

```bash
# List the NCCR datasources (with real record counts)
synthpediatric sources remote

# Inspect variables that have published frequencies for a source
synthpediatric profile remote --source CTC

# Generate a synthetic registry cohort + clinical rules, then score it
synthpediatric generate remote --source CTC \
    -n 20000 \
    --rules examples/ctc_consistency_rules.json \
    --seed 42 \
    --out out/ctc.parquet \
    --evaluate

# Score an existing cohort against the published marginals
synthpediatric evaluate remote --source CTC out/ctc.parquet
```

NCCR sources: `CTC` (registry), `ABM`, `CCDI`, `COG`, `MCD`, `MCE`, `MCP`, `PHARM`,
`RO`. Add `--value-mode code` to use raw code notations instead of labels. For repeat
runs, download `nccr_instances.ttl` once and pass its path instead of `remote`.

## Config-driven runs (`synthpediatric run`)

A run can be described in one YAML (or JSON) file: the metadata source, a **profile**,
and the parameters of each **rule** (marginals, overrides, cohort, oversample, joints,
constraints, survival). The profile is the "how many rules" dial: `marginals_only`,
`standard` or `full`. Individual rules can be switched with `rules: {name: true|false}`.

```yaml
name: CTC demo
metadata: examples/nccr_ctc_dictionary.json   # or: remote, with source: CTC
n: 5000
seed: 42
profile: standard            # marginals_only | standard | full
targets:
  marginals:
    sex: {Male: 0.52, Female: 0.48}
constraints:
  file: examples/nccr_ctc_rules.json
no_frequency: uniform        # variables with no published frequency: uniform | nullify | suppress
```

```bash
synthpediatric run examples/profiles/standard.yaml --out-dir out/standard
synthpediatric run examples/recipe_ctc.yaml        # needs network (metadata: remote)
```

The run writes the cohort plus `coverage.csv`, `conformance.csv`, `fidelity.csv`,
`dictionary.json` and `manifest.json`. The manifest records the resolved profile and rule
list, the applied oversampling factors, the config and its hash, so a run can be
reproduced from it alone. Existing JSON recipes keep working. The full specification,
rule order and precedence are in [docs/config-and-rules.md](docs/config-and-rules.md);
profile examples are in `examples/profiles/`. To write your own, start from the tested
recipes in the [cookbook](docs/cookbook.md).

## Why marginals are not enough (stated up front)

Sampling every variable independently reproduces each variable's distribution
perfectly but destroys the relationships *between* variables — the joint distribution
cannot be recovered from marginals alone. Two mechanisms address this:

1. **Consistency rules** patch the most important, well-known relationships (e.g.
   Gleason score does not apply to female patients; retinoblastoma occurs in early
   childhood).
2. **Joint calibration** (`synthpediatric.calibrate`) learns cross-variable structure
   from an individual-level proxy (e.g. SEER research data) and uses iterative
   proportional fitting (raking) to make its margins match the published marginals —
   the proxy's correlations wearing the target's distribution — while preserving
   association. This is transparent and auditable rather than a black-box model.

## Python API

```python
from synthpediatric import generate, marginal_fidelity, overall_score
from synthpediatric.constraints import RuleSet
from synthpediatric.nccr_rdf import load_graph, build_dictionary   # NCCR adapter

graph = load_graph(["nccr_instances.ttl"])   # or default: the published URL
d = build_dictionary(graph, "CTC")           # -> a DataDictionary for one source

rules = RuleSet.from_json("examples/ctc_consistency_rules.json")
result = generate(d, n=20000, rng=42, ruleset=rules)

print(result.data.head())
print(result.repairs)                         # per-rule repair counts
print(overall_score(marginal_fidelity(d, result.data)))
```

Joint calibration:

```python
from synthpediatric.calibrate import calibrate_to_dictionary, generate_calibrated

cal = calibrate_to_dictionary(proxy_df, ["sex", "ageRecode19Groups", "icccMajor"], d)
result = generate_calibrated(d, cal.joint, n=20000, rng=42, ruleset=rules)
```

## Consistency rules format

Declarative JSON. The `allowed_values` rule says: when `trigger_col` holds one of
`trigger_values`, `target_col` must be one of `allowed_values` (violations are
repaired by resampling). See `examples/ctc_consistency_rules.json`.

```json
{
  "max_iterations": 5,
  "constraints": [
    {
      "type": "allowed_values",
      "name": "retinoblastoma_is_early_childhood",
      "trigger_col": "icccMajor",
      "trigger_values": ["V. Retinoblastoma"],
      "target_col": "ageRecode19Groups",
      "allowed_values": ["00 years", "01-04 years", "05-09 years"],
      "description": "Retinoblastoma occurs almost exclusively in early childhood."
    }
  ]
}
```

## Privacy posture

- **Metadata-only generation** (the default): derived solely from published aggregate
  frequencies, no individual records — privacy-safe by construction.
- **Joint-calibrated generation**: once an individual-level proxy is used, outputs are
  derived from disclosure-controlled inputs and should pass the privacy evaluation
  suite (nearest-neighbor distance, membership inference) before any public release.

## Status

Metadata-driven generation, consistency rules, marginal-fidelity scoring, and
transparent joint calibration are implemented, with an NCCR adapter and CI. Additional
source adapters and richer fidelity/privacy metrics are on the roadmap.

## License

Apache-2.0. See [LICENSE](LICENSE). A CloudR project. Synthetic output contains
**no real patient data**; the tool reads only published aggregate metadata.
