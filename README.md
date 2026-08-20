# synthpediatric

Generate **privacy-safe synthetic pediatric/AYA cancer cohorts** directly from the
**published NCCR Data Platform metadata** — the permissible-value frequencies that
NCI publishes as machine-readable linked data.

`synthpediatric` reads the real NCCR metadata, samples each variable from its published
marginal distribution, and repairs clinically incoherent records with a declarative
consistency-rules engine. Because the metadata path consumes only **aggregate
published frequencies** and no individual-level records, the synthetic output is
privacy-safe by construction: there is no training population to re-identify.

> **Status: metadata-driven generation (Phase 0).** This release reproduces each
> variable's published distribution and enforces clinical consistency rules. It
> does **not** yet reproduce the joint (multivariate) structure between variables.
> Joint structure is the next phase: learn correlations from a public
> individual-level proxy (e.g. SEER research data) and calibrate them to these NCCR
> marginals. Until then, treat the output as marginal-faithful and rule-consistent,
> but not yet fully correlation-faithful.

## Why marginals are not enough (stated up front)

Sampling every variable independently reproduces each variable's distribution
perfectly but destroys the relationships between variables — the joint distribution
cannot be recovered from marginals alone. The consistency-rules engine patches the
most important, well-known relationships (e.g. Gleason score does not apply to
female patients; retinoblastoma occurs in early childhood). Full joint fidelity is
the next-phase feature described above.

## Install

```bash
pip install -e ".[rdf]"     # includes rdflib, needed to read the NCCR metadata
```

Core generation depends only on numpy, pandas, and pyarrow (Python 3.9+). The
`[rdf]` extra adds `rdflib` for loading the published NCCR RDF/Turtle metadata.

## Quickstart — real NCCR metadata

The metadata is published at
<https://github.com/NCI-DCCPS/nccr-metadata>. Use `remote` to fetch it, or pass a
local `.ttl` file.

```bash
# 1. List the NCCR datasources (with real record counts)
synthpediatric sources remote

# 2. Inspect the variables that have published frequencies for a source
synthpediatric profile remote --source CTC

# 3. Generate a synthetic registry cohort + clinical rules, then score it
synthpediatric generate remote --source CTC \
    -n 20000 \
    --rules examples/ctc_consistency_rules.json \
    --seed 42 \
    --out out/ctc.parquet \
    --evaluate

# 4. Score an existing cohort against the published marginals
synthpediatric evaluate remote --source CTC out/ctc.parquet
```

Working offline? Download `nccr_instances.ttl` once and pass its path in place of
`remote` (much faster than fetching on every run).

Available sources: `CTC` (registry), `ABM`, `CCDI`, `COG`, `MCD`, `MCE`, `MCP`,
`PHARM`, `RO`. Add `--value-mode code` to use raw code notations instead of labels.

## End-to-end demo

`examples/demo_ctc.py` runs the whole story in one pass — load metadata, generate,
show the incoherence of naive sampling, apply rules, show it fixed, report fidelity
and privacy, and export:

```bash
python examples/demo_ctc.py --metadata nccr_instances.ttl -n 20000
```

## Python API

```python
from synthpediatric import generate, marginal_fidelity, overall_score
from synthpediatric.constraints import RuleSet
from synthpediatric.nccr_rdf import load_graph, build_dictionary

graph = load_graph(["nccr_instances.ttl"])          # or default: the published URL
d = build_dictionary(graph, "CTC")                   # a DataDictionary for one source

rules = RuleSet.from_json("examples/ctc_consistency_rules.json")
result = generate(d, n=20000, rng=42, ruleset=rules)

print(result.data.head())
print(result.repairs)                                # per-rule repair counts
print(overall_score(marginal_fidelity(d, result.data)))
```

## Consistency rules format

Rules are declarative JSON. The `allowed_values` rule says: when `trigger_col`
holds one of `trigger_values`, `target_col` must be one of `allowed_values`
(violations are repaired by resampling). See `examples/ctc_consistency_rules.json`.

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

## Offline / custom dictionaries (JSON)

You can also drive the generator from a plain JSON marginals file instead of the
NCCR RDF — useful for tests or custom sources. Pass a `.json` path anywhere a
dictionary is expected (no `--source` needed):

```bash
synthpediatric generate examples/nccr_ctc_dictionary.json -n 5000 --evaluate
```

```json
{
  "name": "NCCR CTC (example)",
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

## Privacy posture

- **Metadata-only generation** (the default here): derived solely from published
  aggregate frequencies, no individual records — privacy-safe by construction.
- **Joint-calibrated generation** (next phase, when correlations are learned from
  an individual-level proxy): outputs are derived from disclosure-controlled inputs
  and must pass the privacy evaluation suite (nearest-neighbor distance, membership
  inference) before any public release.

## License

Apache-2.0. See [LICENSE](LICENSE). Synthetic output contains **no real patient
data**; the tool reads only published aggregate metadata.
