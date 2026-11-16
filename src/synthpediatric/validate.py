"""Validation toolkit: compare a synthetic cohort with a real one and report similarity.

This is the first tier of the agreed scorecard (see ``docs/validation.md``):

* univariate fidelity: total variation distance (categorical) and Kolmogorov-Smirnov
  distance (numeric), per variable;
* dependency fidelity: pairwise association difference (bias-corrected Cramer's V for
  categorical pairs, correlation ratio for categorical-numeric pairs, absolute Spearman
  correlation for numeric pairs);
* the headline number: a cross-validated real-vs-synthetic discriminator AUC (about 0.5
  means the classifier cannot tell the cohorts apart), with its spread across folds and
  the columns that drive it;
* a replicate envelope: does the real value of each statistic fall inside the spread of
  K synthetic cohorts made with different seeds (separates real bias from sampling noise);
* an iteration history, so the AUC trend across versions (v0, v1, ...) can be shown.

The report is built to leave a secure workspace: it holds aggregate statistics only, and
every category-level count is suppressed below ``min_count`` (default 16). It never holds
row-level values. Only the discriminator needs scikit-learn (``pip install
"synthpediatric[validate]"``); the rest of the module needs only numpy and pandas.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from . import __version__

SCHEMA_VERSION = 1
DEFAULT_MIN_COUNT = 16  # same value as config.DEFAULT_SUPPRESSION_MIN
MISSING = "__missing__"
POOLED_LABEL = "(other levels, each below the threshold in both cohorts)"

# Closed list of metric names, for the reserved ``validate:`` config block.
# ``tvd`` and ``ks`` switch the univariate distances for categorical and numeric
# variables; ``assoc_diff`` the pairwise association difference; ``discriminator_auc``
# the headline classifier AUC; ``replicate_envelope`` the replicate-spread check.
METRIC_NAMES: Dict[str, Tuple[str, ...]] = {
    "fidelity": ("tvd", "ks", "assoc_diff", "discriminator_auc", "replicate_envelope"),
    "utility": (),   # specific-utility metrics are not built yet
    "privacy": (),   # privacy gates are not built yet
}
DEFAULT_METRICS: Tuple[str, ...] = METRIC_NAMES["fidelity"]

_NUMERIC_VTYPES = {
    "numeric", "number", "continuous", "integer", "int", "float", "decimal", "double",
}
_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_HISTORY_FIELDS = [
    "label", "generated_at_utc", "n_real", "n_synthetic", "n_replicates", "auc",
    "auc_fold_std", "univariate_mean", "univariate_max", "dependency_mean",
    "dependency_max", "envelope_fraction_inside", "min_count", "seed", "version",
]


class MetricNameError(ValueError):
    """A metric name is not in the closed list."""


class ValidationError(ValueError):
    """The inputs to a validation run are unusable."""


# ----------------------------------------------------------------- metric names


def check_metric_names(names: Iterable[str], group: str = "fidelity") -> Tuple[str, ...]:
    """Return ``names`` as a tuple after checking each is in the closed list for ``group``."""
    if group not in METRIC_NAMES:
        raise MetricNameError(f"unknown metric group '{group}' (expected {sorted(METRIC_NAMES)})")
    if isinstance(names, str):
        raise MetricNameError(f"{group}: expected a list of metric names, got the string {names!r}")
    allowed = METRIC_NAMES[group]
    out = []
    for name in names:
        if name not in allowed:
            raise MetricNameError(
                f"{group}: unknown metric '{name}'. Allowed: {', '.join(allowed) or '(none yet)'}"
            )
        if name not in out:
            out.append(name)
    return tuple(out)


def check_validate_block(block: Mapping[str, Any]) -> Dict[str, Tuple[str, ...]]:
    """Check every metric list in a ``validate:`` block (fidelity/utility/privacy)."""
    return {
        group: check_metric_names(block.get(group) or [], group) for group in METRIC_NAMES
    }


# ------------------------------------------------------------------ data access


def read_frame(path: Any) -> pd.DataFrame:
    """Read a .csv or .parquet file."""
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(p, low_memory=False)
    if suffix in (".parquet", ".pq"):
        return pd.read_parquet(p)
    raise ValidationError(f"unsupported data file '{p.name}' (use .csv or .parquet)")


def load_context_dictionary(spec: str) -> Any:
    """Load a DataDictionary from a JSON dictionary or from a YAML/JSON generation config."""
    from .dictionary import DataDictionary

    path = Path(spec)
    is_yaml = path.suffix.lower() in (".yaml", ".yml")
    if not is_yaml:
        with path.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)
        if isinstance(raw, dict) and "variables" in raw:
            return DataDictionary.from_dict(raw)
    from .config import load_config, normalize_config
    from .recipe import _load_dictionary

    return _load_dictionary(normalize_config(load_config(path)))


# ----------------------------------------------------------- column preparation


def _cat_values(s: pd.Series) -> pd.Series:
    """Categorical view of a column: strings, missing as MISSING, integral floats as ints."""
    if pd.api.types.is_float_dtype(s):
        nonnull = s.dropna()
        if len(nonnull) and bool(np.all(np.mod(nonnull.to_numpy(float), 1) == 0)):
            s = s.astype("Int64")
    out = s.astype("string").fillna(MISSING)
    return out.astype(object)


def _num_values(s: pd.Series) -> np.ndarray:
    x = pd.to_numeric(s, errors="coerce").to_numpy(dtype=float)
    x[~np.isfinite(x)] = np.nan
    return x


def detect_types(
    frames: Sequence[pd.DataFrame],
    columns: Sequence[str],
    dictionary: Any = None,
    max_levels: int = 20,
) -> Dict[str, str]:
    """Label each column ``numeric`` or ``categorical``.

    The dictionary decides when it lists the column: a numeric-like ``vtype`` makes it
    numeric, any other vtype makes it categorical. Without a dictionary entry a column
    is numeric when it has a numeric dtype in every cohort and more than ``max_levels``
    distinct values in the first (real) cohort; otherwise categorical. A column that is
    not numeric-typed in every cohort is always categorical.
    """
    types: Dict[str, str] = {}
    for col in columns:
        all_numeric = all(
            pd.api.types.is_numeric_dtype(f[col]) and not pd.api.types.is_bool_dtype(f[col])
            for f in frames
        )
        var = None
        if dictionary is not None:
            var = getattr(dictionary, "variables", {}).get(col)
        if var is not None:
            wants_numeric = str(var.vtype).lower() in _NUMERIC_VTYPES
        else:
            wants_numeric = all_numeric and frames[0][col].nunique(dropna=True) > max_levels
        types[col] = "numeric" if (wants_numeric and all_numeric) else "categorical"
    return types


class _Cohort:
    """Per-cohort prepared columns: category strings or float arrays, keyed by column."""

    def __init__(self, df: pd.DataFrame, columns: Sequence[str], types: Mapping[str, str]):
        self.n = len(df)
        self.cat: Dict[str, pd.Series] = {}
        self.num: Dict[str, np.ndarray] = {}
        for col in columns:
            if types[col] == "numeric":
                self.num[col] = _num_values(df[col])
            else:
                self.cat[col] = _cat_values(df[col])


def _levels(series: pd.Series, max_levels: int) -> List[str]:
    return list(series.value_counts().index[:max_levels])


def _codes(series: pd.Series, levels: Sequence[str]) -> np.ndarray:
    codes = pd.Categorical(series, categories=list(levels)).codes.astype(np.int64)
    codes[codes < 0] = len(levels)  # everything outside `levels` goes to one pooled code
    return codes


# ------------------------------------------------------------ univariate measures


def tv_distance(a: pd.Series, b: pd.Series) -> float:
    """Total variation distance between two categorical samples, in [0, 1]."""
    pa = a.value_counts(normalize=True)
    pb = b.value_counts(normalize=True)
    index = pa.index.union(pb.index)
    diff = np.abs(
        pa.reindex(index, fill_value=0.0).to_numpy() - pb.reindex(index, fill_value=0.0).to_numpy()
    )
    return 0.5 * float(diff.sum())


def ks_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Two-sample Kolmogorov-Smirnov statistic (max CDF gap), in [0, 1]. NaN if a side is empty."""
    a = np.sort(a[~np.isnan(a)])
    b = np.sort(b[~np.isnan(b)])
    if a.size == 0 or b.size == 0:
        return float("nan")
    grid = np.concatenate([a, b])
    cdf_a = np.searchsorted(a, grid, side="right") / a.size
    cdf_b = np.searchsorted(b, grid, side="right") / b.size
    return float(np.max(np.abs(cdf_a - cdf_b)))


def _univariate_table(
    real: _Cohort, syn: _Cohort, columns: Sequence[str], types: Mapping[str, str],
    metrics: Sequence[str],
) -> Dict[str, Tuple[str, float]]:
    out: Dict[str, Tuple[str, float]] = {}
    for col in columns:
        if types[col] == "categorical" and "tvd" in metrics:
            out[col] = ("tvd", tv_distance(real.cat[col], syn.cat[col]))
        elif types[col] == "numeric" and "ks" in metrics:
            out[col] = ("ks", ks_distance(real.num[col], syn.num[col]))
    return out


# ------------------------------------------------------------ dependency measures


def cramers_v(codes_a: np.ndarray, ka: int, codes_b: np.ndarray, kb: int) -> float:
    """Bias-corrected Cramer's V (Bergsma 2013) from integer codes, in [0, 1]."""
    table = np.bincount(codes_a * kb + codes_b, minlength=ka * kb).reshape(ka, kb).astype(float)
    table = table[table.sum(axis=1) > 0][:, table.sum(axis=0) > 0]
    r, c = table.shape
    n = table.sum()
    if r < 2 or c < 2 or n < 2:
        return 0.0
    expected = np.outer(table.sum(axis=1), table.sum(axis=0)) / n
    phi2 = float(((table - expected) ** 2 / expected).sum() / n)
    phi2c = max(0.0, phi2 - (r - 1) * (c - 1) / (n - 1))
    rc = r - (r - 1) ** 2 / (n - 1)
    cc = c - (c - 1) ** 2 / (n - 1)
    denom = min(cc - 1, rc - 1)
    return float(min(1.0, np.sqrt(phi2c / denom))) if denom > 0 else 0.0


def correlation_ratio(codes: np.ndarray, k: int, x: np.ndarray) -> float:
    """Bias-adjusted correlation ratio (eta) of numeric ``x`` on category codes, in [0, 1]."""
    keep = ~np.isnan(x)
    codes, x = codes[keep], x[keep]
    n = x.size
    if n < 3:
        return 0.0
    counts = np.bincount(codes, minlength=k).astype(float)
    sums = np.bincount(codes, weights=x, minlength=k)
    used = counts > 0
    groups = int(used.sum())
    sst = float(((x - x.mean()) ** 2).sum())
    if groups < 2 or sst <= 0 or n <= groups:
        return 0.0
    ssb = float((counts[used] * (sums[used] / counts[used] - x.mean()) ** 2).sum())
    eta2 = min(1.0, ssb / sst)
    adj = 1.0 - (1.0 - eta2) * (n - 1) / (n - groups)
    return float(np.sqrt(max(0.0, adj)))


def _abs_spearman(x: np.ndarray, y: np.ndarray) -> float:
    keep = ~(np.isnan(x) | np.isnan(y))
    if keep.sum() < 3:
        return 0.0
    rho = pd.Series(x[keep]).corr(pd.Series(y[keep]), method="spearman")
    return 0.0 if np.isnan(rho) else float(abs(rho))


def _association_table(
    cohort: _Cohort, columns: Sequence[str], types: Mapping[str, str],
    levels: Mapping[str, List[str]],
) -> Dict[Tuple[str, str], Tuple[str, float]]:
    codes = {c: _codes(cohort.cat[c], levels[c]) for c in cohort.cat}
    ks = {c: len(levels[c]) + 1 for c in cohort.cat}
    out: Dict[Tuple[str, str], Tuple[str, float]] = {}
    for i, a in enumerate(columns):
        for b in columns[i + 1:]:
            ta, tb = types[a], types[b]
            if ta == "categorical" and tb == "categorical":
                out[(a, b)] = ("cramers_v", cramers_v(codes[a], ks[a], codes[b], ks[b]))
            elif ta == "numeric" and tb == "numeric":
                out[(a, b)] = ("abs_spearman", _abs_spearman(cohort.num[a], cohort.num[b]))
            else:
                cat, num = (a, b) if ta == "categorical" else (b, a)
                out[(a, b)] = (
                    "correlation_ratio",
                    correlation_ratio(codes[cat], ks[cat], cohort.num[num]),
                )
    return out


# ------------------------------------------------------------------ discriminator


def _require_sklearn() -> None:
    try:
        import sklearn  # noqa: F401
    except ImportError as exc:  # pragma: no cover - exercised through monkeypatch in tests
        raise ImportError(
            "The discriminator AUC needs scikit-learn. Install it with: "
            'pip install "synthpediatric[validate]"'
        ) from exc


def discriminator_auc(
    real: _Cohort,
    syn: _Cohort,
    columns: Sequence[str],
    types: Mapping[str, str],
    *,
    seed: int,
    n_splits: int = 5,
    max_rows_per_class: int = 20000,
    max_levels: int = 50,
    n_trees: int = 100,
    importance_repeats: int = 3,
    importance_rows: int = 2000,
    top_k: int = 10,
) -> Dict[str, Any]:
    """Cross-validated AUC of a random forest telling real from synthetic.

    The larger cohort is down-sampled (seeded, without replacement) to the size of the
    smaller one, capped at ``max_rows_per_class``, so classes are balanced. Categorical
    columns are integer-coded by pooled frequency (top ``max_levels`` levels; rarer
    levels share one code; missing is its own level); numeric missing values become -1e12
    so trees can split them off. Column importance is the mean drop in held-out AUC when
    that column is permuted (on at most ``importance_rows`` held-out rows per fold).
    """
    _require_sklearn()
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.inspection import permutation_importance
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import StratifiedKFold

    n = min(real.n, syn.n, max_rows_per_class)
    if n < max(50, 2 * n_splits):
        raise ValidationError(
            f"discriminator needs at least {max(50, 2 * n_splits)} rows per cohort, got {n}"
        )
    rng = np.random.default_rng(seed)
    real_idx = np.sort(rng.choice(real.n, size=n, replace=False))
    syn_idx = np.sort(rng.choice(syn.n, size=n, replace=False))

    feats: List[np.ndarray] = []
    for col in columns:
        if types[col] == "numeric":
            x = np.concatenate([real.num[col][real_idx], syn.num[col][syn_idx]])
        else:
            both = pd.concat([real.cat[col].iloc[real_idx], syn.cat[col].iloc[syn_idx]])
            x = _codes(both.reset_index(drop=True), _levels(both, max_levels)).astype(float)
        feats.append(x)
    X = np.column_stack(feats)
    y = np.concatenate([np.zeros(n, dtype=int), np.ones(n, dtype=int)])
    X[np.isnan(X)] = -1e12

    folds = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    aucs: List[float] = []
    drops = np.zeros((n_splits, len(columns)))
    for k, (tr, te) in enumerate(folds.split(X, y)):
        model = RandomForestClassifier(
            n_estimators=n_trees, min_samples_leaf=5, max_features="sqrt",
            random_state=seed, n_jobs=1,
        )
        model.fit(X[tr], y[tr])
        aucs.append(float(roc_auc_score(y[te], model.predict_proba(X[te])[:, 1])))
        sub = te
        if te.size > importance_rows:
            sub = np.sort(rng.choice(te, size=importance_rows, replace=False))
        imp = permutation_importance(
            model, X[sub], y[sub], scoring="roc_auc", n_repeats=importance_repeats,
            random_state=seed, n_jobs=1,
        )
        drops[k] = imp.importances_mean
    mean_drop = drops.mean(axis=0)
    order = np.argsort(-mean_drop)[:top_k]
    return {
        "auc": float(np.mean(aucs)),
        "auc_fold_std": float(np.std(aucs, ddof=1)) if len(aucs) > 1 else 0.0,
        "fold_aucs": [round(a, 6) for a in aucs],
        "n_splits": n_splits,
        "classifier": f"RandomForestClassifier(n_estimators={n_trees}, min_samples_leaf=5)",
        "rows_per_class": int(n),
        "rows_available": {"real": int(real.n), "synthetic": int(syn.n)},
        "top_columns": [
            {"column": columns[i], "auc_drop": round(float(mean_drop[i]), 6)} for i in order
        ],
    }


# ------------------------------------------------------- disclosure-safe counts


def _suppress(counts: List[Optional[int]], min_count: int) -> List[bool]:
    """Flag counts below ``min_count``; if exactly one is flagged, also flag the smallest
    other count so the total cannot reveal it (complementary suppression)."""
    flags = [c is not None and c < min_count for c in counts]
    if sum(flags) == 1:
        rest = [(c, i) for i, c in enumerate(counts) if not flags[i] and c is not None]
        if rest:
            flags[min(rest)[1]] = True
    return flags


def category_detail(
    real: pd.Series, syn: pd.Series, min_count: int, max_rows: int = 25
) -> Dict[str, Any]:
    """Category counts for one variable with every count below ``min_count`` suppressed.

    A level is listed when its real or synthetic count reaches ``min_count`` (so no real
    label with a small count is released). All other levels, and any beyond ``max_rows``,
    are pooled into one row. Counts that are suppressed are ``None``.
    """
    rc = real.value_counts()
    sc = syn.value_counts()
    index = list(rc.index.union(sc.index))
    rows = []
    for lv in index:
        r, s = int(rc.get(lv, 0)), int(sc.get(lv, 0))
        rows.append((lv, r, s))
    rows.sort(key=lambda t: (-(t[1] + t[2]), str(t[0])))
    keep = [t for t in rows if max(t[1], t[2]) >= min_count][:max_rows]
    kept = {t[0] for t in keep}
    pooled_r = sum(t[1] for t in rows if t[0] not in kept)
    pooled_s = sum(t[2] for t in rows if t[0] not in kept)
    labels = [str(t[0]) for t in keep]
    rcounts: List[Optional[int]] = [t[1] for t in keep]
    scounts: List[Optional[int]] = [t[2] for t in keep]
    if pooled_r or pooled_s:
        labels.append(POOLED_LABEL)
        rcounts.append(pooled_r)
        scounts.append(pooled_s)
    rflag = _suppress(rcounts, min_count)
    sflag = _suppress(scounts, min_count)
    levels = [
        {
            "level": labels[i],
            "real_n": None if rflag[i] else rcounts[i],
            "synthetic_n": None if sflag[i] else scounts[i],
        }
        for i in range(len(labels))
    ]
    return {"levels": levels, "suppressed_below": min_count}


def audit_report(report: Mapping[str, Any], min_count: int, max_list: int = 1000) -> None:
    """Raise if the report holds a category count below ``min_count`` or a very long list."""

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, val in node.items():
                if key in ("real_n", "synthetic_n") and val is not None and val < min_count:
                    raise ValidationError(f"unsuppressed count {val} at {path}.{key}")
                walk(val, f"{path}.{key}")
        elif isinstance(node, list):
            if len(node) > max_list:
                raise ValidationError(f"list of {len(node)} items at {path}: not an aggregate")
            for i, val in enumerate(node):
                walk(val, f"{path}[{i}]")

    walk(report, "report")


# ------------------------------------------------------------ replicate envelope


def _cohort_statistics(
    cohort: _Cohort, columns: Sequence[str], types: Mapping[str, str],
    assoc: Optional[Mapping[Tuple[str, str], Tuple[str, float]]],
    cat_levels: Mapping[str, List[str]],
) -> Dict[str, Tuple[str, float]]:
    """Cohort-level statistics used by the envelope: (family, value) by statistic name."""
    stats: Dict[str, Tuple[str, float]] = {}
    for col in columns:
        if types[col] == "categorical":
            props = cohort.cat[col].value_counts(normalize=True)
            for lv in cat_levels[col]:
                stats[f"proportion[{col}={lv}]"] = ("univariate", float(props.get(lv, 0.0)))
        else:
            x = cohort.num[col][~np.isnan(cohort.num[col])]
            if x.size:
                stats[f"mean[{col}]"] = ("univariate", float(x.mean()))
                stats[f"sd[{col}]"] = ("univariate", float(x.std()))
                stats[f"median[{col}]"] = ("univariate", float(np.median(x)))
    if assoc is not None:
        for (a, b), (_, val) in assoc.items():
            stats[f"association[{a}|{b}]"] = ("dependency", val)
    return stats


def _envelope_levels(real: pd.Series, min_count: int, max_levels: int = 50) -> List[str]:
    """Real levels whose proportion the envelope may report.

    Only levels with at least ``min_count`` real rows are used. If the rows left out
    would add up to between 1 and ``min_count - 1`` (recoverable as 1 minus the sum of
    the listed proportions), the smallest listed level is left out too.
    """
    counts = real.value_counts()
    keep = [(lv, int(n)) for lv, n in counts.items() if n >= min_count][:max_levels]
    rest = int(counts.sum()) - sum(n for _, n in keep)
    if keep and 0 < rest < min_count:
        keep = keep[:-1]
    return [lv for lv, _ in keep]


def replicate_envelope(
    real_stats: Mapping[str, Tuple[str, float]],
    replicate_stats: Sequence[Mapping[str, Tuple[str, float]]],
    top_k: int = 10,
) -> Dict[str, Any]:
    """Check whether each real statistic lies inside the range of the K replicate values.

    With K exchangeable replicates the real value falls inside their [min, max] range with
    probability (K - 1) / (K + 1) when there is no bias, so that is reported as the
    expected fraction. A much lower fraction points at real bias, not sampling noise.
    """
    k = len(replicate_stats)
    if k < 2:
        return {
            "available": False,
            "reason": f"needs at least 2 synthetic replicates, got {k}",
            "n_replicates": k,
        }
    families: Dict[str, Dict[str, Any]] = {}
    outside: Dict[str, List[Dict[str, Any]]] = {}
    for name, (family, real_val) in real_stats.items():
        vals = np.array([r[name][1] for r in replicate_stats if name in r], dtype=float)
        if vals.size != k or np.isnan(real_val) or np.isnan(vals).any():
            continue
        lo, hi = float(vals.min()), float(vals.max())
        tol = 1e-12
        inside = lo - tol <= real_val <= hi + tol
        fam = families.setdefault(family, {"n_statistics": 0, "n_inside": 0})
        fam["n_statistics"] += 1
        fam["n_inside"] += int(inside)
        if not inside:
            gap = lo - real_val if real_val < lo else real_val - hi
            outside.setdefault(family, []).append(
                {"statistic": name, "real": round(real_val, 6), "replicate_min": round(lo, 6),
                 "replicate_max": round(hi, 6), "gap": round(float(gap), 6)}
            )
    for family, fam in families.items():
        fam["fraction_inside"] = round(fam["n_inside"] / fam["n_statistics"], 4)
        worst = sorted(outside.get(family, []), key=lambda d: -d["gap"])
        fam["worst_outside"] = worst[:top_k]
    total = sum(f["n_statistics"] for f in families.values())
    inside_total = sum(f["n_inside"] for f in families.values())
    return {
        "available": True,
        "n_replicates": k,
        "expected_fraction_inside_if_unbiased": round((k - 1) / (k + 1), 4),
        "n_statistics": total,
        "fraction_inside": round(inside_total / total, 4) if total else None,
        "families": families,
    }


def generate_replicates(
    generate_fn: Callable[[int], pd.DataFrame], k: int, seed: int = 0
) -> List[pd.DataFrame]:
    """Make ``k`` synthetic cohorts by calling ``generate_fn(seed)`` with seeds seed+1..seed+k."""
    if k < 1:
        raise ValidationError("k must be at least 1")
    return [generate_fn(seed + i + 1) for i in range(k)]


# --------------------------------------------------------------------- main entry


def _check_label(label: str) -> str:
    if not _LABEL_RE.match(label or ""):
        raise ValidationError(
            f"label {label!r} must be 1-64 characters: letters, digits, '.', '_' or '-'"
        )
    return label


def _mean_dict(tables: Sequence[Mapping[Any, Tuple[str, float]]]) -> Dict[Any, Tuple[str, float]]:
    out: Dict[Any, Tuple[str, float]] = {}
    for key in tables[0]:
        vals = [t[key][1] for t in tables]
        mean = float("nan") if all(np.isnan(vals)) else float(np.nanmean(vals))
        out[key] = (tables[0][key][0], mean)
    return out


def _summary(values: Mapping[Any, float], top_k: int) -> Dict[str, Any]:
    clean = {k: v for k, v in values.items() if not np.isnan(v)}
    if not clean:
        return {"n": 0, "mean": None, "max": None, "worst": []}
    worst = sorted(clean.items(), key=lambda kv: -kv[1])[:top_k]
    return {
        "n": len(clean),
        "mean": round(float(np.mean(list(clean.values()))), 6),
        "max": round(float(max(clean.values())), 6),
        "worst": [{"variable": k, "distance": round(float(v), 6)} for k, v in worst],
    }


def validate_cohorts(
    real: pd.DataFrame,
    synthetic: Any,
    *,
    label: str = "run",
    dictionary: Any = None,
    seed: int = 0,
    min_count: int = DEFAULT_MIN_COUNT,
    metrics: Optional[Iterable[str]] = None,
    exclude: Sequence[str] = (),
    n_splits: int = 5,
    top_k: int = 10,
    max_rows_per_class: int = 20000,
) -> Dict[str, Any]:
    """Compare ``real`` with one or more synthetic cohorts and return the report dict.

    ``synthetic`` is a DataFrame or a list of DataFrames (replicates from different seeds).
    Scalar results are means over the replicates; per-replicate AUCs are listed.
    """
    _check_label(label)
    if min_count < 1:
        raise ValidationError("min_count must be at least 1")
    syns = [synthetic] if isinstance(synthetic, pd.DataFrame) else list(synthetic)
    if not syns:
        raise ValidationError("at least one synthetic cohort is required")
    metrics = DEFAULT_METRICS if metrics is None else check_metric_names(metrics)
    if len(real) < min_count:
        raise ValidationError(
            f"the real cohort has {len(real)} rows, below the disclosure threshold {min_count}"
        )
    shared = [
        c for c in real.columns if c not in exclude and all(c in s.columns for s in syns)
    ]
    if not shared:
        raise ValidationError("the real and synthetic cohorts share no columns")
    types = detect_types([real] + syns, shared, dictionary)
    real_c = _Cohort(real, shared, types)
    syn_c = [_Cohort(s, shared, types) for s in syns]
    k = len(syn_c)

    report: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "label": label,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "synthpediatric_version": __version__,
        "settings": {
            "seed": seed, "min_count": min_count, "metrics": list(metrics),
            "n_splits": n_splits, "max_rows_per_class": max_rows_per_class,
        },
        "data": {
            "n_real": int(len(real)),
            "n_synthetic": [int(len(s)) for s in syns],
            "n_replicates": k,
            "columns_compared": len(shared),
            "columns_only_in_real": [c for c in real.columns if c not in shared and c not in exclude
                                     and not all(c in s.columns for s in syns)],
            "columns_only_in_synthetic": sorted(
                {c for s in syns for c in s.columns} - set(real.columns) - set(exclude)
            ),
            "columns_excluded": [c for c in exclude if c in real.columns],
            "types": types,
        },
        "disclosure": DISCLOSURE_STATEMENT.format(min_count=min_count),
    }

    uni_tabs = _univariate_table_all(real_c, syn_c, shared, types, metrics)
    if uni_tabs is not None:
        uni = {c: v[1] for c, v in uni_tabs.items()}
        report["univariate"] = {
            "per_variable": [
                {"variable": c, "type": types[c], "measure": uni_tabs[c][0],
                 "distance": round(uni_tabs[c][1], 6)}
                for c in sorted(uni, key=lambda c: -np.nan_to_num(uni[c]))
            ],
            "summary": _summary(uni, top_k),
        }
        cat_worst = [c for c in sorted(uni, key=lambda c: -np.nan_to_num(uni[c]))
                     if types[c] == "categorical"][:top_k]
        report["category_detail"] = {
            c: category_detail(real_c.cat[c], syn_c[0].cat[c], min_count) for c in cat_worst
        }

    levels = {c: _levels(real_c.cat[c], 50) for c in real_c.cat}
    real_assoc = syn_assocs = None
    if "assoc_diff" in metrics and len(shared) > 1:
        real_assoc = _association_table(real_c, shared, types, levels)
        syn_assocs = [_association_table(s, shared, types, levels) for s in syn_c]
        mean_syn = _mean_dict(syn_assocs)
        diffs = {p: abs(real_assoc[p][1] - mean_syn[p][1]) for p in real_assoc}
        pairs = sorted(diffs, key=lambda p: -diffs[p])
        report["dependency"] = {
            "summary": {
                "n_pairs": len(diffs),
                "mean_abs_diff": round(float(np.mean(list(diffs.values()))), 6),
                "max_abs_diff": round(float(max(diffs.values())), 6),
            },
            "worst_pairs": [
                {"a": a, "b": b, "measure": real_assoc[(a, b)][0],
                 "real": round(real_assoc[(a, b)][1], 6),
                 "synthetic": round(mean_syn[(a, b)][1], 6),
                 "abs_diff": round(diffs[(a, b)], 6)}
                for a, b in pairs[:top_k]
            ],
        }

    if "discriminator_auc" in metrics:
        runs = [
            discriminator_auc(real_c, s, shared, types, seed=seed + i, n_splits=n_splits,
                              max_rows_per_class=max_rows_per_class, top_k=top_k)
            for i, s in enumerate(syn_c)
        ]
        disc = dict(runs[0])
        disc["auc"] = round(float(np.mean([r["auc"] for r in runs])), 6)
        disc["auc_fold_std"] = round(float(np.mean([r["auc_fold_std"] for r in runs])), 6)
        if k > 1:
            disc["auc_by_replicate"] = [round(r["auc"], 6) for r in runs]
            drop: Dict[str, float] = {}
            for r in runs:
                for t in r["top_columns"]:
                    drop[t["column"]] = drop.get(t["column"], 0.0) + t["auc_drop"] / k
            disc["top_columns"] = [
                {"column": c, "auc_drop": round(v, 6)}
                for c, v in sorted(drop.items(), key=lambda kv: -kv[1])[:top_k]
            ]
            del disc["fold_aucs"]
        disc["interpretation"] = (
            "AUC 0.5 = classifier cannot tell the cohorts apart; 1.0 = perfectly separable"
        )
        report["discriminator"] = disc

    if "replicate_envelope" in metrics:
        cat_levels = {c: _envelope_levels(real_c.cat[c], min_count) for c in real_c.cat}
        real_stats = _cohort_statistics(real_c, shared, types, real_assoc, cat_levels)
        rep_stats = [
            _cohort_statistics(s, shared, types, syn_assocs[i] if syn_assocs else None, cat_levels)
            for i, s in enumerate(syn_c)
        ]
        report["replicate_envelope"] = replicate_envelope(real_stats, rep_stats, top_k)

    audit_report(report, min_count)
    return report


def _univariate_table_all(
    real_c: _Cohort, syn_c: Sequence[_Cohort], shared: Sequence[str],
    types: Mapping[str, str], metrics: Sequence[str],
) -> Optional[Dict[str, Tuple[str, float]]]:
    if "tvd" not in metrics and "ks" not in metrics:
        return None
    tables = [_univariate_table(real_c, s, shared, types, metrics) for s in syn_c]
    return _mean_dict(tables)


DISCLOSURE_STATEMENT = (
    "Contents: aggregate statistics only (distances, association strengths, classifier AUC, "
    "column names, counts of rows). No row-level values. Category-level counts below "
    "{min_count} are suppressed (null), with complementary suppression, and levels whose "
    "real and synthetic counts are both below {min_count} are pooled."
)


# ----------------------------------------------------------------- output files


def render_summary(report: Mapping[str, Any]) -> str:
    """Short human-readable summary of a report."""
    d = report["data"]
    lines = [
        f"Validation run '{report['label']}'  ({report['generated_at_utc']})",
        f"Real rows: {d['n_real']:,}   synthetic cohorts: {d['n_replicates']} "
        f"(rows {', '.join(f'{n:,}' for n in d['n_synthetic'])})   "
        f"columns compared: {d['columns_compared']}",
    ]
    disc = report.get("discriminator")
    if disc:
        lines += ["", f"HEADLINE  discriminator AUC = {disc['auc']:.3f} "
                  f"(fold std {disc['auc_fold_std']:.3f}; target 0.5)"]
        if disc.get("auc_by_replicate"):
            per = ", ".join(f"{a:.3f}" for a in disc["auc_by_replicate"])
            lines.append(f"  per replicate: {per}")
        lines.append("  columns that drive it (AUC drop when permuted):")
        for t in disc["top_columns"][:5]:
            lines.append(f"    {t['column']:<28} {t['auc_drop']:+.4f}")
    uni = report.get("univariate")
    if uni:
        s = uni["summary"]
        lines += ["", f"Univariate distance (TVD/KS): mean {s['mean']}, max {s['max']}; worst:"]
        lines += [f"    {w['variable']:<28} {w['distance']:.4f}" for w in s["worst"][:5]]
    dep = report.get("dependency")
    if dep:
        s = dep["summary"]
        lines += [
            "",
            f"Dependency difference over {s['n_pairs']} pairs: mean {s['mean_abs_diff']}, "
            f"max {s['max_abs_diff']}; worst pairs:",
        ]
        lines += [
            f"    {p['a']} x {p['b']}: real {p['real']:.3f} vs synthetic {p['synthetic']:.3f}"
            for p in dep["worst_pairs"][:5]
        ]
    env = report.get("replicate_envelope")
    if env:
        if env["available"]:
            expected = env["expected_fraction_inside_if_unbiased"]
            lines += [
                "",
                f"Replicate envelope: {env['fraction_inside']:.1%} of {env['n_statistics']} real "
                f"statistics inside the range of {env['n_replicates']} replicates "
                f"(about {expected:.1%} expected if unbiased)",
            ]
        else:
            lines += ["", f"Replicate envelope: not available ({env['reason']})"]
    lines += ["", report["disclosure"]]
    return "\n".join(lines) + "\n"


def history_row(report: Mapping[str, Any]) -> Dict[str, Any]:
    """Headline numbers of a report as one history row."""
    uni = (report.get("univariate") or {}).get("summary") or {}
    dep = (report.get("dependency") or {}).get("summary") or {}
    disc = report.get("discriminator") or {}
    env = report.get("replicate_envelope") or {}
    d = report["data"]
    return {
        "label": report["label"],
        "generated_at_utc": report["generated_at_utc"],
        "n_real": d["n_real"],
        "n_synthetic": d["n_synthetic"][0] if len(set(d["n_synthetic"])) == 1
        else sum(d["n_synthetic"]),
        "n_replicates": d["n_replicates"],
        "auc": disc.get("auc", ""),
        "auc_fold_std": disc.get("auc_fold_std", ""),
        "univariate_mean": uni.get("mean", ""),
        "univariate_max": uni.get("max", ""),
        "dependency_mean": dep.get("mean_abs_diff", ""),
        "dependency_max": dep.get("max_abs_diff", ""),
        "envelope_fraction_inside": env.get("fraction_inside", "") if env.get("available") else "",
        "min_count": report["settings"]["min_count"],
        "seed": report["settings"]["seed"],
        "version": report["synthpediatric_version"],
    }


def append_history(path: Any, report: Mapping[str, Any]) -> bool:
    """Append the report's headline row to a CSV history file. Returns True if the label
    was already present (the new row is still appended; the latest row wins)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    row = history_row(report)
    duplicate = False
    if p.exists() and p.stat().st_size > 0:
        with p.open("r", newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames != _HISTORY_FIELDS:
                raise ValidationError(
                    f"history file {p} has different columns than this version writes; "
                    "use a new file"
                )
            duplicate = any(r["label"] == row["label"] for r in reader)
        new_file = False
    else:
        new_file = True
    with p.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_HISTORY_FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerow(row)
    return duplicate


def read_history(path: Any) -> pd.DataFrame:
    """Load a history file (one row per run, in the order they were appended)."""
    return pd.read_csv(path)


def write_report(
    report: Mapping[str, Any], out_dir: Any, history_path: Any = None
) -> Dict[str, Path]:
    """Write ``report_<label>.json``, ``summary_<label>.txt`` and append to the history."""
    audit_report(report, int(report["settings"]["min_count"]))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    label = report["label"]
    json_path = out / f"report_{label}.json"
    txt_path = out / f"summary_{label}.txt"
    text = json.dumps(report, indent=2, default=_json_default)
    json_path.write_text(text + "\n", encoding="utf-8")
    txt_path.write_text(render_summary(report), encoding="utf-8")
    hist = Path(history_path) if history_path else out / "history.csv"
    if append_history(hist, report):
        print(f"warning: label '{label}' was already in {hist}; the new row was appended",
              file=sys.stderr)
    return {"report": json_path, "summary": txt_path, "history": hist}


def _json_default(obj: Any) -> Any:
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return None if np.isnan(obj) else float(obj)
    raise TypeError(f"not JSON serializable: {type(obj).__name__}")


# --------------------------------------------------------------------------- CLI


def run_cli(args: Any) -> int:
    """Implementation of ``synthpediatric validate`` (parsed arguments from cli.py)."""
    from .cli import _is_rdf_spec, _load_dictionary

    try:
        real = read_frame(args.real)
        syns = [read_frame(p) for p in args.synthetic]
        dictionary = None
        if args.dictionary:
            dictionary = (
                _load_dictionary(args) if _is_rdf_spec(args.dictionary)
                else load_context_dictionary(args.dictionary)
            )
        metrics = [m.strip() for m in (args.metrics or "").split(",") if m.strip()] or None
        exclude = [c.strip() for c in args.exclude.split(",") if c.strip()] if args.exclude else []
        report = validate_cohorts(
            real, syns, label=args.label, dictionary=dictionary, seed=args.seed,
            min_count=args.min_count, metrics=metrics, exclude=exclude, n_splits=args.folds,
        )
    except (ValidationError, MetricNameError, ImportError, FileNotFoundError) as exc:
        raise SystemExit(f"validate: {exc}")
    paths = write_report(report, args.out_dir, args.history)
    print(render_summary(report))
    print(f"Wrote: {paths['report']}, {paths['summary']}, history {paths['history']}")
    return 0
