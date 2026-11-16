"""Privacy tier of the validation scorecard.

Four measures, all computed from a real cohort and one or more synthetic cohorts:

* ``nn_distance_ratio``: nearest-neighbour distance from synthetic records to real records,
  divided by the nearest-neighbour distance from real records to other real records;
* ``identifiability``: the ADS-GAN identifiability score (Yoon et al. 2020), the share of
  real records whose nearest synthetic record is strictly closer than their nearest other
  real record, with attributes weighted by inverse entropy;
* ``attribute_inference``: an attacker who knows a real participant's other fields predicts
  a chosen sensitive field from the synthetic data (nearest-neighbour vote); reported
  against a baseline that guesses the most common value of the field's marginal;
* ``membership_inference``: AUC of a distance-to-nearest-synthetic-record attack that
  separates real records the generator may have seen (members) from real records it did
  not (a holdout).

Distance: weighted Gower distance for mixed records. A categorical field contributes 0 when
the two values are equal and 1 otherwise (missing is its own value); a numeric field
contributes ``|a - b| / range`` (range of the real cohort, capped at 1; one missing value
contributes 1, two missing values 0). The distance is the weighted mean over fields, so it
lies in [0, 1]. Everything here uses numpy and pandas only (no scikit-learn).

Distance work is quadratic, so each cohort is sampled (seeded, without replacement) to at
most ``max_records`` rows; see ``docs/validation.md``. The output holds aggregate numbers
only, never a row, a category count or a record value.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from .validate import METRIC_NAMES, ValidationError, _cat_values, _num_values

PRIVACY_METRICS: Tuple[str, ...] = METRIC_NAMES["privacy"]
DEFAULT_MAX_RECORDS = 2000
MIN_RECORDS = 30          # fewer records than this and the privacy numbers are not meaningful
DEFAULT_K = 5             # neighbours that vote in the attribute-inference attack
_VOTE_EPS = 0.001         # votes are weighted 1 / (distance + eps)
_ENTROPY_BINS = 10

# threshold key -> (metric, direction). "max": pass when value <= threshold;
# "min": pass when value >= threshold. No default value exists for any of them.
THRESHOLDS: Dict[str, Tuple[str, str]] = {
    "identifiability_max": ("identifiability", "max"),
    "nn_distance_ratio_min": ("nn_distance_ratio", "min"),
    "membership_auc_max": ("membership_inference", "max"),
    "attribute_inference_lift_max": ("attribute_inference", "max"),
}
NO_THRESHOLD = "no threshold configured"


class PrivacyInputError(ValidationError):
    """A privacy metric cannot be computed from the given inputs."""


# ------------------------------------------------------------------- encoding


class _Encoded:
    """Columns of several frames as aligned arrays: integer codes or range-scaled floats."""

    def __init__(
        self, frames: Sequence[pd.DataFrame], columns: Sequence[str], types: Mapping[str, str]
    ):
        self.columns = list(columns)
        self.kinds = ["n" if types[c] == "numeric" else "c" for c in self.columns]
        self.n_levels: List[int] = []
        self.feats: List[List[np.ndarray]] = [[] for _ in frames]
        for col, kind in zip(self.columns, self.kinds):
            if kind == "n":
                arrays = [_num_values(f[col]) for f in frames]
                ref = arrays[0][np.isfinite(arrays[0])]
                lo, hi = (float(ref.min()), float(ref.max())) if ref.size else (0.0, 0.0)
                span = hi - lo if hi > lo else 1.0
                for i, a in enumerate(arrays):
                    self.feats[i].append((a - lo) / span)
                self.n_levels.append(0)
            else:
                series = [_cat_values(f[col]) for f in frames]
                levels = pd.unique(pd.concat(series, ignore_index=True))
                for i, s in enumerate(series):
                    codes = pd.Categorical(s, categories=levels).codes.astype(np.int64)
                    self.feats[i].append(codes)
                self.n_levels.append(len(levels))

    def rows(self, which: int, idx: np.ndarray) -> List[np.ndarray]:
        return [feat[idx] for feat in self.feats[which]]


def _entropy(p: np.ndarray) -> float:
    p = p[p > 0]
    return float(-(p * np.log(p)).sum())


def entropy_weights(enc: _Encoded, which: int = 0) -> np.ndarray:
    """Inverse-entropy attribute weights from one cohort (Yoon et al. 2020).

    Entropy is in nats; numeric fields are binned into 10 equal-width bins first. A field
    with no variation has zero entropy and gets weight 0.
    """
    w = np.zeros(len(enc.columns))
    for j, kind in enumerate(enc.kinds):
        x = enc.feats[which][j]
        if kind == "c":
            counts = np.bincount(x, minlength=enc.n_levels[j]).astype(float)
        else:
            x = x[np.isfinite(x)]
            if x.size == 0:
                continue
            counts = np.histogram(x, bins=_ENTROPY_BINS)[0].astype(float)
        if counts.sum() == 0:
            continue
        h = _entropy(counts / counts.sum())
        w[j] = 1.0 / h if h > 1e-9 else 0.0
    return w


# ------------------------------------------------------------------- distances


def _chunk_rows(m: int) -> int:
    return max(1, int(4_000_000 // max(m, 1)))


def _distance_block(
    A: Sequence[np.ndarray], B: Sequence[np.ndarray], kinds: Sequence[str],
    w: np.ndarray, lo: int, hi: int,
) -> np.ndarray:
    """Weighted Gower distances from rows ``lo:hi`` of A to every row of B."""
    D = np.zeros((hi - lo, len(B[0])))
    wsum = 0.0
    for j, kind in enumerate(kinds):
        if w[j] <= 0:
            continue
        a = A[j][lo:hi, None]
        b = B[j][None, :]
        if kind == "c":
            d = (a != b).astype(float)
        else:
            an, bn = np.isnan(a), np.isnan(b)
            d = np.minimum(np.abs(a - b), 1.0)
            if an.any() or bn.any():
                d = np.where(an | bn, (an != bn).astype(float), d)
        D += w[j] * d
        wsum += w[j]
    if wsum <= 0:
        raise PrivacyInputError("no field varies in the real cohort, so no distance is defined")
    return D / wsum


def nearest_distances(
    A: Sequence[np.ndarray], B: Sequence[np.ndarray], kinds: Sequence[str], w: np.ndarray,
    *, same: bool = False, want_cols: bool = False,
) -> Tuple[np.ndarray, Optional[np.ndarray]]:
    """Distance from each row of A to its nearest row of B (and the reverse when asked).

    With ``same=True`` A and B are the same rows and a row is not its own neighbour.
    """
    n, m = len(A[0]), len(B[0])
    row_min = np.empty(n)
    col_min = np.full(m, np.inf) if want_cols else None
    step = _chunk_rows(m)
    for lo in range(0, n, step):
        hi = min(n, lo + step)
        D = _distance_block(A, B, kinds, w, lo, hi)
        if same:
            r = np.arange(lo, hi)
            D[r - lo, r] = np.inf
        row_min[lo:hi] = D.min(axis=1)
        if col_min is not None:
            col_min = np.minimum(col_min, D.min(axis=0))
    return row_min, col_min


def _sample(n_avail: int, n_use: int, rng: np.random.Generator) -> np.ndarray:
    if n_use >= n_avail:
        return np.arange(n_avail)
    return np.sort(rng.choice(n_avail, size=n_use, replace=False))


def _balanced_size(sizes: Sequence[int], cap: int, what: str) -> int:
    n = min(min(sizes), cap)
    if n < MIN_RECORDS:
        raise PrivacyInputError(f"{what} needs at least {MIN_RECORDS} records per cohort, got {n}")
    return n


# --------------------------------------------------------------------- metrics


def nn_distance_ratio(
    enc: _Encoded, real_i: int, syn_i: int, *, max_records: int, rng: np.random.Generator
) -> Dict[str, Any]:
    """Synthetic-to-real versus real-to-real nearest-neighbour distance (unweighted Gower)."""
    n = _balanced_size([len(enc.feats[real_i][0]), len(enc.feats[syn_i][0])], max_records,
                       "nn_distance_ratio")
    ri = _sample(len(enc.feats[real_i][0]), n, rng)
    si = _sample(len(enc.feats[syn_i][0]), n, rng)
    R, S = enc.rows(real_i, ri), enc.rows(syn_i, si)
    w = np.ones(len(enc.columns))
    d_rr, _ = nearest_distances(R, R, enc.kinds, w, same=True)
    _, d_sr = nearest_distances(R, S, enc.kinds, w, want_cols=True)
    mean_rr, mean_sr = float(d_rr.mean()), float(d_sr.mean())
    return {
        "records_per_cohort": int(n),
        "mean_real_to_real": round(mean_rr, 6),
        "mean_synthetic_to_real": round(mean_sr, 6),
        "ratio": round(mean_sr / mean_rr, 6) if mean_rr > 0 else None,
        "share_synthetic_identical_to_a_real_record": round(float((d_sr == 0).mean()), 6),
        "share_real_identical_to_another_real_record": round(float((d_rr == 0).mean()), 6),
    }


def identifiability(
    enc: _Encoded, real_i: int, syn_i: int, *, max_records: int, rng: np.random.Generator
) -> Dict[str, Any]:
    """Identifiability score of Yoon et al. 2020 (inverse-entropy weighted Gower distance).

    For each real record i: ``d_i`` is the distance to its nearest other real record and
    ``d_hat_i`` the distance to its nearest synthetic record. The score is the share of
    real records with ``d_hat_i < d_i`` (strict). Ties count as not closer; their share is
    reported. For a synthetic cohort drawn independently from the same distribution, with
    n real and n synthetic records, the score is expected near n / (2n - 1), about 0.5.
    """
    n = _balanced_size([len(enc.feats[real_i][0]), len(enc.feats[syn_i][0])], max_records,
                       "identifiability")
    ri = _sample(len(enc.feats[real_i][0]), n, rng)
    si = _sample(len(enc.feats[syn_i][0]), n, rng)
    R, S = enc.rows(real_i, ri), enc.rows(syn_i, si)
    w = entropy_weights(enc, real_i)
    d_rr, _ = nearest_distances(R, R, enc.kinds, w, same=True)
    d_rs, _ = nearest_distances(R, S, enc.kinds, w)
    return {
        "records_per_cohort": int(n),
        "score": round(float((d_rs < d_rr).mean()), 6),
        "share_ties": round(float((d_rs == d_rr).mean()), 6),
        "reference_if_independent": round(n / (2 * n - 1), 6),
        "fields_with_weight": int((w > 0).sum()),
    }


def _knn_predict(
    Q: Sequence[np.ndarray], S: Sequence[np.ndarray], kinds: Sequence[str],
    s_target: np.ndarray, n_classes: int, k: int,
) -> np.ndarray:
    """Weighted-vote k-nearest-neighbour prediction of ``s_target`` for each query row."""
    m = len(S[0])
    k = min(k, m)
    w = np.ones(len(kinds))
    out = np.empty(len(Q[0]), dtype=np.int64)
    step = _chunk_rows(m)
    for lo in range(0, len(Q[0]), step):
        hi = min(len(Q[0]), lo + step)
        D = _distance_block(Q, S, kinds, w, lo, hi)
        idx = (np.argpartition(D, k - 1, axis=1)[:, :k] if m > k
               else np.tile(np.arange(m), (hi - lo, 1)))
        dist = np.take_along_axis(D, idx, axis=1)
        wts = 1.0 / (dist + _VOTE_EPS)
        votes = np.zeros((hi - lo, n_classes))
        classes = s_target[idx]
        rows = np.arange(hi - lo)
        for j in range(idx.shape[1]):
            votes[rows, classes[:, j]] += wts[:, j]
        out[lo:hi] = votes.argmax(axis=1)
    return out


def attribute_inference(
    frames: Sequence[pd.DataFrame], types: Mapping[str, str], columns: Sequence[str],
    sensitive: str, *, max_records: int, rng: np.random.Generator, k: int = DEFAULT_K,
) -> Dict[str, Any]:
    """Predict ``sensitive`` for real records from the synthetic cohort and score it.

    ``frames`` is ``[real, synthetic]``. The attacker knows every other column of a real
    record, finds its ``k`` nearest synthetic records (unweighted Gower distance over the
    known columns) and takes a vote weighted by 1 / (distance + 0.001). The baseline guesses
    the most common value of the synthetic marginal of the field, with no other knowledge.
    """
    if sensitive not in columns:
        raise PrivacyInputError(f"sensitive field '{sensitive}' is not a compared column")
    if types[sensitive] != "categorical":
        raise PrivacyInputError(
            f"sensitive field '{sensitive}' is numeric; only categorical fields are supported"
        )
    known = [c for c in columns if c != sensitive]
    if not known:
        raise PrivacyInputError("no other columns remain to use as known fields")
    real, syn = frames
    nr = min(len(real), max_records)
    ns = min(len(syn), max_records)
    if min(nr, ns) < MIN_RECORDS:
        raise PrivacyInputError(
            f"attribute_inference needs at least {MIN_RECORDS} records per cohort, "
            f"got {min(nr, ns)}"
        )
    real = real.iloc[_sample(len(real), nr, rng)].reset_index(drop=True)
    syn = syn.iloc[_sample(len(syn), ns, rng)].reset_index(drop=True)
    enc = _Encoded([real, syn], known, types)
    t_real = _cat_values(real[sensitive])
    t_syn = _cat_values(syn[sensitive])
    levels = pd.unique(pd.concat([t_real, t_syn], ignore_index=True))
    y_real = pd.Categorical(t_real, categories=levels).codes.astype(np.int64)
    y_syn = pd.Categorical(t_syn, categories=levels).codes.astype(np.int64)
    pred = _knn_predict(enc.rows(0, np.arange(nr)), enc.rows(1, np.arange(ns)), enc.kinds,
                        y_syn, len(levels), k)
    accuracy = float((pred == y_real).mean())
    mode = int(np.bincount(y_syn, minlength=len(levels)).argmax())
    baseline = float((y_real == mode).mean())
    return {
        "sensitive_field": sensitive,
        "n_known_fields": len(known),
        "n_attacked_records": int(nr),
        "n_synthetic_records": int(ns),
        "k": int(min(k, ns)),
        "accuracy": round(accuracy, 6),
        "baseline_accuracy": round(baseline, 6),
        "lift": round(accuracy - baseline, 6),
    }


def _auc(pos: np.ndarray, neg: np.ndarray) -> float:
    """Probability that a random positive scores above a random negative (ties count half)."""
    ranks = pd.Series(np.concatenate([pos, neg])).rank(method="average").to_numpy()
    n1, n0 = len(pos), len(neg)
    return float((ranks[:n1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def membership_inference(
    enc: _Encoded, members_i: int, non_i: int, syn_i: int, *, max_records: int,
    rng: np.random.Generator,
) -> Dict[str, Any]:
    """AUC of the attack "a record is a member if a synthetic record lies close to it".

    The score of a record is minus its distance to the nearest synthetic record (unweighted
    Gower). Members and non-members are sampled to the same size. About 0.5 means the
    attacker cannot tell them apart.
    """
    sizes = [len(enc.feats[i][0]) for i in (members_i, non_i, syn_i)]
    n = _balanced_size(sizes[:2], max_records, "membership_inference")
    ns = _balanced_size(sizes[2:], max_records, "membership_inference")
    mi = _sample(sizes[0], n, rng)
    ni = _sample(sizes[1], n, rng)
    si = _sample(sizes[2], ns, rng)
    S = enc.rows(syn_i, si)
    w = np.ones(len(enc.columns))
    d_m, _ = nearest_distances(enc.rows(members_i, mi), S, enc.kinds, w)
    d_n, _ = nearest_distances(enc.rows(non_i, ni), S, enc.kinds, w)
    return {
        "members": int(n), "non_members": int(n), "synthetic_records": int(ns),
        "auc": round(_auc(-d_m, -d_n), 6),
    }


# ---------------------------------------------------------------- orchestration


def _mean(values: Sequence[Optional[float]]) -> Optional[float]:
    clean = [v for v in values if v is not None]
    return round(float(np.mean(clean)), 6) if clean else None


def evaluate_gates(
    headline: Mapping[str, Optional[float]], thresholds: Optional[Mapping[str, float]]
) -> List[Dict[str, Any]]:
    """Compare each headline number with its configured threshold, if any.

    ``headline`` maps a metric name to its number. A metric with no configured threshold
    reports 'no threshold configured'; there is no default threshold for any metric.
    """
    thresholds = thresholds or {}
    out = []
    for key, (metric, direction) in THRESHOLDS.items():
        value = headline.get(metric)
        limit = thresholds.get(key)
        if limit is None:
            status = NO_THRESHOLD
        elif value is None:
            status = "not computed"
        elif direction == "max":
            status = "pass" if value <= limit else "fail"
        else:
            status = "pass" if value >= limit else "fail"
        out.append({"metric": metric, "threshold_key": key, "direction": direction,
                    "value": value, "threshold": limit, "status": status})
    return out


def privacy_report(
    real: pd.DataFrame,
    syns: Sequence[pd.DataFrame],
    columns: Sequence[str],
    types: Mapping[str, str],
    *,
    metrics: Sequence[str],
    holdout: Optional[pd.DataFrame] = None,
    sensitive: Sequence[str] = (),
    thresholds: Optional[Mapping[str, float]] = None,
    max_records: int = DEFAULT_MAX_RECORDS,
    seed: int = 0,
    k: int = DEFAULT_K,
) -> Dict[str, Any]:
    """Compute the requested privacy metrics; return ``{"privacy": {...}, "skipped": [...]}``.

    A metric that cannot run (no holdout, no sensitive field, too few records) is listed in
    ``skipped`` with the reason; nothing is dropped silently. Scalar results are means over
    the synthetic cohorts, with the per-cohort values listed.
    """
    unknown = [m for m in metrics if m not in PRIVACY_METRICS]
    if unknown:
        raise PrivacyInputError(f"unknown privacy metric(s): {', '.join(unknown)}")
    if max_records < MIN_RECORDS:
        raise PrivacyInputError(f"max_records must be at least {MIN_RECORDS}")
    columns = list(columns)
    skipped: List[Dict[str, str]] = []
    out: Dict[str, Any] = {}
    headline: Dict[str, Optional[float]] = {}

    def skip(metric: str, reason: str) -> None:
        skipped.append({"metric": metric, "reason": reason})

    hold_cols = columns
    if holdout is not None:
        hold_cols = [c for c in columns if c in holdout.columns]

    frames = [real] + list(syns)
    use_hold = holdout is not None and "membership_inference" in metrics and len(hold_cols) > 0
    if use_hold:
        frames.append(holdout)
    enc_cache: Dict[Tuple[str, ...], _Encoded] = {}

    def encoded(cols: Sequence[str], with_holdout: bool) -> _Encoded:
        key = (*cols, "H" if with_holdout else "-")
        if key not in enc_cache:
            fr = frames if with_holdout else frames[: 1 + len(syns)]
            enc_cache[key] = _Encoded(fr, cols, types)
        return enc_cache[key]

    def per_syn(name: str, fn) -> Optional[List[Dict[str, Any]]]:
        results = []
        for i in range(len(syns)):
            try:
                results.append(fn(i, np.random.default_rng([seed, i, len(name)])))
            except PrivacyInputError as exc:
                skip(name, str(exc))
                return None
        return results

    def combine(results: List[Dict[str, Any]], key: str) -> Dict[str, Any]:
        merged = dict(results[0])
        if len(results) > 1:
            merged[key] = _mean([r[key] for r in results])
            merged[f"{key}_by_replicate"] = [r[key] for r in results]
        return merged

    if "nn_distance_ratio" in metrics:
        res = per_syn("nn_distance_ratio", lambda i, rng: nn_distance_ratio(
            encoded(columns, False), 0, 1 + i, max_records=max_records, rng=rng))
        if res:
            merged = combine(res, "ratio")
            merged["interpretation"] = (
                "Mean distance from a synthetic record to its nearest real record, divided by "
                "the mean distance from a real record to its nearest other real record. About "
                "1 means synthetic records are no closer to real individuals than real "
                "individuals are to each other; near 0 means synthetic records sit on top of "
                "real ones (copying). Values well above 1 only say the synthetic cohort is "
                "further from the real one; that is a fidelity matter, not a privacy risk."
            )
            out["nn_distance_ratio"] = merged
            headline["nn_distance_ratio"] = merged["ratio"]
    if "identifiability" in metrics:
        res = per_syn("identifiability", lambda i, rng: identifiability(
            encoded(columns, False), 0, 1 + i, max_records=max_records, rng=rng))
        if res:
            merged = combine(res, "score")
            merged["interpretation"] = (
                "Share of real records whose nearest synthetic record is closer than their "
                "nearest other real record (Yoon et al. 2020). If the synthetic cohort is an "
                f"independent draw from the same distribution the score is expected near "
                f"{merged['reference_if_independent']:.2f}, so that value is the neutral "
                "reference here, not 0. Scores toward 1 mean synthetic records sit unusually "
                "close to individual real records. No release threshold has been agreed."
            )
            out["identifiability"] = merged
            headline["identifiability"] = merged["score"]
    if "attribute_inference" in metrics:
        if not sensitive:
            skip("attribute_inference",
                 "no sensitive fields configured (validate.sensitive / --sensitive); none are "
                 "assumed")
        else:
            fields = []
            for col in sensitive:
                res = per_syn("attribute_inference", lambda i, rng, col=col: attribute_inference(
                    [real, syns[i]], types, columns, col, max_records=max_records, rng=rng, k=k))
                if res is None:
                    continue
                merged = combine(res, "accuracy")
                for key in ("baseline_accuracy", "lift"):
                    if len(res) > 1:
                        merged[key] = _mean([r[key] for r in res])
                fields.append(merged)
            if fields:
                lift = max(f["lift"] for f in fields)
                out["attribute_inference"] = {
                    "fields": fields,
                    "max_lift": round(lift, 6),
                    "interpretation": (
                        "Accuracy of predicting the sensitive field of a real record from the "
                        "synthetic data, given the record's other fields, compared with the "
                        "accuracy of always guessing the field's most common value. A lift near "
                        "0 means the other fields add nothing. A positive lift can also come "
                        "from a genuine population-level relationship that the synthetic data "
                        "reproduces; it is not proof that individuals are exposed."
                    ),
                }
                headline["attribute_inference"] = round(lift, 6)
    if "membership_inference" in metrics:
        if holdout is None:
            skip("membership_inference",
                 "needs a holdout of real records that were not used to build the synthetic "
                 "data (validate.holdout / --holdout)")
        elif not use_hold:
            skip("membership_inference", "the holdout shares no columns with the compared data")
        else:
            res = per_syn("membership_inference", lambda i, rng: membership_inference(
                encoded(hold_cols, True), 0, 1 + len(syns), 1 + i,
                max_records=max_records, rng=rng))
            if res:
                merged = combine(res, "auc")
                merged["columns_used"] = len(hold_cols)
                merged["interpretation"] = (
                    "AUC of an attacker who guesses that a record belongs to the real "
                    "(member) group when a synthetic record lies close to it. About 0.5 means "
                    "the attacker cannot tell members from non-members; toward 1 means the "
                    "synthetic data sits closer to members, which indicates copying."
                )
                out["membership_inference"] = merged
                headline["membership_inference"] = merged["auc"]
    gates = evaluate_gates(headline, thresholds)
    gate = next(g for g in gates if g["metric"] == "identifiability")
    out["settings"] = {
        "metrics": [m for m in metrics], "max_records": int(max_records), "seed": int(seed),
        "distance": "weighted Gower (identifiability: inverse-entropy weights; others: equal)",
        "attribute_inference_k": int(k),
    }
    out["thresholds"] = gates
    out["release_gate"] = {
        **gate,
        "note": (
            "The identifiability score is the proposed release gate. No threshold has been "
            "agreed; thresholds are set in the config and are unset by default."
        ),
    }
    return {"privacy": out, "skipped": skipped, "headline": headline}
