# Changelog

## 0.1.0

First public code release. This release contains code, documentation and example configs only. It ships no data files.

### Generation

- Config-driven recipe runner and `run` command for reproducible generation, with YAML configs, a rule registry, profiles and up-front config validation.
- Input ingestion from frequency tables, cohort filters and cross-tab joints, with full-coverage metadata loading (uniform fallback and a conformance and coverage report).
- Nine NCCR sources generated as standalone tables, with a dropped/invented report, value modes and a source policy.
- Linked generation of all nine NCCR sources on `nccrId`, so patient-level keys agree across tables.
- Conditional rule: age and sex given a grouping variable, using exact sequential sampling and keeping derived age variables consistent.
- Sex-by-ICCC target for the all-NCCR 0-19 configs, plus a linked all-NCCR 0-19 example config at 10 percent.
- Null handling: repairs use the variable's own not-applicable code from the metadata (or NULL when none exists), and a null-code map with a not-applicable fraction.
- Optional zip output (`outputs.archive: zip`, `run --archive`), with the data CSV as the only entry in the zip.
- Derived age and ICCC variables are consistent in conditional cohorts.

### Validation and evaluation

- Draft clinical consistency battery: rules, output checks and a verification worksheet.
- Core validation toolkit: discriminator AUC, fidelity, replicate envelope and the `validate` command.
- Live `validate:` block in `run`, plus the privacy tier (identifiability, nearest-neighbour ratio, attribute inference, membership).
- `synthpediatric measure`: disclosure-controlled aggregate export for use inside CGC.
- `cgc/` folder with an install guide, measure templates and a quick start, and an R heat map script for CGC evaluation.

### Fixes

- CI: the legacy golden cohort is compared per column with a float tolerance.

### Known limits

- Code columns that have no value set are written blank. The claims and pharmacy tables are structural only.
- Variables without a target are drawn from all-age dictionary marginals, independently of tumor type.
- Rows per patient follow a Poisson-like distribution.
- The privacy metrics have not yet been run against real data.
