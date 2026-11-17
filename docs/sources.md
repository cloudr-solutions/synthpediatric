# The nine NCCR sources, one table each

synthpediatric generates each NCCR datasource as its own **unlinked, single-source table**.

> **Rows cannot be joined across sources.** The published metadata has no participant key
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
