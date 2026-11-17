#!/usr/bin/env Rscript
# Self-check for synth_heatmap.R. Base R only. Run from the repo root:
#   Rscript cgc/R/test_synth_heatmap.R
# Exits with status 1 and lists the failed checks if anything is wrong.

args <- commandArgs(trailingOnly = FALSE)
here <- dirname(sub("^--file=", "", args[grep("^--file=", args)][1]))
source(file.path(here, "synth_heatmap.R"))

failures <- character(0)
check <- function(ok, what) {
  if (!isTRUE(ok)) failures <<- c(failures, what)
  cat(if (isTRUE(ok)) "ok    " else "FAIL  ", what, "\n", sep = "")
}
near <- function(a, b, tol = 1e-9) isTRUE(all(abs(a - b) < tol))

# Cramer's V: a perfect 2x2 association and an independent table.
ca <- c(rep(1L, 50), rep(2L, 50)); cb <- ca
check(near(cramers_v(ca, 2L, cb, 2L), 1), "Cramer's V is 1 for a perfect association")
ind_a <- rep(1:2, each = 50); ind_b <- rep(1:2, times = 50)
check(near(cramers_v(ind_a, 2L, ind_b, 2L), 0), "Cramer's V is 0 for independent columns")
check(near(cramers_v(rep(1L, 20), 2L, rep(1L, 20), 2L), 0), "Cramer's V is 0 for a constant column")

# Hand-computed value: table [[30,10],[10,30]], n = 80, bias-corrected.
a <- c(rep(1L, 40), rep(2L, 40)); b <- c(rep(1L, 30), rep(2L, 10), rep(1L, 10), rep(2L, 30))
phi2 <- 0.25                                   # chi2 = 20, n = 80
phi2c <- max(0, phi2 - 1 / 79)
k <- 2 - 1 / 79
check(near(cramers_v(a, 2L, b, 2L), sqrt(phi2c / (k - 1))), "Cramer's V matches the Bergsma formula")

# TVD and KS.
check(near(tv_distance(c("a", "a", "b", "b"), c("a", "b", "b", "b")), 0.25), "TVD of two small samples")
check(near(tv_distance(c("a", "b"), c("c", "d")), 1), "TVD is 1 for disjoint samples")
check(near(ks_distance(c(1, 2, 3, 4), c(1, 2, 3, 4)), 0), "KS is 0 for equal samples")
check(near(ks_distance(c(1, 2, 3, 4), c(3, 4, 5, 6)), 0.5), "KS of shifted samples")
check(is.na(ks_distance(c(NA_real_), c(1, 2))), "KS is NA for an empty side")


# Suppression rule (validate._suppress).
check(identical(suppress_flags(c(100, 5, 50, 40), 16), c(FALSE, TRUE, FALSE, TRUE)),
      "one small count also hides the smallest other count")
check(identical(suppress_flags(c(100, 5, 8, 40), 16), c(FALSE, TRUE, TRUE, FALSE)),
      "two small counts hide only themselves")
check(identical(suppress_flags(c(100, 50), 16), c(FALSE, FALSE)), "nothing small, nothing hidden")
tab <- matrix(c(200, 150, 5, 120, 180, 100, 90, 110, 80), 3, 3, byrow = TRUE)
fl <- suppress_table(tab, 16)
check(identical(which(fl), which(matrix(c(FALSE, TRUE, TRUE, FALSE, FALSE, FALSE, FALSE, FALSE, TRUE), 3, 3, byrow = TRUE))),
      "table: the small cell, its row partner and its column partner are hidden")

# Missing-value tokens, types and labels.
col <- prep_column(c("1", "2", NA, "3.0"))
check(col$numdtype && identical(col$cat, c("1", "2", MISSING, "3")), "integral numbers get integer labels")
col2 <- prep_column(c("1", "2.5", NA))
check(identical(col2$cat, c("1.0", "2.5", MISSING)), "a column with fractions keeps '.0' like pandas")
check(!prep_column(c("a", "1"))$numdtype, "a column with text is not numeric")
check(identical(detect_type(prep_column(as.character(1:30)), prep_column(as.character(1:30))), "numeric"),
      "a numeric column with more than 20 values is numeric")
check(identical(detect_type(prep_column(as.character(1:5)), prep_column(as.character(1:5))), "categorical"),
      "a numeric column with 5 values is categorical")

# CSV with a quoted label that holds a line break and a comma.
tmp <- tempfile(fileext = ".csv")
writeLines(c("id,label", "1,\"Leukemia,\nlymphoma\"", "2,plain", "3,"), tmp)
rd <- read_cohort(tmp)
check(nrow(rd) == 3L && identical(rd$label[1], "Leukemia,\nlymphoma") && is.na(rd$label[3]),
      "a quoted label with a line break is read as one field; blank is missing")
tmpzip <- file.path(tempdir(), "one.zip")
old <- setwd(dirname(tmp)); zip_ok <- tryCatch({ utils::zip(tmpzip, basename(tmp), flags = "-q"); TRUE }, error = function(e) FALSE, warning = function(w) FALSE)
setwd(old)
if (zip_ok && file.exists(tmpzip)) {
  check(nrow(read_cohort(tmpzip)) == 3L, "a zip with one CSV is read")
} else {
  cat("skip  zip read (no zip program on this machine)\n")
}

# Cell comparison: a small real cell must never show.
set.seed(1)
make_pair <- function(counts) {
  g <- rep(rep(c("G1", "G2", "G3"), each = 3), times = as.vector(t(counts)) / as.vector(t(counts)) * 0 + 1)
  rows <- rep(c("G1", "G2", "G3"), each = 3); cols <- rep(c("H1", "H2", "H3"), times = 3)
  list(a = rep(rows, times = as.vector(t(counts))), b = rep(cols, times = as.vector(t(counts))))
}
real <- make_pair(tab)
syn <- make_pair(matrix(c(190, 160, 12, 130, 170, 95, 100, 100, 85), 3, 3, byrow = TRUE))
cc <- cell_comparison(real$a, real$b, syn$a, syn$b, 16)
check(is.na(cc$real_share["G1", "H3"]) && is.na(cc$syn_share["G1", "H3"]) && is.na(cc$diff["G1", "H3"]),
      "the small cell shows no real share, synthetic share or difference")
check(is.na(cc$real_share["G1", "H2"]) && is.na(cc$real_share["G3", "H3"]),
      "complementary cells are hidden in the row and the column")
check(!is.na(cc$real_share["G2", "H2"]) && near(cc$real_share["G2", "H2"], 180 / sum(tab)), "a large cell shows its real share")
ii <- rep(seq_along(cc$rows), times = length(cc$cols)); jj <- rep(seq_along(cc$cols), each = length(cc$rows))
df <- data.frame(row_level = cc$rows[ii], col_level = cc$cols[jj],
                 real_share = cc$real_share[cbind(ii, jj)], synthetic_share = cc$syn_share[cbind(ii, jj)],
                 diff_synthetic_minus_real = cc$diff[cbind(ii, jj)], stringsAsFactors = FALSE)
check(sum(cc$flags) == 3L && all(is.na(cc$real_share[cc$flags])), "three cells are blanked")
check(length(audit_cell_frame(df, real$a, real$b, 16)) == 0L, "the audit passes a correct table")
bad <- df
k <- bad$row_level == "G1" & bad$col_level == "H3"
bad$real_share[k] <- 5 / sum(tab); bad$synthetic_share[k] <- 0.01; bad$diff_synthetic_minus_real[k] <- 0
check(length(audit_cell_frame(bad, real$a, real$b, 16)) > 0L, "the audit catches a leaked small cell")
bad2 <- df
bad2$real_share[bad2$row_level == "G2" & bad2$col_level == "H2"] <- NA
check(length(audit_cell_frame(bad2, real$a, real$b, 16)) > 0L, "the audit catches a cell blank in only one table")

# A rare label must not be released: level H4 has 6 records in total.
real2 <- list(a = c(real$a, rep("G1", 6)), b = c(real$b, rep("H4", 6)))
cc2 <- cell_comparison(real2$a, real2$b, syn$a, syn$b, 16)
check(!("H4" %in% cc2$cols) && OTHER_LABEL %in% cc2$cols, "a label with fewer than 16 real records is pooled, not named")

if (length(failures)) {
  cat("\n", length(failures), " check(s) failed\n", sep = "")
  quit(status = 1)
}
cat("\nall checks passed\n")
