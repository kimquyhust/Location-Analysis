"""Gate 4 Contextual Normalization MVP runner: one reviewed Gate 3 run ->
fitted cohort statistics -> contextual transforms -> one immutable run.

    python -m src.normalization.run_gate4_mvp                 # data/gate4/run_<UTC>/
    python -m src.normalization.run_gate4_mvp --output-root /tmp/x   # e.g. a determinism check

The contract is `config/gate4_mvp.yaml` (transform formulas, cohorts, tie
and neighborhood policies, pre-registered publish rules). The Gate 3
input is pinned by run id, feature-set version and SHA-256; a mismatch
fails before anything is computed. Nothing here scores, weights, imputes,
or reads customer/mobility data, and nothing in `data/gate3/` is written.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional

import h3
import numpy as np
import pandas as pd

try:  # pragma: no cover - import root differs between CLI and tests
    from ..features.schema import DISTANCE_FEATURES, STATUS_COLUMN_OF, load_features_config
    from ..spatial.benchmark import (RunContext, code_version, environment, hash_config, sha256_of,
                                     utc_now_iso, write_run_manifest)
    from ..spatial.run_gate2_mvp import verify_checksums, write_checksums
    from .schema import (GATE4_LINEAGE, NEIGHBORHOOD_COLUMNS, load_gate4_config, local_ratio_name, log1p_name,
                         percentile_name, resolve_group, status_name, validate_config, validate_outputs)
    from .transforms import (ECDF_COLUMNS, OK, NeighborhoodPolicy, aoi_equal_weights, apply_ecdf, fit_ecdf,
                             local_ratio, log1p_transform, neighborhoods, peer_groups_are_sufficient, skewness)
except ImportError:  # pragma: no cover
    from features.schema import DISTANCE_FEATURES, STATUS_COLUMN_OF, load_features_config
    from spatial.benchmark import (RunContext, code_version, environment, hash_config, sha256_of,
                                   utc_now_iso, write_run_manifest)
    from spatial.run_gate2_mvp import verify_checksums, write_checksums
    from normalization.schema import (GATE4_LINEAGE, NEIGHBORHOOD_COLUMNS, load_gate4_config, local_ratio_name,
                                      log1p_name, percentile_name, resolve_group, status_name, validate_config,
                                      validate_outputs)
    from normalization.transforms import (ECDF_COLUMNS, OK, NeighborhoodPolicy, aoi_equal_weights, apply_ecdf,
                                          fit_ecdf, local_ratio, log1p_transform, neighborhoods,
                                          peer_groups_are_sufficient, skewness)

GATE4_CONFIG = Path("config/gate4_mvp.yaml")
REQUIRED_OUTPUTS = ["contextual_features.parquet", "diagnostic_features.parquet", "cohort_statistics.parquet",
                    "normalization_manifest.json", "validation_summary.json", "benchmark_runs.parquet",
                    "run_manifest.json"]
RUN_METADATA_COLUMNS = ["normalization_run_id", "computed_at_utc"]


class InputMismatch(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# input verification
# ---------------------------------------------------------------------------

def verify_gate3_input(cfg: dict, features_cfg: dict) -> dict:
    """The Gate 3 run named in the config must exist, be a full
    checksummed run, carry the pinned feature-set version, and every
    pinned file must hash to the pinned SHA-256. Returns the verification
    record for the manifest."""
    inp = cfg["input"]
    run_dir = Path(inp["gate3_run_dir"])
    if not run_dir.exists():
        raise InputMismatch(f"Gate 3 run directory missing: {run_dir}")
    bad = verify_checksums(run_dir)
    if bad:
        raise InputMismatch(f"Gate 3 SHA256SUMS mismatch for {bad}")
    hashes = {}
    for name, expected in inp["sha256"].items():
        actual = sha256_of(run_dir / name)
        hashes[name] = actual
        if actual != expected:
            raise InputMismatch(f"{name}: sha256 {actual} != pinned {expected}")
    manifest = json.loads((run_dir / "run_manifest.json").read_text())
    if manifest.get("gate") != 3 or manifest.get("run_kind") != "atomic_feature_mvp":
        raise InputMismatch("input is not a full Gate 3 atomic_feature_mvp run")
    if str(manifest.get("run_id")) != str(inp["gate3_run_id"]):
        raise InputMismatch(f"run_id {manifest.get('run_id')} != pinned {inp['gate3_run_id']}")
    for key, pinned in (("feature_set_version", inp["feature_set_version"]),
                        ("poi_taxonomy_version", inp["poi_taxonomy_version"])):
        if str(manifest.get(key)) != str(pinned):
            raise InputMismatch(f"{key} {manifest.get(key)} != pinned {pinned}")
    if str(features_cfg["feature_set_version"]) != str(inp["feature_set_version"]):
        raise InputMismatch("config/features.yaml feature_set_version differs from the pinned input version")
    if not manifest.get("validation_passed", False):
        raise InputMismatch("Gate 3 run did not pass its own validation")
    if int(manifest.get("rows", -1)) != int(inp["expected_rows"]):
        raise InputMismatch(f"rows {manifest.get('rows')} != pinned {inp['expected_rows']}")
    return {"gate3_run_id": str(manifest["run_id"]), "gate3_run_dir": str(run_dir), "sha256": hashes,
            "gate3_code_version": manifest.get("code_version"), "gate3_config_hash": manifest.get("config_hash"),
            "gate3_config_sha256": manifest.get("config_sha256"), "feature_set_version": manifest["feature_set_version"],
            "poi_taxonomy_version": manifest["poi_taxonomy_version"], "rows": int(manifest["rows"]),
            "gate3_sha256sums_verified": True}


def load_atomic(cfg: dict) -> pd.DataFrame:
    inp = cfg["input"]
    df = pd.read_parquet(Path(inp["gate3_run_dir"]) / "atomic_features.parquet")
    if len(df) != int(inp["expected_rows"]) or not df["spatial_unit_id"].is_unique:
        raise InputMismatch("atomic table rows/keys differ from the pinned input")
    if set(df["aoi_id"].astype(str)) != set(inp["aoi_ids"]):
        raise InputMismatch(f"AOIs {sorted(set(df['aoi_id']))} != pinned {inp['aoi_ids']}")
    if (df["feature_set_version"].astype(str) != str(inp["feature_set_version"])).any():
        raise InputMismatch("row feature_set_version differs from the pinned version")
    return df


# ---------------------------------------------------------------------------
# diagnostics on the atomic input
# ---------------------------------------------------------------------------

def _q(v: np.ndarray, q: float) -> Optional[float]:
    return float(np.percentile(v, q)) if len(v) else None


def distribution_diagnostics(atomic: pd.DataFrame, features: list[str]) -> dict:
    out: dict = {}
    groups = [("pooled", atomic)] + [(a, s) for a, s in atomic.groupby("aoi_id")]
    for f in features:
        out[f] = {}
        for name, sub in groups:
            v = sub[f].to_numpy(dtype="float64", na_value=np.nan)
            st = sub[STATUS_COLUMN_OF[f]].value_counts().to_dict()
            fin = v[np.isfinite(v)]
            out[f][name] = {
                "rows": int(len(v)), "null_rate": float(np.isnan(v).mean()),
                "zero_rate_of_valid": float((fin == 0).mean()) if len(fin) else None,
                "n_valid": int(len(fin)), "n_distinct": int(len(np.unique(fin))),
                "min": float(fin.min()) if len(fin) else None, "p50": _q(fin, 50), "p95": _q(fin, 95),
                "max": float(fin.max()) if len(fin) else None,
                "skew_raw": skewness(fin), "skew_log1p": skewness(np.log1p(fin)) if len(fin) and fin.min() >= 0 else None,
                "status_counts": {str(k): int(c) for k, c in st.items()},
            }
    return out


def distance_selection_bias(atomic: pd.DataFrame) -> dict:
    """Why distances are not transformed: the null rows are the far cells.
    For each distance feature and AOI: share truncated, and the ok values'
    distribution against the row's complete-search radius (an ok value is
    bounded above by that radius, so the observed sample is right-censored)."""
    out = {}
    for f in DISTANCE_FEATURES:
        st_col = STATUS_COLUMN_OF[f]
        out[f] = {}
        for aoi, sub in atomic.groupby("aoi_id"):
            st = sub[st_col]
            ok = (st == OK).to_numpy()
            v = sub[f].to_numpy(dtype="float64", na_value=np.nan)
            cr = sub["distance_search_complete_radius_m"].to_numpy(dtype="float64")
            scale = 1000.0 if f.endswith("_km") else 1.0
            out[f][aoi] = {
                "rows": int(len(sub)), "status_counts": {str(k): int(c) for k, c in st.value_counts().items()},
                "ok_share": float(ok.mean()),
                "ok_p50_m": _q(v[ok] * scale, 50), "ok_max_m": float(np.max(v[ok] * scale)) if ok.any() else None,
                "complete_radius_p50_m": _q(cr, 50),
                "ok_values_bounded_by_complete_radius": bool((v[ok] * scale <= cr[ok] + 1e-6).all()) if ok.any() else None,
                "truncated_rows_complete_radius_p50_m": _q(cr[(st == "search_truncated_by_extract").to_numpy()], 50),
            }
    return out


# ---------------------------------------------------------------------------
# transforms
# ---------------------------------------------------------------------------

def run_log1p(atomic: pd.DataFrame, cfg: dict, nv: str) -> tuple[pd.DataFrame, dict, dict]:
    t = cfg["transforms"]["log1p"]
    feats = resolve_group(cfg, t["candidates"])
    rule = t["publish_rule"]
    cols, specs, elig = {}, {}, {}
    for f in feats:
        name = log1p_name(cfg, f)
        v, s = log1p_transform(atomic[f], atomic[STATUS_COLUMN_OF[f]], name)
        cols[name], cols[status_name(name)] = v, s
        raw = atomic[f].to_numpy(dtype="float64", na_value=np.nan)
        fin = raw[np.isfinite(raw)]
        sk_raw, sk_log = skewness(fin), skewness(np.log1p(fin))
        met = bool(np.isfinite(sk_raw) and sk_raw >= float(rule["minimum_raw_skewness"])
                   and (abs(sk_log) < abs(sk_raw) or not rule["require_skew_reduction"]))
        disposition = t["disposition_if_rule_met"] if met else t["disposition_if_rule_not_met"]
        elig[f] = {"output": name, "skew_raw": sk_raw, "skew_log1p": sk_log, "n_valid": int(len(fin)),
                   "zero_share_of_valid": float((fin == 0).mean()) if len(fin) else None,
                   "publish_rule_met": met, "disposition": disposition}
        specs[name] = {"source_feature": f, "transform": "log1p", "formula": t["formula"],
                       "unit": f"log(1 + <unit of {f}>)", "cohort_id": None, "normalization_version": nv,
                       "status_column": status_name(name), "disposition": disposition,
                       "status_counts": {str(k): int(c) for k, c in s.value_counts().items()}}
    return pd.DataFrame(cols, index=atomic.index), specs, elig


def _cohort_id(pattern: str, **kw) -> str:
    return pattern.format(**kw)


def fit_percentile_cohorts(atomic: pd.DataFrame, cfg: dict, nv: str) -> tuple[pd.DataFrame, dict]:
    """FIT step: ECDF tables for the pooled cohort (cell- and AOI-equal-
    weighted) and each within-AOI cohort (cell-weighted). The peer cohort
    is fitted only when every context has enough AOIs; otherwise it is
    recorded as blocked and nothing is fitted for it."""
    p = cfg["transforms"]["percentile"]
    feats = resolve_group(cfg, p["candidates"])
    g3 = str(cfg["input"]["gate3_run_id"])
    n_min = int(p["minimum_cohort_size"])
    tables, cohorts = [], {}
    pooled_id = _cohort_id(p["cohorts"]["mvp_pooled_percentile"]["cohort_id_pattern"], normalization_version=nv, gate3_run_id=g3)
    aoi_w = aoi_equal_weights(atomic["aoi_id"].astype(str))
    cohorts[pooled_id] = {"kind": "mvp_pooled_percentile", "members": sorted(set(atomic["aoi_id"].astype(str))),
                          "rows": int(len(atomic)), "weightings": ["cell", "aoi_equal"],
                          "aoi_row_share": {a: float(n / len(atomic)) for a, n in atomic["aoi_id"].value_counts().items()},
                          "disposition": p["cohorts"]["mvp_pooled_percentile"]["disposition"], "features": {}}
    for f in feats:
        for weighting, w in (("cell", None), ("aoi_equal", aoi_w)):
            tab = fit_ecdf(atomic[f], atomic[STATUS_COLUMN_OF[f]], w, pooled_id, f, weighting, n_min)
            tables.append(tab)
            cohorts[pooled_id]["features"].setdefault(f, {})[weighting] = _fit_summary(tab)
    for aoi, sub in atomic.groupby("aoi_id"):
        cid = _cohort_id(p["cohorts"]["within_aoi_percentile"]["cohort_id_pattern"], aoi_id=aoi, normalization_version=nv, gate3_run_id=g3)
        cohorts[cid] = {"kind": "within_aoi_percentile", "members": [str(aoi)], "rows": int(len(sub)),
                        "weightings": ["cell"], "disposition": p["cohorts"]["within_aoi_percentile"]["disposition"],
                        "features": {}}
        for f in feats:
            tab = fit_ecdf(sub[f], sub[STATUS_COLUMN_OF[f]], None, cid, f, "cell", n_min)
            tables.append(tab)
            cohorts[cid]["features"][f] = {"cell": _fit_summary(tab)}
    peer_cfg = p["cohorts"]["peer_percentile"]
    peer = peer_groups_are_sufficient(atomic["aoi_id"], atomic[peer_cfg["peer_group_column"]],
                                      int(peer_cfg["minimum_aois_per_peer_group"]))
    peer_record = {"kind": "peer_percentile", "peer_group_column": peer_cfg["peer_group_column"], **peer,
                   "disposition": (peer_cfg["disposition_if_requirement_met"] if peer["sufficient"]
                                   else peer_cfg["disposition_if_requirement_not_met"]),
                   "reason": None if peer["sufficient"] else
                   "one AOI per aoi_context in the Gate 3 input: a peer cohort would be a single AOI and cannot be "
                   "distinguished from the within-AOI percentile; no peer cohort fitted, no column emitted"}
    if peer["sufficient"]:  # pragma: no cover - not reachable with the current four-AOI input
        raise NotImplementedError("peer cohorts satisfied the requirement; fitting them needs a reviewed peer-group definition")
    ecdf = pd.concat(tables, ignore_index=True)[ECDF_COLUMNS]
    return ecdf, {"cohorts": cohorts, "peer_percentile": peer_record, "features": feats,
                  "minimum_cohort_size": n_min, "tie_method": p["tie_method"]}


def _fit_summary(tab: pd.DataFrame) -> dict:
    row = tab.iloc[0]
    return {"fit_status": str(row["fit_status"]), "n_obs": int(row["n_obs"]), "n_distinct": int(row["n_distinct"]),
            "weight_total": float(row["weight_total"])}


def apply_percentiles(atomic: pd.DataFrame, ecdf: pd.DataFrame, cfg: dict, fit: dict, nv: str) -> tuple[pd.DataFrame, dict, dict]:
    """APPLY step from the persisted table only: pooled (primary weighting,
    primary tie method) and within-AOI percentiles as output columns, plus
    the sensitivities (AOI-equal weighting, tie methods, pooled-vs-within,
    leave-one-AOI-out) as summary numbers."""
    p = cfg["transforms"]["percentile"]
    feats = fit["features"]
    tie = p["tie_method"]
    pooled_id = next(c for c, r in fit["cohorts"].items() if r["kind"] == "mvp_pooled_percentile")
    within_ids = {r["members"][0]: c for c, r in fit["cohorts"].items() if r["kind"] == "within_aoi_percentile"}
    aoi = atomic["aoi_id"].astype(str)
    cols: dict = {"mvp_pooled_cohort_id": pd.Series(pooled_id, index=atomic.index),
                  "within_aoi_cohort_id": aoi.map(within_ids)}
    specs, sens = {}, {}
    for f in feats:
        st = atomic[STATUS_COLUMN_OF[f]]
        v_pool, s_pool = apply_ecdf(atomic[f], st, ecdf, pooled_id, f, "cell", tie)
        v_aoiw, _ = apply_ecdf(atomic[f], st, ecdf, pooled_id, f, "aoi_equal", tie)
        v_within = pd.Series(np.nan, index=atomic.index)
        s_within = pd.Series("", index=atomic.index, dtype=object)
        for a, cid in within_ids.items():
            m = (aoi == a).to_numpy()
            vv, ss = apply_ecdf(atomic.loc[m, f], st[m], ecdf, cid, f, "cell", tie)
            v_within[m], s_within[m] = vv, ss
        n_pool, n_within = percentile_name(cfg, "mvp_pooled_percentile", f), percentile_name(cfg, "within_aoi_percentile", f)
        cols[n_pool], cols[status_name(n_pool)] = v_pool, s_pool
        cols[n_within], cols[status_name(n_within)] = v_within, s_within.astype(str)
        specs[n_pool] = {"source_feature": f, "transform": "percentile", "formula": p["formula"], "cohort_id": pooled_id,
                         "weighting": "cell", "tie_method": tie, "unit": "percentile [0, 1] within the fitted cohort",
                         "normalization_version": nv, "status_column": status_name(n_pool),
                         "disposition": p["cohorts"]["mvp_pooled_percentile"]["disposition"],
                         "status_counts": {str(k): int(c) for k, c in s_pool.value_counts().items()}}
        specs[n_within] = {"source_feature": f, "transform": "percentile", "formula": p["formula"],
                           "cohort_id_column": "within_aoi_cohort_id", "weighting": "cell", "tie_method": tie,
                           "unit": "percentile [0, 1] within the row's AOI", "normalization_version": nv,
                           "status_column": status_name(n_within),
                           "disposition": p["cohorts"]["within_aoi_percentile"]["disposition"],
                           "status_counts": {str(k): int(c) for k, c in s_within.value_counts().items()}}
        # --- sensitivities (ok rows only) ---
        ok_pool = (s_pool == OK).to_numpy()
        ok = ok_pool & (s_within == OK).to_numpy()   # rows where BOTH percentiles exist
        x = atomic[f].to_numpy(dtype="float64", na_value=np.nan)
        d_pw = (v_pool - v_within).to_numpy()[ok]
        d_cw = (v_pool - v_aoiw).to_numpy()[ok]
        per_aoi = {}
        for a in sorted(within_ids):
            m = ok & (aoi == a).to_numpy()
            per_aoi[a] = {"n_ok": int(m.sum()),
                          "pooled_p50": _q(v_pool.to_numpy()[m], 50), "within_p50": _q(v_within.to_numpy()[m], 50),
                          "mean_abs_pooled_minus_within": float(np.abs((v_pool - v_within).to_numpy()[m]).mean()) if m.any() else None,
                          "mean_pooled_minus_aoi_equal": float((v_pool - v_aoiw).to_numpy()[m].mean()) if m.any() else None,
                          "mean_abs_pooled_minus_aoi_equal": float(np.abs((v_pool - v_aoiw).to_numpy()[m]).mean()) if m.any() else None}
        # tie / zero mass under the three tie methods (pooled, cell-weighted)
        zero = ok_pool & (x == 0)
        ties = {}
        for tm in [tie] + list(p.get("tie_sensitivity_methods", [])):
            vt, _ = apply_ecdf(atomic[f], st, ecdf, pooled_id, f, "cell", tm)
            ties[tm] = {"percentile_of_zero": float(vt.to_numpy()[zero][0]) if zero.any() else None,
                        "max_abs_diff_vs_primary": float(np.abs((vt - v_pool).to_numpy()[ok_pool]).max()) if ok_pool.any() else None}
        sel = ecdf[(ecdf["cohort_id"] == pooled_id) & (ecdf["feature"] == f) & (ecdf["weighting"] == "cell") & (ecdf["fit_status"] == OK)]
        tied_weight = float(sel.loc[sel["weight_equal"] > 1, "weight_equal"].sum()) if len(sel) else 0.0
        # leave-one-AOI-out: refit pooled without one AOI, apply to the rest
        loao = {}
        for a in sorted(within_ids):
            keep = (aoi != a).to_numpy()
            tab = fit_ecdf(atomic.loc[keep, f], st[keep], None, "loao", f, "cell", fit["minimum_cohort_size"])
            if (tab["fit_status"] != OK).any():
                loao[a] = {"fit_status": str(tab["fit_status"].iloc[0])}
                continue
            vl, sl = apply_ecdf(atomic.loc[keep, f], st[keep], tab, "loao", f, "cell", tie)
            mm = (sl == OK).to_numpy()
            d = np.abs(vl.to_numpy()[mm] - v_pool.to_numpy()[keep][mm])
            loao[a] = {"held_out": a, "n_ok": int(mm.sum()), "mean_abs_change": float(d.mean()) if mm.any() else None,
                       "max_abs_change": float(d.max()) if mm.any() else None}
        sens[f] = {"n_ok_pooled": int(ok_pool.sum()), "n_ok_pooled_and_within": int(ok.sum()),
                   "zero_share_of_pooled_ok": float(zero.sum() / ok_pool.sum()) if ok_pool.any() else None,
                   "share_of_pooled_ok_rows_in_tie_groups": float(tied_weight / ok_pool.sum()) if ok_pool.any() else None,
                   "pooled_vs_within": {"mean_abs_diff": float(np.abs(d_pw).mean()) if ok.any() else None,
                                        "max_abs_diff": float(np.abs(d_pw).max()) if ok.any() else None},
                   "cell_vs_aoi_equal": {"mean_abs_diff": float(np.abs(d_cw).mean()) if ok.any() else None,
                                         "max_abs_diff": float(np.abs(d_cw).max()) if ok.any() else None},
                   "per_aoi": per_aoi, "tie_methods": ties, "leave_one_aoi_out": loao}
    return pd.DataFrame(cols, index=atomic.index), specs, sens


def run_local_ratio(atomic: pd.DataFrame, cfg: dict, nv: str) -> tuple[pd.DataFrame, dict, dict]:
    lr = cfg["transforms"]["local_ratio"]
    nb = lr["neighborhood"]
    policy = NeighborhoodPolicy(k=int(nb["k"]), exclude_centre=bool(nb["exclude_centre"]),
                                reference_statistic=nb["reference_statistic"],
                                require_all_neighbors_present=bool(nb["require_all_neighbors_present"]),
                                minimum_valid_neighbors=int(nb["minimum_valid_neighbors"]))
    nbh = neighborhoods(atomic["spatial_unit_id"], policy.k, lambda c, k: list(h3.grid_disk(c, k)))
    interior = (atomic["aoi_overlap_fraction"] >= 1 - 1e-9).to_numpy()
    complete = nbh["neighborhood_complete"].to_numpy()
    completeness = {"k": policy.k, "pooled": _completeness(interior, complete)}
    for a, m in atomic.groupby("aoi_id").indices.items():
        completeness[str(a)] = _completeness(interior[m], complete[m])
    cols: dict = {"neighborhood_k_ring": pd.Series(policy.k, index=atomic.index),
                  "neighborhood_neighbor_count": nbh["neighbor_count"].astype("int64"),
                  "neighborhood_neighbors_present": nbh["neighbors_present"].astype("int64"),
                  "neighborhood_complete": nbh["neighborhood_complete"].astype(bool)}
    specs, elig = {}, {}
    thr = float(lr["publish_rule"]["minimum_finite_share_of_eligible"])
    for f in lr["candidates"]:
        st = atomic[STATUS_COLUMN_OF[f]]
        v, s, ref = local_ratio(atomic[f], st, atomic["spatial_unit_id"], nbh, policy, f)
        v_mean, s_mean, _ = local_ratio(atomic[f], st, atomic["spatial_unit_id"], nbh, policy, f,
                                        reference_statistic=nb["sensitivity_statistic"])
        name = local_ratio_name(cfg, f)
        cols[name], cols[status_name(name)] = v, s
        s_np = s.to_numpy()
        eligible = np.isin(s_np, [OK, "neighborhood_reference_zero"])
        finite_share = float((s_np == OK).sum() / eligible.sum()) if eligible.any() else 0.0
        met = finite_share >= thr
        disposition = lr["disposition_if_rule_met"] if met else lr["disposition_if_rule_not_met"]
        per_aoi = {}
        for a, m in atomic.groupby("aoi_id").indices.items():
            sa = s_np[m]
            ea = np.isin(sa, [OK, "neighborhood_reference_zero"])
            per_aoi[str(a)] = {"status_counts": {str(k): int(c) for k, c in pd.Series(sa).value_counts().items()},
                               "finite_share_of_eligible": float((sa == OK).sum() / ea.sum()) if ea.any() else None,
                               "ratio_p50": _q(v.to_numpy()[m][sa == OK], 50), "ratio_p95": _q(v.to_numpy()[m][sa == OK], 95)}
        both = (s_np == OK) & (s_mean.to_numpy() == OK)
        rho = None
        if both.sum() > 2:
            rho = float(pd.Series(v.to_numpy()[both]).corr(pd.Series(v_mean.to_numpy()[both]), method="spearman"))
        elig[f] = {"output": name, "eligible_rows": int(eligible.sum()), "finite_rows": int((s_np == OK).sum()),
                   "reference_zero_rows": int((s_np == "neighborhood_reference_zero").sum()),
                   "finite_share_of_eligible": finite_share, "publish_rule_met": met, "disposition": disposition,
                   "per_aoi": per_aoi,
                   "sensitivity_reference_mean": {
                       "finite_rows": int((s_mean.to_numpy() == OK).sum()),
                       "finite_share_of_eligible": float((s_mean.to_numpy() == OK).sum() /
                                                         np.isin(s_mean.to_numpy(), [OK, "neighborhood_reference_zero"]).sum())
                       if np.isin(s_mean.to_numpy(), [OK, "neighborhood_reference_zero"]).any() else None,
                       "spearman_vs_median_where_both_finite": rho, "n_both_finite": int(both.sum())}}
        specs[name] = {"source_feature": f, "transform": "local_ratio", "formula": lr["formula"],
                       "neighborhood": {**nb, "k": policy.k}, "unit": "dimensionless ratio to the neighborhood median",
                       "cohort_id": None, "normalization_version": nv, "status_column": status_name(name),
                       "disposition": disposition,
                       "status_counts": {str(k): int(c) for k, c in s.value_counts().items()}}
    return pd.DataFrame(cols, index=atomic.index), specs, {"completeness": completeness, "features": elig,
                                                           "policy": policy.__dict__}


def _completeness(interior: np.ndarray, complete: np.ndarray) -> dict:
    return {"cells": int(len(interior)), "aoi_interior_cells": int(interior.sum()), "aoi_edge_cells": int((~interior).sum()),
            "ring_complete_cells": int(complete.sum()),
            "ring_complete_share_interior": float(complete[interior].mean()) if interior.any() else None,
            "ring_complete_share_edge": float(complete[~interior].mean()) if (~interior).any() else None}


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------

def run(cfg: dict, config_path: Path = GATE4_CONFIG, output_root: Optional[Path] = None) -> dict:
    run_cfg = cfg["run"]
    features_path, spatial_path = Path(run_cfg["features_config"]), Path(run_cfg["spatial_config"])
    features_cfg = load_features_config(features_path)
    validate_config(cfg, features_cfg)
    nv = str(cfg["normalization_version"])
    input_record = verify_gate3_input(cfg, features_cfg)

    ctx = RunContext(run_id=pd.Timestamp.now("UTC").strftime("%Y%m%dT%H%M%SZ"),
                     config_hash=hash_config(config_path, features_path, spatial_path),
                     code_version=code_version(), environment=environment(),
                     source_releases={"gate3_run_id": input_record["gate3_run_id"],
                                      "gate3_run_dir": input_record["gate3_run_dir"]})
    out_dir = Path(output_root or run_cfg["output_root"]) / f"{run_cfg['run_dir_prefix']}{ctx.run_id}"
    out_dir.mkdir(parents=True, exist_ok=False)
    computed_at = utc_now_iso()
    print(f"gate4 run_id={ctx.run_id}  out={out_dir}  input=gate3 {input_record['gate3_run_id']}  normalization_version={nv}")

    with ctx.stage(stage="load_input") as s:
        atomic = load_atomic(cfg)
        s.rows = len(atomic)
    lineage = atomic[cfg["lineage_columns"]].copy()
    lineage["normalization_version"] = nv
    lineage["normalization_run_id"] = ctx.run_id
    lineage["gate3_run_id"] = input_record["gate3_run_id"]
    lineage["computed_at_utc"] = computed_at

    with ctx.stage(stage="input_diagnostics") as s:
        pct_feats = resolve_group(cfg, cfg["transforms"]["percentile"]["candidates"])
        diag_feats = list(dict.fromkeys(resolve_group(cfg, cfg["transforms"]["log1p"]["candidates"]) + pct_feats
                                        + list(cfg["transforms"]["local_ratio"]["candidates"])))
        distributions = distribution_diagnostics(atomic, diag_feats)
        dist_bias = distance_selection_bias(atomic)
        s.rows = len(diag_feats)
    with ctx.stage(stage="log1p") as s:
        log_df, log_specs, log_elig = run_log1p(atomic, cfg, nv)
        s.rows = len(log_specs)
    with ctx.stage(stage="percentile_fit") as s:
        ecdf, fit = fit_percentile_cohorts(atomic, cfg, nv)
        s.rows = len(ecdf)
    with ctx.stage(stage="percentile_apply") as s:
        pct_df, pct_specs, pct_sens = apply_percentiles(atomic, ecdf, cfg, fit, nv)
        s.rows = len(pct_specs)
    with ctx.stage(stage="local_ratio") as s:
        lr_df, lr_specs, lr_diag = run_local_ratio(atomic, cfg, nv)
        s.rows = len(lr_specs)

    specs = {**log_specs, **pct_specs, **lr_specs}
    specs_pub = {c: v for c, v in specs.items() if v["disposition"] == "publishable"}
    specs_diag = {c: v for c, v in specs.items() if v["disposition"] != "publishable"}
    all_cols = pd.concat([log_df, pct_df, lr_df], axis=1)
    if not (all_cols.index == atomic.index).all():
        raise RuntimeError("row alignment lost")

    def table_for(sp: dict) -> pd.DataFrame:
        cols = []
        for c in sp:
            cols += [c, status_name(c)]
        extra = []
        if any(v["transform"] == "local_ratio" for v in sp.values()):
            extra += NEIGHBORHOOD_COLUMNS
        if any(v["transform"] == "percentile" and v.get("cohort_id") for v in sp.values()):
            extra.append("mvp_pooled_cohort_id")
        if any(v.get("cohort_id_column") == "within_aoi_cohort_id" for v in sp.values()):
            extra.append("within_aoi_cohort_id")
        return pd.concat([lineage, all_cols[extra + cols]], axis=1).reset_index(drop=True)

    publishable = table_for(specs_pub)
    diagnostic = table_for(specs_diag)

    cohort_ids = set(fit["cohorts"])
    with ctx.stage(stage="validate") as s:
        rep_pub = validate_outputs(publishable, atomic, cfg, specs_pub, cohort_ids, cfg["publish"]["publishable_table"])
        rep_diag = validate_outputs(diagnostic, atomic, cfg, specs_diag, cohort_ids, cfg["publish"]["diagnostic_table"])
        s.rows = len(publishable) + len(diagnostic)

    with ctx.stage(stage="write_outputs") as s:
        publishable.to_parquet(out_dir / cfg["publish"]["publishable_table"], index=False)
        diagnostic.to_parquet(out_dir / cfg["publish"]["diagnostic_table"], index=False)
        ecdf.to_parquet(out_dir / "cohort_statistics.parquet", index=False)
        s.rows = len(publishable)
        s.output_bytes = sum((out_dir / n).stat().st_size for n in
                             (cfg["publish"]["publishable_table"], cfg["publish"]["diagnostic_table"], "cohort_statistics.parquet"))

    sd = cfg["transforms"]["source_defined_ghs_smod_class"]
    normalization_manifest = {
        "gate": 4, "normalization_version": nv, "normalization_run_id": ctx.run_id,
        "gate4_config_version": str(cfg["version"]), "config_sha256": {str(p): sha256_of(p) for p in (config_path, features_path, spatial_path)},
        "config_hash": ctx.config_hash,
        "input": input_record, "join_contract": {"key": cfg["input"]["join_key"], "relation": "1:1 with atomic_features.parquet",
                                                  "gate3_columns_copied": cfg["lineage_columns"]},
        "aoi_context_note": "aoi_context is Gate 2 experiment metadata (one AOI per context); it is not a source-defined settlement class",
        "status_vocabulary": sorted(set(cfg["status_vocabulary"]["atomic_passthrough"]) | set(cfg["status_vocabulary"]["gate4"].values())),
        "tables": {cfg["publish"]["publishable_table"]: {"disposition": "publishable", "rows": int(len(publishable)),
                                                          "columns": {c: specs_pub[c] for c in specs_pub}},
                   cfg["publish"]["diagnostic_table"]: {"disposition": "diagnostic", "rows": int(len(diagnostic)),
                                                         "columns": {c: specs_diag[c] for c in specs_diag}}},
        "cohorts": fit["cohorts"], "peer_percentile": fit["peer_percentile"],
        "percentile_policy": {k: cfg["transforms"]["percentile"][k] for k in
                              ("tie_method", "tie_sensitivity_methods", "minimum_cohort_size", "constant_cohort_policy", "range", "weightings", "formula")},
        "local_ratio_policy": {**cfg["transforms"]["local_ratio"]["neighborhood"],
                               "denominator_zero_policy": cfg["transforms"]["local_ratio"]["denominator_zero_policy"],
                               "formula": cfg["transforms"]["local_ratio"]["formula"]},
        "log1p_policy": {"formula": cfg["transforms"]["log1p"]["formula"], "rules": cfg["transforms"]["log1p"]["rules"],
                         "publish_rule": cfg["transforms"]["log1p"]["publish_rule"]},
        "source_defined_ghs_smod_class": {"status": sd["status"], "source": sd["source"], "enabled": False,
                                          "substitute_with_custom_threshold": False},
        "candidates": {
            "log1p": log_elig,
            "mvp_pooled_percentile": {"disposition": "diagnostic", "features": fit["features"],
                                      "note": "pooled over four hand-picked AOIs; not a national percentile"},
            "within_aoi_percentile": {"disposition": "diagnostic", "features": fit["features"]},
            "peer_percentile": fit["peer_percentile"],
            "local_ratio": {f: {k: v for k, v in e.items() if k != "per_aoi"} for f, e in lr_diag["features"].items()},
            "source_defined_ghs_smod_class": {"disposition": "blocked", "status": sd["status"]},
        },
        "publishable_columns": sorted(specs_pub), "diagnostic_columns": sorted(specs_diag),
        "excluded_from_all_transforms": {"distances": cfg["feature_groups"]["distances_excluded"],
                                         "reason": "right-censored by the halo clip (search_truncated_by_extract); see validation_summary.distance_selection_bias"},
    }
    (out_dir / "normalization_manifest.json").write_text(json.dumps(_sanitize(normalization_manifest), indent=2, sort_keys=True, default=_json_default))

    bench = pd.DataFrame(ctx.rows)
    ok_rows = bench[bench["status"] == "ok"]
    validation = {
        "run_id": ctx.run_id, "gate3_run_id": input_record["gate3_run_id"], "normalization_version": nv,
        "input_verification": input_record, "rows": int(len(atomic)),
        "aois": {str(a): int(n) for a, n in atomic["aoi_id"].value_counts().items()},
        "schema": {"publishable": rep_pub, "diagnostic": rep_diag},
        "distributions": distributions, "distance_selection_bias": dist_bias,
        "log1p": log_elig, "percentile": {"fit": {k: v for k, v in fit.items() if k != "cohorts"},
                                          "cohort_table_rows": int(len(ecdf)), "sensitivity": pct_sens},
        "local_ratio": lr_diag,
        "runtime": {"wall_time_s_total": float(ok_rows["wall_time_s"].sum()),
                    "wall_time_s_by_stage": ok_rows.groupby("stage")["wall_time_s"].sum().to_dict(),
                    "peak_rss_bytes": int(ok_rows["peak_rss_bytes"].max()) if len(ok_rows) else None},
    }
    validation["passed"] = bool(rep_pub["passed"] and rep_diag["passed"])
    (out_dir / "validation_summary.json").write_text(json.dumps(_sanitize(validation), indent=2, sort_keys=True, default=_json_default))
    bench.to_parquet(out_dir / "benchmark_runs.parquet", index=False)

    manifest_path = write_run_manifest(out_dir, ctx, {
        "gate": 4, "run_kind": "contextual_normalization_mvp", "normalization_version": nv,
        "config_path": str(config_path), "configs_hashed": [str(config_path), str(features_path), str(spatial_path)],
        "config_sha256": normalization_manifest["config_sha256"],
        "gate4_config_version": str(cfg["version"]),
        "input": input_record,
        "feature_set_version": input_record["feature_set_version"],
        "spatial_unit": {"method": "h3", "h3_resolution": int(_load_yaml(spatial_path)["spatial_unit"]["h3_resolution"])},
        "artifacts": {n: {"bytes": (out_dir / n).stat().st_size, "sha256": sha256_of(out_dir / n)}
                      for n in REQUIRED_OUTPUTS if n != "run_manifest.json"},
        "rows": int(len(publishable)),
        "publishable_columns": sorted(specs_pub), "diagnostic_columns": sorted(specs_diag),
        "validation_passed": validation["passed"],
    })
    sums = write_checksums(out_dir, [out_dir / n for n in REQUIRED_OUTPUTS])
    assert verify_checksums(out_dir) == []
    print(f"\nrows={len(publishable)}  publishable={len(specs_pub)}  diagnostic={len(specs_diag)}  "
          f"validation_passed={validation['passed']}\nmanifest: {manifest_path}\nchecksums: {sums}")
    if not validation["passed"]:
        print("PROBLEMS:", rep_pub["problems"] + rep_diag["problems"])
    return {"run_id": ctx.run_id, "out_dir": str(out_dir), "validation": validation, "manifest": normalization_manifest}


def latest_full_run(root: Path = Path("data/gate4"), prefix: str = "run_") -> Optional[Path]:
    if not root.exists():
        return None
    for run in sorted(root.glob(f"{prefix}*"), reverse=True):
        m = run / "run_manifest.json"
        if not (run / "SHA256SUMS").exists() or not m.exists():
            continue
        try:
            body = json.loads(m.read_text())
        except json.JSONDecodeError:
            continue
        if body.get("gate") == 4 and body.get("run_kind") == "contextual_normalization_mvp":
            return run
    return None


def _load_yaml(path: Path) -> dict:
    import yaml
    with open(path) as f:
        return yaml.safe_load(f)


def _sanitize(v):
    """JSON-safe copy: numpy scalars to Python, non-finite floats to null."""
    if isinstance(v, dict):
        return {str(k): _sanitize(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_sanitize(x) for x in v]
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, (np.floating, float)):
        return None if not np.isfinite(v) else float(v)
    return v


def _json_default(v):
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return None if not np.isfinite(v) else float(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, float) and not np.isfinite(v):
        return None
    return str(v)


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Gate 4 contextual-normalization MVP.")
    parser.add_argument("--config", type=Path, default=GATE4_CONFIG)
    parser.add_argument("--output-root", type=Path, default=None, help="override run.output_root (e.g. a determinism check)")
    args = parser.parse_args(argv)
    run(load_gate4_config(args.config), args.config, args.output_root)


if __name__ == "__main__":
    main()
