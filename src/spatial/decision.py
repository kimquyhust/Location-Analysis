"""Gate 2 acceptance rules, Pareto selection, and `decision_matrix.md`.

The rules are the pre-registered ones in `docs/spatial_unit_decision.md`.
They are applied here mechanically from the measured tables -- no candidate
receives an adjustment, and in particular H3 receives no convenience bonus.

When `config/gate2.yaml` records `feasibility_budget.provided: false` (the
current state, because `PROJECT_BRIEF.md` contains no hardware, runtime, or
storage budget), the feasibility gate cannot be evaluated and this module
returns an explicit NO DECISION with a Pareto frontier rather than naming a
winner the evidence does not support.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


def _pick(df: pd.DataFrame, metric: str, support: Optional[str] = None,
          dimension: Optional[str] = None) -> pd.DataFrame:
    sel = df[df["metric"] == metric]
    if support is not None:
        sel = sel[sel["spatial_support"] == support]
    if dimension is not None:
        sel = sel[sel["dimension"] == dimension]
    return sel


def _by_candidate(df: pd.DataFrame, metric: str, agg: str = "median", **kw) -> pd.Series:
    sel = _pick(df, metric, **kw)
    if not len(sel):
        return pd.Series(dtype="float64")
    return sel.groupby("candidate_id")["value"].agg(agg)


def completeness_gate(metrics: pd.DataFrame, coverage: pd.DataFrame, config: dict,
                      expected_candidates: list[str], expected_aois: list[str]) -> dict:
    """Every required candidate x AOI must have measured metrics, raster
    processing coverage must clear the configured floor, and vector ingest
    must have no technical failures."""
    have = set(map(tuple, metrics[["aoi_id", "candidate_id"]].drop_duplicates().to_numpy()))
    want = {(a, c) for a in expected_aois for c in expected_candidates}
    missing = sorted(want - have)

    floor = float(config["acceptance"]["minimum_raster_processing_coverage"])
    raster = coverage[coverage["source_role"].isin(["population", "land_cover", "built_up"])]
    below = raster[raster["processing_coverage"].notna() & (raster["processing_coverage"] < floor)]
    vector_failures = coverage[(coverage["source_role"] == "poi_roads")
                               & (coverage["ingest_status"] != "ok")]

    zonal = metrics[metrics["metric"].isin(["landcover_processing_coverage",
                                            "builtup_processing_coverage"])]
    zonal_below = zonal[zonal["value"].notna() & (zonal["value"] < floor)]

    return {
        "passed": not missing and not len(below) and not len(vector_failures) and not len(zonal_below),
        "missing_candidate_aoi_pairs": missing,
        "expected_pairs": len(want), "present_pairs": len(want) - len(missing),
        "raster_coverage_floor": floor,
        "raster_rows_below_floor": int(len(below)),
        "zonal_rows_below_floor": int(len(zonal_below)),
        "vector_ingest_failures": int(len(vector_failures)),
    }


def coarse_gate(metrics: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Reject a candidate in a context when at least `N` anchor features
    have a median within-unit sample range over the configured fraction of
    their between-unit IQR."""
    need = int(config["acceptance"]["coarse_minimum_anchor_features_triggered"])
    sel = _pick(metrics, "too_coarse_anchor_features_triggered")
    out = sel.groupby(["candidate_id", "aoi_id", "context"])["value"].max().reset_index()
    out = out.rename(columns={"value": "anchor_features_triggered"})
    out["rejected_in_context"] = out["anchor_features_triggered"] >= need
    return out


def fine_gate(metrics: pd.DataFrame, bench: pd.DataFrame, config: dict, ordering: list[str]) -> pd.DataFrame:
    """Reject a finer candidate that costs more than `k`x the next coarser
    one while improving both semantic mixing and location loss by less than
    the configured margin, or whose adjacent units are mostly
    indistinguishable."""
    acc = config["acceptance"]
    cost_mult = float(acc["fine_cost_multiplier_vs_next_coarser"])
    min_improve = float(acc["fine_minimum_error_improvement"])
    max_indist = float(acc["fine_maximum_indistinguishable_neighbor_fraction"])

    runtime = bench[bench["status"] == "ok"].groupby("candidate_id")["wall_time_s"].sum()
    storage = _by_candidate(metrics, "storage_nationwide_projected_bytes", "median")
    mixing = _by_candidate(metrics, "landcover_dominant_share_median", "median")
    loss = _by_candidate(metrics, "within_unit_range_over_between_unit_iqr", "median")
    indist = _by_candidate(metrics, "indistinguishable_neighbor_pair_share", "median")

    rows = []
    for finer, coarser in zip(ordering[:-1], ordering[1:]):
        if finer not in runtime.index or coarser not in runtime.index:
            continue
        cost_ratio = runtime.get(finer, np.nan) / runtime.get(coarser, np.nan)
        storage_ratio = storage.get(finer, np.nan) / storage.get(coarser, np.nan)
        # Higher dominant share = less mixing = better; lower loss = better.
        mix_improve = (mixing.get(finer, np.nan) - mixing.get(coarser, np.nan)) / abs(mixing.get(coarser, np.nan)) \
            if np.isfinite(mixing.get(coarser, np.nan)) and mixing.get(coarser, 0) != 0 else np.nan
        loss_improve = (loss.get(coarser, np.nan) - loss.get(finer, np.nan)) / abs(loss.get(coarser, np.nan)) \
            if np.isfinite(loss.get(coarser, np.nan)) and loss.get(coarser, 0) != 0 else np.nan
        costly = (cost_ratio > cost_mult) or (storage_ratio > cost_mult)
        marginal = (np.isfinite(mix_improve) and mix_improve < min_improve) and \
                   (np.isfinite(loss_improve) and loss_improve < min_improve)
        too_indistinct = bool(np.isfinite(indist.get(finer, np.nan)) and indist.get(finer) > max_indist)
        rows.append({
            "candidate_id": finer, "next_coarser": coarser,
            "runtime_ratio": cost_ratio, "storage_ratio": storage_ratio,
            "mixing_improvement": mix_improve, "loss_improvement": loss_improve,
            "indistinguishable_neighbor_share": indist.get(finer, np.nan),
            "rejected": bool((costly and marginal) or too_indistinct),
            "reason": "; ".join(filter(None, [
                "cost>threshold with <5% improvement in both error terms" if (costly and marginal) else "",
                f"indistinguishable neighbour share over {max_indist}" if too_indistinct else "",
            ])) or "not rejected",
        })
    return pd.DataFrame(rows)


def robustness_gate(metrics: pd.DataFrame, config: dict) -> pd.DataFrame:
    """A candidate may not reverse rank in more than one context under
    origin shift or point jitter. Rank is taken on the within-unit loss
    ratio, the metric the coarse gate turns on."""
    loss = _pick(metrics, "within_unit_range_over_between_unit_iqr")
    if not len(loss):
        return pd.DataFrame()
    per_ctx = loss.groupby(["aoi_id", "candidate_id"])["value"].median().reset_index()
    per_ctx["rank"] = per_ctx.groupby("aoi_id")["value"].rank()
    overall = per_ctx.groupby("candidate_id")["rank"].median().rank()

    jitter = _by_candidate(metrics, "jitter_assignment_change_share", "median")
    origin = _by_candidate(metrics, "origin_shift_copartition_flip_share", "median")

    rows = []
    for cand, overall_rank in overall.items():
        sub = per_ctx[per_ctx["candidate_id"] == cand]
        reversals = int((np.sign(sub["rank"] - overall_rank) != 0).sum() and
                        (abs(sub["rank"] - overall_rank) > 2).sum())
        rows.append({
            "candidate_id": cand, "median_rank": float(overall_rank),
            "contexts_with_large_rank_movement": reversals,
            "jitter_assignment_change_share": float(jitter.get(cand, np.nan)),
            "origin_shift_copartition_flip_share": float(origin.get(cand, np.nan))
            if cand in origin.index else np.nan,
            # H3 emits the row with a null value and source_status
            # "not_applicable"; presence of the row is not applicability.
            "origin_shift_applicable": bool(np.isfinite(origin.get(cand, np.nan))),
            "passed": reversals <= 1,
        })
    return pd.DataFrame(rows)


def pareto_frontier(objectives: pd.DataFrame) -> pd.DataFrame:
    """Non-dominated set over a frame whose every column is "lower is
    better". A row dominates another if it is no worse everywhere and
    strictly better somewhere. Rows with any missing objective are marked
    undetermined rather than being dropped or imputed."""
    obj = objectives.copy()
    cols = [c for c in obj.columns if c != "candidate_id"]
    vals = obj[cols].to_numpy(dtype="float64")
    complete = np.isfinite(vals).all(axis=1)

    nondominated = np.zeros(len(obj), dtype=bool)
    for i in range(len(obj)):
        if not complete[i]:
            continue
        dominated = False
        for j in range(len(obj)):
            if i == j or not complete[j]:
                continue
            if np.all(vals[j] <= vals[i]) and np.any(vals[j] < vals[i]):
                dominated = True
                break
        nondominated[i] = not dominated
    obj["objectives_complete"] = complete
    obj["pareto_nondominated"] = np.where(complete, nondominated, False)
    obj["pareto_status"] = np.where(~complete, "undetermined",
                                    np.where(nondominated, "nondominated", "dominated"))
    return obj


def build_objectives(metrics: pd.DataFrame, bench: pd.DataFrame, lookup: pd.DataFrame) -> pd.DataFrame:
    """The selection objectives, all oriented so lower is better."""
    runtime = bench[bench["status"] == "ok"].groupby("candidate_id")["wall_time_s"].sum()
    rss = bench[bench["status"] == "ok"].groupby("candidate_id")["peak_rss_bytes"].max()
    storage = _by_candidate(metrics, "storage_nationwide_projected_bytes", "median")
    loss = _by_candidate(metrics, "within_unit_range_over_between_unit_iqr", "median")
    mixing = _by_candidate(metrics, "landcover_dominant_share_median", "median")
    ring1 = _by_candidate(metrics, "ring_circle_jaccard_median", "median", support="buffer_1km")
    ring3 = _by_candidate(metrics, "ring_circle_jaccard_median", "median", support="buffer_3km")
    poi_zero = _by_candidate(metrics, "poi_zero_share", "median", support="unit_footprint",
                             dimension="all_categories")
    lookup_p95 = lookup[lookup["lookup_mode"] == "batch"].groupby("candidate_id")["p95_latency_us"].median()

    # Stage rows that belong to the AOI rather than to a candidate (source
    # loading) carry an empty candidate_id; they are not candidates.
    cands = sorted(c for c in (set(runtime.index) | set(storage.index)) if c)
    return pd.DataFrame({
        "candidate_id": cands,
        "nationwide_storage_bytes": [storage.get(c, np.nan) for c in cands],
        "total_runtime_s": [runtime.get(c, np.nan) for c in cands],
        "peak_rss_bytes": [rss.get(c, np.nan) for c in cands],
        "within_unit_loss_ratio": [loss.get(c, np.nan) for c in cands],
        "semantic_mixing_error": [1.0 - mixing.get(c, np.nan) for c in cands],
        "ring_1km_error": [1.0 - ring1.get(c, np.nan) for c in cands],
        "ring_3km_error": [1.0 - ring3.get(c, np.nan) for c in cands],
        "poi_zero_share": [poi_zero.get(c, np.nan) for c in cands],
        "lookup_p95_latency_us": [lookup_p95.get(c, np.nan) for c in cands],
    })


def write_decision_matrix(out_dir: Path, metrics: pd.DataFrame, bench: pd.DataFrame,
                          lookup: pd.DataFrame, coverage: pd.DataFrame, config: dict,
                          expected_candidates: list[str], expected_aois: list[str]) -> dict:
    completeness = completeness_gate(metrics, coverage, config, expected_candidates, expected_aois)
    coarse = coarse_gate(metrics, config)
    ordering = (metrics[["candidate_id", "family"]].drop_duplicates()
                .merge(_pick(metrics, "unit_area_km2_median").groupby("candidate_id")["value"].median()
                       .rename("area").reset_index(), on="candidate_id")
                .sort_values(["family", "area"]))
    fine_rows = []
    for family, grp in ordering.groupby("family"):
        fine_rows.append(fine_gate(metrics, bench, config, grp["candidate_id"].tolist()))
    fine = pd.concat([f for f in fine_rows if len(f)], ignore_index=True) if any(len(f) for f in fine_rows) else pd.DataFrame()
    robust = robustness_gate(metrics, config)

    all_objectives = build_objectives(metrics, bench, lookup)
    objectives = pareto_frontier(all_objectives)
    # A frontier over ten objectives is almost guaranteed to admit
    # everything -- that is a real property of the measurement, not a
    # selection. The core frontier reduces to the three axes the acceptance
    # rules actually turn on (nationwide cost, location loss, semantic
    # mixing) so the trade-off is legible. Both are reported; neither is
    # presented as a choice.
    core_objectives = pareto_frontier(all_objectives[[
        "candidate_id", "nationwide_storage_bytes", "within_unit_loss_ratio",
        "semantic_mixing_error"]])

    budget = config["feasibility_budget"]
    admin = config["candidates"]["administrative"]
    blockers = []
    if not completeness["passed"]:
        blockers.append("completeness gate not passed")
    if not budget.get("provided", False):
        blockers.append("no owner feasibility budget (PROJECT_BRIEF.md supplies none)")
    if not admin.get("enabled", False):
        blockers.append(f"administrative candidate {admin.get('status', 'blocked')} — "
                        f"the three-family comparison is incomplete")

    # A candidate survives the coarse gate only if it passes in EVERY
    # context. Passing on average would hide the contexts it fails in.
    contexts = sorted(coarse["aoi_id"].unique())
    rejected_anywhere = set(coarse[coarse["rejected_in_context"]]["candidate_id"])
    survivors = sorted(set(coarse["candidate_id"]) - rejected_anywhere)

    decision = {
        "decision": "no_decision" if blockers else "select",
        "blockers": blockers,
        "spatial_unit_method": None,
        "completeness": completeness,
        "pareto_frontier": objectives[objectives["pareto_status"] == "nondominated"]["candidate_id"].tolist(),
        "pareto_undetermined": objectives[objectives["pareto_status"] == "undetermined"]["candidate_id"].tolist(),
        "core_pareto_frontier": core_objectives[
            core_objectives["pareto_status"] == "nondominated"]["candidate_id"].tolist(),
        "coarse_gate_survivors_all_contexts": survivors,
        "coarse_gate_rejections": coarse[coarse["rejected_in_context"]][
            ["candidate_id", "aoi_id", "context", "anchor_features_triggered"]].to_dict("records"),
        "contexts_evaluated": contexts,
        "fine_gate_rejections": fine[fine["rejected"]]["candidate_id"].tolist() if len(fine) else [],
        "robustness_failures": robust[~robust["passed"]]["candidate_id"].tolist() if len(robust) else [],
    }

    _render_markdown(out_dir / "decision_matrix.md", decision, completeness, coarse, fine,
                     robust, objectives, core_objectives, config, expected_aois, expected_candidates)
    (out_dir / "decision.json").write_text(json.dumps(decision, indent=2, sort_keys=True, default=str))
    return decision


def _fmt(df: pd.DataFrame, floatfmt: str = "{:.4g}") -> str:
    if not len(df):
        return "_(no rows)_\n"
    d = df.copy()
    for c in d.columns:
        if pd.api.types.is_float_dtype(d[c]):
            d[c] = d[c].map(lambda v: "" if pd.isna(v) else floatfmt.format(v))
    header = "| " + " | ".join(d.columns) + " |"
    sep = "|" + "|".join("---" for _ in d.columns) + "|"
    body = "\n".join("| " + " | ".join(str(v) for v in row) + " |" for row in d.to_numpy())
    return f"{header}\n{sep}\n{body}\n"


def _render_markdown(path: Path, decision: dict, completeness: dict, coarse: pd.DataFrame,
                     fine: pd.DataFrame, robust: pd.DataFrame, objectives: pd.DataFrame,
                     core_objectives: pd.DataFrame, config: dict, aois: list[str],
                     candidates: list[str]) -> None:
    admin = config["candidates"]["administrative"]
    lines = [
        "# Gate 2 decision matrix",
        "",
        f"**Outcome: {decision['decision'].upper().replace('_', ' ')}.** "
        f"`config/spatial.yaml` `spatial_unit.method` stays `null`."
        if decision["decision"] == "no_decision" else
        f"**Outcome: {decision['decision']}.**",
        "",
        "## Blockers",
        "",
    ]
    lines += [f"- {b}" for b in decision["blockers"]] or ["- none"]
    lines += [
        "",
        "## Scope actually measured",
        "",
        f"- AOIs: {len(aois)} — {', '.join(aois)}",
        f"- Candidates: {len(candidates)} — {', '.join(candidates)}",
        f"- Administrative family: **{admin.get('status', 'blocked')}** "
        f"(enabled={admin.get('enabled', False)}). See `{admin.get('qualification_record')}`.",
        "",
        "## Gate 1 — completeness",
        "",
        f"- required candidate x AOI pairs: {completeness['expected_pairs']}, "
        f"present: {completeness['present_pairs']}",
        f"- raster processing-coverage floor {completeness['raster_coverage_floor']}: "
        f"{completeness['raster_rows_below_floor']} source rows and "
        f"{completeness['zonal_rows_below_floor']} zonal rows below it",
        f"- vector ingest failures: {completeness['vector_ingest_failures']}",
        f"- **passed: {completeness['passed']}**",
        "",
        "## Gate 3 — too coarse",
        "",
        "A candidate is rejected in a context when at least "
        f"{config['acceptance']['coarse_minimum_anchor_features_triggered']} anchor features have a "
        "median within-unit sample range above "
        f"{config['acceptance']['coarse_within_unit_range_fraction_of_between_unit_iqr']} of their "
        "between-unit IQR.",
        "",
        f"**Candidates rejected in no context at all:** "
        f"{', '.join(decision['coarse_gate_survivors_all_contexts']) or 'none'}. "
        f"A candidate must pass in every context, not on average -- passing on average would hide "
        f"the contexts it fails in.",
        "",
        _fmt(coarse.pivot_table(index="candidate_id", columns="aoi_id",
                                values="anchor_features_triggered").reset_index(), "{:.0f}"),
        "## Gate 4 — too fine",
        "",
        _fmt(fine),
        "## Gate 5 — robustness",
        "",
        _fmt(robust.sort_values("candidate_id") if len(robust) else robust),
        "## Gate 6 — feasibility",
        "",
        f"- budget provided by the owner: **{config['feasibility_budget'].get('provided')}**",
        "- `PROJECT_BRIEF.md` records no hardware, runtime, or storage budget, so this gate cannot "
        "be evaluated. Per `docs/spatial_unit_decision.md` acceptance rule 6, the Pareto frontier is "
        "reported instead of a single best candidate, and none is invented.",
        "",
        "## Gate 7 — Pareto selection",
        "",
        "Every objective below is oriented so **lower is better**. A candidate is non-dominated when "
        "no other candidate is at least as good on every objective and strictly better on one. "
        "H3 receives no convenience bonus: hexagonal candidates are scored by the same columns as "
        "square ones, and the origin-shift diagnostic H3 structurally cannot run is recorded as "
        "`not_applicable`, never as a pass.",
        "",
        _fmt(objectives.sort_values(["pareto_status", "candidate_id"])),
        f"**Pareto-nondominated across all ten objectives:** "
        f"{', '.join(decision['pareto_frontier']) or 'none'}",
        "",
        "Ten objectives is enough dimensions that almost nothing dominates anything. That is a real "
        "property of this measurement, not a selection. The reduced frontier below uses only the "
        "three axes the acceptance rules actually turn on — projected nationwide storage, within-unit "
        "location loss, and semantic-mixing error — so the trade-off is legible. It is a different "
        "view of the same numbers, not a different result.",
        "",
        _fmt(core_objectives.sort_values(["pareto_status", "candidate_id"])),
        f"**Core-objective Pareto-nondominated:** "
        f"{', '.join(decision['core_pareto_frontier']) or 'none'}",
        "",
        f"**Undetermined (an objective could not be measured):** "
        f"{', '.join(decision['pareto_undetermined']) or 'none'}",
        "",
        "## What this does and does not settle",
        "",
        "The frontier above is a measured trade-off surface across the square and H3 families only. "
        "It is not a selection. With the administrative family blocked and no feasibility budget "
        "recorded, naming one unit would be a preference presented as a result.",
        "",
    ]
    path.write_text("\n".join(lines))
