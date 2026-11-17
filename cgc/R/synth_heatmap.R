#!/usr/bin/env Rscript
# synth_heatmap.R: compare a synthetic cohort with the real cohort and draw heat maps.
#
# Run it INSIDE the CGC workspace, where the real extract lives:
#   Rscript cgc/R/synth_heatmap.R --real real.csv --synth cohort.zip --out heatmap_out
#
# All numbers are computed in base R. readr and ggplot2 are used only when installed
# (reading and drawing). The numbers follow `synthpediatric validate`
# (src/synthpediatric/validate.py) so that the R and Python results agree:
#   variable types, missing values, TVD, KS, bias-corrected Cramer's V,
#   and the minimum cell size 16 with complementary suppression.
# See cgc/R/README.md for the options, the outputs and the disclosure rules.

SH_VERSION <- "0.2.0"
# Optional packages. Numbers are always computed in base R; these only read files and draw.
# SYNTH_HEATMAP_BASE_ONLY=1 forces the base-R path (used to test it).
.base_only <- nzchar(Sys.getenv("SYNTH_HEATMAP_BASE_ONLY"))
HAS_GGPLOT2 <- !.base_only && requireNamespace("ggplot2", quietly = TRUE)
HAS_READR   <- !.base_only && requireNamespace("readr", quietly = TRUE)
HAS_DT      <- requireNamespace("data.table", quietly = TRUE)
MISSING <- "__missing__"
OTHER_LABEL <- "(other levels)"
DEFAULT_MIN_CELL <- 16L
MAX_CELL_LEVELS <- 30L
ALLOWED_EXT <- c("png", "pdf", "csv", "txt")
# The strings pandas.read_csv reads as missing, so R and Python see the same blanks.
NA_TOKENS <- c("", "#N/A", "#N/A N/A", "#NA", "-1.#IND", "-1.#QNAN", "-NaN", "-nan",
               "1.#IND", "1.#QNAN", "<NA>", "N/A", "NA", "NULL", "NaN", "None", "n/a",
               "nan", "null")

# ------------------------------------------------------------------ reading data

# Every column is read as text, so no value is converted before we decide its type.
read_csv_text <- function(path) {
  if (HAS_READR) {
    df <- tryCatch(
      as.data.frame(readr::read_csv(path, col_types = readr::cols(.default = readr::col_character()),
                                    na = character(), name_repair = "minimal", progress = FALSE,
                                    trim_ws = FALSE, show_col_types = FALSE),
                    stringsAsFactors = FALSE, check.names = FALSE),
      error = function(e) NULL)
    if (!is.null(df)) return(df)
  }
  utils::read.csv(path, colClasses = "character", na.strings = "\001none\001",
                  check.names = FALSE, stringsAsFactors = FALSE, comment.char = "",
                  quote = "\"", strip.white = FALSE, fileEncoding = "UTF-8-BOM")
}

read_cohort <- function(path) {
  if (!file.exists(path)) stop("file not found: ", path)
  if (grepl("\\.zip$", path, ignore.case = TRUE)) {
    members <- utils::unzip(path, list = TRUE)$Name
    csvs <- members[grepl("\\.csv$", members, ignore.case = TRUE) &
                      !grepl("(^|/)__MACOSX/|(^|/)\\._", members)]
    if (length(csvs) != 1L) {
      stop("the zip ", path, " must contain exactly one .csv file, found ", length(csvs))
    }
    tmp <- tempfile("synth_zip_")
    dir.create(tmp)
    on.exit(unlink(tmp, recursive = TRUE), add = TRUE)
    utils::unzip(path, files = csvs, exdir = tmp)
    df <- read_csv_text(file.path(tmp, csvs))
  } else {
    # A real CSV parser: quoted fields may hold commas and line breaks.
    df <- read_csv_text(path)
  }
  for (j in seq_along(df)) {
    x <- df[[j]]
    x[x %in% NA_TOKENS] <- NA_character_
    df[[j]] <- x
  }
  df
}

# ----------------------------------------------------------- column preparation

# Python float repr, close enough for labels: shortest of %.15g / %.17g that round-trips;
# whole numbers in a column that has fractions get ".0" as pandas does.
float_labels <- function(x) {
  s <- sprintf("%.15g", x)
  bad <- !is.na(x) & suppressWarnings(as.numeric(s)) != x
  s[bad] <- sprintf("%.17g", x[bad])
  whole <- !is.na(x) & x %% 1 == 0 & !grepl("[.eE]", s)
  s[whole] <- paste0(s[whole], ".0")
  s
}

# One column of one cohort: category strings (missing = MISSING) and numbers, as
# validate.py's _cat_values and _num_values do. `numdtype` is TRUE when every non-missing
# value parses as a number (the R counterpart of a numeric pandas dtype).
prep_column <- function(x) {
  present <- !is.na(x)
  num <- suppressWarnings(as.numeric(x))
  numdtype <- all(!is.na(num[present]))
  if (numdtype) {
    nn <- num[present]
    if (length(nn) && all(is.finite(nn)) && all(nn %% 1 == 0)) {
      s <- sprintf("%.0f", num)
    } else {
      s <- float_labels(num)
    }
    s[!present] <- MISSING
    num[!is.finite(num)] <- NA_real_
    list(cat = s, num = num, numdtype = TRUE)
  } else {
    s <- x
    s[!present] <- MISSING
    list(cat = s, num = NULL, numdtype = FALSE)
  }
}

# Without a dictionary validate.py calls a column numeric when it is numeric in every
# cohort and the real cohort has more than max_levels (20) distinct values.
detect_type <- function(real_col, syn_col, max_levels = 20L) {
  if (real_col$numdtype && syn_col$numdtype &&
      length(unique(real_col$num[!is.na(real_col$num)])) > max_levels) "numeric" else "categorical"
}

top_levels <- function(cat, max_levels = 50L) {
  tb <- table(factor(cat, levels = unique(cat)))
  nm <- names(tb)
  nm[order(-as.integer(tb), seq_along(nm))][seq_len(min(max_levels, length(nm)))]
}

as_codes <- function(cat, levels) {
  m <- match(cat, levels)
  m[is.na(m)] <- length(levels) + 1L   # one pooled code for everything else
  m
}

# --------------------------------------------------------------------- measures

tv_distance <- function(a, b) {
  pa <- table(a) / length(a)
  pb <- table(b) / length(b)
  idx <- union(names(pa), names(pb))
  da <- pa[idx]; da[is.na(da)] <- 0
  db <- pb[idx]; db[is.na(db)] <- 0
  0.5 * sum(abs(as.numeric(da) - as.numeric(db)))
}

ks_distance <- function(a, b) {
  a <- sort(a[!is.na(a)]); b <- sort(b[!is.na(b)])
  if (length(a) == 0L || length(b) == 0L) return(NA_real_)
  grid <- c(a, b)
  max(abs(findInterval(grid, a) / length(a) - findInterval(grid, b) / length(b)))
}

# Bias-corrected Cramer's V (Bergsma 2013), from integer codes 1..ka and 1..kb.
cramers_v <- function(ca, ka, cb, kb) {
  tab <- matrix(tabulate((ca - 1L) * kb + cb, nbins = ka * kb), nrow = ka, ncol = kb,
                byrow = TRUE)
  tab <- tab[rowSums(tab) > 0, colSums(tab) > 0, drop = FALSE]
  r <- nrow(tab); c <- ncol(tab); n <- sum(tab)
  if (r < 2L || c < 2L || n < 2) return(0)
  expected <- outer(rowSums(tab), colSums(tab)) / n
  phi2 <- sum((tab - expected)^2 / expected) / n
  phi2c <- max(0, phi2 - (r - 1) * (c - 1) / (n - 1))
  rc <- r - (r - 1)^2 / (n - 1)
  cc <- c - (c - 1)^2 / (n - 1)
  denom <- min(cc - 1, rc - 1)
  if (denom > 0) min(1, sqrt(phi2c / denom)) else 0
}

# Cramer's V matrix of one cohort over the categorical variables. `cohort` is list(cat=)
# keyed by variable; `levels` are the real cohort's top-50 levels per variable.
assoc_matrix <- function(cohort, vars, levels) {
  n <- length(vars)
  M <- matrix(0, n, n, dimnames = list(vars, vars))
  diag(M) <- 1
  codes <- list(); ks <- list()
  for (v in vars) {
    codes[[v]] <- as_codes(cohort$cat[[v]], levels[[v]])
    ks[[v]] <- length(levels[[v]]) + 1L
  }
  for (i in seq_len(n - 1L)) for (j in (i + 1L):n) {
    a <- vars[i]; b <- vars[j]
    val <- cramers_v(codes[[a]], ks[[a]], codes[[b]], ks[[b]])
    M[i, j] <- val; M[j, i] <- val
  }
  M
}

# ----------------------------------------------------------------- suppression

# validate.py's _suppress: flag counts below min_cell; if exactly one is flagged, also
# flag the smallest other count (lowest position on ties).
suppress_flags <- function(counts, min_cell) {
  flags <- counts < min_cell
  if (sum(flags) == 1L) {
    rest <- which(!flags)
    if (length(rest)) flags[rest[order(counts[rest], rest)[1L]]] <- TRUE
  }
  flags
}

# The same rule on a table: primary flags are counts below min_cell. A row or a column
# with exactly one primary flag also hides its smallest other cell. Rows and columns are
# judged on the primary flags, so the result does not depend on the order.
suppress_table <- function(counts, min_cell) {
  flags <- counts < min_cell
  prim <- flags
  for (i in seq_len(nrow(counts))) {
    f <- suppress_flags(counts[i, ], min_cell)
    flags[i, ] <- flags[i, ] | f
  }
  for (j in seq_len(ncol(counts))) {
    f <- suppress_flags(counts[, j], min_cell)
    flags[, j] <- flags[, j] | f
  }
  flags | prim
}

# ------------------------------------------------------------ cell comparison

# Levels shown for one variable: real levels with at least min_cell records in total (so
# no small real label is released), at most max_levels of them, in label order with the
# missing level last. Everything else is pooled into OTHER_LABEL.
cell_levels <- function(real_cat, min_cell, max_levels = MAX_CELL_LEVELS) {
  tb <- table(factor(real_cat, levels = unique(real_cat)))
  nm <- names(tb)[tb >= min_cell]
  cnt <- as.integer(tb[nm])
  nm <- nm[order(-cnt, seq_along(nm))]
  nm <- nm[seq_len(min(max_levels, length(nm)))]
  c(sort(setdiff(nm, MISSING), method = "radix"), intersect(nm, MISSING))
}

cell_comparison <- function(real_a, real_b, syn_a, syn_b, min_cell) {
  la <- cell_levels(real_a, min_cell); lb <- cell_levels(real_b, min_cell)
  lab <- function(x, lv) ifelse(x %in% lv, x, OTHER_LABEL)
  tab <- function(a, b, rows, cols) {
    unclass(table(factor(lab(a, la), levels = rows), factor(lab(b, lb), levels = cols)))
  }
  rows <- c(la, OTHER_LABEL); cols <- c(lb, OTHER_LABEL)
  real_n <- tab(real_a, real_b, rows, cols)
  syn_n <- tab(syn_a, syn_b, rows, cols)
  # drop the pooled row or column when neither cohort has anything in it
  keep_r <- rows != OTHER_LABEL | (rowSums(real_n) + rowSums(syn_n)) > 0
  keep_c <- cols != OTHER_LABEL | (colSums(real_n) + colSums(syn_n)) > 0
  real_n <- real_n[keep_r, keep_c, drop = FALSE]
  syn_n <- syn_n[keep_r, keep_c, drop = FALSE]
  flags <- suppress_table(real_n, min_cell)
  rs <- real_n / length(real_a)
  ss <- syn_n / length(syn_a)
  rs[flags] <- NA; ss[flags] <- NA
  list(rows = rownames(real_n), cols = colnames(real_n), real_count = real_n,
       real_share = rs, syn_share = ss, diff = ss - rs, flags = flags)
}

# One matrix as a data frame: first column holds the row levels, the others the column levels.
cell_matrix_frame <- function(M, rows, cols, var_a) {
  df <- data.frame(rows, M, check.names = FALSE, stringsAsFactors = FALSE)
  names(df) <- c(var_a, cols)
  df
}

# ----------------------------------------------------------------------- audit

# Problems found in a cell-comparison table read back from disk (character vector,
# empty when clean). `real_a`, `real_b` are the real category strings; n_real their length.
audit_cell_frame <- function(df, real_a, real_b, min_cell) {
  problems <- character(0)
  n_real <- length(real_a)
  for (k in seq_len(nrow(df))) {
    shown <- c(df$real_share[k], df$synthetic_share[k], df$diff_synthetic_minus_real[k])
    where <- paste0("cell (", df$row_level[k], ", ", df$col_level[k], ")")
    if (any(is.na(shown)) && !all(is.na(shown))) {
      problems <- c(problems, paste(where, "is blank in some of the three tables but not all"))
    }
    if (!is.na(df$real_share[k])) {
      n_cell <- round(df$real_share[k] * n_real)
      if (n_cell < min_cell) problems <- c(problems, paste(where, "shows a real count below", min_cell))
      ra <- df$row_level[k]; cb <- df$col_level[k]
      if (ra != OTHER_LABEL && cb != OTHER_LABEL) {
        direct <- sum(real_a == ra & real_b == cb)
        if (direct < min_cell) problems <- c(problems, paste(where, "has a real count below", min_cell))
      }
    }
  }
  for (lv in unique(c(df$row_level, df$col_level))) {
    if (lv == OTHER_LABEL) next
    if (!(lv %in% c(real_a, real_b))) next
    tot <- max(sum(real_a == lv), sum(real_b == lv))
    if (tot < min_cell) problems <- c(problems, paste("level label", shQuote(lv), "has a real total below", min_cell))
  }
  problems
}

audit_outputs <- function(out_dir, written, cell_info, min_cell) {
  problems <- character(0)
  present <- list.files(out_dir, full.names = FALSE)
  extra <- setdiff(present, written)
  if (length(extra)) problems <- c(problems, paste("unexpected files in the output folder:", paste(extra, collapse = ", ")))
  for (f in written) {
    ext <- tolower(tools::file_ext(f))
    if (!(ext %in% ALLOWED_EXT)) problems <- c(problems, paste("file type not allowed:", f))
    if (ext == "csv") {
      hdr <- names(utils::read.csv(file.path(out_dir, f), nrows = 1, check.names = FALSE))
      if (any(grepl("(^|_)(n|count|counts|real_n|synthetic_n)$", hdr, ignore.case = TRUE))) {
        problems <- c(problems, paste("a count-like column in", f))
      }
    }
  }
  if (!is.null(cell_info)) {
    rd <- function(f) {
      m <- utils::read.csv(file.path(out_dir, f), stringsAsFactors = FALSE, na.strings = "",
                           check.names = FALSE, colClasses = "character")
      list(rows = m[[1]], cols = names(m)[-1], v = suppressWarnings(as.matrix(
        data.frame(lapply(m[-1], as.numeric), check.names = FALSE))))
    }
    r <- rd("cell_real_share.csv"); sy <- rd("cell_synth_share.csv"); d <- rd("cell_diff.csv")
    if (!identical(r$cols, sy$cols) || !identical(r$cols, d$cols) ||
        !identical(r$rows, sy$rows) || !identical(r$rows, d$rows)) {
      problems <- c(problems, "the three cell tables have different row or column labels")
    } else {
      ii <- rep(seq_along(r$rows), times = length(r$cols))
      jj <- rep(seq_along(r$cols), each = length(r$rows))
      df <- data.frame(row_level = r$rows[ii], col_level = r$cols[jj],
                       real_share = r$v[cbind(ii, jj)], synthetic_share = sy$v[cbind(ii, jj)],
                       diff_synthetic_minus_real = d$v[cbind(ii, jj)], stringsAsFactors = FALSE)
      problems <- c(problems, audit_cell_frame(df, cell_info$real_a, cell_info$real_b, min_cell))
    }
  }
  problems
}

# -------------------------------------------------------------------- drawing

diverging_cols <- function(n = 101) grDevices::hcl.colors(n, "Blue-Red 3")
sequential_cols <- function(n = 101) rev(grDevices::hcl.colors(n, "YlOrRd"))

shorten <- function(x, n = 30L) ifelse(nchar(x) > n, paste0(substr(x, 1, n - 1L), "~"), x)

draw_panel <- function(M, zlim, cols, main, show_vals = FALSE, digits = 2, cexlab = NULL,
                       grey_na = TRUE) {
  nr <- nrow(M); nc <- ncol(M)
  rl <- shorten(rownames(M)); cl <- shorten(colnames(M))
  if (is.null(cexlab)) cexlab <- max(0.35, min(0.9, 14 / max(nr, nc)))
  lines_l <- min(16, max(4, 0.55 * cexlab * max(nchar(rl)) + 1.5))
  lines_b <- min(16, max(4, 0.55 * cexlab * max(nchar(cl)) + 1.5))
  graphics::par(mar = c(lines_b, lines_l, 3, 1))
  Z <- t(M[nr:1, , drop = FALSE])
  Z[!is.na(Z)] <- pmin(pmax(Z[!is.na(Z)], zlim[1]), zlim[2])
  graphics::plot(NA, xlim = c(0.5, nc + 0.5), ylim = c(0.5, nr + 0.5), xaxs = "i", yaxs = "i",
                 axes = FALSE, xlab = "", ylab = "", main = main, cex.main = 0.95)
  if (grey_na) graphics::rect(0.5, 0.5, nc + 0.5, nr + 0.5, col = "grey80", border = NA)
  graphics::image(seq_len(nc), seq_len(nr), Z, zlim = zlim, col = cols, add = TRUE)
  graphics::box()
  graphics::axis(1, at = seq_len(nc), labels = cl, las = 2, cex.axis = cexlab, tick = FALSE, line = -0.5)
  graphics::axis(2, at = seq_len(nr), labels = rev(rl), las = 2, cex.axis = cexlab, tick = FALSE, line = -0.5)
  if (show_vals) {
    vals <- t(M[nr:1, , drop = FALSE])
    g <- expand.grid(x = seq_len(nc), y = seq_len(nr))
    v <- as.vector(vals)
    ok <- !is.na(v)
    if (any(ok)) graphics::text(g$x[ok], g$y[ok], formatC(v[ok], format = "f", digits = digits),
                   cex = max(0.3, min(0.8, 9 / max(nr, nc))))
  }
}

draw_legend <- function(zlim, cols, title) {
  graphics::par(mar = c(3, 2, 1, 2))
  z <- seq(zlim[1], zlim[2], length.out = length(cols))
  graphics::image(z, 1, matrix(z, ncol = 1), col = cols, zlim = zlim, axes = FALSE,
                  xlab = title, ylab = "", cex.lab = 0.9)
  graphics::axis(1, cex.axis = 0.8)
  graphics::box()
}

# Open PNG and PDF devices around `fn`; a missing PNG device is reported, not fatal.
save_figure <- function(base, width_in, height_in, fn) {
  written <- character(0)
  ok <- tryCatch({
    grDevices::png(paste0(base, ".png"), width = round(width_in * 100), height = round(height_in * 100), res = 100)
    fn(); grDevices::dev.off(); TRUE
  }, error = function(e) {
    try(grDevices::dev.off(), silent = TRUE)
    unlink(paste0(base, ".png"))
    message("note: PNG device unavailable (", conditionMessage(e), "); writing the PDF only")
    FALSE
  })
  if (ok) written <- c(written, basename(paste0(base, ".png")))
  grDevices::pdf(paste0(base, ".pdf"), width = width_in, height = height_in)
  fn(); grDevices::dev.off()
  c(written, basename(paste0(base, ".pdf")))
}

# One heat map as PNG and PDF. Grey cells are NA (suppressed). ggplot2 when installed,
# base graphics otherwise.
fig_matrix <- function(base, M, zlim, cols, title, legend_title, show_vals = FALSE, digits = 2) {
  nr <- nrow(M); nc <- ncol(M)
  w <- max(5, 0.28 * nc + 3.5); h <- max(4.5, 0.26 * nr + 3.5)
  if (HAS_GGPLOT2) {
    d <- data.frame(row = factor(rep(rownames(M), times = nc), levels = rev(rownames(M))),
                    col = factor(rep(colnames(M), each = nr), levels = colnames(M)),
                    value = as.vector(M), stringsAsFactors = FALSE)
    d$value <- pmin(pmax(d$value, zlim[1]), zlim[2])
    g <- ggplot2::ggplot(d, ggplot2::aes(x = col, y = row, fill = value)) +
      ggplot2::geom_tile(colour = "white") +
      ggplot2::scale_fill_gradientn(colours = cols, limits = zlim, na.value = "grey80",
                                    name = legend_title) +
      ggplot2::scale_x_discrete(position = "top", labels = function(x) shorten(x)) +
      ggplot2::scale_y_discrete(labels = function(x) shorten(x)) +
      ggplot2::labs(title = title, x = NULL, y = NULL) +
      ggplot2::theme_minimal(base_size = 9) +
      ggplot2::theme(axis.text.x = ggplot2::element_text(angle = 90, hjust = 0, vjust = 0.5),
                     panel.grid = ggplot2::element_blank())
    if (show_vals) {
      dv <- d[!is.na(d$value), ]
      g <- g + ggplot2::geom_text(data = dv, ggplot2::aes(label = formatC(value, format = "f", digits = digits)), size = 2.2)
    }
    ggplot2::ggsave(paste0(base, ".png"), g, width = w, height = h, dpi = 100)
    ggplot2::ggsave(paste0(base, ".pdf"), g, width = w, height = h)
    return(paste0(basename(base), c(".png", ".pdf")))
  }
  # base graphics: leave room for label margins (up to 16 lines = 3.2 in) and the legend strip
  w <- 0.3 * nc + 3.6; h <- 0.26 * nr + 3.2 + 1.4 + 0.8
  fn <- function() {
    graphics::layout(matrix(1:2, 2, 1), heights = c(h - 1.4, 1.4))
    draw_panel(M, zlim, cols, title, show_vals, digits)
    draw_legend(zlim, cols, legend_title)
  }
  save_figure(base, w, h, fn)
}

fig_univariate <- function(base, uni) {
  d <- uni[order(uni$distance, decreasing = TRUE), ]
  n <- nrow(d)
  h <- max(3.5, 1.6 + 0.2 * n)
  if (HAS_GGPLOT2) {
    d$label <- factor(shorten(d$variable, 40L), levels = rev(shorten(d$variable, 40L)))
    g <- ggplot2::ggplot(d, ggplot2::aes(x = distance, y = label, fill = measure)) +
      ggplot2::geom_col() +
      ggplot2::scale_fill_manual(values = c(tvd = "#3b6ea8", ks = "#d98a2b"),
                                 labels = c(tvd = "TVD (categorical)", ks = "KS (numeric)")) +
      ggplot2::labs(title = "Univariate fidelity, worst variable at the top",
                    x = "distance (0 = identical, 1 = completely different)", y = NULL, fill = NULL) +
      ggplot2::theme_minimal(base_size = 9)
    ggplot2::ggsave(paste0(base, ".png"), g, width = 8, height = h, dpi = 100)
    ggplot2::ggsave(paste0(base, ".pdf"), g, width = 8, height = h)
    return(paste0(basename(base), c(".png", ".pdf")))
  }
  fn <- function() {
    lab <- shorten(d$variable, 40L)
    graphics::par(mar = c(4, min(18, 0.5 * max(nchar(lab)) * 0.8 + 2), 3, 1))
    cols <- ifelse(d$measure == "tvd", "#3b6ea8", "#d98a2b")
    graphics::barplot(rev(d$distance), horiz = TRUE, names.arg = rev(lab), las = 1, col = rev(cols),
                      cex.names = max(0.4, min(0.9, 25 / n)), xlim = c(0, max(0.05, d$distance, na.rm = TRUE) * 1.05),
                      xlab = "distance (0 = identical, 1 = completely different)",
                      main = "Univariate fidelity, worst variable at the top")
    graphics::legend("bottomright", legend = c("TVD (categorical)", "KS (numeric)"),
                     fill = c("#3b6ea8", "#d98a2b"), bty = "n", cex = 0.8)
  }
  save_figure(base, 8, h, fn)
}

# ------------------------------------------------------------------- arguments

usage_text <- function() {
  paste(
    "Usage: Rscript synth_heatmap.R --real <real.csv> --synth <synth.csv|.zip> [--vars v1,v2,...]\n       [--pair a,b] [--out <dir>] [--min-cell 16] [--max-vars N]",
    "",
    "  --real <file>        the real extract, one row per record (CSV). Stays in CGC.",
    "  --synth <file>       the synthetic cohort: a CSV, or a zip holding exactly one CSV",
    "  --vars a,b,c         variables to compare (default: all columns in both files)",
    "  --out <dir>          output folder (default: synth_heatmap_out)",
    "  --min-cell <n>       smallest real cell count that may be shown (default 16)",
    "  --max-vars <n>       keep only the n variables with the most non-missing real values",
    "  --pair a,b           pair for the cell-level comparison (default icccMajor,ageRecode19Groups",
    "                       when both exist, else the pair with the largest Cramer's V difference)",
    "  --help               this text", sep = "\n")
}

parse_args <- function(argv) {
  opts <- list(real = NULL, synth = NULL, vars = NULL, out = "synth_heatmap_out",
               min_cell = DEFAULT_MIN_CELL, max_vars = NULL, pair = NULL, help = FALSE)
  known <- c("real", "synth", "vars", "out", "min-cell", "max-vars", "pair")
  i <- 1L
  while (i <= length(argv)) {
    a <- argv[i]
    if (a %in% c("-h", "--help")) { opts$help <- TRUE; i <- i + 1L; next }
    if (!grepl("^--", a)) stop("unexpected argument '", a, "'. Use --help.")
    key <- sub("^--", "", a); val <- NULL
    if (grepl("=", key, fixed = TRUE)) {
      val <- sub("^[^=]*=", "", key); key <- sub("=.*$", "", key); i <- i + 1L
    } else {
      if (i == length(argv)) stop("option --", key, " needs a value")
      val <- argv[i + 1L]; i <- i + 2L
    }
    if (!(key %in% known)) stop("unknown option --", key, ". Use --help.")
    switch(key,
      "real" = opts$real <- val, "synth" = opts$synth <- val, "out" = opts$out <- val,
      "vars" = opts$vars <- trimws(strsplit(val, ",", fixed = TRUE)[[1]]),
      "pair" = opts$pair <- trimws(strsplit(val, ",", fixed = TRUE)[[1]]),
      "min-cell" = opts$min_cell <- suppressWarnings(as.integer(val)),
      "max-vars" = opts$max_vars <- suppressWarnings(as.integer(val)))
  }
  opts
}

check_opts <- function(o) {
  if (is.null(o$real) || is.null(o$synth)) stop("both --real and --synth are required. Use --help.")
  if (is.na(o$min_cell) || o$min_cell < 1L) stop("--min-cell must be a whole number of at least 1")
  if (!is.null(o$max_vars) && (is.na(o$max_vars) || o$max_vars < 2L)) stop("--max-vars must be a whole number of at least 2")
  if (!is.null(o$pair) && length(o$pair) != 2L) stop("--pair needs exactly two variable names: a,b")
  if (!is.null(o$vars) && length(o$vars) < 2L) stop("--vars needs at least two variable names")
  o
}

# ------------------------------------------------------------------------ main

run <- function(argv) {
  o <- check_opts(parse_args(argv))
  if (o$min_cell < DEFAULT_MIN_CELL) {
    message("WARNING: --min-cell ", o$min_cell, " is below the project threshold of ", DEFAULT_MIN_CELL,
            ". Do not release these outputs without approval.")
  }
  real_df <- read_cohort(o$real)
  syn_df <- read_cohort(o$synth)
  n_real <- nrow(real_df); n_syn <- nrow(syn_df)
  if (n_real < o$min_cell) stop("the real cohort has ", n_real, " rows, below the disclosure threshold ", o$min_cell)
  if (n_syn < 1L) stop("the synthetic cohort has no rows")

  shared <- intersect(names(real_df), names(syn_df))
  if (!is.null(o$vars)) {
    miss <- setdiff(o$vars, shared)
    if (length(miss)) stop("--vars not found in both files: ", paste(miss, collapse = ", "))
    vars <- unique(o$vars)
  } else {
    vars <- shared
  }
  notes <- character(0)
  if (!is.null(o$max_vars) && length(vars) > o$max_vars) {
    filled <- vapply(vars, function(v) sum(!is.na(real_df[[v]]) & !(real_df[[v]] %in% NA_TOKENS)), 0)
    keep <- order(-filled, seq_along(vars))[seq_len(o$max_vars)]
    notes <- c(notes, sprintf("%d variables available; the %d with the most non-missing real values are compared.", length(vars), o$max_vars))
    vars <- vars[sort(keep)]
  }
  only <- c(setdiff(names(real_df), names(syn_df)), setdiff(names(syn_df), names(real_df)))
  if (length(only)) warning("columns present in only one file are ignored: ", paste(only, collapse = ", "), call. = FALSE)
  if (length(vars) < 2L) stop("need at least two variables in both files, found ", length(vars))

  pair <- o$pair
  if (is.null(pair)) {
    default_pair <- c("icccMajor", "ageRecode19Groups")
    if (all(default_pair %in% shared)) pair <- default_pair
  } else if (!all(pair %in% shared)) {
    stop("--pair variables not found in both files: ", paste(setdiff(pair, shared), collapse = ", "))
  }

  need <- unique(c(vars, pair))
  rp <- lapply(stats::setNames(need, need), function(v) prep_column(real_df[[v]]))
  sp <- lapply(stats::setNames(need, need), function(v) prep_column(syn_df[[v]]))
  types <- stats::setNames(vapply(vars, function(v) detect_type(rp[[v]], sp[[v]]), ""), vars)
  real_c <- list(cat = lapply(rp, `[[`, "cat"), num = lapply(rp, `[[`, "num"))
  syn_c <- list(cat = lapply(sp, `[[`, "cat"), num = lapply(sp, `[[`, "num"))

  dir.create(o$out, showWarnings = FALSE, recursive = TRUE)
  written <- character(0)
  fail_clean <- function() {
    unlink(file.path(o$out, written))
  }
  put_csv <- function(df, name, row_names = FALSE) {
    utils::write.csv(df, file.path(o$out, name), row.names = row_names, na = "")
    written <<- c(written, name)
  }

  # ---- heat map 1: dependency structure (Cramer's V, categorical pairs only)
  cvars <- vars[types == "categorical"]
  if (length(cvars) < 2L) stop("need at least two categorical variables for the Cramer's V heat maps, found ", length(cvars))
  levels <- lapply(stats::setNames(cvars, cvars), function(v) top_levels(real_c$cat[[v]], 50L))
  Mr <- assoc_matrix(real_c, cvars, levels)
  Ms <- assoc_matrix(syn_c, cvars, levels)
  Md <- abs(Mr - Ms)
  ord <- seq_along(cvars)
  if (length(cvars) >= 3L) {
    ord <- stats::hclust(stats::as.dist(1 - Mr), method = "complete")$order
  }
  Mr <- Mr[ord, ord]; Ms <- Ms[ord, ord]; Md <- Md[ord, ord]
  as_frame <- function(M) data.frame(variable = rownames(M), M, check.names = FALSE, stringsAsFactors = FALSE)
  put_csv(as_frame(Mr), "cramersv_real.csv")
  put_csv(as_frame(Ms), "cramersv_synth.csv")
  put_csv(as_frame(Md), "cramersv_diff.csv")
  ut <- which(upper.tri(Md), arr.ind = TRUE)
  pairs <- data.frame(var1 = rownames(Md)[ut[, 1]], var2 = colnames(Md)[ut[, 2]], stringsAsFactors = FALSE)
  pairs$real_V <- Mr[ut]; pairs$synth_V <- Ms[ut]; pairs$abs_diff <- Md[ut]
  pairs <- pairs[order(-pairs$abs_diff, pairs$var1, pairs$var2), ]
  rownames(pairs) <- NULL
  dmax <- max(Md[upper.tri(Md)], 0.01)
  seqc <- sequential_cols()
  show <- length(cvars) <= 20
  written <- c(written,
    fig_matrix(file.path(o$out, "heatmap_cramersv_real"), Mr, c(0, 1), seqc, "Cramer's V, real", "Cramer's V", show),
    fig_matrix(file.path(o$out, "heatmap_cramersv_synth"), Ms, c(0, 1), seqc, "Cramer's V, synthetic", "Cramer's V", show),
    fig_matrix(file.path(o$out, "heatmap_cramersv_diff"), Md, c(0, dmax), seqc, "Cramer's V, absolute difference", "abs. difference", show))

  # ---- heat map 2: univariate fidelity
  uni <- do.call(rbind, lapply(vars, function(v) {
    if (types[[v]] == "categorical") {
      data.frame(variable = v, type = "categorical", measure = "tvd",
                 distance = tv_distance(real_c$cat[[v]], syn_c$cat[[v]]), stringsAsFactors = FALSE)
    } else {
      data.frame(variable = v, type = "numeric", measure = "ks",
                 distance = ks_distance(real_c$num[[v]], syn_c$num[[v]]), stringsAsFactors = FALSE)
    }
  }))
  uni <- uni[order(-ifelse(is.na(uni$distance), 0, uni$distance), uni$variable), ]
  put_csv(uni, "univariate_fidelity.csv")
  written <- c(written, fig_univariate(file.path(o$out, "heatmap_univariate"), uni))

  # ---- heat map 3: cell-level comparison for one pair
  if (is.null(pair) && nrow(pairs) > 0L) {
    pair <- c(pairs$var1[1], pairs$var2[1])
    notes <- c(notes, sprintf("default pair icccMajor x ageRecode19Groups not in both files; used the pair with the largest difference: %s x %s", pair[1], pair[2]))
  }
  cc <- NULL; cell_info <- NULL
  if (!is.null(pair)) {
    for (v in pair) {
      if (is.null(rp[[v]])) {
        rp[[v]] <- prep_column(real_df[[v]]); sp[[v]] <- prep_column(syn_df[[v]])
        real_c$cat[[v]] <- rp[[v]]$cat; syn_c$cat[[v]] <- sp[[v]]$cat
      }
      if (detect_type(rp[[v]], sp[[v]]) == "numeric") stop("--pair variable '", v, "' is numeric; the cell comparison needs categorical variables")
    }
    cc <- cell_comparison(real_c$cat[[pair[1]]], real_c$cat[[pair[2]]], syn_c$cat[[pair[1]]], syn_c$cat[[pair[2]]], o$min_cell)
    put_csv(cell_matrix_frame(cc$real_share, cc$rows, cc$cols, pair[1]), "cell_real_share.csv")
    put_csv(cell_matrix_frame(cc$syn_share, cc$rows, cc$cols, pair[1]), "cell_synth_share.csv")
    put_csv(cell_matrix_frame(cc$diff, cc$rows, cc$cols, pair[1]), "cell_diff.csv")
    Mr3 <- cc$real_share; Ms3 <- cc$syn_share; Md3 <- cc$diff
    dimnames(Mr3) <- dimnames(Ms3) <- dimnames(Md3) <- list(cc$rows, cc$cols)
    zs <- c(0, max(Mr3, Ms3, 0.001, na.rm = TRUE))
    zd <- max(abs(Md3), 0.001, na.rm = TRUE) * c(-1, 1)
    show3 <- length(cc$flags) <= 400
    sub <- paste0("\n(rows ", pair[1], ", columns ", pair[2], "; grey = suppressed)")
    written <- c(written,
      fig_matrix(file.path(o$out, "heatmap_cell_real_share"), Mr3, zs, seqc, paste0("Real, share of records", sub), "share", show3, 3),
      fig_matrix(file.path(o$out, "heatmap_cell_synth_share"), Ms3, zs, seqc, paste0("Synthetic, share of records", sub), "share", show3, 3),
      fig_matrix(file.path(o$out, "heatmap_cell_diff"), Md3, zd, diverging_cols(), paste0("Synthetic minus real, share", sub), "difference", show3, 3))
    cell_info <- list(real_a = real_c$cat[[pair[1]]], real_b = real_c$cat[[pair[2]]])
  } else {
    notes <- c(notes, "cell comparison skipped: no categorical pair available")
  }

  # ---- summary
  top <- utils::head(pairs, 10L)
  L <- c(
    sprintf("synth_heatmap.R %s   %s", SH_VERSION, R.version.string),
    sprintf("Real rows: %s   synthetic rows: %s   variables compared: %d (%d categorical, %d numeric)",
            format(n_real, big.mark = ","), format(n_syn, big.mark = ","), length(vars),
            sum(types[vars] == "categorical"), sum(types[vars] == "numeric")),
    "",
    sprintf("CRAMER'S V (%d categorical variables, %d pairs): mean absolute difference %.4f, max %.4f",
            length(cvars), nrow(pairs), mean(pairs$abs_diff), max(pairs$abs_diff)),
    "Top 10 worst pairs (var1, var2, real_V, synth_V, abs_diff):",
    sprintf("  %-24s %-24s %.3f  %.3f  %.3f", top$var1, top$var2, top$real_V, top$synth_V, top$abs_diff),
    "",
    sprintf("UNIVARIATE: mean distance %.4f, max %.4f. Worst:", mean(uni$distance, na.rm = TRUE), max(uni$distance, na.rm = TRUE)),
    sprintf("  %-28s %-4s %.4f", utils::head(uni$variable, 5L), toupper(utils::head(uni$measure, 5L)), utils::head(uni$distance, 5L))
  )
  if (!is.null(cc)) {
    L <- c(L, "", sprintf("CELL COMPARISON %s by %s: %d cells, %d suppressed (real count below %d, or hidden to protect one).",
                          pair[1], pair[2], length(cc$flags), sum(cc$flags), o$min_cell))
    L <- c(L, sprintf("  Total absolute share difference over the shown cells: %.2f %% points.", 100 * sum(abs(cc$diff), na.rm = TRUE)))
  }
  if (length(notes)) L <- c(L, "", paste("NOTE:", notes))
  L <- c(L,
         "",
         "Cramer's V is a marginal pairwise measure. It is not the discriminator AUC from `synthpediatric validate`.",
         "TVD and KS are univariate: they say nothing about joint structure.",
         sprintf("Disclosure: only aggregates are written. Real counts are never written; cells with a real count below %d are blank (suppressed).", o$min_cell),
         "R and Python agree on the definitions; see cgc/R/README.md for the differences.")
  writeLines(L, file.path(o$out, "summary.txt"))
  written <- c(written, "summary.txt")

  # ---- audit: no output may keep a real cell below the threshold
  problems <- audit_outputs(o$out, written, cell_info, o$min_cell)
  if (length(problems)) {
    fail_clean()
    stop("AUDIT FAILED. The outputs were deleted. Nothing may leave CGC from this run.\n  ",
         paste(problems, collapse = "\n  "))
  }
  cat(paste(L, collapse = "\n"), "\n", sep = "")
  cat(sprintf("\nAudit passed: no disclosure violation found (%d files). Outputs are in %s\n",
              length(written), normalizePath(o$out)))
  invisible(0L)
}

main <- function(argv) {
  a <- tryCatch(parse_args(argv), error = function(e) e)
  if (inherits(a, "error")) { message("ERROR: ", conditionMessage(a)); return(2L) }
  if (isTRUE(a$help)) { cat(usage_text(), "\n", sep = ""); return(0L) }
  res <- tryCatch({ run(argv); 0L }, error = function(e) { message("ERROR: ", conditionMessage(e)); 1L })
  res
}

if (sys.nframe() == 0L) quit(status = main(commandArgs(trailingOnly = TRUE)))
