# Synthetic datasets, generation 2026-11-17

First shared generation of synthetic NCCR datasets. All data are synthetic. Generated on 2026-11-17 (UTC 15:01 to 15:02), one run at a time.

## Code version

Generator: CloudR `synthpediatric`, branch `main`, commit `94658ca`, git tree `75c1ebf68314236d66bddd4bd03a2f4686efc1cf` (version string 0.0.1). The working tree was clean before and after the runs; nothing in the repository was changed. Python 3.12.13 from the repository's own venv.

Metadata: the local snapshot `nccr_instances.ttl` (Jamboree-Handoff/demo/artifacts). It is the file that lists 1,614,685 CTC records.

## Folder layout

| Folder | What it holds |
|---|---|
| `MANIFEST.md` | Rows, columns, zip size, CSV size and SHA-256 of the CSV inside, for each of the 12 zips |
| `configs/<dataset>/config.yaml` | The config that produced the dataset |
| `CHECKS.md` | All verification tables |

The 12 zips (one CSV each) are not stored in git. They are attached to the GitHub Release `synthdata-2026-11-17`. `CHECKS.md` refers to run files (`run/`, `_scratch/verify.py`, per-dataset reports) that were kept with the generation, not in this repository.

## Datasets

The rule for every dataset: follow the data dictionary (permissible values and published frequencies) plus only what its config states. No consistency rules file, no extra rules, no mixing of sources. Each dataset is a single-source table; rows cannot be joined across datasets.

### A. one_registry (CTC, ages 0-19, one state registry)

Real aggregate numbers from one state registry (state not named), childhood cancers ages 0-19, diagnosis years 2014-2023: age and sex by ICCC major group, from an aggregate table in CGC, cleared as synthesis inputs by the team lead on 2026-11-16. Config is the committed `examples/conditional/one_registry_age_sex_by_iccc.yaml`, with only the metadata path, outputs and n changed. Profile `standard`, seed 2026.

- `one_registry_n23930.zip`: n = 23,930 (10 times the 2,393 cases in the table).
- `one_registry_n2393.zip`: n = 2,393 (real size).

What the config sets: the ICCC group mix (the table's Number column), the age distribution within each group (four bands: 0-4, 5-9, 10-14, 15-19; the 0-4 band is split into 00 years and 01-04 years by the published ratio), and the male share within each group. Two ICCC groups the table does not list (neuroblastoma and 'Not classified') are excluded. The other age variables and the ICCC subgroup variables are derived from those.

### B. nccr_0_19 (CTC, ages 0-19, all NCCR)

`nccr_0_19_n261056.zip`: n = 261,056. Config is the committed `examples/conditional/nccr_age_by_iccc_0_19.yaml`, with only the metadata path and outputs changed. It sets the mix of 13 ICCC groups and the age bands within each group. It has no sex rule. Profile `standard`, seed 2026.

### C. Nine sources at 10% of the published record count

Profile `marginals_only`, default source policies (which turn the not-applicable fraction on for NCCR metadata sources), no consistency rules file. n = round(0.10 x published record count) from `synthpediatric sources`. Seed = 2026 plus the position of the source in the order RO, CCDI, COG, MCE, ABM, CTC, PHARM, MCD, MCP: RO 2026, CCDI 2027, COG 2028, MCE 2029, ABM 2030, CTC 2031, PHARM 2032, MCD 2033, MCP 2034.

| Zip | Source | Published records | n | Columns |
|---|---|---|---|---|
| ro_10pct | Radiation Oncology | 5,060 | 506 | 10 |
| ccdi_10pct | CCDI Mappings | 69,716 | 6,972 | 1 |
| cog_10pct | Children's Oncology Group | 1,483,916 | 148,392 | 7 |
| mce_10pct | Medical Claims Enrollment | 1,483,916 | 148,392 | 361 |
| abm_10pct | Area-Based Measures | 1,614,685 | 161,468 | 4 |
| ctc_10pct | Consolidated Tumor Case | 1,614,685 | 161,468 | 76 |
| pharm_10pct | Pharmacy Claims | 13,017,829 | 1,301,783 | 3 |
| mcd_10pct | Medical Claims Diagnosis | 56,660,564 | 5,666,056 | 2 |
| mcp_10pct | Medical Claims Procedure | 65,745,499 | 6,574,550 | 2 |

Columns are independent of each other (marginals only). CTC, for example, has no link between ICCC group and age.

## How to regenerate

From any machine with the repository at commit 94658ca and its venv (extras `rdf`, `yaml`, `validate`):

```
cd <repo>
./.venv/bin/synthpediatric run "<this folder>/configs/<dataset>/config.yaml"
```

The `metadata` and `outputs.dir` entries in each config are absolute paths of the generating laptop; change them to your paths first. The same seed, config and commit give the same CSV (the SHA-256 in `MANIFEST.md` is the check). `outputs.archive_name` sets the zip and CSV name.

## What is and is not captured

Captured: the published frequency of each variable, the permissible values of each variable (no out-of-vocabulary values in any dataset), the not-applicable fraction of variables where the published counts leave a large uncovered share (for example the Gleason and PSA columns of CTC are about 99.9% not applicable or blank), and, for A and B, the cross of ICCC group with age (and with sex in A) as given by the tables.

Not captured: relations between columns beyond those the A and B configs state. In particular, in all datasets the records are not real persons, the 85p and 90p single-year age variables are drawn separately (they disagree for about 73% of the conditional-cohort records, see `CHECKS.md`), the two ICCC subgroup variables are each consistent with ICCC major group but not with each other, and the sources cannot be joined. PHARM's medicationDispenseDuration and MCE's 359 enrollment-month columns are discussed in `CHECKS.md`.

## Known findings (from CHECKS.md)

None of these was fixed in this generation.

- Privacy status: privacy metrics have not yet been run on real CGC data. Treat the files as synthetic test data until they have been.
- ageRecodeSingle85p and ageRecodeSingle90p disagree in 73.5% of records in `one_registry_n23930`, 71.8% in `one_registry_n2393` and 73.4% in `nccr_0_19_n261056`. Both stay inside the band of ageRecode19Groups.
- iccc2017Recode and iccc2017ExtendedRecode are each consistent with icccMajor but not with each other (subgroup letters differ in 56% to 60% of records in the three conditional cohorts).
- `nccr_0_19_n261056`: the age variables differ from the all-ages published frequencies by design. One age cell is above 3 standard errors (Retinoblastoma, 10-14 years).
- `pharm_10pct`: the dictionary strings of medicationDispenseDuration look like record counts, so a check against them flags 1,193,699 values, while the generator's own conformance report gives 0. The generated values (30, 28, 10, 5, 7) look like real durations. The metadata needs a look by its owner.
- combinedSsPubDetailed (CTC-based sets): about 32% not applicable against a manifest target of 24.5%.
- `mce_10pct`: 359 of 361 columns are entirely blank (enrollment-month columns with no published values).
- `ro_10pct`: one invented column is filled uniformly.
- For the CTC-based sets, the recomputed total variation distance differs from fidelity.csv by more than 0.01 in 3 to 4 columns. The cause was not traced.

## Notes for users

- CTC (all CTC-based datasets: A, B and ctc_10pct): four value labels contain line breaks inside quoted cells. Read the CSV with a CSV reader (pandas, R `read.csv`/readr, Python `csv`); do not split the file on lines.
- Blank cells in some columns are the not-applicable marker where the dictionary has no null label.
- The privacy metrics (the disclosure and re-identification checks of `validate`) have not yet been run against the real data in CGC. Treat these files as synthetic test data until that has been done.
