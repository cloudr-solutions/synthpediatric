# DRAFT clinical consistency battery: verification worksheet

**Status: DRAFT, nothing verified.** Every row below is a statement from Section 4 of the
Jamboree read-ahead (also Section 6b of 'additional decisions for Jamboree'). None has been checked against
SEER*Stat or NCCR treatment data, and no clinician has pruned the list. A row becomes a rule
or a test only when its verdict is filled in, and then its `status` in
`examples/battery/ctc_battery_draft.json` is changed from `draft` to `verified` (or `rejected`).

Files: rules and check definitions in `examples/battery/ctc_battery_draft.json`; output checks
in `src/synthpediatric/battery.py`; tests in `tests/test_battery.py`.

## How to fill this in

- **Input team**: run the query in the column "Real data to look at" and write the finding in the
  Notes column (counts must follow the CGC small-cell rule, nothing under 16 leaves CGC).
- **Clinicians**: give the verdict. Use `confirmed`, `corrected: <new wording>` or `reject`.
- **verified by / date / verdict** are blank on purpose.

## Decisions on the open points

| Point | Choice | Why |
|---|---|---|
| Is `allowed_values` enough, or a new rule type? | `allowed_values` is enough. `constraints.py` is not changed. | The only absolute statement that CTC can express (cervical only in females) is a trigger and an allowed set. The other statements are probabilistic, so they are not repair rules and are kept as checks. Existing rule files and outputs are untouched by construction. |
| How does a rule say it is draft? | Every item carries `"status": "draft"` (allowed: `draft`, `verified`, `rejected`), plus `family`, `id` and `source_statement`. The file and every report row repeat it. | `RuleSet.from_dict` reads only the keys it knows, so extra keys are harmless and the same file still loads through `constraints.file`. `Battery.ruleset(statuses=...)` lets a run exclude rejected items. The engine does not refuse draft rules: the status is a label and a filter, not a gate. |
| How are the rule and its check kept from drifting apart? | One file holds both. The hard-rule check calls `find_violations` on the same constraint objects that repair uses. Probabilistic checks sit in the same file under `checks` with the same id, family and status. | Loading fails if an item lacks `id`, `family`, `status`, `source_statement` or `description`, or if ids repeat. A test fails if this worksheet lacks any id in the file. |
| Hard rule or distribution for each statement? | Hard only where the statement is absolute (S1.3). Wording such as 'concentrated', 'rising', 'large majority', 'more than two standard deviations' is a distribution comparison with no pass or fail and no cut-off. | The read-ahead says most items are probabilistic and gives no thresholds. The existing example rules use hard age sets for retinoblastoma and similar; this battery does not copy them because no cut-off is verified. |
| Generation side of probabilistic items | No repair. Each check names the mechanism (`targets.joints` or `targets.survival`) that would reproduce it once a verified cross-tab or survival spec exists. | A resampling repair would distort marginals for a statement that is not absolute. |
| Small-cell suppression | Counts from 1 to `min_cell - 1` are blanked, default `min_cell = 16`, and values derived from them (rates, shares, differences) are blanked too. A count of 0 is shown. Group counts in the stage check are not record counts, but a stage level with fewer than `min_cell` records is left out. | CGC rule. Showing zero is what lets an Output reader see that a hard rule has no violations. The team should confirm that zero may be shown. |

## Real CTC variables used

| Need | CTC variable (column) | Notes |
|---|---|---|
| ICCC group | `icccMajor` (13 groups), `iccc2017Recode`, `iccc2017ExtendedRecode` (144 labels) | Labels differ from the older example files (for example `V RETINOBLASTOMA`, not `V Retinoblastoma`). |
| Primary site, histology | `primarySite`, `histologicTypeIcdO3`, `histologyBehaviorRecodePublic` | Columns exist but have no published value list, so the generator does not produce them. This blocks the testis and ovary statements. |
| Age | `ageRecode19Groups`, `ageRecode20Groups`, `ageRecodeSingle85p`, `ageRecodeSingle90p` | Age groups, not exact ages. |
| Sex | `sex` | Male, Female. |
| Stage | `combinedSsPubDetailed` (2004+), `derivedAjcc7StageGrp` (no value list) | No risk group in CTC. |
| Treatment | `radiationRecode`, `rxSummChemoRecode` (yes or no/unknown), `rxSummTransplntEndocr`, `rxSummBrm`, `monthsFromDxTo*` | No drug names. |
| Vital status, survival | `vitalStatusRecode`; `months` and `event` exist only when the survival rule ran | Real survival months are not in the published metadata. |
| Diagnosis year | `yearOfDiagnosis` | Column exists, no published value list, not generated. |

## Existing example rules and the permissible-value problem (open question)

The Day-1 demo run reported that `examples/ctc_consistency_rules.json` repairs the six prostate
variables to `'Not applicable'`, which is not a permissible value of those variables in the real CTC
metadata (12,187 out-of-vocabulary records per variable in a 20,000-row run, TV distance 0.61). This
battery does not touch those files. Its one repair target (`sex = Female`) is a real permissible
value, and a test asserts that every value the battery writes or reads is in the real metadata.
**Open question for the team**: where a repair needs a 'not applicable' value and none exists
in the real value list, what should the generator write? No value has been invented here.

## Worksheet

Columns: id, family, source sentence, implemented by, real data to look at, verified by, date, verdict, notes.

| id | family | Source sentence (read-ahead) | Implemented by | Real data to look at | Verified by | Date | Verdict | Notes |
|---|---|---|---|---|---|---|---|---|
| S1.1 | sex_restricted_sites | Sex-restricted sites: testicular germ cell tumors only in males | roadmap only: CTC has no testis or ovary category. ICCC group Xc (gonadal germ cell tumors) mixes both sexes. Primary Site (primarySite) and histology (histologicTypeIcdO3) are CTC columns but have no published value list, so they are not generated. | Roadmap, not implemented. Needs: A published value list for primarySite, or a testis-versus-ovary split in the ICCC variables. |  |  |  |  |
| S1.2 | sex_restricted_sites | ovarian ... only in females | roadmap only: Same as S1.1: no ovary category in the generated CTC variables. | Roadmap, not implemented. Needs: A published value list for primarySite. |  |  |  |  |
| S1.3 | sex_restricted_sites | cervical only in females | rule `cervical_carcinoma_is_female` (repair) + hard check, same object | SEER*Stat, CTC frequency: Sex by iccc2017ExtendedRecode = 'XIf7 Carcinomas of cervix uteri'. Expect zero Male records. If any exist, report them and do not turn this into a rule. |  |  |  |  |
| S2.1 | age_implausible_diagnoses | retinoblastoma ... concentrated in early childhood | check `age_retinoblastoma` (distribution); no repair rule | SEER*Stat frequency of Age recode with <1 year olds (ageRecode19Groups) for the group below, by 5-year band of year of diagnosis. Give the real shape to clinicians to confirm the wording 'concentrated'/'rising', and say which age groups count as early childhood or adolescence. Group: iccc2017ExtendedRecode = 'V RETINOBLASTOMA'. |  |  |  |  |
| S2.2 | age_implausible_diagnoses | hepatoblastoma ... concentrated in early childhood | check `age_hepatoblastoma` (distribution); no repair rule | SEER*Stat frequency of Age recode with <1 year olds (ageRecode19Groups) for the group below, by 5-year band of year of diagnosis. Give the real shape to clinicians to confirm the wording 'concentrated'/'rising', and say which age groups count as early childhood or adolescence. Group: iccc2017ExtendedRecode = 'VIIa1 Hepatoblastoma'. |  |  |  |  |
| S2.3 | age_implausible_diagnoses | neuroblastoma concentrated in early childhood | check `age_neuroblastoma` (distribution); no repair rule | SEER*Stat frequency of Age recode with <1 year olds (ageRecode19Groups) for the group below, by 5-year band of year of diagnosis. Give the real shape to clinicians to confirm the wording 'concentrated'/'rising', and say which age groups count as early childhood or adolescence. Group: iccc2017ExtendedRecode = 'IVa Neuroblastoma and ganglioneuroblastoma'. |  |  |  |  |
| S2.4 | age_implausible_diagnoses | Hodgkin lymphoma ... rising through adolescence | check `age_hodgkin` (distribution); no repair rule | SEER*Stat frequency of Age recode with <1 year olds (ageRecode19Groups) for the group below, by 5-year band of year of diagnosis. Give the real shape to clinicians to confirm the wording 'concentrated'/'rising', and say which age groups count as early childhood or adolescence. Group: iccc2017ExtendedRecode = 'IIa Hodgkin lymphomas'. |  |  |  |  |
| S2.5 | age_implausible_diagnoses | bone sarcomas ... rising through adolescence | check `age_bone_tumors` (distribution); no repair rule | SEER*Stat frequency of Age recode with <1 year olds (ageRecode19Groups) for the group below, by 5-year band of year of diagnosis. Give the real shape to clinicians to confirm the wording 'concentrated'/'rising', and say which age groups count as early childhood or adolescence. Group: icccMajor = 'VIII. Malignant Bone Tumors'. Clinicians: is ICCC major group VIII the right stand-in for 'bone sarcomas' (it includes chondrosarcoma and chordoma)? |  |  |  |  |
| S2.6 | age_implausible_diagnoses | thyroid carcinoma rising through adolescence | check `age_thyroid` (distribution); no repair rule | SEER*Stat frequency of Age recode with <1 year olds (ageRecode19Groups) for the group below, by 5-year band of year of diagnosis. Give the real shape to clinicians to confirm the wording 'concentrated'/'rising', and say which age groups count as early childhood or adolescence. Group: iccc2017ExtendedRecode = 'XIb Thyroid carcinomas'. |  |  |  |  |
| S2.7 | age_implausible_diagnoses | a flag for any diagnosis more than two standard deviations outside its real age distribution | check `age_outlier_flag` (age_outlier); no repair rule | SEER*Stat age distribution (ageRecode19Groups) per iccc2017ExtendedRecode group. Input team: supply the real counts as a reference table and decide whether 2 SD on age-group midpoints is meaningful, or whether single-year age (ageRecodeSingle85p) is needed. Clinicians: confirm the 2 SD threshold. |  |  |  |  |
| S3.1 | diagnosis_treatment_coherence | asparaginase and vincristine-heavy regimens with acute lymphoblastic leukemia | roadmap only: CTC records chemotherapy only as yes or no/unknown (rxSummChemoRecode). Drug names live in pharmacy claims (PHARM), which are a separate table. | Roadmap, not implemented. Needs: Linked PHARM and CTC (Option B). |  |  |  |  |
| S3.2 | diagnosis_treatment_coherence | cisplatin with germ cell tumors and hepatoblastoma | roadmap only: Same as S3.1: no drug names in CTC. | Roadmap, not implemented. Needs: Linked PHARM and CTC (Option B). |  |  |  |  |
| S3.3 | diagnosis_treatment_coherence | no radiation for the large majority of standard-risk ALL | check `radiation_precursor_leukemia` (distribution); no repair rule | SEER*Stat frequency of Radiation recode (radiationRecode) for iccc2017ExtendedRecode = 'Ia1 Precursor cell leukemias', by age group and year of diagnosis. Check how much of 'None/Unknown' is truly unknown. Standard-risk ALL cannot be isolated in CTC: ask whether COG data can. |  |  |  |  |
| S3.4 | diagnosis_treatment_coherence | stem cell transplant concentrated in high-risk neuroblastoma, relapsed leukemia, and selected lymphomas | check `transplant_by_diagnosis` (distribution); no repair rule | SEER*Stat frequency of icccMajor among records with RX Summ--Transplnt/Endocr (rxSummTransplntEndocr) in the four transplant codes listed in the check. Compare with the statement. High-risk neuroblastoma and relapse are not in CTC. Clinicians: is 'Stem cell harvest and infusion' a transplant? |  |  |  |  |
| S4.1 | stage_risk_outcome_monotonicity | survival should decrease with stage or risk group within each diagnosis | check `survival_decreases_with_stage` (stage_monotone); no repair rule | SEER*Stat survival session (case listing with survival months and vital status): 5-year relative or observed survival by Combined Summary Stage (combinedSsPubDetailed) within each icccMajor group. Check that survival falls from localized to regional to distant. Clinicians: confirm the stage ordering, especially among the three regional levels. Diagnosis years 2004+ only for this variable. |  |  |  |  |
| S4.2 | stage_risk_outcome_monotonicity | 5-year survival by diagnosis should match SEER*Stat (e.g., ALL around 90%) | check `five_year_survival_all` (survival_5y); no repair rule | SEER*Stat survival session: 5-year survival for iccc2017ExtendedRecode = 'Ia1 Precursor cell leukemias'. Decide and record the population (ages, diagnosis years, observed or relative survival) and replace the 0.90 target in the file with the verified number and its source. |  |  |  |  |
| S4.3 | stage_risk_outcome_monotonicity | (e.g., ... high-risk neuroblastoma around 50%) | roadmap only: CTC has no neuroblastoma risk group. Only neuroblastoma overall (ICCC IVa) is available. | Not checkable on CTC (no risk group). Record what COG or other data would carry the high-risk neuroblastoma figure. |  |  |  |  |
| S5.1 | temporal_ordering | diagnosis before COG enrollment before first chemotherapy claim before first pharmacy fill | roadmap only: Needs COG enrollment, claim and fill dates in four tables. CTC holds only month-from-diagnosis bins for first-course treatment. | Roadmap, not implemented. Needs: Linked COG, MCP and PHARM tables with event dates (Option B). |  |  |  |  |
| S5.2 | temporal_ordering | central line placement near treatment start | roadmap only: Central line procedures are claims in MCP. CTC has no procedure dates. | Roadmap, not implemented. Needs: Linked MCP and CTC (Option B). |  |  |  |  |
| S5.3 | temporal_ordering | no encounters, claims, or fills after date of death | roadmap only: Needs claim and fill dates plus a date of death. CTC has vital status but no date of death in the generated variables, and no claim tables. | Roadmap, not implemented. Needs: Linked MCD, MCP, PHARM and CTC with dates (Option B). |  |  |  |  |
| S5.4 | temporal_ordering | insurance coverage overlapping treatment dates | roadmap only: Enrollment is in MCE and treatment dates are in claims. Not in CTC. | Roadmap, not implemented. Needs: Linked MCE and claims tables (Option B). |  |  |  |  |
| S6.1 | era_effects | protocol names, targeted agents, and immunotherapies appearing only in diagnosis years when they existed | roadmap only: Year of Diagnosis (yearOfDiagnosis) is a CTC column but has no published value list, so it is not generated. No list of which protocols and agents existed in which years exists in the project. CTC has no protocol or agent names. | Roadmap, not implemented. Needs: A yearOfDiagnosis value list, an era table for agents, and drug-level data (PHARM). |  |  |  |  |
| S6.2 | era_effects | survival improving across treatment eras | roadmap only: Needs yearOfDiagnosis in the cohort. It is not generated today. | Roadmap, not implemented. Needs: A yearOfDiagnosis value list and survival by year of diagnosis from SEER*Stat. After that this becomes a check on the CTC table. |  |  |  |  |
| S7.1 | utilization_shape | inpatient-heavy claims during induction, tapering through maintenance | roadmap only: Needs claim-level utilization over time (MCD, MCP). CTC has no claims. | Roadmap, not implemented. Needs: Claims tables with service dates (Option B). |  |  |  |  |
| S7.2 | utilization_shape | a survivorship pattern of periodic surveillance visits | roadmap only: Needs repeated visit data over time. Not in CTC. | Roadmap, not implemented. Needs: Claims tables with service dates (Option B). |  |  |  |  |
| S7.3 | utilization_shape | antiemetic and growth-factor fills clustered around chemotherapy cycles | roadmap only: Needs pharmacy fills and chemotherapy dates (PHARM, MCP). | Roadmap, not implemented. Needs: Linked PHARM and MCP (Option B). |  |  |  |  |
| S8.1 | late_effects | cardiac diagnoses more frequent after anthracycline exposure | roadmap only: Needs anthracycline exposure (PHARM) and cardiac diagnoses (MCD) linked per patient. CTC has neither. | Roadmap, not implemented. Needs: Linked PHARM, MCD and CTC (Option B). |  |  |  |  |
| S8.2 | late_effects | secondary malignancies rising with time since radiation | roadmap only: CTC has sequence number and months from index diagnosis to tumor, but no radiation date relative to the second tumor, and only first-course radiation. The interval the statement needs cannot be formed. | Roadmap, not implemented. Needs: Radiation Oncology (RO) dates linked to CTC (Option B), or a clinician-agreed proxy from CTC columns. |  |  |  |  |

## Not in the read-ahead, noticed while reading CTC (not implemented)

- CTC has `monthsFromDxTo*` bins next to yes or no treatment fields. A treatment flag of No
  paired with a month value would be incoherent, but no read-ahead statement says so. Clinicians
  may want to add it.

## Reading the report

`run_battery` returns one row per item. `result` is `ok` or `VIOLATIONS` for hard rules,
`compared` or `needs_reference` for distribution checks (no pass or fail), `reported` for the stage
check without a reference, `not_evaluable` when a column is missing, `suppressed` when a count is
under the threshold, and `not_implementable` for roadmap items.
