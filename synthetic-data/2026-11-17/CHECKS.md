# CHECKS, generation 2026-11-17

All numbers are computed from the generated zips and the run manifests by `_scratch/verify.py` (kept for reproduction). One section per dataset follows the summary. Per-dataset copies are in each dataset folder.

## Summary

| Dataset | n | rows = n | zip entries | testzip | out-of-vocabulary values (own / report) | NA variables applied | published-column TVD (manifest) | wall s | max RSS MiB |
|---|---|---|---|---|---|---|---|---|---|
| one_registry_n23930 | 23,930 | yes | 1 | ok | 0 / 0 | 32 | 0.0775 | 5.2 | 210 |
| one_registry_n2393 | 2,393 | yes | 1 | ok | 0 / 0 | 32 | 0.1013 | 4.3 | 183 |
| nccr_0_19_n261056 | 261,056 | yes | 1 | ok | 0 / 0 | 32 | 0.0559 | 23.7 | 478 |
| ro_10pct | 506 | yes | 1 | ok | 0 / 0 | 0 | 0.0454 | 3.2 | 173 |
| ccdi_10pct | 6,972 | yes | 1 | ok | 0 / 0 | 0 | 0.0238 | 3.3 | 174 |
| cog_10pct | 148,392 | yes | 1 | ok | 0 / 0 | 0 | 0.0005 | 4.1 | 198 |
| mce_10pct | 148,392 | yes | 1 | ok | 0 / 0 | 0 | 0.0009 | 9.5 | 1,050 |
| abm_10pct | 161,468 | yes | 1 | ok | 0 / 0 | 0 | 0.0018 | 3.6 | 189 |
| ctc_10pct | 161,468 | yes | 1 | ok | 0 / 0 | 32 | 0.0080 | 16.0 | 402 |
| pharm_10pct | 1,301,783 | yes | 1 | ok | 1193699 / 0 | 1 | 0.0010 | 5.5 | 278 |
| mcd_10pct | 5,666,056 | yes | 1 | ok | 0 / 0 | 0 | 0.0007 | 8.9 | 503 |
| mcp_10pct | 6,574,550 | yes | 1 | ok | 0 / 0 | 0 | 0.0007 | 9.5 | 564 |

## Reading notes (nothing here was fixed; these are observations)

1. pharm_10pct, column medicationDispenseDuration: my own conformance check reports 1,193,699 values outside the dictionary strings, while the run's conformance.csv reports 0. The dictionary categories of this numeric variable are strings such as '19163', '207907', '6733138', which look like record counts (6,733,138 of 13,017,829 is 51.7%, and the value 30 makes up 51.7% of the first 200,000 generated rows). The generated values are plausible dispensing durations (30, 28, 10, 5, 7 days). So my check against the dictionary strings is not meaningful for this column, and the generator's 0 is the number to use. The own-TVD of 1.0 for this column in that dataset has the same cause. The metadata quirk is worth a look by the metadata owner; I did not trace it further.
2. combinedSsPubDetailed (all CTC-based sets): the generated share of the not-applicable code is about 32% against a manifest target of 24.5%. The manifest flags this column as `code_counted: true`, meaning the code also has published counts inside the covered share, so the observed share is the target plus the covered share of that code. I did not trace the arithmetic in the generator. The same flag applies to breslowDepthRecode and lymphVasInvasionPublic, where the gap is under 0.01 points.
3. mce_10pct: 359 of 361 columns are entirely blank. They are the enrollment-month columns that have no published values; the source policy for MCE writes such columns blank (`no_frequency: nullify`). Only enrollIndexDxMonth and reportedInsuranceEnrollment carry values.
4. ro_10pct: one invented column is filled uniformly (frequency source `uniform` in fidelity.csv).
5. Own TVD versus fidelity.csv: I recomputed the total variation distance over rows whose value has a published probability, renormalised on both sides. It matches fidelity.csv to rounding for RO, CCDI, COG, MCE, ABM, MCD and MCP. For the CTC-based sets it differs by more than 0.01 in 3 columns (ctc_10pct) or 4 columns (the three conditional cohorts); I did not identify which method difference causes it and did not trace the generator's calculation. For PHARM see note 1. The manifest figure is the one reported in the summary above.
6. The age columns of the conditional cohorts differ from the published all-ages frequencies by design (ages 0-19 only), so the mean TVD of A and B is higher than that of the unconditional sets.

# Dataset: one_registry_n23930

Source `CTC`, n requested 23,930. Everything below is computed from `one_registry_n23930/run/one_registry_n23930.zip` (one pass over the CSV) and the run's `manifest.json`, `conformance.csv` and `fidelity.csv`.

### 1. Rows, archive, run cost

| Check | Result |
|---|---|
| rows in the CSV | 23,930 (n 23,930): OK |
| columns | 76 |
| zip entries | 1 ['one_registry_n23930.csv']: OK |
| testzip() | None (OK) |
| zip size | 3,068,888 bytes |
| CSV size | 72,569,454 bytes |
| SHA-256 of the CSV inside | 0b992999acc568f9aba1bd9efba5f65b54f729bd75401535d411bf5de25790d9 |
| matches manifest archive.csv_sha256 | yes |
| wall time (CLI, /usr/bin/time -l) | 5.2 s |
| max resident set size | 210 MiB |
| peak memory footprint | 182 MiB |

### 2. Conformance (values outside the dictionary vocabulary)

Columns in the CSV: 76. Columns not in the dictionary: none. Columns with out-of-vocabulary values (own check, blanks excluded): 0. conformance.csv: 0 out-of-vocabulary values in 0 columns.
Columns with blank cells: 17 (blank is how a not-applicable column is written when the dictionary has no null label).

### 3. Not-applicable fraction (manifest na_fraction against the generated data)

Mode `on` (supplied by default), minimum share 0.005. Variables applied: 32, of which written blank: 17. Rows: 23,930.

| Variable | written as | target share | manifest generated share | observed in the CSV | observed - target (points) |
|---|---|---|---|---|---|
| brainMolecularMarkers | code | 97.6141% | 97.6139% | 97.6139% | -0.000 |
| breslowDepthRecode | code, code also has published counts | 95.1686% | 95.1692% | 95.1692% | +0.001 |
| cocAccreditedFlag | code | 74.6822% | 74.6803% | 74.6803% | -0.002 |
| combinedSsPubDetailed | code, code also has published counts | 24.5206% | 24.5215% | 32.2273% | +7.707 |
| esophagusAndEgjTumorEpicenter | blank | 99.9893% | 99.9875% | 99.9875% | -0.002 |
| gleasonPatternClinicalRecode | code | 99.8849% | 99.8830% | 99.8830% | -0.002 |
| gleasonPatternPathologicRecode | code | 99.8795% | 99.8788% | 99.8788% | -0.001 |
| gleasonScoreClinicalRecode | code | 99.8835% | 99.8830% | 99.8830% | -0.001 |
| gleasonScorePathologicRecode | code | 99.8780% | 99.8788% | 99.8788% | +0.001 |
| gleasonTertiaryPattern | code | 99.9212% | 99.9206% | 99.9206% | -0.001 |
| gradeRecodePre2018 | blank | 25.3597% | 25.3615% | 25.3615% | +0.002 |
| ldhPretreatmentLabValue | code | 97.9078% | 97.9064% | 97.9064% | -0.001 |
| lymphVasInvasionPublic | code, code also has published counts | 96.8329% | 96.8324% | 96.8324% | -0.001 |
| microsatelliteInstability | code | 99.0824% | 99.0807% | 99.0807% | -0.002 |
| p16Recode | code | 99.6242% | 99.6239% | 99.6239% | -0.000 |
| pathReportsFlag | blank | 0.9004% | 0.8985% | 0.8985% | -0.002 |
| psaLabValueRecode | blank | 99.9147% | 99.9164% | 99.9164% | +0.002 |
| radiationRecode | blank | 13.4613% | 13.4601% | 13.4601% | -0.001 |
| reasonForNoRadiation | blank | 74.7477% | 74.7472% | 74.7472% | -0.001 |
| reasonForNoSurgery | blank | 3.9428% | 3.9448% | 3.9448% | +0.002 |
| regionalNodesExamined | blank | 2.1989% | 2.1981% | 2.1981% | -0.001 |
| regionalNodesPositive | blank | 2.2090% | 2.2106% | 2.2106% | +0.002 |
| rxSummBrm | blank | 3.7938% | 3.7944% | 3.7944% | +0.001 |
| rxSummHormone | blank | 3.7928% | 3.7944% | 3.7944% | +0.002 |
| rxSummOther | blank | 3.8351% | 3.8362% | 3.8362% | +0.001 |
| rxSummSurgOthRegDis | blank | 21.7224% | 21.7217% | 21.7217% | -0.001 |
| rxSummSurgPrimSite | code | 14.6781% | 14.6761% | 14.6761% | -0.002 |
| rxSummSurgPrimSite2023 | code | 95.5226% | 95.5244% | 95.5244% | +0.002 |
| rxSummSystemicSurSeq | blank | 34.0544% | 34.0535% | 34.0535% | -0.001 |
| rxSummTransplntEndocr | blank | 7.3036% | 7.3046% | 7.3046% | +0.001 |
| scope2003pPublic | blank | 21.7224% | 21.7217% | 21.7217% | -0.001 |
| treatmentStatusPublic | blank | 44.3164% | 44.3168% | 44.3168% | +0.000 |

Variables skipped, by reason: rule_target: 2; below_min_share: 4; suppression_only: 4.

Gleason and PSA columns: share of rows that are not applicable or blank (the manifest code for the column, or blank).

| Column | NA code | blank | NA or blank | rows with a real value |
|---|---|---|---|---|
| gleasonPatternClinicalRecode | 99.883% | 0.000% | 99.883% | 28 |
| gleasonPatternPathologicRecode | 99.879% | 0.000% | 99.879% | 29 |
| gleasonScoreClinicalRecode | 99.883% | 0.000% | 99.883% | 28 |
| gleasonScorePathologicRecode | 99.879% | 0.000% | 99.879% | 29 |
| gleasonTertiaryPattern | 99.921% | 0.000% | 99.921% | 19 |
| psaLabValueRecode | 0.000% | 99.916% | 99.916% | 20 |

### 4. Published-column fidelity

Manifest: published columns 76, invented columns 0, mean total variation distance over published columns 0.0775. Frequency source counts in fidelity.csv: {'published': 76}.

Own recomputation from the CSV against the dictionary probabilities, over the rows whose value has a published probability (both sides renormalised; blank and not-applicable fill rows are outside it): mean TVD 0.1160; largest |own - fidelity.csv| per column 0.9510 (columns where it exceeds 0.01: 4).

| Column (largest TVD in fidelity.csv) | fidelity.csv TVD | own TVD |
|---|---|---|
| ageRecode20Groups | 0.8383 | 0.8383 |
| ageRecodeSingle90p | 0.8383 | 0.8383 |
| ageRecodeSingle85p | 0.8383 | 0.8383 |
| esophagusAndEgjTumorEpicenter | 0.5756 | 0.5756 |
| iccc2017Recode | 0.4350 | 0.4350 |
| icccMajor | 0.4350 | 0.4350 |
| iccc2017ExtendedRecode | 0.4338 | 0.4338 |
| gleasonTertiaryPattern | 0.2046 | 0.2046 |

For the conditional cohorts the age variables are set by the table rules and the cohort filter (ages 0-19), so their distance to the all-ages published frequencies is large by design; the mean above includes them.

### 5. ICCC group mix: target versus generated

z = (generated - expected) / binomial sd at n = 23,930. Target share = group number / sum of the listed groups (2,393).

| Group | table number | target share | generated | generated share | diff (points) | z |
|---|---|---|---|---|---|---|
| Leukemias | 654 | 27.330% | 6491 | 27.125% | -0.205 | -0.71 |
| Lymphomas | 389 | 16.256% | 3880 | 16.214% | -0.042 | -0.18 |
| Brain and CNS | 379 | 15.838% | 3797 | 15.867% | +0.029 | +0.12 |
| Epithelial neoplasms and melanomas | 329 | 13.748% | 3362 | 14.049% | +0.301 | +1.35 |
| Soft tissue sarcomas | 185 | 7.731% | 1895 | 7.919% | +0.188 | +1.09 |
| Bone tumors | 146 | 6.101% | 1440 | 6.018% | -0.084 | -0.54 |
| Germ cell and Gonadal Tumors | 123 | 5.140% | 1176 | 4.914% | -0.226 | -1.58 |
| Renal tumors | 101 | 4.221% | 1035 | 4.325% | +0.104 | +0.80 |
| Hepatic tumors | 45 | 1.880% | 419 | 1.751% | -0.130 | -1.48 |
| Retinoblastoma | 31 | 1.295% | 323 | 1.350% | +0.054 | +0.74 |
| Other and unspecified malignant neoplasms | 11 | 0.460% | 112 | 0.468% | +0.008 | +0.19 |

ICCC groups generated that are not in the table: none. Largest |z| = 1.58; |z| > 3: 0; |z| > 2: 0 of 11.

### 6. Age bands within each ICCC group: target versus generated

Cell = generated share (target share) z. Target = the config row normalized to 100%. The bands 0-4 combine '00 years' and '01-04 years'.

| Group | n | 0-4 | 5-9 | 10-14 | 15-19 |
|---|---|---|---|---|---|
| Leukemias | 6491 | 42.6% (42.9%) z=-0.42 | 21.8% (21.8%) z=+0.06 | 17.8% (17.2%) z=+1.37 | 17.7% (18.1%) z=-0.87 |
| Lymphomas | 3880 | 12.9% (12.3%) z=+1.06 | 15.8% (15.1%) z=+1.17 | 24.8% (24.7%) z=+0.17 | 46.5% (47.9%) z=-1.69 |
| Brain and CNS | 3797 | 32.6% (32.9%) z=-0.39 | 26.1% (26.9%) z=-1.08 | 22.3% (21.9%) z=+0.65 | 18.9% (18.3%) z=+1.01 |
| Epithelial neoplasms and melanomas | 3362 | 3.4% (2.9%) z=+1.59 | 5.2% (5.3%) z=-0.32 | 21.1% (21.2%) z=-0.16 | 70.4% (70.6%) z=-0.29 |
| Soft tissue sarcomas | 1895 | 25.1% (25.1%) z=+0.02 | 18.6% (16.9%) z=+2.01 | 22.2% (24.6%) z=-2.41 | 34.0% (33.4%) z=+0.59 |
| Bone tumors | 1440 | 4.2% (4.2%) z=-0.06 | 14.8% (15.9%) z=-1.13 | 39.4% (38.8%) z=+0.53 | 41.6% (41.2%) z=+0.34 |
| Germ cell and Gonadal Tumors | 1176 | 13.1% (14.0%) z=-0.89 | 6.0% (5.5%) z=+0.81 | 15.9% (16.8%) z=-0.82 | 65.0% (63.7%) z=+0.90 |
| Renal tumors | 1035 | 67.4% (67.2%) z=+0.14 | 20.5% (20.6%) z=-0.08 | 5.7% (5.4%) z=+0.44 | 6.4% (6.8%) z=-0.53 |
| Hepatic tumors | 419 | 73.0% (70.3%) z=+1.22 | 7.2% (7.7%) z=-0.41 | 7.6% (8.5%) z=-0.63 | 12.2% (13.5%) z=-0.80 |
| Retinoblastoma | 323 | 95.7% (95.8%) z=-0.12 | 3.1% (3.4%) z=-0.30 | 0.3% (0.6%) z=-0.67 | 0.9% (0.2%) z=+2.93 |
| Other and unspecified malignant neoplasms | 112 | 38.4% (37.8%) z=+0.13 | 9.8% (9.1%) z=+0.27 | 8.0% (15.3%) z=-2.14 | 43.8% (37.8%) z=+1.30 |

Cells: 44. Largest |z| = 2.93. |z| > 3: 0. |z| > 2: 4 (about 2.0 expected by chance). Sum of z squared = 47.2 (about 44 if matched).

Split inside 0-4: '00 years' 1,526 : '01-04 years' 5,138 (22.90% under one year).

### 7. Male share per ICCC group

Target = Male / (Male + Female) from the config counts.

| Group | n | target male share | generated male share | z |
|---|---|---|---|---|
| Leukemias | 6491 | 54.84% | 55.26% | +0.68 |
| Lymphomas | 3880 | 32.42% | 31.39% | -1.36 |
| Brain and CNS | 3797 | 59.02% | 60.23% | +1.52 |
| Epithelial neoplasms and melanomas | 3362 | 59.10% | 59.88% | +0.91 |
| Soft tissue sarcomas | 1895 | 57.84% | 57.41% | -0.37 |
| Bone tumors | 1440 | 37.62% | 38.06% | +0.34 |
| Germ cell and Gonadal Tumors | 1176 | 58.22% | 56.63% | -1.10 |
| Renal tumors | 1035 | 52.03% | 51.88% | -0.10 |
| Hepatic tumors | 419 | 54.55% | 54.65% | +0.04 |
| Retinoblastoma | 323 | 54.84% | 58.20% | +1.22 |
| Other and unspecified malignant neoplasms | 112 | 45.45% | 57.14% | +2.48 |

Largest |z| = 2.48; |z| > 3: 0; |z| > 2: 1. Values of sex generated: ['Female', 'Male'].

### 8. Age variables: agreement with ageRecode19Groups at band level

| Variable | records whose band does not overlap the 19-group band | records with an unparsable label |
|---|---|---|
| ageRecode20Groups | 0 | 0 |
| ageRecodeSingle85p | 0 | 0 |
| ageRecodeSingle90p | 0 | 0 |

### 9. Re-check 1: ageRecodeSingle85p versus ageRecodeSingle90p

Records where the two single-year labels differ: 17,590 of 23,930 (73.51%). Every record is aged 0-19, so both variables should give the same single year (the 85+ and 90+ top groups cannot apply).
Mean absolute difference in years among the disagreeing records: 1.91; largest 4. Records of either variable outside the 19-group band (section 8): 0 and 0.

| 19-group band | records | disagree | share |
|---|---|---|---|
| 00 years | 1526 | 0 | 0.00% |
| 01-04 years | 5138 | 3828 | 74.50% |
| 05-09 years | 4095 | 3276 | 80.00% |
| 10-14 years | 4955 | 3957 | 79.86% |
| 15-19 years | 8216 | 6529 | 79.47% |

The full cross of the two variables is in `crosstab_single85p_by_single90p.csv`.

### 10. Re-check 2: ICCC subgroup variables against icccMajor

#### icccMajor by iccc2017Recode

Distinct (group, subgroup) pairs: 46. Subgroup labels: 46. Impossible pairs (the subgroup's Roman numeral differs from the group's): 0, covering 0 of 23,930 records (0.00%).

| icccMajor | records | distinct subgroup labels | records with a consistent subgroup |
|---|---|---|---|
| I. Leukemias, Myeloproliferative And Myelodysplastic Disease | 6491 | 5 | 6491 |
| II. Lymphomas and reticuloendothelial neoplasms | 3880 | 5 | 3880 |
| III. CNS and Miscellaneous Intracranial and Intraspinal Neop | 3797 | 6 | 3797 |
| IX. Soft Tissue And Other Extraosseous Sarcomas | 1895 | 5 | 1895 |
| V. Retinoblastoma | 323 | 1 | 323 |
| VI. Renal Tumors | 1035 | 3 | 1035 |
| VII. Hepatic Tumors | 419 | 3 | 419 |
| VIII. Malignant Bone Tumors | 1440 | 5 | 1440 |
| X. Germ Cell Tumors, Trophoblastic Tumors And Neoplasms Of G | 1176 | 5 | 1176 |
| XI. Other Malignant Epithelial Neoplasms And Malignant Melan | 3362 | 6 | 3362 |
| XII. Other And Unspecified Malignant Neoplasms | 112 | 2 | 112 |

#### icccMajor by iccc2017ExtendedRecode

Distinct (group, subgroup) pairs: 108. Subgroup labels: 108. Impossible pairs (the subgroup's Roman numeral differs from the group's): 0, covering 0 of 23,930 records (0.00%).

| icccMajor | records | distinct subgroup labels | records with a consistent subgroup |
|---|---|---|---|
| I. Leukemias, Myeloproliferative And Myelodysplastic Disease | 6491 | 8 | 6491 |
| II. Lymphomas and reticuloendothelial neoplasms | 3880 | 8 | 3880 |
| III. CNS and Miscellaneous Intracranial and Intraspinal Neop | 3797 | 16 | 3797 |
| IX. Soft Tissue And Other Extraosseous Sarcomas | 1895 | 18 | 1895 |
| V. Retinoblastoma | 323 | 1 | 323 |
| VI. Renal Tumors | 1035 | 5 | 1035 |
| VII. Hepatic Tumors | 419 | 4 | 419 |
| VIII. Malignant Bone Tumors | 1440 | 9 | 1440 |
| X. Germ Cell Tumors, Trophoblastic Tumors And Neoplasms Of G | 1176 | 19 | 1176 |
| XI. Other Malignant Epithelial Neoplasms And Malignant Melan | 3362 | 15 | 3362 |
| XII. Other And Unspecified Malignant Neoplasms | 112 | 5 | 112 |

#### iccc2017Recode by iccc2017ExtendedRecode (extra check, same rule as above at the letter level)

Distinct pairs: 441. Pairs whose subgroup letters differ: 348 covering 14,295 records (59.74%). Extended labels with no letter (for example 'IX SOFT TISSUE...') are compared by Roman numeral only.

| iccc2017Recode | iccc2017ExtendedRecode | records |
|---|---|---|
| Ia Lymphoid leukemias | Ib Acute myeloid leukemias | 772 |
| IIb Non-Hodgkin lymphomas (except Burkitt lymphoma) | IIa Hodgkin lymphomas | 751 |
| Ib Acute myeloid leukemias | Ia1 Precursor cell leukemias | 708 |
| Ia Lymphoid leukemias | Ic Chronic myeloproliferative diseases | 678 |
| Ic Chronic myeloproliferative diseases | Ia1 Precursor cell leukemias | 584 |
| IIa Hodgkin lymphomas | IIb2 Mature B-cell lymphomas (except Burkitt lymphoma) | 555 |
| IIIe Other specified intracranial and intraspinal neopl | IIIb Astrocytomas | 479 |
| XIf Other and unspecified carcinomas | XIb Thyroid carcinomas | 431 |
| XIf Other and unspecified carcinomas | XId Malignant melanomas | 363 |
| Ic Chronic myeloproliferative diseases | Ib Acute myeloid leukemias | 297 |
| Ib Acute myeloid leukemias | Ic Chronic myeloproliferative diseases | 271 |
| IIIb Astrocytomas | IIIe1 Pituitary adenomas and carcinomas | 261 |
| VIIIc Ewing tumor and related sarcomas of bone | VIIIa Osteosarcomas | 174 |
| IXd Other specified soft tissue sarcomas | IXc Kaposi sarcoma | 165 |
| XIb Thyroid carcinomas | XIf6 Carcinomas of breast | 163 |
| VIb Renal carcinomas | VIa1 Nephroblastoma | 154 |
| VIa Nephroblastoma and other non-epithelial renal tumor | VIb Renal carcinomas | 154 |
| IIa Hodgkin lymphomas | IIb3 Mature T-cell and NK-cell lymphomas | 147 |
| VIIIa Osteosarcomas | VIIIc1 Ewing tumor and Askin tumor of bone | 140 |
| IIIe Other specified intracranial and intraspinal neopl | IIId2 Mixed and unspecified gliomas | 139 |
| IIId Other gliomas | IIIe1 Pituitary adenomas and carcinomas | 134 |
| Ia Lymphoid leukemias | Id Myelodysplastic syndrome and other myeloproliferative dis | 132 |
| IIIb Astrocytomas | IIIe5 Meningiomas | 131 |
| XId Malignant melanomas | XIf6 Carcinomas of breast | 127 |
| XId Malignant melanomas | XIb Thyroid carcinomas | 127 |



# Dataset: one_registry_n2393

Source `CTC`, n requested 2,393. Everything below is computed from `one_registry_n2393/run/one_registry_n2393.zip` (one pass over the CSV) and the run's `manifest.json`, `conformance.csv` and `fidelity.csv`.

### 1. Rows, archive, run cost

| Check | Result |
|---|---|
| rows in the CSV | 2,393 (n 2,393): OK |
| columns | 76 |
| zip entries | 1 ['one_registry_n2393.csv']: OK |
| testzip() | None (OK) |
| zip size | 308,328 bytes |
| CSV size | 7,259,806 bytes |
| SHA-256 of the CSV inside | 7e7797f98bff796b4ebfc1fec86e7a712963d0b8c3a0f3692d204f323a47d2f2 |
| matches manifest archive.csv_sha256 | yes |
| wall time (CLI, /usr/bin/time -l) | 4.3 s |
| max resident set size | 183 MiB |
| peak memory footprint | 146 MiB |

### 2. Conformance (values outside the dictionary vocabulary)

Columns in the CSV: 76. Columns not in the dictionary: none. Columns with out-of-vocabulary values (own check, blanks excluded): 0. conformance.csv: 0 out-of-vocabulary values in 0 columns.
Columns with blank cells: 17 (blank is how a not-applicable column is written when the dictionary has no null label).

### 3. Not-applicable fraction (manifest na_fraction against the generated data)

Mode `on` (supplied by default), minimum share 0.005. Variables applied: 32, of which written blank: 17. Rows: 2,393.

| Variable | written as | target share | manifest generated share | observed in the CSV | observed - target (points) |
|---|---|---|---|---|---|
| brainMolecularMarkers | code | 97.6141% | 97.6181% | 97.6181% | +0.004 |
| breslowDepthRecode | code, code also has published counts | 95.1686% | 95.1525% | 95.1525% | -0.016 |
| cocAccreditedFlag | code | 74.6822% | 74.6761% | 74.6761% | -0.006 |
| combinedSsPubDetailed | code, code also has published counts | 24.5206% | 24.5299% | 31.8429% | +7.322 |
| esophagusAndEgjTumorEpicenter | blank | 99.9893% | 100.0000% | 100.0000% | +0.011 |
| gleasonPatternClinicalRecode | code | 99.8849% | 99.8746% | 99.8746% | -0.010 |
| gleasonPatternPathologicRecode | code | 99.8795% | 99.8746% | 99.8746% | -0.005 |
| gleasonScoreClinicalRecode | code | 99.8835% | 99.8746% | 99.8746% | -0.009 |
| gleasonScorePathologicRecode | code | 99.8780% | 99.8746% | 99.8746% | -0.003 |
| gleasonTertiaryPattern | code | 99.9212% | 99.9164% | 99.9164% | -0.005 |
| gradeRecodePre2018 | blank | 25.3597% | 25.3656% | 25.3656% | +0.006 |
| ldhPretreatmentLabValue | code | 97.9078% | 97.9106% | 97.9106% | +0.003 |
| lymphVasInvasionPublic | code, code also has published counts | 96.8329% | 96.8241% | 96.8241% | -0.009 |
| microsatelliteInstability | code | 99.0824% | 99.0807% | 99.0807% | -0.002 |
| p16Recode | code | 99.6242% | 99.6239% | 99.6239% | -0.000 |
| pathReportsFlag | blank | 0.9004% | 0.9193% | 0.9193% | +0.019 |
| psaLabValueRecode | blank | 99.9147% | 99.9164% | 99.9164% | +0.002 |
| radiationRecode | blank | 13.4613% | 13.4559% | 13.4559% | -0.005 |
| reasonForNoRadiation | blank | 74.7477% | 74.7597% | 74.7597% | +0.012 |
| reasonForNoSurgery | blank | 3.9428% | 3.9281% | 3.9281% | -0.015 |
| regionalNodesExamined | blank | 2.1989% | 2.2148% | 2.2148% | +0.016 |
| regionalNodesPositive | blank | 2.2090% | 2.2148% | 2.2148% | +0.006 |
| rxSummBrm | blank | 3.7938% | 3.8028% | 3.8028% | +0.009 |
| rxSummHormone | blank | 3.7928% | 3.8028% | 3.8028% | +0.010 |
| rxSummOther | blank | 3.8351% | 3.8445% | 3.8445% | +0.009 |
| rxSummSurgOthRegDis | blank | 21.7224% | 21.7300% | 21.7300% | +0.008 |
| rxSummSurgPrimSite | code | 14.6781% | 14.6678% | 14.6678% | -0.010 |
| rxSummSurgPrimSite2023 | code | 95.5226% | 95.5286% | 95.5286% | +0.006 |
| rxSummSystemicSurSeq | blank | 34.0544% | 34.0577% | 34.0577% | +0.003 |
| rxSummTransplntEndocr | blank | 7.3036% | 7.3130% | 7.3130% | +0.009 |
| scope2003pPublic | blank | 21.7224% | 21.7300% | 21.7300% | +0.008 |
| treatmentStatusPublic | blank | 44.3164% | 44.2959% | 44.2959% | -0.021 |

Variables skipped, by reason: rule_target: 2; below_min_share: 4; suppression_only: 4.

Gleason and PSA columns: share of rows that are not applicable or blank (the manifest code for the column, or blank).

| Column | NA code | blank | NA or blank | rows with a real value |
|---|---|---|---|---|
| gleasonPatternClinicalRecode | 99.875% | 0.000% | 99.875% | 3 |
| gleasonPatternPathologicRecode | 99.875% | 0.000% | 99.875% | 3 |
| gleasonScoreClinicalRecode | 99.875% | 0.000% | 99.875% | 3 |
| gleasonScorePathologicRecode | 99.875% | 0.000% | 99.875% | 3 |
| gleasonTertiaryPattern | 99.916% | 0.000% | 99.916% | 2 |
| psaLabValueRecode | 0.000% | 99.916% | 99.916% | 2 |

### 4. Published-column fidelity

Manifest: published columns 75, invented columns 0, mean total variation distance over published columns 0.1013. Frequency source counts in fidelity.csv: {'published': 75}.

Own recomputation from the CSV against the dictionary probabilities, over the rows whose value has a published probability (both sides renormalised; blank and not-applicable fill rows are outside it): mean TVD 0.1399; largest |own - fidelity.csv| per column 0.9380 (columns where it exceeds 0.01: 4).

| Column (largest TVD in fidelity.csv) | fidelity.csv TVD | own TVD |
|---|---|---|
| ageRecode20Groups | 0.8383 | 0.8383 |
| ageRecodeSingle85p | 0.8383 | 0.8383 |
| ageRecodeSingle90p | 0.8383 | 0.8383 |
| gleasonScoreClinicalRecode | 0.6135 | 0.6135 |
| gleasonTertiaryPattern | 0.4914 | 0.4914 |
| iccc2017ExtendedRecode | 0.4347 | 0.4347 |
| iccc2017Recode | 0.4326 | 0.4326 |
| icccMajor | 0.4324 | 0.4324 |

For the conditional cohorts the age variables are set by the table rules and the cohort filter (ages 0-19), so their distance to the all-ages published frequencies is large by design; the mean above includes them.

### 5. ICCC group mix: target versus generated

z = (generated - expected) / binomial sd at n = 2,393. Target share = group number / sum of the listed groups (2,393).

| Group | table number | target share | generated | generated share | diff (points) | z |
|---|---|---|---|---|---|---|
| Leukemias | 654 | 27.330% | 676 | 28.249% | +0.919 | +1.01 |
| Lymphomas | 389 | 16.256% | 385 | 16.089% | -0.167 | -0.22 |
| Brain and CNS | 379 | 15.838% | 367 | 15.336% | -0.501 | -0.67 |
| Epithelial neoplasms and melanomas | 329 | 13.748% | 336 | 14.041% | +0.293 | +0.42 |
| Soft tissue sarcomas | 185 | 7.731% | 190 | 7.940% | +0.209 | +0.38 |
| Bone tumors | 146 | 6.101% | 132 | 5.516% | -0.585 | -1.20 |
| Germ cell and Gonadal Tumors | 123 | 5.140% | 128 | 5.349% | +0.209 | +0.46 |
| Renal tumors | 101 | 4.221% | 96 | 4.012% | -0.209 | -0.51 |
| Hepatic tumors | 45 | 1.880% | 36 | 1.504% | -0.376 | -1.35 |
| Retinoblastoma | 31 | 1.295% | 40 | 1.672% | +0.376 | +1.63 |
| Other and unspecified malignant neoplasms | 11 | 0.460% | 7 | 0.293% | -0.167 | -1.21 |

ICCC groups generated that are not in the table: none. Largest |z| = 1.63; |z| > 3: 0; |z| > 2: 0 of 11.

### 6. Age bands within each ICCC group: target versus generated

Cell = generated share (target share) z. Target = the config row normalized to 100%. The bands 0-4 combine '00 years' and '01-04 years'.

| Group | n | 0-4 | 5-9 | 10-14 | 15-19 |
|---|---|---|---|---|---|
| Leukemias | 676 | 43.8% (42.9%) z=+0.47 | 19.4% (21.8%) z=-1.52 | 18.0% (17.2%) z=+0.58 | 18.8% (18.1%) z=+0.46 |
| Lymphomas | 385 | 15.8% (12.3%) z=+2.12 | 15.8% (15.1%) z=+0.41 | 21.3% (24.7%) z=-1.55 | 47.0% (47.9%) z=-0.35 |
| Brain and CNS | 367 | 30.2% (32.9%) z=-1.08 | 31.3% (26.9%) z=+1.92 | 21.5% (21.9%) z=-0.17 | 16.9% (18.3%) z=-0.70 |
| Epithelial neoplasms and melanomas | 336 | 2.7% (2.9%) z=-0.24 | 4.8% (5.3%) z=-0.44 | 24.4% (21.2%) z=+1.44 | 68.2% (70.6%) z=-0.98 |
| Soft tissue sarcomas | 190 | 24.2% (25.1%) z=-0.28 | 15.8% (16.9%) z=-0.41 | 25.3% (24.6%) z=+0.21 | 34.7% (33.4%) z=+0.39 |
| Bone tumors | 132 | 4.5% (4.2%) z=+0.20 | 24.2% (15.9%) z=+2.63 | 35.6% (38.8%) z=-0.74 | 35.6% (41.2%) z=-1.30 |
| Germ cell and Gonadal Tumors | 128 | 15.6% (14.0%) z=+0.53 | 5.5% (5.5%) z=-0.02 | 19.5% (16.8%) z=+0.83 | 59.4% (63.7%) z=-1.02 |
| Renal tumors | 96 | 60.4% (67.2%) z=-1.42 | 26.0% (20.6%) z=+1.32 | 6.2% (5.4%) z=+0.37 | 7.3% (6.8%) z=+0.19 |
| Hepatic tumors | 36 | 66.7% (70.3%) z=-0.48 | 16.7% (7.7%) z=+2.02 | 2.8% (8.5%) z=-1.23 | 13.9% (13.5%) z=+0.07 |
| Retinoblastoma | 40 | 97.5% (95.8%) z=+0.53 | 2.5% (3.4%) z=-0.31 | 0.0% (0.6%) z=-0.49 | 0.0% (0.2%) z=-0.28 |
| Other and unspecified malignant neoplasms | 7 | 42.9% (37.8%) z=+0.28 | 14.3% (9.1%) z=+0.48 | 0.0% (15.3%) z=-1.12 | 42.9% (37.8%) z=+0.28 |

Cells: 44. Largest |z| = 2.63. |z| > 3: 0. |z| > 2: 3 (about 2.0 expected by chance). Sum of z squared = 42.7 (about 44 if matched).

Split inside 0-4: '00 years' 160 : '01-04 years' 513 (23.77% under one year).

### 7. Male share per ICCC group

Target = Male / (Male + Female) from the config counts.

| Group | n | target male share | generated male share | z |
|---|---|---|---|---|
| Leukemias | 676 | 54.84% | 53.70% | -0.60 |
| Lymphomas | 385 | 32.42% | 37.92% | +2.31 |
| Brain and CNS | 367 | 59.02% | 54.77% | -1.66 |
| Epithelial neoplasms and melanomas | 336 | 59.10% | 63.99% | +1.82 |
| Soft tissue sarcomas | 190 | 57.84% | 51.05% | -1.89 |
| Bone tumors | 132 | 37.62% | 35.61% | -0.48 |
| Germ cell and Gonadal Tumors | 128 | 58.22% | 64.84% | +1.52 |
| Renal tumors | 96 | 52.03% | 47.92% | -0.81 |
| Hepatic tumors | 36 | 54.55% | 58.33% | +0.46 |
| Retinoblastoma | 40 | 54.84% | 57.50% | +0.34 |
| Other and unspecified malignant neoplasms | 7 | 45.45% | 28.57% | -0.90 |

Largest |z| = 2.31; |z| > 3: 0; |z| > 2: 1. Values of sex generated: ['Female', 'Male'].

### 8. Age variables: agreement with ageRecode19Groups at band level

| Variable | records whose band does not overlap the 19-group band | records with an unparsable label |
|---|---|---|
| ageRecode20Groups | 0 | 0 |
| ageRecodeSingle85p | 0 | 0 |
| ageRecodeSingle90p | 0 | 0 |

### 9. Re-check 1: ageRecodeSingle85p versus ageRecodeSingle90p

Records where the two single-year labels differ: 1,719 of 2,393 (71.83%). Every record is aged 0-19, so both variables should give the same single year (the 85+ and 90+ top groups cannot apply).
Mean absolute difference in years among the disagreeing records: 1.93; largest 4. Records of either variable outside the 19-group band (section 8): 0 and 0.

| 19-group band | records | disagree | share |
|---|---|---|---|
| 00 years | 160 | 0 | 0.00% |
| 01-04 years | 513 | 373 | 72.71% |
| 05-09 years | 425 | 343 | 80.71% |
| 10-14 years | 492 | 376 | 76.42% |
| 15-19 years | 803 | 627 | 78.08% |

The full cross of the two variables is in `crosstab_single85p_by_single90p.csv`.

### 10. Re-check 2: ICCC subgroup variables against icccMajor

#### icccMajor by iccc2017Recode

Distinct (group, subgroup) pairs: 44. Subgroup labels: 44. Impossible pairs (the subgroup's Roman numeral differs from the group's): 0, covering 0 of 2,393 records (0.00%).

| icccMajor | records | distinct subgroup labels | records with a consistent subgroup |
|---|---|---|---|
| I. Leukemias, Myeloproliferative And Myelodysplastic Disease | 676 | 5 | 676 |
| II. Lymphomas and reticuloendothelial neoplasms | 385 | 5 | 385 |
| III. CNS and Miscellaneous Intracranial and Intraspinal Neop | 367 | 6 | 367 |
| IX. Soft Tissue And Other Extraosseous Sarcomas | 190 | 5 | 190 |
| V. Retinoblastoma | 40 | 1 | 40 |
| VI. Renal Tumors | 96 | 2 | 96 |
| VII. Hepatic Tumors | 36 | 3 | 36 |
| VIII. Malignant Bone Tumors | 132 | 5 | 132 |
| X. Germ Cell Tumors, Trophoblastic Tumors And Neoplasms Of G | 128 | 5 | 128 |
| XI. Other Malignant Epithelial Neoplasms And Malignant Melan | 336 | 5 | 336 |
| XII. Other And Unspecified Malignant Neoplasms | 7 | 2 | 7 |

#### icccMajor by iccc2017ExtendedRecode

Distinct (group, subgroup) pairs: 93. Subgroup labels: 93. Impossible pairs (the subgroup's Roman numeral differs from the group's): 0, covering 0 of 2,393 records (0.00%).

| icccMajor | records | distinct subgroup labels | records with a consistent subgroup |
|---|---|---|---|
| I. Leukemias, Myeloproliferative And Myelodysplastic Disease | 676 | 8 | 676 |
| II. Lymphomas and reticuloendothelial neoplasms | 385 | 8 | 385 |
| III. CNS and Miscellaneous Intracranial and Intraspinal Neop | 367 | 15 | 367 |
| IX. Soft Tissue And Other Extraosseous Sarcomas | 190 | 16 | 190 |
| V. Retinoblastoma | 40 | 1 | 40 |
| VI. Renal Tumors | 96 | 4 | 96 |
| VII. Hepatic Tumors | 36 | 3 | 36 |
| VIII. Malignant Bone Tumors | 132 | 8 | 132 |
| X. Germ Cell Tumors, Trophoblastic Tumors And Neoplasms Of G | 128 | 14 | 128 |
| XI. Other Malignant Epithelial Neoplasms And Malignant Melan | 336 | 12 | 336 |
| XII. Other And Unspecified Malignant Neoplasms | 7 | 4 | 7 |

#### iccc2017Recode by iccc2017ExtendedRecode (extra check, same rule as above at the letter level)

Distinct pairs: 283. Pairs whose subgroup letters differ: 210 covering 1,399 records (58.46%). Extended labels with no letter (for example 'IX SOFT TISSUE...') are compared by Roman numeral only.

| iccc2017Recode | iccc2017ExtendedRecode | records |
|---|---|---|
| Ib Acute myeloid leukemias | Ia1 Precursor cell leukemias | 77 |
| IIb Non-Hodgkin lymphomas (except Burkitt lymphoma) | IIa Hodgkin lymphomas | 75 |
| Ia Lymphoid leukemias | Ib Acute myeloid leukemias | 69 |
| Ia Lymphoid leukemias | Ic Chronic myeloproliferative diseases | 65 |
| IIa Hodgkin lymphomas | IIb2 Mature B-cell lymphomas (except Burkitt lymphoma) | 62 |
| Ic Chronic myeloproliferative diseases | Ia1 Precursor cell leukemias | 55 |
| XIf Other and unspecified carcinomas | XIb Thyroid carcinomas | 49 |
| IIIe Other specified intracranial and intraspinal neopl | IIIb Astrocytomas | 42 |
| Ib Acute myeloid leukemias | Ic Chronic myeloproliferative diseases | 29 |
| XIf Other and unspecified carcinomas | XId Malignant melanomas | 23 |
| Ic Chronic myeloproliferative diseases | Ib Acute myeloid leukemias | 23 |
| IIIb Astrocytomas | IIIe1 Pituitary adenomas and carcinomas | 23 |
| VIIIa Osteosarcomas | VIIIc1 Ewing tumor and Askin tumor of bone | 20 |
| IXd Other specified soft tissue sarcomas | IXc Kaposi sarcoma | 19 |
| Ia Lymphoid leukemias | Id Myelodysplastic syndrome and other myeloproliferative dis | 19 |
| VIIId Other specified malignant bone tumors | VIIIa Osteosarcomas | 18 |
| Id Myelodysplastic syndrome and other myeloproliferativ | Ia1 Precursor cell leukemias | 18 |
| VIIIc Ewing tumor and related sarcomas of bone | VIIIa Osteosarcomas | 18 |
| XIb Thyroid carcinomas | XIf6 Carcinomas of breast | 17 |
| IIIb Astrocytomas | IIIe5 Meningiomas | 15 |
| XId Malignant melanomas | XIf6 Carcinomas of breast | 14 |
| XIb Thyroid carcinomas | XId Malignant melanomas | 14 |
| IXd Other specified soft tissue sarcomas | IXa Rhabdomyosarcomas | 13 |
| Ie Unspecified and other specified leukemias | Ia1 Precursor cell leukemias | 13 |
| Ia Lymphoid leukemias | Ie Unspecified and other specified leukemias | 13 |



# Dataset: nccr_0_19_n261056

Source `CTC`, n requested 261,056. Everything below is computed from `nccr_0_19_n261056/run/nccr_0_19_n261056.zip` (one pass over the CSV) and the run's `manifest.json`, `conformance.csv` and `fidelity.csv`.

### 1. Rows, archive, run cost

| Check | Result |
|---|---|
| rows in the CSV | 261,056 (n 261,056): OK |
| columns | 76 |
| zip entries | 1 ['nccr_0_19_n261056.csv']: OK |
| testzip() | None (OK) |
| zip size | 33,827,310 bytes |
| CSV size | 792,493,550 bytes |
| SHA-256 of the CSV inside | 6a43b2811c9e8fcf39c0b37ed0a52c3573327d4ef3660e60df800ed165670644 |
| matches manifest archive.csv_sha256 | yes |
| wall time (CLI, /usr/bin/time -l) | 23.7 s |
| max resident set size | 478 MiB |
| peak memory footprint | 460 MiB |

### 2. Conformance (values outside the dictionary vocabulary)

Columns in the CSV: 76. Columns not in the dictionary: none. Columns with out-of-vocabulary values (own check, blanks excluded): 0. conformance.csv: 0 out-of-vocabulary values in 0 columns.
Columns with blank cells: 17 (blank is how a not-applicable column is written when the dictionary has no null label).

### 3. Not-applicable fraction (manifest na_fraction against the generated data)

Mode `on` (supplied by default), minimum share 0.005. Variables applied: 32, of which written blank: 17. Rows: 261,056.

| Variable | written as | target share | manifest generated share | observed in the CSV | observed - target (points) |
|---|---|---|---|---|---|
| brainMolecularMarkers | code | 97.6141% | 97.6139% | 97.6139% | -0.000 |
| breslowDepthRecode | code, code also has published counts | 95.1686% | 95.1685% | 95.1715% | +0.003 |
| cocAccreditedFlag | code | 74.6822% | 74.6821% | 74.6821% | -0.000 |
| combinedSsPubDetailed | code, code also has published counts | 24.5206% | 24.5204% | 32.3463% | +7.826 |
| esophagusAndEgjTumorEpicenter | blank | 99.9893% | 99.9893% | 99.9893% | -0.000 |
| gleasonPatternClinicalRecode | code | 99.8849% | 99.8847% | 99.8847% | -0.000 |
| gleasonPatternPathologicRecode | code | 99.8795% | 99.8797% | 99.8797% | +0.000 |
| gleasonScoreClinicalRecode | code | 99.8835% | 99.8835% | 99.8835% | +0.000 |
| gleasonScorePathologicRecode | code | 99.8780% | 99.8778% | 99.8778% | -0.000 |
| gleasonTertiaryPattern | code | 99.9212% | 99.9211% | 99.9211% | -0.000 |
| gradeRecodePre2018 | blank | 25.3597% | 25.3597% | 25.3597% | +0.000 |
| ldhPretreatmentLabValue | code | 97.9078% | 97.9077% | 97.9077% | -0.000 |
| lymphVasInvasionPublic | code, code also has published counts | 96.8329% | 96.8329% | 96.8340% | +0.001 |
| microsatelliteInstability | code | 99.0824% | 99.0822% | 99.0822% | -0.000 |
| p16Recode | code | 99.6242% | 99.6242% | 99.6242% | +0.000 |
| pathReportsFlag | blank | 0.9004% | 0.9006% | 0.9006% | +0.000 |
| psaLabValueRecode | blank | 99.9147% | 99.9146% | 99.9146% | -0.000 |
| radiationRecode | blank | 13.4613% | 13.4611% | 13.4611% | -0.000 |
| reasonForNoRadiation | blank | 74.7477% | 74.7476% | 74.7476% | -0.000 |
| reasonForNoSurgery | blank | 3.9428% | 3.9428% | 3.9428% | +0.000 |
| regionalNodesExamined | blank | 2.1989% | 2.1988% | 2.1988% | -0.000 |
| regionalNodesPositive | blank | 2.2090% | 2.2091% | 2.2091% | +0.000 |
| rxSummBrm | blank | 3.7938% | 3.7938% | 3.7938% | +0.000 |
| rxSummHormone | blank | 3.7928% | 3.7927% | 3.7927% | -0.000 |
| rxSummOther | blank | 3.8351% | 3.8352% | 3.8352% | +0.000 |
| rxSummSurgOthRegDis | blank | 21.7224% | 21.7225% | 21.7225% | +0.000 |
| rxSummSurgPrimSite | code | 14.6781% | 14.6781% | 14.6781% | -0.000 |
| rxSummSurgPrimSite2023 | code | 95.5226% | 95.5224% | 95.5224% | -0.000 |
| rxSummSystemicSurSeq | blank | 34.0544% | 34.0544% | 34.0544% | -0.000 |
| rxSummTransplntEndocr | blank | 7.3036% | 7.3034% | 7.3034% | -0.000 |
| scope2003pPublic | blank | 21.7224% | 21.7225% | 21.7225% | +0.000 |
| treatmentStatusPublic | blank | 44.3164% | 44.3165% | 44.3165% | +0.000 |

Variables skipped, by reason: rule_target: 2; below_min_share: 4; suppression_only: 4.

Gleason and PSA columns: share of rows that are not applicable or blank (the manifest code for the column, or blank).

| Column | NA code | blank | NA or blank | rows with a real value |
|---|---|---|---|---|
| gleasonPatternClinicalRecode | 99.885% | 0.000% | 99.885% | 301 |
| gleasonPatternPathologicRecode | 99.880% | 0.000% | 99.880% | 314 |
| gleasonScoreClinicalRecode | 99.884% | 0.000% | 99.884% | 304 |
| gleasonScorePathologicRecode | 99.878% | 0.000% | 99.878% | 319 |
| gleasonTertiaryPattern | 99.921% | 0.000% | 99.921% | 206 |
| psaLabValueRecode | 0.000% | 99.915% | 99.915% | 223 |

### 4. Published-column fidelity

Manifest: published columns 76, invented columns 0, mean total variation distance over published columns 0.0559. Frequency source counts in fidelity.csv: {'published': 76}.

Own recomputation from the CSV against the dictionary probabilities, over the rows whose value has a published probability (both sides renormalised; blank and not-applicable fill rows are outside it): mean TVD 0.0948; largest |own - fidelity.csv| per column 0.9615 (columns where it exceeds 0.01: 4).

| Column (largest TVD in fidelity.csv) | fidelity.csv TVD | own TVD |
|---|---|---|
| ageRecode20Groups | 0.8383 | 0.8383 |
| ageRecodeSingle90p | 0.8383 | 0.8383 |
| ageRecodeSingle85p | 0.8383 | 0.8383 |
| iccc2017Recode | 0.4263 | 0.4263 |
| icccMajor | 0.4263 | 0.4263 |
| iccc2017ExtendedRecode | 0.4251 | 0.4251 |
| esophagusAndEgjTumorEpicenter | 0.1346 | 0.1346 |
| gleasonPatternPathologicRecode | 0.0515 | 0.0515 |

For the conditional cohorts the age variables are set by the table rules and the cohort filter (ages 0-19), so their distance to the all-ages published frequencies is large by design; the mean above includes them.

### 5. ICCC group mix: target versus generated

z = (generated - expected) / binomial sd at n = 261,056. Target share = group number / sum of the listed groups (261,056).

| Group | table number | target share | generated | generated share | diff (points) | z |
|---|---|---|---|---|---|---|
| I. Leukemias, Myeloproliferative And Myelodysplastic Diseases | 61530 | 23.570% | 61684 | 23.629% | +0.059 | +0.71 |
| II. Lymphomas and reticuloendothelial neoplasms | 35406 | 13.563% | 35231 | 13.496% | -0.067 | -1.00 |
| III. CNS and Miscellaneous Intracranial and Intraspinal Neoplasms | 58901 | 22.563% | 58794 | 22.522% | -0.041 | -0.50 |
| IV. Neuroblastoma And Other Peripheral Nervous Cell Tumors | 10766 | 4.124% | 10926 | 4.185% | +0.061 | +1.57 |
| V. Retinoblastoma | 4186 | 1.603% | 4135 | 1.584% | -0.020 | -0.79 |
| VI. Renal Tumors | 8559 | 3.279% | 8587 | 3.289% | +0.011 | +0.31 |
| VII. Hepatic Tumors | 3355 | 1.285% | 3436 | 1.316% | +0.031 | +1.41 |
| VIII. Malignant Bone Tumors | 11850 | 4.539% | 11920 | 4.566% | +0.027 | +0.66 |
| IX. Soft Tissue And Other Extraosseous Sarcomas | 15464 | 5.924% | 15402 | 5.900% | -0.024 | -0.51 |
| X. Germ Cell Tumors, Trophoblastic Tumors And Neoplasms Of Gonads | 15848 | 6.071% | 15739 | 6.029% | -0.042 | -0.89 |
| XI. Other Malignant Epithelial Neoplasms And Malignant Melanomas | 25244 | 9.670% | 25176 | 9.644% | -0.026 | -0.45 |
| XII. Other And Unspecified Malignant Neoplasms | 1163 | 0.445% | 1188 | 0.455% | +0.010 | +0.73 |
| Not classified by SEER or in situ | 8784 | 3.365% | 8838 | 3.385% | +0.021 | +0.59 |

ICCC groups generated that are not in the table: none. Largest |z| = 1.57; |z| > 3: 0; |z| > 2: 0 of 13.

### 6. Age bands within each ICCC group: target versus generated

Cell = generated share (target share) z. Target = the config row normalized to 100%. The bands 0-4 combine '00 years' and '01-04 years'.

| Group | n | 0-4 | 5-9 | 10-14 | 15-19 |
|---|---|---|---|---|---|
| I. Leukemias, Myeloproliferative And Myelodyspla | 61684 | 42.1% (41.9%) z=+0.97 | 21.9% (22.0%) z=-0.44 | 17.4% (17.8%) z=-2.27 | 18.5% (18.3%) z=+1.48 |
| II. Lymphomas and reticuloendothelial neoplasms | 35231 | 11.9% (12.1%) z=-0.77 | 15.0% (15.2%) z=-0.94 | 24.5% (24.8%) z=-1.14 | 48.5% (47.9%) z=+2.16 |
| III. CNS and Miscellaneous Intracranial and Intr | 58794 | 25.6% (25.4%) z=+1.06 | 23.7% (23.7%) z=-0.06 | 22.6% (22.8%) z=-1.19 | 28.2% (28.1%) z=+0.14 |
| IV. Neuroblastoma And Other Peripheral Nervous C | 10926 | 80.5% (80.5%) z=-0.04 | 11.9% (11.6%) z=+1.09 | 4.2% (4.5%) z=-1.16 | 3.4% (3.4%) z=-0.50 |
| V. Retinoblastoma | 4135 | 94.8% (95.5%) z=-2.43 | 4.1% (3.6%) z=+1.65 | 1.1% (0.6%) z=+3.37 | 0.1% (0.2%) z=-1.75 |
| VI. Renal Tumors | 8587 | 67.2% (67.6%) z=-0.94 | 19.8% (19.9%) z=-0.18 | 5.8% (5.4%) z=+1.41 | 7.3% (7.0%) z=+0.76 |
| VII. Hepatic Tumors | 3436 | 66.9% (66.5%) z=+0.47 | 9.7% (9.9%) z=-0.34 | 10.8% (10.4%) z=+0.76 | 12.7% (13.3%) z=-1.04 |
| VIII. Malignant Bone Tumors | 11920 | 3.5% (3.8%) z=-1.61 | 15.4% (16.0%) z=-1.73 | 39.0% (39.0%) z=-0.06 | 42.1% (41.2%) z=+1.98 |
| IX. Soft Tissue And Other Extraosseous Sarcomas | 15402 | 23.6% (23.8%) z=-0.72 | 17.2% (17.1%) z=+0.12 | 24.4% (24.6%) z=-0.33 | 34.8% (34.5%) z=+0.85 |
| X. Germ Cell Tumors, Trophoblastic Tumors And Ne | 15739 | 15.1% (15.1%) z=-0.01 | 6.2% (6.0%) z=+1.03 | 16.7% (16.8%) z=-0.59 | 62.0% (62.1%) z=-0.04 |
| XI. Other Malignant Epithelial Neoplasms And Mal | 25176 | 2.3% (2.3%) z=-0.73 | 5.4% (5.4%) z=+0.19 | 21.8% (22.1%) z=-0.93 | 70.5% (70.2%) z=+0.99 |
| XII. Other And Unspecified Malignant Neoplasms | 1188 | 34.4% (33.3%) z=+0.84 | 9.4% (10.3%) z=-1.01 | 16.8% (17.6%) z=-0.79 | 39.4% (38.8%) z=+0.43 |
| Not classified by SEER or in situ | 8838 | 18.6% (19.0%) z=-0.87 | 12.1% (12.2%) z=-0.21 | 19.8% (19.8%) z=-0.13 | 49.5% (49.0%) z=+0.93 |

Cells: 52. Largest |z| = 3.37. |z| > 3: 1. |z| > 2: 4 (about 2.4 expected by chance). Sum of z squared = 68.7 (about 52 if matched).

Split inside 0-4: '00 years' 17,216 : '01-04 years' 57,876 (22.93% under one year).

### 8. Age variables: agreement with ageRecode19Groups at band level

| Variable | records whose band does not overlap the 19-group band | records with an unparsable label |
|---|---|---|
| ageRecode20Groups | 0 | 0 |
| ageRecodeSingle85p | 0 | 0 |
| ageRecodeSingle90p | 0 | 0 |

### 9. Re-check 1: ageRecodeSingle85p versus ageRecodeSingle90p

Records where the two single-year labels differ: 191,592 of 261,056 (73.39%). Every record is aged 0-19, so both variables should give the same single year (the 85+ and 90+ top groups cannot apply).
Mean absolute difference in years among the disagreeing records: 1.91; largest 4. Records of either variable outside the 19-group band (section 8): 0 and 0.

| 19-group band | records | disagree | share |
|---|---|---|---|
| 00 years | 17216 | 0 | 0.00% |
| 01-04 years | 57876 | 43136 | 74.53% |
| 05-09 years | 44216 | 35548 | 80.40% |
| 10-14 years | 52492 | 41777 | 79.59% |
| 15-19 years | 89256 | 71131 | 79.69% |

The full cross of the two variables is in `crosstab_single85p_by_single90p.csv`.

### 10. Re-check 2: ICCC subgroup variables against icccMajor

#### icccMajor by iccc2017Recode

Distinct (group, subgroup) pairs: 49. Subgroup labels: 49. Impossible pairs (the subgroup's Roman numeral differs from the group's): 0, covering 0 of 261,056 records (0.00%).

| icccMajor | records | distinct subgroup labels | records with a consistent subgroup |
|---|---|---|---|
| I. Leukemias, Myeloproliferative And Myelodysplastic Disease | 61684 | 5 | 61684 |
| II. Lymphomas and reticuloendothelial neoplasms | 35231 | 5 | 35231 |
| III. CNS and Miscellaneous Intracranial and Intraspinal Neop | 58794 | 6 | 58794 |
| IV. Neuroblastoma And Other Peripheral Nervous Cell Tumors | 10926 | 2 | 10926 |
| IX. Soft Tissue And Other Extraosseous Sarcomas | 15402 | 5 | 15402 |
| Not classified by SEER or in situ | 8838 | 1 | 8838 |
| V. Retinoblastoma | 4135 | 1 | 4135 |
| VI. Renal Tumors | 8587 | 3 | 8587 |
| VII. Hepatic Tumors | 3436 | 3 | 3436 |
| VIII. Malignant Bone Tumors | 11920 | 5 | 11920 |
| X. Germ Cell Tumors, Trophoblastic Tumors And Neoplasms Of G | 15739 | 5 | 15739 |
| XI. Other Malignant Epithelial Neoplasms And Malignant Melan | 25176 | 6 | 25176 |
| XII. Other And Unspecified Malignant Neoplasms | 1188 | 2 | 1188 |

#### icccMajor by iccc2017ExtendedRecode

Distinct (group, subgroup) pairs: 116. Subgroup labels: 116. Impossible pairs (the subgroup's Roman numeral differs from the group's): 0, covering 0 of 261,056 records (0.00%).

| icccMajor | records | distinct subgroup labels | records with a consistent subgroup |
|---|---|---|---|
| I. Leukemias, Myeloproliferative And Myelodysplastic Disease | 61684 | 8 | 61684 |
| II. Lymphomas and reticuloendothelial neoplasms | 35231 | 8 | 35231 |
| III. CNS and Miscellaneous Intracranial and Intraspinal Neop | 58794 | 16 | 58794 |
| IV. Neuroblastoma And Other Peripheral Nervous Cell Tumors | 10926 | 2 | 10926 |
| IX. Soft Tissue And Other Extraosseous Sarcomas | 15402 | 18 | 15402 |
| Not classified by SEER or in situ | 8838 | 1 | 8838 |
| V. Retinoblastoma | 4135 | 1 | 4135 |
| VI. Renal Tumors | 8587 | 5 | 8587 |
| VII. Hepatic Tumors | 3436 | 5 | 3436 |
| VIII. Malignant Bone Tumors | 11920 | 9 | 11920 |
| X. Germ Cell Tumors, Trophoblastic Tumors And Neoplasms Of G | 15739 | 20 | 15739 |
| XI. Other Malignant Epithelial Neoplasms And Malignant Melan | 25176 | 16 | 25176 |
| XII. Other And Unspecified Malignant Neoplasms | 1188 | 7 | 1188 |

#### iccc2017Recode by iccc2017ExtendedRecode (extra check, same rule as above at the letter level)

Distinct pairs: 528. Pairs whose subgroup letters differ: 416 covering 146,922 records (56.28%). Extended labels with no letter (for example 'IX SOFT TISSUE...') are compared by Roman numeral only.

| iccc2017Recode | iccc2017ExtendedRecode | records |
|---|---|---|
| Ia Lymphoid leukemias | Ib Acute myeloid leukemias | 7293 |
| IIIe Other specified intracranial and intraspinal neopl | IIIb Astrocytomas | 7160 |
| IIb Non-Hodgkin lymphomas (except Burkitt lymphoma) | IIa Hodgkin lymphomas | 7062 |
| Ib Acute myeloid leukemias | Ia1 Precursor cell leukemias | 6373 |
| Ia Lymphoid leukemias | Ic Chronic myeloproliferative diseases | 5992 |
| Ic Chronic myeloproliferative diseases | Ia1 Precursor cell leukemias | 5556 |
| IIa Hodgkin lymphomas | IIb2 Mature B-cell lymphomas (except Burkitt lymphoma) | 4835 |
| IIIb Astrocytomas | IIIe1 Pituitary adenomas and carcinomas | 4299 |
| XIf Other and unspecified carcinomas | XIb Thyroid carcinomas | 3362 |
| Ib Acute myeloid leukemias | Ic Chronic myeloproliferative diseases | 3032 |
| Ic Chronic myeloproliferative diseases | Ib Acute myeloid leukemias | 2965 |
| XIf Other and unspecified carcinomas | XId Malignant melanomas | 2326 |
| IIIe Other specified intracranial and intraspinal neopl | IIId2 Mixed and unspecified gliomas | 2126 |
| IIId Other gliomas | IIIe1 Pituitary adenomas and carcinomas | 2104 |
| IIIb Astrocytomas | IIIe5 Meningiomas | 1842 |
| Xc Malignant gonadal germ cell tumors | Xd Gonadal carcinomas | 1618 |
| IIId Other gliomas | IIIb Astrocytomas | 1583 |
| IVa Neuroblastoma and ganglioneuroblastoma | IVb Other peripheral nervous cell tumors | 1471 |
| IVb Other peripheral nervous cell tumors | IVa Neuroblastoma and ganglioneuroblastoma | 1461 |
| XIb Thyroid carcinomas | XIf6 Carcinomas of breast | 1414 |
| VIIIc Ewing tumor and related sarcomas of bone | VIIIa Osteosarcomas | 1384 |
| IIIe Other specified intracranial and intraspinal neopl | IIIa1 Ependymomas | 1355 |
| IXd Other specified soft tissue sarcomas | IXc Kaposi sarcoma | 1304 |
| VIa Nephroblastoma and other non-epithelial renal tumor | VIb Renal carcinomas | 1302 |
| IIIe Other specified intracranial and intraspinal neopl | IIId1 Oligodendrogliomas | 1264 |



# Dataset: ro_10pct

Source `RO`, n requested 506. Everything below is computed from `ro_10pct/run/ro_10pct.zip` (one pass over the CSV) and the run's `manifest.json`, `conformance.csv` and `fidelity.csv`.

### 1. Rows, archive, run cost

| Check | Result |
|---|---|
| rows in the CSV | 506 (n 506): OK |
| columns | 10 |
| zip entries | 1 ['ro_10pct.csv']: OK |
| testzip() | None (OK) |
| zip size | 5,986 bytes |
| CSV size | 105,891 bytes |
| SHA-256 of the CSV inside | 0fe4b95197b724080c85a64cc7fe32a677688e59838080ed82ba7cab64cf9ed2 |
| matches manifest archive.csv_sha256 | yes |
| wall time (CLI, /usr/bin/time -l) | 3.2 s |
| max resident set size | 173 MiB |
| peak memory footprint | 136 MiB |

### 2. Conformance (values outside the dictionary vocabulary)

Columns in the CSV: 10. Columns not in the dictionary: none. Columns with out-of-vocabulary values (own check, blanks excluded): 0. conformance.csv: 0 out-of-vocabulary values in 0 columns.
Columns with blank cells: 0 (blank is how a not-applicable column is written when the dictionary has no null label).

### 3. Not-applicable fraction (manifest na_fraction against the generated data)

Mode `on` (supplied by default), minimum share 0.005. Variables applied: 0, of which written blank: 0. Rows: 506.

| Variable | written as | target share | manifest generated share | observed in the CSV | observed - target (points) |
|---|---|---|---|---|---|

Variables skipped, by reason: suppression_only: 8.

### 4. Published-column fidelity

Manifest: published columns 9, invented columns 1, mean total variation distance over published columns 0.0454. Frequency source counts in fidelity.csv: {'published': 9, 'uniform': 1}.

Own recomputation from the CSV against the dictionary probabilities, over the rows whose value has a published probability (both sides renormalised; blank and not-applicable fill rows are outside it): mean TVD 0.0454; largest |own - fidelity.csv| per column 0.0000 (columns where it exceeds 0.01: 0).

| Column (largest TVD in fidelity.csv) | fidelity.csv TVD | own TVD |
|---|---|---|
| radiation_anatomic_site | 0.0676 | 0.0676 |
| months_from_dx_to_tx_start | 0.0632 | 0.0632 |
| radiation_energy_type | 0.0625 | 0.0625 |
| months_from_dx_to_treatment_end | 0.0600 | 0.0600 |
| radiation_fractions_delivered | 0.0515 | 0.0515 |
| radiation_dose_delivered | 0.0369 | 0.0369 |
| radiation_therapy_type | 0.0352 | 0.0352 |
| radiation_dose_prescribed | 0.0170 | 0.0170 |



# Dataset: ccdi_10pct

Source `CCDI`, n requested 6,972. Everything below is computed from `ccdi_10pct/run/ccdi_10pct.zip` (one pass over the CSV) and the run's `manifest.json`, `conformance.csv` and `fidelity.csv`.

### 1. Rows, archive, run cost

| Check | Result |
|---|---|
| rows in the CSV | 6,972 (n 6,972): OK |
| columns | 1 |
| zip entries | 1 ['ccdi_10pct.csv']: OK |
| testzip() | None (OK) |
| zip size | 14,959 bytes |
| CSV size | 303,563 bytes |
| SHA-256 of the CSV inside | a9b3a8c58c7e92a6b7c596202f933a24b0a183314312a99a8b49f26c7f795b6f |
| matches manifest archive.csv_sha256 | yes |
| wall time (CLI, /usr/bin/time -l) | 3.3 s |
| max resident set size | 174 MiB |
| peak memory footprint | 137 MiB |

### 2. Conformance (values outside the dictionary vocabulary)

Columns in the CSV: 1. Columns not in the dictionary: none. Columns with out-of-vocabulary values (own check, blanks excluded): 0. conformance.csv: 0 out-of-vocabulary values in 0 columns.
Columns with blank cells: 0 (blank is how a not-applicable column is written when the dictionary has no null label).

### 3. Not-applicable fraction (manifest na_fraction against the generated data)

Mode `on` (supplied by default), minimum share 0.005. Variables applied: 0, of which written blank: 0. Rows: 6,972.

| Variable | written as | target share | manifest generated share | observed in the CSV | observed - target (points) |
|---|---|---|---|---|---|

Variables skipped, by reason: suppression_only: 1.

### 4. Published-column fidelity

Manifest: published columns 1, invented columns 0, mean total variation distance over published columns 0.0238. Frequency source counts in fidelity.csv: {'published': 1}.

Own recomputation from the CSV against the dictionary probabilities, over the rows whose value has a published probability (both sides renormalised; blank and not-applicable fill rows are outside it): mean TVD 0.0238; largest |own - fidelity.csv| per column 0.0000 (columns where it exceeds 0.01: 0).

| Column (largest TVD in fidelity.csv) | fidelity.csv TVD | own TVD |
|---|---|---|
| resourceName | 0.0238 | 0.0238 |



# Dataset: cog_10pct

Source `COG`, n requested 148,392. Everything below is computed from `cog_10pct/run/cog_10pct.zip` (one pass over the CSV) and the run's `manifest.json`, `conformance.csv` and `fidelity.csv`.

### 1. Rows, archive, run cost

| Check | Result |
|---|---|
| rows in the CSV | 148,392 (n 148,392): OK |
| columns | 7 |
| zip entries | 1 ['cog_10pct.csv']: OK |
| testzip() | None (OK) |
| zip size | 358,377 bytes |
| CSV size | 47,855,967 bytes |
| SHA-256 of the CSV inside | eef91dbf886f14717c6ddf7ec29777de1bac94385a91c3cf2f4a6e5fb7215f1c |
| matches manifest archive.csv_sha256 | yes |
| wall time (CLI, /usr/bin/time -l) | 4.1 s |
| max resident set size | 198 MiB |
| peak memory footprint | 161 MiB |

### 2. Conformance (values outside the dictionary vocabulary)

Columns in the CSV: 7. Columns not in the dictionary: none. Columns with out-of-vocabulary values (own check, blanks excluded): 0. conformance.csv: 0 out-of-vocabulary values in 0 columns.
Columns with blank cells: 0 (blank is how a not-applicable column is written when the dictionary has no null label).

### 3. Not-applicable fraction (manifest na_fraction against the generated data)

Mode `on` (supplied by default), minimum share 0.005. Variables applied: 0, of which written blank: 0. Rows: 148,392.

| Variable | written as | target share | manifest generated share | observed in the CSV | observed - target (points) |
|---|---|---|---|---|---|

Variables skipped, by reason: suppression_only: 6.

### 4. Published-column fidelity

Manifest: published columns 7, invented columns 0, mean total variation distance over published columns 0.0005. Frequency source counts in fidelity.csv: {'published': 7}.

Own recomputation from the CSV against the dictionary probabilities, over the rows whose value has a published probability (both sides renormalised; blank and not-applicable fill rows are outside it): mean TVD 0.0005; largest |own - fidelity.csv| per column 0.0000 (columns where it exceeds 0.01: 0).

| Column (largest TVD in fidelity.csv) | fidelity.csv TVD | own TVD |
|---|---|---|
| supportiveStudyCount | 0.0009 | 0.0009 |
| therapeuticOtherTrialCount | 0.0007 | 0.0007 |
| therapeuticRelapsedTrialCount | 0.0005 | 0.0005 |
| biobankingTumorClassStudyCount | 0.0005 | 0.0005 |
| registryStudyCount | 0.0003 | 0.0003 |
| therapeuticFrontLineTrialCount | 0.0001 | 0.0001 |
| reportedCOGEnrollment | 0.0001 | 0.0001 |



# Dataset: mce_10pct

Source `MCE`, n requested 148,392. Everything below is computed from `mce_10pct/run/mce_10pct.zip` (one pass over the CSV) and the run's `manifest.json`, `conformance.csv` and `fidelity.csv`.

### 1. Rows, archive, run cost

| Check | Result |
|---|---|
| rows in the CSV | 148,392 (n 148,392): OK |
| columns | 361 |
| zip entries | 1 ['mce_10pct.csv']: OK |
| testzip() | None (OK) |
| zip size | 382,765 bytes |
| CSV size | 66,813,239 bytes |
| SHA-256 of the CSV inside | f3539eb42cd7ae2674155b153f68ba6889aef6e3cad2a1ac66a05b01b6ef4aa0 |
| matches manifest archive.csv_sha256 | yes |
| wall time (CLI, /usr/bin/time -l) | 9.5 s |
| max resident set size | 1,050 MiB |
| peak memory footprint | 1,031 MiB |

### 2. Conformance (values outside the dictionary vocabulary)

Columns in the CSV: 361. Columns not in the dictionary: none. Columns with out-of-vocabulary values (own check, blanks excluded): 0. conformance.csv: 0 out-of-vocabulary values in 0 columns.
Columns with blank cells: 359 (blank is how a not-applicable column is written when the dictionary has no null label).

### 3. Not-applicable fraction (manifest na_fraction against the generated data)

Mode `on` (supplied by default), minimum share 0.005. Variables applied: 0, of which written blank: 0. Rows: 148,392.

| Variable | written as | target share | manifest generated share | observed in the CSV | observed - target (points) |
|---|---|---|---|---|---|

Variables skipped, by reason: .

### 4. Published-column fidelity

Manifest: published columns 2, invented columns 0, mean total variation distance over published columns 0.0009. Frequency source counts in fidelity.csv: {'published': 2}.

Own recomputation from the CSV against the dictionary probabilities, over the rows whose value has a published probability (both sides renormalised; blank and not-applicable fill rows are outside it): mean TVD 0.0009; largest |own - fidelity.csv| per column 0.0000 (columns where it exceeds 0.01: 0).

| Column (largest TVD in fidelity.csv) | fidelity.csv TVD | own TVD |
|---|---|---|
| reportedInsuranceEnrollment | 0.0011 | 0.0011 |
| enrollIndexDxMonth | 0.0006 | 0.0006 |



# Dataset: abm_10pct

Source `ABM`, n requested 161,468. Everything below is computed from `abm_10pct/run/abm_10pct.zip` (one pass over the CSV) and the run's `manifest.json`, `conformance.csv` and `fidelity.csv`.

### 1. Rows, archive, run cost

| Check | Result |
|---|---|
| rows in the CSV | 161,468 (n 161,468): OK |
| columns | 4 |
| zip entries | 1 ['abm_10pct.csv']: OK |
| testzip() | None (OK) |
| zip size | 501,893 bytes |
| CSV size | 23,964,984 bytes |
| SHA-256 of the CSV inside | 2b182a298119a4bad9f731ec4a43792b48a3f5055357acabb661bf384272c21f |
| matches manifest archive.csv_sha256 | yes |
| wall time (CLI, /usr/bin/time -l) | 3.6 s |
| max resident set size | 189 MiB |
| peak memory footprint | 152 MiB |

### 2. Conformance (values outside the dictionary vocabulary)

Columns in the CSV: 4. Columns not in the dictionary: none. Columns with out-of-vocabulary values (own check, blanks excluded): 0. conformance.csv: 0 out-of-vocabulary values in 0 columns.
Columns with blank cells: 0 (blank is how a not-applicable column is written when the dictionary has no null label).

### 3. Not-applicable fraction (manifest na_fraction against the generated data)

Mode `on` (supplied by default), minimum share 0.005. Variables applied: 0, of which written blank: 0. Rows: 161,468.

| Variable | written as | target share | manifest generated share | observed in the CSV | observed - target (points) |
|---|---|---|---|---|---|

Variables skipped, by reason: .

### 4. Published-column fidelity

Manifest: published columns 4, invented columns 0, mean total variation distance over published columns 0.0018. Frequency source counts in fidelity.csv: {'published': 4}.

Own recomputation from the CSV against the dictionary probabilities, over the rows whose value has a published probability (both sides renormalised; blank and not-applicable fill rows are outside it): mean TVD 0.0018; largest |own - fidelity.csv| per column 0.0000 (columns where it exceeds 0.01: 0).

| Column (largest TVD in fidelity.csv) | fidelity.csv TVD | own TVD |
|---|---|---|
| uricA | 0.0025 | 0.0025 |
| persistentPoverty | 0.0019 | 0.0019 |
| yostUSBasedQuintile | 0.0018 | 0.0018 |
| rucaC | 0.0011 | 0.0011 |



# Dataset: ctc_10pct

Source `CTC`, n requested 161,468. Everything below is computed from `ctc_10pct/run/ctc_10pct.zip` (one pass over the CSV) and the run's `manifest.json`, `conformance.csv` and `fidelity.csv`.

### 1. Rows, archive, run cost

| Check | Result |
|---|---|
| rows in the CSV | 161,468 (n 161,468): OK |
| columns | 76 |
| zip entries | 1 ['ctc_10pct.csv']: OK |
| testzip() | None (OK) |
| zip size | 21,482,594 bytes |
| CSV size | 490,217,341 bytes |
| SHA-256 of the CSV inside | dd6dc1ad02be0b14d1638cba48aee82dbbe2a5bf15065e18a58effe571b8e44b |
| matches manifest archive.csv_sha256 | yes |
| wall time (CLI, /usr/bin/time -l) | 16.0 s |
| max resident set size | 402 MiB |
| peak memory footprint | 380 MiB |

### 2. Conformance (values outside the dictionary vocabulary)

Columns in the CSV: 76. Columns not in the dictionary: none. Columns with out-of-vocabulary values (own check, blanks excluded): 0. conformance.csv: 0 out-of-vocabulary values in 0 columns.
Columns with blank cells: 17 (blank is how a not-applicable column is written when the dictionary has no null label).

### 3. Not-applicable fraction (manifest na_fraction against the generated data)

Mode `on` (supplied by default), minimum share 0.005. Variables applied: 32, of which written blank: 17. Rows: 161,468.

| Variable | written as | target share | manifest generated share | observed in the CSV | observed - target (points) |
|---|---|---|---|---|---|
| brainMolecularMarkers | code | 97.6141% | 97.6144% | 97.6144% | +0.000 |
| breslowDepthRecode | code, code also has published counts | 95.1686% | 95.1687% | 95.1699% | +0.001 |
| cocAccreditedFlag | code | 74.6822% | 74.6823% | 74.6823% | +0.000 |
| combinedSsPubDetailed | code, code also has published counts | 24.5206% | 24.5206% | 32.2844% | +7.764 |
| esophagusAndEgjTumorEpicenter | blank | 99.9893% | 99.9895% | 99.9895% | +0.000 |
| gleasonPatternClinicalRecode | code | 99.8849% | 99.8848% | 99.8848% | -0.000 |
| gleasonPatternPathologicRecode | code | 99.8795% | 99.8799% | 99.8799% | +0.000 |
| gleasonScoreClinicalRecode | code | 99.8835% | 99.8836% | 99.8836% | +0.000 |
| gleasonScorePathologicRecode | code | 99.8780% | 99.8780% | 99.8780% | -0.000 |
| gleasonTertiaryPattern | code | 99.9212% | 99.9213% | 99.9213% | +0.000 |
| gradeRecodePre2018 | blank | 25.3597% | 25.3598% | 25.3598% | +0.000 |
| ldhPretreatmentLabValue | code | 97.9078% | 97.9079% | 97.9079% | +0.000 |
| lymphVasInvasionPublic | code, code also has published counts | 96.8329% | 96.8328% | 96.8347% | +0.002 |
| microsatelliteInstability | code | 99.0824% | 99.0822% | 99.0822% | -0.000 |
| p16Recode | code | 99.6242% | 99.6241% | 99.6241% | -0.000 |
| pathReportsFlag | blank | 0.9004% | 0.9005% | 0.9005% | +0.000 |
| psaLabValueRecode | blank | 99.9147% | 99.9145% | 99.9145% | -0.000 |
| radiationRecode | blank | 13.4613% | 13.4615% | 13.4615% | +0.000 |
| reasonForNoRadiation | blank | 74.7477% | 74.7479% | 74.7479% | +0.000 |
| reasonForNoSurgery | blank | 3.9428% | 3.9426% | 3.9426% | -0.000 |
| regionalNodesExamined | blank | 2.1989% | 2.1992% | 2.1992% | +0.000 |
| regionalNodesPositive | blank | 2.2090% | 2.2091% | 2.2091% | +0.000 |
| rxSummBrm | blank | 3.7938% | 3.7939% | 3.7939% | +0.000 |
| rxSummHormone | blank | 3.7928% | 3.7927% | 3.7927% | -0.000 |
| rxSummOther | blank | 3.8351% | 3.8348% | 3.8348% | -0.000 |
| rxSummSurgOthRegDis | blank | 21.7224% | 21.7226% | 21.7226% | +0.000 |
| rxSummSurgPrimSite | code | 14.6781% | 14.6778% | 14.6778% | -0.000 |
| rxSummSurgPrimSite2023 | code | 95.5226% | 95.5223% | 95.5223% | -0.000 |
| rxSummSystemicSurSeq | blank | 34.0544% | 34.0544% | 34.0544% | -0.000 |
| rxSummTransplntEndocr | blank | 7.3036% | 7.3036% | 7.3036% | +0.000 |
| scope2003pPublic | blank | 21.7224% | 21.7226% | 21.7226% | +0.000 |
| treatmentStatusPublic | blank | 44.3164% | 44.3165% | 44.3165% | +0.000 |

Variables skipped, by reason: suppression_only: 6; below_min_share: 4.

Gleason and PSA columns: share of rows that are not applicable or blank (the manifest code for the column, or blank).

| Column | NA code | blank | NA or blank | rows with a real value |
|---|---|---|---|---|
| gleasonPatternClinicalRecode | 99.885% | 0.000% | 99.885% | 186 |
| gleasonPatternPathologicRecode | 99.880% | 0.000% | 99.880% | 194 |
| gleasonScoreClinicalRecode | 99.884% | 0.000% | 99.884% | 188 |
| gleasonScorePathologicRecode | 99.878% | 0.000% | 99.878% | 197 |
| gleasonTertiaryPattern | 99.921% | 0.000% | 99.921% | 127 |
| psaLabValueRecode | 0.000% | 99.915% | 99.915% | 138 |

### 4. Published-column fidelity

Manifest: published columns 76, invented columns 0, mean total variation distance over published columns 0.0080. Frequency source counts in fidelity.csv: {'published': 76}.

Own recomputation from the CSV against the dictionary probabilities, over the rows whose value has a published probability (both sides renormalised; blank and not-applicable fill rows are outside it): mean TVD 0.0359; largest |own - fidelity.csv| per column 0.9568 (columns where it exceeds 0.01: 3).

| Column (largest TVD in fidelity.csv) | fidelity.csv TVD | own TVD |
|---|---|---|
| esophagusAndEgjTumorEpicenter | 0.1050 | 0.1050 |
| gleasonScoreClinicalRecode | 0.0790 | 0.0790 |
| gleasonPatternPathologicRecode | 0.0666 | 0.0666 |
| gleasonPatternClinicalRecode | 0.0631 | 0.0631 |
| gleasonScorePathologicRecode | 0.0538 | 0.0538 |
| psaLabValueRecode | 0.0283 | 0.0283 |
| microsatelliteInstability | 0.0273 | 0.0273 |
| p16Recode | 0.0267 | 0.0267 |



# Dataset: pharm_10pct

Source `PHARM`, n requested 1,301,783. Everything below is computed from `pharm_10pct/run/pharm_10pct.zip` (one pass over the CSV) and the run's `manifest.json`, `conformance.csv` and `fidelity.csv`.

### 1. Rows, archive, run cost

| Check | Result |
|---|---|
| rows in the CSV | 1,301,783 (n 1,301,783): OK |
| columns | 3 |
| zip entries | 1 ['pharm_10pct.csv']: OK |
| testzip() | None (OK) |
| zip size | 2,953,837 bytes |
| CSV size | 60,703,979 bytes |
| SHA-256 of the CSV inside | fb748b369a2dbc56de3f746c28161922fb728e32c6db16baead077cdf1221d7d |
| matches manifest archive.csv_sha256 | yes |
| wall time (CLI, /usr/bin/time -l) | 5.5 s |
| max resident set size | 278 MiB |
| peak memory footprint | 252 MiB |

### 2. Conformance (values outside the dictionary vocabulary)

Columns in the CSV: 3. Columns not in the dictionary: none. Columns with out-of-vocabulary values (own check, blanks excluded): 1. conformance.csv: 0 out-of-vocabulary values in 0 columns.
- medicationDispenseDuration: 1193699 values, e.g. ['0', '1', '10']
Columns with blank cells: 1 (blank is how a not-applicable column is written when the dictionary has no null label).

### 3. Not-applicable fraction (manifest na_fraction against the generated data)

Mode `on` (supplied by default), minimum share 0.005. Variables applied: 1, of which written blank: 1. Rows: 1,301,783.

| Variable | written as | target share | manifest generated share | observed in the CSV | observed - target (points) |
|---|---|---|---|---|---|
| medicationDispenseDuration | blank | 8.3004% | 8.3005% | 8.3005% | +0.000 |

Variables skipped, by reason: .

### 4. Published-column fidelity

Manifest: published columns 3, invented columns 0, mean total variation distance over published columns 0.0010. Frequency source counts in fidelity.csv: {'published': 3}.

Own recomputation from the CSV against the dictionary probabilities, over the rows whose value has a published probability (both sides renormalised; blank and not-applicable fill rows are outside it): mean TVD 0.3339; largest |own - fidelity.csv| per column 0.9986 (columns where it exceeds 0.01: 1).

| Column (largest TVD in fidelity.csv) | fidelity.csv TVD | own TVD |
|---|---|---|
| medicationDispenseDuration | 0.0014 | 1.0000 |
| monthsFromIndexDxtoDispense | 0.0014 | 0.0014 |
| canmedDrugCategory | 0.0004 | 0.0004 |



# Dataset: mcd_10pct

Source `MCD`, n requested 5,666,056. Everything below is computed from `mcd_10pct/run/mcd_10pct.zip` (one pass over the CSV) and the run's `manifest.json`, `conformance.csv` and `fidelity.csv`.

### 1. Rows, archive, run cost

| Check | Result |
|---|---|
| rows in the CSV | 5,666,056 (n 5,666,056): OK |
| columns | 2 |
| zip entries | 1 ['mcd_10pct.csv']: OK |
| testzip() | None (OK) |
| zip size | 8,933,964 bytes |
| CSV size | 66,202,634 bytes |
| SHA-256 of the CSV inside | 2a0bc9ddb7f2e6e4b6adbdf38f30ca5f980534be5cf10617c565d7b31b3c8d7f |
| matches manifest archive.csv_sha256 | yes |
| wall time (CLI, /usr/bin/time -l) | 8.9 s |
| max resident set size | 503 MiB |
| peak memory footprint | 474 MiB |

### 2. Conformance (values outside the dictionary vocabulary)

Columns in the CSV: 2. Columns not in the dictionary: none. Columns with out-of-vocabulary values (own check, blanks excluded): 0. conformance.csv: 0 out-of-vocabulary values in 0 columns.
Columns with blank cells: 0 (blank is how a not-applicable column is written when the dictionary has no null label).

### 3. Not-applicable fraction (manifest na_fraction against the generated data)

Mode `on` (supplied by default), minimum share 0.005. Variables applied: 0, of which written blank: 0. Rows: 5,666,056.

| Variable | written as | target share | manifest generated share | observed in the CSV | observed - target (points) |
|---|---|---|---|---|---|

Variables skipped, by reason: .

### 4. Published-column fidelity

Manifest: published columns 2, invented columns 0, mean total variation distance over published columns 0.0007. Frequency source counts in fidelity.csv: {'published': 2}.

Own recomputation from the CSV against the dictionary probabilities, over the rows whose value has a published probability (both sides renormalised; blank and not-applicable fill rows are outside it): mean TVD 0.0007; largest |own - fidelity.csv| per column 0.0000 (columns where it exceeds 0.01: 0).

| Column (largest TVD in fidelity.csv) | fidelity.csv TVD | own TVD |
|---|---|---|
| monthsFromIndexDxToDiagnosisCode | 0.0010 | 0.0010 |
| claimDiagnosisCodeSequence | 0.0004 | 0.0004 |



# Dataset: mcp_10pct

Source `MCP`, n requested 6,574,550. Everything below is computed from `mcp_10pct/run/mcp_10pct.zip` (one pass over the CSV) and the run's `manifest.json`, `conformance.csv` and `fidelity.csv`.

### 1. Rows, archive, run cost

| Check | Result |
|---|---|
| rows in the CSV | 6,574,550 (n 6,574,550): OK |
| columns | 2 |
| zip entries | 1 ['mcp_10pct.csv']: OK |
| testzip() | None (OK) |
| zip size | 9,497,848 bytes |
| CSV size | 76,691,227 bytes |
| SHA-256 of the CSV inside | fb569e6d8d0fe5f5500fbfcb9e0660c67d738132cf685af2b29db317c33a2027 |
| matches manifest archive.csv_sha256 | yes |
| wall time (CLI, /usr/bin/time -l) | 9.5 s |
| max resident set size | 564 MiB |
| peak memory footprint | 535 MiB |

### 2. Conformance (values outside the dictionary vocabulary)

Columns in the CSV: 2. Columns not in the dictionary: none. Columns with out-of-vocabulary values (own check, blanks excluded): 0. conformance.csv: 0 out-of-vocabulary values in 0 columns.
Columns with blank cells: 0 (blank is how a not-applicable column is written when the dictionary has no null label).

### 3. Not-applicable fraction (manifest na_fraction against the generated data)

Mode `on` (supplied by default), minimum share 0.005. Variables applied: 0, of which written blank: 0. Rows: 6,574,550.

| Variable | written as | target share | manifest generated share | observed in the CSV | observed - target (points) |
|---|---|---|---|---|---|

Variables skipped, by reason: .

### 4. Published-column fidelity

Manifest: published columns 2, invented columns 0, mean total variation distance over published columns 0.0007. Frequency source counts in fidelity.csv: {'published': 2}.

Own recomputation from the CSV against the dictionary probabilities, over the rows whose value has a published probability (both sides renormalised; blank and not-applicable fill rows are outside it): mean TVD 0.0007; largest |own - fidelity.csv| per column 0.0000 (columns where it exceeds 0.01: 0).

| Column (largest TVD in fidelity.csv) | fidelity.csv TVD | own TVD |
|---|---|---|
| monthsFromIndexDxToProcedureCode | 0.0011 | 0.0011 |
| claimProcedureCodeSequence | 0.0003 | 0.0003 |


