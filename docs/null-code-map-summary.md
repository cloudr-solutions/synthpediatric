# Null-code map: summary

Built from: nccr_instances.ttl

3,978 permissible values, 919 classified as null-type (not_applicable 372, unknown 67, no_data 457, not_performed 23), 3,059 real. 0 per-code overrides applied.

## Values per source and kind

| source | values | not_applicable | unknown | no_data | not_performed | real |
|---|---:|---:|---:|---:|---:|---:|
| ABM | 22 | 0 | 0 | 9 | 0 | 13 |
| CCDI | 74 | 0 | 0 | 0 | 0 | 74 |
| COG | 33 | 0 | 0 | 7 | 0 | 26 |
| CTC | 2,169 | 25 | 64 | 40 | 23 | 2,017 |
| MCD | 65 | 0 | 0 | 1 | 0 | 64 |
| MCE | 1,093 | 347 | 0 | 385 | 0 | 361 |
| MCP | 65 | 0 | 0 | 1 | 0 | 64 |
| PHARM | 133 | 0 | 0 | 2 | 0 | 131 |
| RO | 324 | 0 | 3 | 12 | 0 | 309 |
| **all** | 3,978 | 372 | 67 | 457 | 23 | 3,059 |

## Borderline classifications for review (37 distinct descriptions)

| kind | rule | description | values | examples |
|---|---|---|---:|---|
| no_data | no_data_not_provided | Enrollment Status not Provided | 24 | MCE.enrollMonthPostIndexDx1.6, MCE.enrollMonthPostIndexDx10.6, ... |
| no_data | no_data_not_provided | Patient not Found at Time of Linkage | 2 | COG.reportedCOGEnrollment.0, MCE.reportedInsuranceEnrollment.0 |
| not_applicable | na_not_paired | Not a paired site | 1 | CTC.laterality.0 |
| not_applicable | na_or_in_text | Tumor Size Not Consistent Over Time or Not Applicable for this Site | 2 | CTC.tumorSizeOverTime.XX1, CTC.tumorSizeOverTime.XX2 |
| not_applicable | na_period | Diagnosed after 2022 or before 1998 | 1 | CTC.rxSummSurgPrimSite.Blank |
| not_applicable | na_period | Diagnosed prior to 2023 | 1 | CTC.rxSummSurgPrimSite2023.Blank |
| not_performed | not_performed_was | Hematologic transplant and/or endocrine surgery/radiation was not administered because the patient died prior to planned or recommended ther | 1 | CTC.rxSummTransplntEndocr.85 |
| not_performed | not_performed_was | Hematologic transplant and/or endocrine surgery/radiation was not administered. It was recommended by the patient's physician, but was not a | 1 | CTC.rxSummTransplntEndocr.86 |
| not_performed | not_performed_was | Hematologic transplant and/or endocrine surgery/radiation was not administered; it was recommended by the patient's physician, but this trea | 1 | CTC.rxSummTransplntEndocr.87 |
| not_performed | not_performed_was | Hormone therapy was not administered because the patient died prior to planned or recommended therapy. | 1 | CTC.rxSummHormone.85 |
| not_performed | not_performed_was | Hormone therapy was not administered. It was recommended by the patient's physician, but this treatment was refused by the patient, the pati | 1 | CTC.rxSummHormone.87 |
| not_performed | not_performed_was | Hormone therapy was not administered. It was recommended by the patient's physician, but was not administered as part of first-course therap | 1 | CTC.rxSummHormone.86 |
| not_performed | not_performed_was | Immunotherapy was not administered because the patient died prior to planned or recommended therapy. | 1 | CTC.rxSummBrm.85 |
| not_performed | not_performed_was | Immunotherapy was not administered. It was recommended by the patient's physician, but this treatment was refused by the patient, the patien | 1 | CTC.rxSummBrm.87 |
| not_performed | not_performed_was | Immunotherapy was not administered. It was recommended by the patient's physician, but was not administered as part of first-course therapy. | 1 | CTC.rxSummBrm.86 |
| not_performed | not_performed_was | Radiation therapy was not administered because it was contraindicated due to patient risk factors (comorbid conditions, advanced age, etc). | 1 | CTC.reasonForNoRadiation.2 |
| not_performed | not_performed_was | Radiation therapy was not administered because it was not part of the planned first-course treatment. Diagnosed at autopsy. | 1 | CTC.reasonForNoRadiation.1 |
| not_performed | not_performed_was | Radiation therapy was not administered because the patient died prior to planned or recommended treatment. | 1 | CTC.reasonForNoRadiation.5 |
| not_performed | not_performed_was | Radiation therapy was not administered; it was recommended by the patient's physician, but this treatment was refused by the patient, the pa | 1 | CTC.reasonForNoRadiation.7 |
| not_performed | not_performed_was | Radiation therapy was not administered; it was recommended by the patient's physician, but was not administered as part of the first-course  | 1 | CTC.reasonForNoRadiation.6 |
| not_performed | not_performed_was | Surgery of the primary site was not performed because it was not part of the planned first-course treatment. | 1 | CTC.reasonForNoSurgery.1 |
| not_performed | not_performed_was | Surgery of the primary site was not performed because the patient died prior to planned or recommended surgery. | 1 | CTC.reasonForNoSurgery.5 |
| not_performed | not_performed_was | Surgery of the primary site was not performed; it was recommended by the patient's physician, but this treatment was refused by the patient, | 1 | CTC.reasonForNoSurgery.7 |
| not_performed | not_performed_was | Surgery of the primary site was not performed; it was recommended by the patient's physician, but was not performed as part of the first-cou | 1 | CTC.reasonForNoSurgery.6 |
| unknown | unknown_gleason_both | Primary pattern unknown, secondary pattern unknown | 2 | CTC.gleasonPatternClinicalRecode.X6, CTC.gleasonPatternPathologicRecode.X6 |
| unknown | unknown_no_information | Paired site, but no information concerning laterality | 1 | CTC.laterality.9 |
| unknown | unknown_not_classified | Not Yet Classified by NAACCR NCCR Metadata Working Group | 5 | CTC.nccrSiteMorphRecodeLevel1.6666666, CTC.nccrSiteMorphRecodeLevel2.6666666, ... |
| unknown | unknown_not_classified | Test ordered, results not in chart | 3 | CTC.brainMolecularMarkers.87, CTC.ldhPretreatmentLabValue.XXXXX.7, ... |
| unknown | unknown_not_documented | X: Esophagus, NOS Specific location of epicenter not documented in medical record Specific location of epicenter not assessed or unknown if  | 1 | CTC.esophagusAndEgjTumorEpicenter.9 |
| unknown | unknown_or_na | It is unknown whether nodes are positive; not applicable; not stated in patient record | 1 | CTC.regionalNodesPositive.99 |
| unknown | unknown_or_na | Unknown or not applicable | 1 | CTC.scope2003pPublic.9 |
| unknown | unknown_race | Non-Hispanic Unknown Race | 1 | CTC.raceAndOriginRecode.9 |
| unknown | unknown_trail | Borderline/Unknown | 3 | CTC.erRecode.4, CTC.her2Recode.4, ... |
| unknown | unknown_trail | No/Unknown | 1 | CTC.rxSummChemoRecode.0 |
| unknown | unknown_trail | None/Unknown | 1 | CTC.radiationRecode.0 |
| unknown | unknown_trail | Number of regional lymph nodes removed unknown | 1 | CTC.scope2003pPublic.3 |
| unknown | unknown_trail | Regional lymph nodes were surgically removed, but the number of lymph nodes is unknown/not stated and not documented as a sampling or dissec | 1 | CTC.regionalNodesExamined.98 |

## False positives excluded (51 values, 33 distinct descriptions)

A keyword scan (unknown, unspecified, missing, not classified, refused, ...) flags these, the rules keep them real.

| description | values | example |
|---|---:|---|
| Bilateral involvement at time of diagnosis, lateral origin unknown for a single primary; or both ovaries involved simultaneously, single his | 1 | CTC.laterality.4 |
| IIId2 Mixed and unspecified gliomas | 1 | CTC.iccc2017ExtendedRecode.025 |
| IIIf Unspecified intracranial and intraspinal neoplasms | 2 | CTC.iccc2017ExtendedRecode.032 |
| IIa1.5 Classic HL, subtype unknown or other | 1 | CTC.nccrSiteMorphRecodeLevel4.358758 |
| IIe Unspecified lymphomas | 2 | CTC.iccc2017ExtendedRecode.016 |
| IXe Unspecified soft tissue sarcomas | 2 | CTC.iccc2017ExtendedRecode.071 |
| Ie Unspecified and other specified leukemias | 3 | CTC.iccc2017ExtendedRecode.008 |
| No radiation and/or no surgery; unknown if surgery and/or radiation given | 1 | CTC.rxSummSurgRadSeq.0 |
| No systemic therapy and/or surgical procedures; unknown if surgery and/or systemic therapy given | 1 | CTC.rxSummSystemicSurSeq.0 |
| Not classified by ICCC or in situ | 1 | CTC.iccc2017Recode.999 |
| Not classified by SEER or in situ | 2 | CTC.iccc2017ExtendedRecode.999 |
| Only one side involved, right or left origin unspecified | 1 | CTC.laterality.3 |
| Positive nodes are documented, but the number is unspecified | 1 | CTC.regionalNodesPositive.97 |
| Primary pattern 1, secondary pattern unknown | 2 | CTC.gleasonPatternClinicalRecode.19 |
| Primary pattern 2, secondary pattern unknown | 2 | CTC.gleasonPatternClinicalRecode.29 |
| Primary pattern 3, secondary pattern unknown | 2 | CTC.gleasonPatternClinicalRecode.39 |
| Primary pattern 4, secondary pattern unknown | 2 | CTC.gleasonPatternClinicalRecode.49 |
| Primary pattern 5, secondary pattern unknown | 2 | CTC.gleasonPatternClinicalRecode.59 |
| Refused (1988+) | 1 | CTC.radiationRecode.7 |
| Regional lymph node removal was documented as a dissection, and the number of nodes is unknown/not stated | 1 | CTC.regionalNodesExamined.97 |
| Regional lymph node removal was documented as a sampling, and the number of nodes is unknown/not stated | 1 | CTC.regionalNodesExamined.96 |
| Sequence indicator for patient with at least one radiation record with missing start date | 1 | RO.sequenceId.901-998 |
| Sequence unknown, but both surgery and radiation were given | 1 | CTC.rxSummSurgRadSeq.9 |
| Sequence unknown, but both surgery and systemic therapy given | 1 | CTC.rxSummSystemicSurSeq.9 |
| VIIIe Unspecified malignant bone tumors | 2 | CTC.iccc2017ExtendedRecode.054 |
| VIIc Unspecified malignant hepatic tumors | 2 | CTC.iccc2017ExtendedRecode.045 |
| VIc Unspecified malignant renal tumors | 2 | CTC.iccc2017ExtendedRecode.040 |
| XII OTHER AND UNSPECIFIED MALIGNANT NEOPLASMS | 2 | CTC.iccc2017ExtendedRecode.109-115 |
| XII. Other And Unspecified Malignant Neoplasms | 1 | CTC.icccMajor.12 |
| XIIb Other unspecified malignant tumors | 2 | CTC.iccc2017ExtendedRecode.115 |
| XIf Other and unspecified carcinomas | 2 | CTC.iccc2017ExtendedRecode.98-108 |
| XIf11 Carcinomas of unspecified site | 1 | CTC.iccc2017ExtendedRecode.108 |
| Xe Other and unspecified malignant gonadal tumors | 2 | CTC.iccc2017ExtendedRecode.092 |
