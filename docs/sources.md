# The nine NCCR sources, one table each

synthpediatric generates each NCCR datasource as its own **unlinked, single-source table**
by default. A config with a `linked:` block generates all nine sources of one cohort, joined
on `nccrId` (see [Linked runs](#linked-runs) below).

> **Without a `linked:` block, rows cannot be joined across sources.** The published metadata
> has no participant key
> (`dataRequestPatientId` is not a variable in `nccr_instances.ttl`), so nothing ties a row
> of one table to a row of another, and the sources have different units of record (about
> 1 row per patient for CTC and ABM, about 190 to 220 rows per covered patient for MCD and
> MCP). The manifest of every run says this (`table_type`, `source`, `linkage`) and so does
> the CLI summary line. Do not join these tables on a row number or an invented id.

How a run treats the variables of a source is described in
[config-and-rules.md](config-and-rules.md) ("Dropped and invented variables" and "Source
policy"). In short: a variable with **no value set** in the metadata is *dropped* (there is
nothing to sample); a variable with a value set but **no published count** is *invented*
(uniform fallback), and is blanked by default for MCE only.

## What the numbers below are

They come from one run per source on the published metadata: `nccr_instances.ttl` from
`NCCR-DCCPS/nccr-metadata` main (the file that has CTC 1,614,685 records), `n: 2000`,
`seed: 1`, `profile: marginals_only`, default `source_policy`. `Mean TVD` is the
`overall_tv_distance` of the manifest: the mean total variation distance over columns with
published counts, so invented columns are not in it. The opt-in test
`SYNTHPEDIATRIC_NETWORK_TESTS=1 pytest tests/test_nine_sources.py -k real_metadata` repeats
the run on the live metadata and prints one summary line per source. The offline smoke test
(`tests/test_nine_sources.py`, fixture `tests/data/nine_sources.ttl`) runs in CI.

| Source | Metadata records | Published columns | Dropped | Invented | Mean TVD | Policy default |
|---|---|---|---|---|---|---|
| CTC | 1,614,685 | 76 | 33 | 0 | 0.0129 | survival allowed |
| ABM | 1,614,685 | 4 | 1 | 0 | 0.0134 | survival refused |
| CCDI | 69,716 | 1 | 2 | 0 | 0.0367 | survival refused |
| COG | 1,483,916 | 7 | 0 | 0 | 0.0029 | survival refused |
| MCD | 56,660,564 | 2 | 1 | 0 | 0.0291 | survival refused |
| MCE | 1,483,916 | 2 | 2 | 359 (blanked) | 0.0015 | `no_frequency: nullify`, survival refused |
| MCP | 65,745,499 | 2 | 6 | 0 | 0.0281 | survival refused |
| PHARM | 13,017,829 | 3 | 13 | 0 | 0.0245 | `medicationDispenseDuration` in `code` mode, survival refused |
| RO | 5,060 | 9 | 4 | 1 (uniform) | 0.0190 | survival refused |

Before invented columns were left out of the score, the MCE run reported 0.0127 and the RO
run 0.0186, because the uniform columns were scored against themselves. MCE with
`no_frequency: uniform` has 359 invented columns of 361: 99% of that table would be noise.

## Known issues that apply to every source (not fixed here)

- **Subpopulation-only variables (resolved).** A variable whose published counts cover only
  part of the records (CTC has 17 below 50%, such as the Gleason and PSA fields) used to
  get a value in every row, because the counts were normalised to 1. The not-applicable
  fraction now gives the uncovered share of rows the variable's own not-applicable code, or
  a blank when it has none. It is on by default for the NCCR sources and recorded in the
  manifest as `na_fraction`. See [null-codes.md](null-codes.md). The `generate` command
  does not apply it (only `run` and recipes do).
- **Suppressed cells are never sampled.** A value without a count (a cell under 16
  records, or a header placeholder such as `Exact grays`) gets weight 0 inside a counted
  variable. Rare values therefore never appear (RO `radiation_anatomic_site`: 231 values,
  26 with counts). `build_dictionary` has a `suppressed_fill` argument that no CLI option
  or config key exposes.
- **Binned variables are text.** Month, dose and count variables are bins such as
  `10 to 12` or `> 100.0`. `max` / `min` cohort filters fail on them; use `equals`.
- **Columns are independent.** Each column is drawn on its own from its marginal. Without
  consistency rules, values can disagree within a row.
- **Sentinel labels are ordinary categories**: `Missing`, `Unknown`,
  `No Data Available ...` are sampled at their published frequency. They are now classified
  (not applicable, unknown, no data, not performed) in the null-code map, see
  [null-codes.md](null-codes.md); the classification is used to pick the not-applicable fill,
  and does not change how the counted values are sampled.
- **Size.** Nothing is chunked. MCE at 100,000 rows needs about 2 GB of memory and 31 s,
  mostly to write the 361 columns; the claims sources at their real size (56 to 66 million
  rows) are out of reach.

## CTC: Consolidated Tumor Case

One row per tumor (about 1.09 per patient). The only person-level table, and the only one
where survival is allowed.

- **Generated (76):** the 68 categorical and 8 binned variables that have a value set, for
  example `ageRecode19Groups`, `behaviorICDO3Public`, `daysToRxRecode`, `erRecode`.
- **Dropped (33).** 32 have `no_value_set`: stage and schema fields (`csExtension`,
  `derivedAjcc7*`, `eod*`, `schemaId`), `histologicTypeIcdO3`, `primarySite`,
  `tumorRecordNumber`, `tumorOrder`, `yearOfDiagnosis`, `survMosActiveFollowup`,
  `survMosPresumedAlive`, `gradeClinical` and the other grade fields. 1 is
  `too_few_values`: `scope9802Public`.
- **Caveats.** `scope9802Public` has 8 codes that all carry the label `* 0-9`, so the 8
  codes merge into one category and the variable is skipped; reading it in `code` mode
  (`value_modes: {scope9802Public: code}`) keeps it. That is a labelling defect in the
  metadata, not fixed here. Year of diagnosis is not generated, so there are no dates.
  Existing CTC configs give the same cohort as before (the legacy golden test is
  unchanged).

## ABM: Area-Based Measures

One row per tumor, with area measures for the census tract at diagnosis. Shares
`tumorRecordNumber` with CTC in the registry, but that id is not published.

- **Generated (4):** `persistentPoverty`, `rucaC`, `uricA`, `yostUSBasedQuintile`.
- **Dropped (1):** `tumorRecordNumber` (`no_value_set`).
- **Caveats.** The four columns are numeric-typed but hold labels such as `Urban`,
  `Rural`, `Missing`. `No Data Available for Variable for Year of Diagnosis` is 31% of
  `rucaC` records because it depends on the diagnosis year, which is not generated, so the
  pattern is reproduced as a share but not explained.

## CCDI: CCDI Mappings

One row per mapping of a patient to an external resource.

- **Generated (1):** `resourceName` (74 values).
- **Dropped (2):** `resourceParticipantId` and `resourceIntersection` (`no_value_set`).
- **Caveats.** A one-column table of resource names. It has the highest TVD of the nine
  (0.0367). 6 of its 74 values have no published count and are never sampled, and 2000
  rows spread over 68 sampled values leave a larger sampling error than for the other
  sources.

## COG: Children's Oncology Group

One row per cohort patient (records equal the CTC patient count); 42,031 have a confirmed
study enrollment.

- **Generated (7):** `reportedCOGEnrollment` and six trial and study count bins
  (`registryStudyCount`, `supportiveStudyCount`, `therapeuticFrontLineTrialCount`, ...).
- **Dropped (0).**
- **Caveats.** The best covered source (TVD 0.0029). The columns are independent, so a
  row can say "patient not found at linkage" next to a nonzero trial count. Placeholder
  values such as `0-999 trials` have no count and are never sampled.

## MCD: Medical Claims Diagnosis

One row per claim diagnosis record (about 189 rows per covered patient in the real data).

- **Generated (2):** `claimDiagnosisCodeSequence` (32 values) and
  `monthsFromIndexDxToDiagnosisCode` (33 bins).
- **Dropped (1):** `claimDiagnosisCode` (`no_value_set`). No ICD diagnosis code is ever
  generated, so the table has a sequence number and a month bin and nothing clinical.
- **Caveats.** Survival is refused. Rows per patient is not published, so a 2000-row table
  has no notion of rows of the same patient.

## MCE: Medical Claims Enrollment

One row per cohort patient in a wide layout: monthly enrollment status before and after
the index diagnosis. 303,620 of 1,483,916 patients have confirmed enrollment.

- **Generated (2 with counts):** `enrollIndexDxMonth` and `reportedInsuranceEnrollment`.
- **Invented (359):** every `enrollMonthPostIndexDxN` and `enrollMonthPriorIndexDxN`
  column has a value set (3 or 4 statuses, including "Not Applicable-Patient Reported as
  Deceased") and no count. **By default they are blanked** (`no_frequency: nullify`): the
  table keeps its 361 columns and 359 are empty. `no_frequency: uniform` fills them with
  random statuses (the sequence of months is linked, e.g. death makes all later months
  "deceased", so independent draws are meaningless); `suppress` leaves a 2-column table.
- **Dropped (2):** `patientsEnrolledPostIndexCancer` and `patientsEnrolledPriorToIdxCancer`
  (`no_value_set`, they are report counts).
- **Caveats.** The 0.0015 TVD is for the 2 published columns only. A 361-column table is
  heavy to write (see the size note above).

## MCP: Medical Claims Procedure

One row per claim procedure record (about 219 rows per covered patient in the real data).

- **Generated (2):** `claimProcedureCodeSequence` (32) and
  `monthsFromIndexDxToProcedureCode` (33).
- **Dropped (6):** `claimProcedureCode`, `claimProcedureCodeMod1` to `Mod4` and
  `claimProcedureCodeText` (`no_value_set`). No procedure code is generated.
- **Caveats.** Same as MCD: two columns, no clinical content.

## PHARM: Pharmacy Claims

One row per dispensing (prescription fill), about 52 per covered patient in the real data.

- **Generated (3):** `canmedDrugCategory` (8), `medicationDispenseDuration` (92) and
  `monthsFromIndexDxtoDispense` (33).
- **Dropped (13):** NDC9 and NDC11 (`medicationRequestNdc9`, `medicationRequestNdc11`),
  RxNorm fields (`rxnormRxcui`, `rxnormConceptName`, ...), CanMED class and name fields and
  `medicationDispenseQuantity` (all `no_value_set`). No drug is named.
- **Policy: `medicationDispenseDuration` is read in `code` mode.** In the metadata the
  label of each value is its record count and the day value is its code. In `label` mode
  the column held numbers such as 212722 and 288868 as "days" (90 of 92 values); in `code`
  mode the 2000-row run gives 30 (1,100 rows), 28 (165), 10 (114), 5 (99), 7 (75). Set
  `value_modes: {medicationDispenseDuration: label}` to get the old behaviour back.
  A check of a PHARM file against the dictionary must load it with the same modes (the run's
  `dictionary.json` and `manifest.json` `source_policy.value_modes` say which), or the day
  values look out of vocabulary: against a default `label` dictionary 18,339 of 20,000 rows
  are flagged, against the run's own dictionary none.
- **Caveats.** Three columns and no drug.

## RO: Radiation Oncology

One row per radiation record or series. The smallest source (5,060 records, 2,650 patients).

- **Generated (9 with counts):** treatment start and end month bins, prescribed and
  delivered dose and fraction bins, `radiation_anatomic_site` (231 values),
  `radiation_energy_type`, `radiation_therapy_type`.
- **Invented (1):** `sequenceId` (descriptive values with no counts), filled uniformly
  because the default for RO is `uniform`.
- **Dropped (4):** `recordId` (`too_few_values`: one value, a header), and the free-text
  `untransformed_anatomic_site`, `untransformed_rad_energy_type` and
  `untransformed_rad_therapy_type` (`no_value_set`).
- **Caveats.** Dates and doses are incoherent within a row: in the run, treatment end
  `7 to 9` months next to start `10 to 12`, and a prescribed dose `> 100.0` next to a
  delivered dose `30.001 to 40.0`. Multi-valued fields (anatomic site, therapy type) are
  published as one label with ` | ` between the parts and are treated as one category. Of the
  324 permissible values, 218 have no count and are never sampled. The CTC consistency rules
  file fails on RO (it names `sex`); RO needs its own rules.

## Linked runs

A config with a `linked:` block (see `examples/linked/` and
[config-and-rules.md](config-and-rules.md), "Linked runs") generates all nine sources of one
cohort. CTC is the parent. The other eight are linked to it, so a join across the nine CSVs
works. The links are generated, not observed: no real patient is behind any key.

| Source | Role | Key columns (first) | Rows |
|---|---|---|---|
| CTC | parent | `nccrId`, `tumorRecordNumber` | `n` (tumors) |
| ABM | child | `nccrId`, `tumorRecordNumber` | `n`, the same pairs as CTC row for row |
| COG, MCE | child | `nccrId` | `coverage` x patients x `rows_per_patient` |
| CCDI, RO, PHARM, MCD, MCP | child | `nccrId` | same |

- **`nccrId`**: the primary key in the NCCR dictionaries (RAW-JSON, `Dictionary_Elements[0]`,
  string, length 64). One per patient, a seeded random 64-character hex string.
- **`tumorRecordNumber`**: string, length 2 (CTC and ABM only). The 2-character zero-padded
  rank of the tumor within its patient: `01`, `02`, and so on. `(nccrId, tumorRecordNumber)` is
  unique in CTC, and ABM carries the same pairs.
- **Patients**: `round(n / tumors_per_patient)`. Every patient has one tumor and the other
  tumors are assigned uniformly (default `tumors_per_patient` 1.0881 = 1,614,685 CTC records
  over 1,483,916 patients).
- **Children**: `coverage` is the share of patients that have rows, `rows_per_patient` is the
  mean over the patients that have rows. Defaults come from the record and patient counts of
  `nccr-metadata/erd.dbml` (packaged as `nccr_linkage_defaults.json`).

| Child | Default coverage | Default rows per patient |
|---|---|---|
| COG, MCE | 1 | 1 |
| CCDI | 0.011088 | 4.2371 |
| RO | 0.001786 | 1.9094 |
| PHARM | 0.16788 | 52.2553 |
| MCD | 0.202428 | 188.6173 |
| MCP | 0.202473 | 218.8203 |

At `n: 2393` (2,199 patients) MCD and MCP get about 84,000 rows each and PHARM about 19,000.
Rows are spread over the covered patients with a uniform multinomial, so the counts per
patient are Poisson-like. Real claims counts are heavier tailed. Totals are exact.

### Columns

Every table has the full dictionary column set of its source: the RAW-JSON names in RAW-JSON
order, then the columns only the RDF metadata (`nccr_instances.ttl`) has, sorted. `nccrId` is
first, and `tumorRecordNumber` second in CTC and ABM.

| Source | RAW-JSON | RDF | Only RAW-JSON | Only RDF | Linked table columns |
|---|---|---|---|---|---|
| CTC | 114 | 109 | `nccrId`, `referenceId1` to `referenceId4` | none | 114 |
| ABM | 6 | 5 | `nccrId` | none | 6 |
| CCDI | 3 | 3 | `nccrId` | `resourceIntersection` | 4 |
| COG | 8 | 7 | `nccrId` | none | 8 |
| MCD | 4 | 3 | `nccrId` | none | 4 |
| MCE | 362 | 363 | `nccrId` | `patientsEnrolledPostIndexCancer`, `patientsEnrolledPriorToIdxCancer` | 364 |
| MCP | 9 | 8 | `nccrId` | none | 9 |
| PHARM | 17 | 16 | `nccrId` | none | 17 |
| RO | 15 | 14 | `nccrId` | none | 15 |

A variable with no value set (or with too few values) cannot be sampled, so its column is
written **blank**, and the run does not invent a value. Codes, drug names, NDC and RxNorm
values, ICD codes and free text would look real if made up. The manifest of the table lists
each blank column under `linked.blank_columns` with a `reason` (`no_value_set`,
`too_few_values`, `not_in_rdf_metadata`, `no_frequency_nullified`), its `semantic_type` and
its `field_length` from the dictionary, so "not generated" is distinguishable from "missing".
The one exception is RO `recordId`, which the dictionary defines as a unique 8-digit number
per record: it is generated, drawn without replacement.

### Sequence variables

CTC `tumorOrder`, `numberOfPrimaries`, `sequenceNumberCentral` and `recordNumberRecode` are
set from the patient grouping after the parent run, so they agree with the keys. For a
patient with k tumors and a tumor of rank j:

| Variable | Value |
|---|---|
| `tumorOrder` | `j` (no value set in the metadata) |
| `numberOfPrimaries` | `k`, or the largest numeric code in the value set that is at most `k` |
| `recordNumberRecode` | `01` for j = 1, else `02` ("Record number 02 through 98") |
| `sequenceNumberCentral` | `00` when k = 1; otherwise `01` for j = 1 and `02` for j >= 2 |

The not-applicable fraction leaves these four variables alone (they are protected). A
constraints file that mentions them is not run again after they are set.

### Limits

- The tables are consistent on keys and on the four sequence variables only. Nothing makes
  the claims, radiation or pharmacy rows clinically coherent with the tumor of their patient
  (for example, a diagnosis code that fits the cancer). Each table is still sampled from its
  own published marginals.
- Sex and birth cohort are not made equal between the tumors of one patient.
- Diagnosis-date order across tumors cannot be checked: `yearOfDiagnosis` has no value set.
- Rows per patient are Poisson-like, not heavy tailed.

## Design notes (linked runs)

- **RAW-JSON and RDF.** RAW-JSON is the upstream dictionary (it has the keys and
  `referenceId1` to `referenceId4`). The RDF metadata is where the value sets live and it has
  three variables RAW-JSON lacks, so the full column set is the union of both.
- **No value set.** Blank columns, not invented values (see Columns).
- **Sequence variables.** Consistent with the keys (see Sequence variables).
- **Conditional rule, `source_policy`, `na_fraction`, null repair.** The linked step runs after
  the parent run, so the `conditional`, `cohort` and `constraints` rules act on the `n` tumor
  rows as before. `n` counts tumors. The children use the default policy of their own source,
  with `profile: marginals_only`. Null repair and `na_fraction` run inside each per-source run.
- **Configs without `linked:`** take the old code path: same canonical config, same hash,
  same manifest (`unlinked_single_source`).
