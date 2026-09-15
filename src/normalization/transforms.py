"""Pure Gate 4 transforms: log1p, percentile (fit / apply on a persisted
ECDF table), and the k-ring local ratio.

Every function here takes plain Series/DataFrames and returns new objects;
nothing mutates its input, reads a file, or knows about run directories.
Every output value comes with a status: the atomic input's status is
copied verbatim when it is not `ok` (the value stays null -- never
imputed), and transform-specific failures use the Gate 4 vocabulary in
`config/gate4_mvp.yaml`. No weights, no scores.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np
import pandas as pd

OK = "ok"
COHORT_TOO_SMALL = "cohort_too_small"
COHORT_DEGENERATE = "cohort_degenerate"
COHORT_NOT_FITTED = "cohort_not_fitted"
NEIGHBORHOOD_INCOMPLETE = "neighborhood_incomplete"
NEIGHBORHOOD_INSUFFICIENT_VALID = "neighborhood_insufficient_valid"
NEIGHBORHOOD_REFERENCE_ZERO = "neighborhood_reference_zero"

TIE_METHODS = ("midrank_ecdf", "min_ecdf", "max_ecdf")
REFERENCE_STATISTICS = ("median", "mean")

ECDF_COLUMNS = ["cohort_id", "feature", "weighting", "value", "weight_equal", "weight_below",
                "weight_total", "n_obs", "n_distinct", "fit_status"]


class TransformInputError(ValueError):
    """The atomic input violates the transform's domain (e.g. a negative
    value under log1p). This is a contract failure, not a missing value."""


def _as_float(values: pd.Series) -> np.ndarray:
    return values.to_numpy(dtype="float64", na_value=np.nan)


def _check_status_consistency(values: np.ndarray, status: pd.Series, name: str) -> None:
    ok = (status == OK).to_numpy()
    if status.isna().any():
        raise TransformInputError(f"{name}: null status")
    if (ok & np.isnan(values)).any():
        raise TransformInputError(f"{name}: null value with status ok (bare null)")
    if (~ok & ~np.isnan(values)).any():
        raise TransformInputError(f"{name}: non-null value with a failure status")


# ---------------------------------------------------------------------------
# A. log1p
# ---------------------------------------------------------------------------

def log1p_transform(values: pd.Series, status: pd.Series, name: str = "") -> tuple[pd.Series, pd.Series]:
    """ln(1 + x) for `ok` rows; null with the atomic status otherwise.
    0 -> 0 exactly. A negative finite value raises."""
    x = _as_float(values)
    _check_status_consistency(x, status, name or str(values.name))
    finite = np.isfinite(x)
    if (x[finite] < 0).any():
        n = int((x[finite] < 0).sum())
        raise TransformInputError(f"{name or values.name}: {n} negative value(s); log1p is defined on x >= 0 only")
    out = np.full(len(x), np.nan)
    out[finite] = np.log1p(x[finite])
    return (pd.Series(out, index=values.index, name=name or None),
            pd.Series(status.to_numpy(), index=values.index).astype(str))


# ---------------------------------------------------------------------------
# B. percentile: fit -> persisted ECDF table -> apply
# ---------------------------------------------------------------------------

def fit_ecdf(values: pd.Series, status: pd.Series, weights: Optional[pd.Series], cohort_id: str,
             feature: str, weighting: str, minimum_cohort_size: int) -> pd.DataFrame:
    """One ECDF table for (cohort, feature, weighting): every distinct
    valid value with its weight and the cumulative weight strictly below
    it. Rows with a non-`ok` status are not part of the cohort. A cohort
    below `minimum_cohort_size` or with a single distinct value is
    recorded with a non-`ok` fit_status and no value rows, so `apply`
    can report it instead of guessing."""
    x = _as_float(values)
    _check_status_consistency(x, status, feature)
    w = np.ones(len(x)) if weights is None else weights.to_numpy(dtype="float64")
    if (w < 0).any() or not np.isfinite(w).all():
        raise TransformInputError(f"{feature}: weights must be finite and non-negative")
    valid = np.isfinite(x) & (w > 0)
    xv, wv = x[valid], w[valid]
    n_obs = int(valid.sum())
    base = {"cohort_id": cohort_id, "feature": feature, "weighting": weighting}
    if n_obs < minimum_cohort_size:
        return pd.DataFrame([{**base, "value": np.nan, "weight_equal": np.nan, "weight_below": np.nan,
                              "weight_total": float(wv.sum()), "n_obs": n_obs, "n_distinct": int(len(np.unique(xv))),
                              "fit_status": COHORT_TOO_SMALL}], columns=ECDF_COLUMNS)
    uniq, inverse = np.unique(xv, return_inverse=True)
    if len(uniq) < 2:
        return pd.DataFrame([{**base, "value": np.nan, "weight_equal": np.nan, "weight_below": np.nan,
                              "weight_total": float(wv.sum()), "n_obs": n_obs, "n_distinct": int(len(uniq)),
                              "fit_status": COHORT_DEGENERATE}], columns=ECDF_COLUMNS)
    w_eq = np.bincount(inverse, weights=wv, minlength=len(uniq))
    w_below = np.concatenate([[0.0], np.cumsum(w_eq)[:-1]])
    return pd.DataFrame({**base, "value": uniq, "weight_equal": w_eq, "weight_below": w_below,
                         "weight_total": float(w_eq.sum()), "n_obs": n_obs, "n_distinct": int(len(uniq)),
                         "fit_status": OK}, columns=ECDF_COLUMNS)


def _ecdf_lookup(x: np.ndarray, table: pd.DataFrame, tie_method: str) -> np.ndarray:
    """Percentile of each finite x against one fitted (ok) ECDF table.
    Unseen values fall between fitted values (weight_equal 0)."""
    if tie_method not in TIE_METHODS:
        raise ValueError(f"tie_method must be one of {TIE_METHODS}, got {tie_method!r}")
    vals = table["value"].to_numpy(dtype="float64")
    w_eq = table["weight_equal"].to_numpy(dtype="float64")
    w_below = table["weight_below"].to_numpy(dtype="float64")
    total = float(table["weight_total"].iloc[0])
    cum_le = w_below + w_eq
    idx = np.searchsorted(vals, x, side="left")
    below = np.where(idx > 0, cum_le[np.clip(idx - 1, 0, len(vals) - 1)], 0.0)
    hit = (idx < len(vals)) & (vals[np.clip(idx, 0, len(vals) - 1)] == x)
    equal = np.where(hit, w_eq[np.clip(idx, 0, len(vals) - 1)], 0.0)
    if tie_method == "midrank_ecdf":
        p = (below + 0.5 * equal) / total
    elif tie_method == "min_ecdf":
        p = below / total
    else:
        p = (below + equal) / total
    return p


def apply_ecdf(values: pd.Series, status: pd.Series, ecdf: pd.DataFrame, cohort_id: str, feature: str,
               weighting: str, tie_method: str) -> tuple[pd.Series, pd.Series]:
    """Percentile in [0, 1] of each `ok` value against the PERSISTED table
    for (cohort_id, feature, weighting). Non-`ok` input keeps its status
    and a null value; a missing/failed fit gives the fit status."""
    x = _as_float(values)
    _check_status_consistency(x, status, feature)
    out = np.full(len(x), np.nan)
    out_status = status.astype(str).to_numpy().copy()
    ok = (status == OK).to_numpy()
    sel = ecdf[(ecdf["cohort_id"] == cohort_id) & (ecdf["feature"] == feature) & (ecdf["weighting"] == weighting)]
    if len(sel) == 0:
        out_status[ok] = COHORT_NOT_FITTED
    elif (sel["fit_status"] != OK).any():
        out_status[ok] = str(sel["fit_status"].iloc[0])
    else:
        sel = sel.sort_values("value")
        out[ok] = _ecdf_lookup(x[ok], sel, tie_method)
    return pd.Series(out, index=values.index), pd.Series(out_status, index=values.index)


# ---------------------------------------------------------------------------
# C. local ratio on a k-ring neighborhood
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class NeighborhoodPolicy:
    k: int
    exclude_centre: bool
    reference_statistic: str
    require_all_neighbors_present: bool
    minimum_valid_neighbors: int

    def __post_init__(self) -> None:
        if self.k < 1:
            raise ValueError("k must be >= 1")
        if self.reference_statistic not in REFERENCE_STATISTICS:
            raise ValueError(f"reference_statistic must be one of {REFERENCE_STATISTICS}")
        if not self.exclude_centre:
            raise ValueError("the local ratio compares a cell to its NEIGHBORS; exclude_centre must be true")
        if self.minimum_valid_neighbors < 1:
            raise ValueError("minimum_valid_neighbors must be >= 1")


def neighborhoods(unit_ids: pd.Series, k: int, ring_fn: Callable[[str, int], list[str]]) -> pd.DataFrame:
    """Per unit: the ids of its k-ring (centre excluded), how many are in
    the table, and whether the ring is complete. `ring_fn(cell, k)` returns
    the disk of radius k (H3 `grid_disk`); it is injected so tests can use
    a synthetic lattice."""
    ids = unit_ids.astype(str)
    present = set(ids)
    rows = []
    for cell in ids:
        ring = sorted(n for n in ring_fn(cell, k) if n != cell)
        n_present = sum(1 for n in ring if n in present)
        rows.append({"spatial_unit_id": cell, "neighbors": ring, "neighbor_count": len(ring),
                     "neighbors_present": n_present, "neighborhood_complete": n_present == len(ring)})
    return pd.DataFrame(rows, index=unit_ids.index)


def local_ratio(values: pd.Series, status: pd.Series, unit_ids: pd.Series, nbh: pd.DataFrame,
                policy: NeighborhoodPolicy, feature: str = "",
                reference_statistic: Optional[str] = None) -> tuple[pd.Series, pd.Series, pd.Series]:
    """x / stat(neighbors' x) with stat = median (or mean). Returns
    (ratio, status, reference). Null with an explicit status when the
    centre is not ok, the ring is incomplete, too few neighbors are ok, or
    the reference is 0 -- no epsilon, ever."""
    stat_name = reference_statistic or policy.reference_statistic
    if stat_name not in REFERENCE_STATISTICS:
        raise ValueError(f"reference_statistic must be one of {REFERENCE_STATISTICS}")
    x = _as_float(values)
    _check_status_consistency(x, status, feature or str(values.name))
    ids = unit_ids.astype(str).to_numpy()
    value_of = dict(zip(ids, x))
    ok_of = dict(zip(ids, (status == OK).to_numpy()))
    out = np.full(len(x), np.nan)
    ref = np.full(len(x), np.nan)
    out_status = status.astype(str).to_numpy().copy()
    stat = np.median if stat_name == "median" else np.mean
    for i, (cell, ok) in enumerate(zip(ids, (status == OK).to_numpy())):
        if not ok:
            continue
        row = nbh.iloc[i]
        if policy.require_all_neighbors_present and not bool(row["neighborhood_complete"]):
            out_status[i] = NEIGHBORHOOD_INCOMPLETE
            continue
        vals = [value_of[n] for n in row["neighbors"] if n in value_of and ok_of[n]]
        if len(vals) < policy.minimum_valid_neighbors:
            out_status[i] = NEIGHBORHOOD_INSUFFICIENT_VALID
            continue
        r = float(stat(np.asarray(vals, dtype="float64")))
        ref[i] = r
        if r == 0.0:
            out_status[i] = NEIGHBORHOOD_REFERENCE_ZERO
            continue
        out[i] = x[i] / r
    return (pd.Series(out, index=values.index), pd.Series(out_status, index=values.index),
            pd.Series(ref, index=values.index))


# ---------------------------------------------------------------------------
# Cohort helpers (no I/O)
# ---------------------------------------------------------------------------

def aoi_equal_weights(aoi_ids: pd.Series) -> pd.Series:
    """Row weights that give every AOI the same total weight (1)."""
    counts = aoi_ids.value_counts()
    return aoi_ids.map(lambda a: 1.0 / counts[a]).astype("float64")


def peer_groups_are_sufficient(aoi_ids: pd.Series, contexts: pd.Series, minimum_aois_per_group: int) -> dict:
    """Distinct AOIs per context and whether every context meets the
    minimum. With one AOI per context a peer cohort is that AOI alone."""
    pairs = pd.DataFrame({"aoi_id": aoi_ids.astype(str), "context": contexts.astype(str)}).drop_duplicates()
    per = pairs.groupby("context")["aoi_id"].nunique().to_dict()
    return {"aois_per_context": {k: int(v) for k, v in per.items()},
            "minimum_aois_per_group": int(minimum_aois_per_group),
            "sufficient": bool(per) and all(v >= minimum_aois_per_group for v in per.values())}


def skewness(x: np.ndarray) -> float:
    """Adjusted Fisher-Pearson sample skewness of the finite values."""
    v = x[np.isfinite(x)]
    n = len(v)
    if n < 3:
        return float("nan")
    m = v.mean()
    s = v.std(ddof=0)
    if s == 0:
        return 0.0
    g1 = np.mean(((v - m) / s) ** 3)
    return float(g1 * np.sqrt(n * (n - 1)) / (n - 2))
