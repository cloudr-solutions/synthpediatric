# Heat maps in R: how close is the synthetic cohort to the real one?

## Purpose

`synth_heatmap.R` is an R companion to `synthpediatric validate` for the Output team. It runs **inside the CGC workspace**, next to the real NCCR extract, and writes heat maps that compare a synthetic cohort with the real one, plus the aggregate tables behind them. Only shares and distances are written, never real counts.

All numbers are computed in base R. If `readr` is installed it reads the CSV files; if `ggplot2` is installed it draws the figures. Without them the script falls back to `read.csv` and base graphics, so it needs no package installs.

Minimum R version: 4.5.1. That is the only version tested (macOS arm64, R 4.5.1 (2025-06-13), on cohorts made by the generator). It has not been run in a CGC workspace yet.

## Commands

```bash
Rscript cgc/R/synth_heatmap.R --real <real.csv> --synth <synth.csv|synth.zip> \
    [--vars v1,v2,...] [--pair a,b] [--out <dir>] [--min-cell 16] [--max-vars N]
```

| Option | Meaning | Default |
|---|---|---|
| `--real <file>` | the real extract, one row per record, CSV. It stays in CGC. | required |
| `--synth <file>` | the synthetic cohort: a CSV, or a zip holding exactly one CSV | required |
| `--vars a,b,c` | variables to compare; each must be in both files | every column in both files |
| `--pair a,b` | the two categorical variables for the cell-level comparison | `icccMajor,ageRecode19Groups` when both exist, else the pair with the largest Cramer's V difference |
| `--out <dir>` | output folder; use a new, empty one | `./synth_heatmap_out` |
| `--min-cell <n>` | smallest real cell count that may be shown | 16 |
| `--max-vars <n>` | keep only the n variables with the most non-missing real values | all |

`Rscript cgc/R/synth_heatmap.R --help` prints the same list. Labels with commas or line breaks inside quotes are read as one value. Columns found in only one file are ignored with a warning.

Variable types follow `validate`: a column is numeric when every value in both files is a number and the real cohort has more than 20 distinct values; otherwise it is categorical. Missing values become the category `__missing__` for categorical variables and are dropped for numeric ones.

A self-check runs the measures, the suppression and the audit on small known inputs:

```bash
Rscript cgc/R/test_synth_heatmap.R      # ends with "all checks passed"
```

## Output files

Every figure is written as PNG and PDF.

| File | What it shows |
|---|---|
| `heatmap_cramersv_real`, `heatmap_cramersv_synth` | bias-corrected Cramer's V (Bergsma 2013) for every pair of categorical variables, real and synthetic, on the scale 0 to 1 |
| `heatmap_cramersv_diff` | the absolute difference of the two, on the scale 0 to the largest difference |
| `cramersv_real.csv`, `cramersv_synth.csv`, `cramersv_diff.csv` | the three matrices. Variables are in the same order everywhere, from complete-linkage clustering of 1 - V of the real matrix. |
| `heatmap_univariate`, `univariate_fidelity.csv` | one value per variable: TVD for categorical variables, KS for numeric ones, worst first. Columns: `variable, type, measure, distance`. |
| `heatmap_cell_real_share`, `heatmap_cell_synth_share`, `heatmap_cell_diff` | for the chosen pair, each cell's share of all records, real and synthetic, and synthetic minus real. Grey cells are suppressed. |
| `cell_real_share.csv`, `cell_synth_share.csv`, `cell_diff.csv` | the same three tables. Rows are levels of the first pair variable, columns levels of the second. Blank = suppressed. |
| `summary.txt` | mean and max Cramer's V difference, the 10 worst pairs (var1, var2, real_V, synth_V, abs_diff), the worst univariate distances, the suppressed cell count |

### What the numbers mean and do not mean

* Cramer's V is a marginal pairwise measure. A small difference means each pair of categorical variables is associated about as strongly as in the real data. It is not the discriminator AUC from `synthpediatric validate`, which uses all columns at once and catches patterns no single pair shows. A cohort can have small pairwise differences and still an AUC well above 0.5.
* Cramer's V measures strength, not direction or shape: two tables with very different cell patterns can have the same V. The cell-level maps show the pattern for one pair.
* Cramer's V is noisy for small groups. With few records per category a difference of 0.05 to 0.10 can be sampling noise. Use the replicate envelope in `validate` to tell noise from bias.
* TVD and KS are univariate. They say how well each variable's own distribution matches, nothing about joint structure. TVD is half the sum of absolute differences in category shares (0.05 means 5 % of records would have to change category). KS is the largest gap between the two cumulative distributions.
* Only the 50 most frequent real levels of a variable get their own code in Cramer's V; the rest share one code, as in `validate`.
* A cell share is a share of all records, not of the row.

## Disclosure rules

* **The real extract never leaves CGC.** Only the output files may leave, and only after the script prints `Audit passed: no disclosure violation found`.
* Real counts are never written to any file. The cell tables hold shares only.
* A cell whose real count is below `--min-cell` (16) is suppressed: blank in all three CSVs and grey in all three figures.
* Complementary suppression: if a row of the real table has exactly one suppressed cell, its smallest other cell is suppressed too. The same rule is applied to each column.
* A category label is named in the cell tables only when it has at least 16 real records, and at most 30 levels per variable are shown. Other levels are pooled into `(other levels)`.
* The Cramer's V and univariate files hold association strengths and distances, not counts.
* The final audit reads every output back. It fails if a shown real share times the real row count is below `--min-cell`, if a cell is blank in some cell tables but not all, if a named label has fewer than `--min-cell` real records, if a CSV has a count-like column, or if the output folder holds any file the script did not write. On failure it deletes the outputs and stops with `AUDIT FAILED`.
* Do not lower `--min-cell` below 16 without approval. The script warns if you do.

## Running alongside `synthpediatric validate`

Run both on the same two files, inside CGC:

```bash
synthpediatric validate extract_ctc.csv cohort.csv --label v0 --out-dir validate_out
Rscript cgc/R/synth_heatmap.R --real extract_ctc.csv --synth cohort.csv --out heatmap_out
```

`validate` gives the discriminator AUC, the replicate envelope and the privacy metrics. The R script gives the heat maps. The TVD, KS and Cramer's V values are the same in both: `tests/test_r_heatmap.py` checks them against `validate.py` (they agreed to about 1e-15 on the test cohorts). `validate` also reports the correlation ratio and Spearman for pairs with numeric variables; the R heat maps cover categorical pairs only.

Known differences:

* `validate --dictionary` can force a column's type. The R script always uses the automatic rule.
* `validate` reads parquet and averages over several synthetic cohorts. The R script reads CSV or zip and takes one cohort.

R is not part of CI. Run `python -m pytest tests/test_r_heatmap.py` by hand on a machine with Rscript 4.5.1; the tests skip when Rscript is missing.
