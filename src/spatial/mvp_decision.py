"""Gate 2 MVP resolution rule: which provisional H3 resolution the MVP uses.

Owner-approved scope reduction (`docs/gate2_mvp_decision.md`). The rule is
the pre-registered too-coarse gate of `docs/spatial_unit_decision.md`
(median within-cell sample-point range > 25% of the between-cell IQR,
rejected when at least two anchors trigger in any context), simplified to
three anchors, followed by the owner's stated order of preference:

    1. if the default resolution (r9) passes in every MVP AOI, select it;
    2. else if the finer fallback (r10) passes, select it;
    3. the coarser alternative (r8) only if it passes everywhere AND is
       cheaper than the default on projected nationwide unit count and
       storage AND shows no greater within-cell location loss than the
       default;
    4. otherwise NO DECISION -- Gate 3 does not start.

Everything here is a pure function of the measured tables plus the config,
so the rule is testable on synthetic inputs and is applied mechanically:
no candidate receives an adjustment, and no threshold beyond the
pre-registered 25% / two-anchor rule is introduced. "Materially greater
location loss" in step 3 is evaluated as "greater" -- the comparison
values are recorded so a reviewer can see exactly how close it was.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


def _by_resolution(cands) -> list[str]:
    """`h3_r8, h3_r9, h3_r10` -- numeric order, not lexicographic."""
    return sorted(cands, key=lambda c: (int(c.split("_r")[1]) if "_r" in c else 0, c))


def _pick(df: pd.DataFrame, metric: str, support: Optional[str] = None,
          dimension: Optional[str] = None) -> pd.DataFrame:
    sel = df[df["metric"] == metric]
    if support is not None:
        sel = sel[sel["spatial_support"] == support]
    if dimension is not None:
        sel = sel[sel["dimension"] == dimension]
    return sel


def coarse_table(metrics: pd.DataFrame, config: dict) -> pd.DataFrame:
    """One row per candidate x AOI x anchor: the measured loss ratio and
    whether it triggers, plus the per-context rejection verdict."""
    threshold = float(config["acceptance"]["coarse_within_unit_range_fraction_of_between_unit_iqr"])
    need = int(config["acceptance"]["coarse_minimum_anchor_features_triggered"])
    anchors = [a["id"] for a in config["anchor_features"]]

    sel = _pick(metrics, "within_unit_range_over_between_unit_iqr")
    sel = sel[sel["dimension"].isin(anchors)]
    rows = []
    for (cand, aoi), grp in sel.groupby(["candidate_id", "aoi_id"]):
        by_anchor = grp.set_index("dimension")["value"]
        triggered = {a: bool(np.isfinite(by_anchor.get(a, np.nan)) and by_anchor.get(a) > threshold)
                     for a in anchors}
        evaluable = {a: bool(np.isfinite(by_anchor.get(a, np.nan))) for a in anchors}
        rows.append({
            "candidate_id": cand, "aoi_id": aoi,
            **{f"ratio_{a}": float(by_anchor.get(a, np.nan)) for a in anchors},
            **{f"triggered_{a}": triggered[a] for a in anchors},
            "anchors_evaluable": int(sum(evaluable.values())),
            "anchors_triggered": int(sum(triggered.values())),
            "rejected_in_context": int(sum(triggered.values())) >= need,
        })
    return pd.DataFrame(rows)


def candidate_summary(metrics: pd.DataFrame, bench: pd.DataFrame, lookup: pd.DataFrame,
                      config: dict) -> pd.DataFrame:
    """Per-candidate medians across AOIs of the quantities the rule and
    the decision matrix report."""
    anchors = [a["id"] for a in config["anchor_features"]]

    def med(metric, **kw):
        s = _pick(metrics, metric, **kw)
        return s.groupby("candidate_id")["value"].median() if len(s) else pd.Series(dtype="float64")

    def tot(metric, **kw):
        s = _pick(metrics, metric, **kw)
        return s.groupby("candidate_id")["value"].sum() if len(s) else pd.Series(dtype="float64")

    loss = _pick(metrics, "within_unit_range_over_between_unit_iqr")
    loss = loss[loss["dimension"].isin(anchors)].groupby("candidate_id")["value"].median()
    ok = bench[bench["status"] == "ok"] if len(bench) else bench
    runtime = ok.groupby("candidate_id")["wall_time_s"].sum() if len(ok) else pd.Series(dtype="float64")
    rss = ok.groupby("candidate_id")["peak_rss_bytes"].max() if len(ok) else pd.Series(dtype="float64")
    single = lookup[lookup["lookup_mode"] == "single"] if len(lookup) else lookup
    lk50 = single.groupby("candidate_id")["p50_latency_us"].median() if len(single) else pd.Series(dtype="float64")
    lk95 = single.groupby("candidate_id")["p95_latency_us"].median() if len(single) else pd.Series(dtype="float64")
    lk_fail = (lookup.groupby("candidate_id")[["correctness_failures", "errors"]].sum().sum(axis=1)
               if len(lookup) else pd.Series(dtype="float64"))

    cands = _by_resolution(set(metrics["candidate_id"]))
    out = pd.DataFrame({
        "candidate_id": cands,
        "units_total_4_aois": [tot("unit_count_total").get(c, np.nan) for c in cands],
        "cell_area_km2_median": [med("unit_area_km2_median").get(c, np.nan) for c in cands],
        "cell_area_km2_p05": [med("unit_area_km2_p05").get(c, np.nan) for c in cands],
        "cell_area_km2_p95": [med("unit_area_km2_p95").get(c, np.nan) for c in cands],
        "nationwide_units_projected": [med("unit_count_nationwide_projected").get(c, np.nan) for c in cands],
        "nationwide_storage_bytes_projected": [med("storage_nationwide_projected_bytes").get(c, np.nan) for c in cands],
        "poi_zero_share_footprint": [med("poi_zero_share", support="unit_footprint",
                                         dimension="all_categories").get(c, np.nan) for c in cands],
        "poi_zero_share_1km": [med("poi_zero_share", support="buffer_1km",
                                   dimension="all_categories").get(c, np.nan) for c in cands],
        "population_zero_share": [med("population_zero_share").get(c, np.nan) for c in cands],
        "population_median": [med("population_median").get(c, np.nan) for c in cands],
        "road_zero_length_share": [med("road_zero_length_share").get(c, np.nan) for c in cands],
        "road_length_median_m": [med("road_length_median_m").get(c, np.nan) for c in cands],
        "within_cell_loss_ratio_median": [loss.get(c, np.nan) for c in cands],
        "runtime_s_total": [runtime.get(c, np.nan) for c in cands],
        "peak_rss_bytes": [rss.get(c, np.nan) for c in cands],
        "lookup_single_p50_us": [lk50.get(c, np.nan) for c in cands],
        "lookup_single_p95_us": [lk95.get(c, np.nan) for c in cands],
        "lookup_failures": [lk_fail.get(c, np.nan) for c in cands],
    })
    return out


def select_resolution(coarse: pd.DataFrame, summary: pd.DataFrame, config: dict,
                      expected_aois: list[str]) -> dict:
    """Apply the owner's selection order to the per-context verdicts.

    A candidate "passes" only if it is rejected in NO expected AOI and has a
    verdict for EVERY expected AOI -- a missing context is not a pass.
    """
    sel = config["selection"]
    default = f"h3_r{int(sel['default'])}"
    finer = f"h3_r{int(sel['finer_fallback'])}"
    coarser = f"h3_r{int(sel['coarser_alternative'])}"
    expected = set(expected_aois)

    def verdict(cand: str) -> dict:
        sub = coarse[coarse["candidate_id"] == cand] if len(coarse) else coarse
        covered = set(sub["aoi_id"]) if len(sub) else set()
        rejected_in = sorted(sub[sub["rejected_in_context"]]["aoi_id"]) if len(sub) else []
        missing = sorted(expected - covered)
        return {"candidate_id": cand, "contexts_rejected": rejected_in,
                "contexts_missing": missing,
                "passes_all_contexts": not rejected_in and not missing}

    verdicts = {c: verdict(c) for c in (coarser, default, finer)}
    s = summary.set_index("candidate_id") if len(summary) else pd.DataFrame()

    def val(cand, col):
        return float(s.loc[cand, col]) if (len(s) and cand in s.index and col in s.columns) else np.nan

    # Step 3 inputs, always recorded so the r8 comparison is visible even
    # when an earlier step fires.
    r8_vs_default = {
        "units_ratio_default_over_coarser": val(default, "nationwide_units_projected") / val(coarser, "nationwide_units_projected"),
        "storage_ratio_default_over_coarser": val(default, "nationwide_storage_bytes_projected") / val(coarser, "nationwide_storage_bytes_projected"),
        "loss_coarser": val(coarser, "within_cell_loss_ratio_median"),
        "loss_default": val(default, "within_cell_loss_ratio_median"),
    }
    cheaper = bool(np.isfinite(r8_vs_default["units_ratio_default_over_coarser"])
                   and r8_vs_default["units_ratio_default_over_coarser"] > 1.0
                   and np.isfinite(r8_vs_default["storage_ratio_default_over_coarser"])
                   and r8_vs_default["storage_ratio_default_over_coarser"] > 1.0)
    no_greater_loss = bool(np.isfinite(r8_vs_default["loss_coarser"]) and np.isfinite(r8_vs_default["loss_default"])
                           and r8_vs_default["loss_coarser"] <= r8_vs_default["loss_default"])
    r8_vs_default.update({"coarser_is_cheaper": cheaper, "coarser_has_no_greater_loss": no_greater_loss})

    selected, rule = None, None
    if verdicts[default]["passes_all_contexts"]:
        selected, rule = default, 1
    elif verdicts[finer]["passes_all_contexts"]:
        selected, rule = finer, 2
    elif verdicts[coarser]["passes_all_contexts"] and cheaper and no_greater_loss:
        selected, rule = coarser, 3

    return {
        "decision": "select" if selected else "no_decision",
        "selected_candidate": selected,
        "selected_h3_resolution": int(selected.split("_r")[1]) if selected else None,
        "selection_rule_fired": rule,
        "decision_status": sel.get("decision_status", "provisional_mvp") if selected else None,
        "selection_order": [default, finer, coarser],
        "verdicts": verdicts,
        "coarser_alternative_comparison": r8_vs_default,
        "contexts_expected": sorted(expected),
        "rule": {
            "anchors": [a["id"] for a in config["anchor_features"]],
            "within_range_over_between_iqr_threshold":
                float(config["acceptance"]["coarse_within_unit_range_fraction_of_between_unit_iqr"]),
            "min_anchors_triggered_to_reject":
                int(config["acceptance"]["coarse_minimum_anchor_features_triggered"]),
        },
    }


def write_mvp_decision(out_dir: Path, metrics: pd.DataFrame, bench: pd.DataFrame,
                       lookup: pd.DataFrame, config: dict, expected_candidates: list[str],
                       expected_aois: list[str], run_id: str) -> dict:
    coarse = coarse_table(metrics, config)
    summary = candidate_summary(metrics, bench, lookup, config)

    have = set(map(tuple, metrics[["aoi_id", "candidate_id"]].drop_duplicates().to_numpy()))
    want = {(a, c) for a in expected_aois for c in expected_candidates}
    missing_pairs = sorted(want - have)
    lookup_failures = int(lookup[["correctness_failures", "errors"]].to_numpy().sum()) if len(lookup) else 0

    result = select_resolution(coarse, summary, config, expected_aois)
    if missing_pairs or lookup_failures:
        # An incomplete or incorrect run cannot select anything.
        result.update({"decision": "no_decision", "selected_candidate": None,
                       "selected_h3_resolution": None, "selection_rule_fired": None,
                       "decision_status": None})
    result.update({
        "run_id": run_id,
        "candidates_expected": _by_resolution(expected_candidates),
        "candidate_aoi_pairs_expected": len(want), "candidate_aoi_pairs_present": len(want - set(missing_pairs)),
        "missing_candidate_aoi_pairs": missing_pairs,
        "lookup_failures_total": lookup_failures,
        "coarse_gate": coarse.to_dict("records"),
        "candidate_summary": summary.to_dict("records"),
        "scope": {
            "family": config["candidates"]["family"],
            "h3_resolutions": list(config["candidates"]["h3_resolutions"]),
            "aois": list(expected_aois),
            "deferred": ["square_grid_family", "administrative_family", "h3_r7", "origin_shift_replicates",
                         "alternate_population_source_sensitivity", "alternate_builtup_source_sensitivity",
                         "semantic_mixing", "neighborhood_representation", "maup_stability",
                         "robustness_gate", "pareto_selection", "nationwide_validation"],
        },
    })
    _render_markdown(out_dir / "decision_matrix.md", result, coarse, summary, config)
    (out_dir / "decision.json").write_text(json.dumps(result, indent=2, sort_keys=True, default=_json_default))
    return result


def _json_default(v):
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return None if not np.isfinite(v) else float(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    return str(v)


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


def _render_markdown(path: Path, result: dict, coarse: pd.DataFrame, summary: pd.DataFrame,
                     config: dict) -> None:
    anchors = result["rule"]["anchors"]
    thr = result["rule"]["within_range_over_between_iqr_threshold"]
    need = result["rule"]["min_anchors_triggered_to_reject"]
    if result["decision"] == "select":
        outcome = (f"**Outcome: SELECT `{result['selected_candidate']}` "
                   f"(H3 resolution {result['selected_h3_resolution']}) — status "
                   f"`{result['decision_status']}`, selection rule {result['selection_rule_fired']} fired.**")
    else:
        outcome = "**Outcome: NO DECISION.** No resolution passed the rule; Gate 3 does not start."

    pivot = (coarse.pivot_table(index="candidate_id", columns="aoi_id", values="anchors_triggered")
             .reindex(_by_resolution(coarse["candidate_id"].unique())).reset_index() if len(coarse) else coarse)
    coarse = coarse.assign(_r=coarse["candidate_id"].map(lambda c: int(c.split("_r")[1]))) \
        .sort_values(["aoi_id", "_r"]).drop(columns="_r") if len(coarse) else coarse
    ratio_cols = ["candidate_id", "aoi_id"] + [f"ratio_{a}" for a in anchors] + ["anchors_triggered", "rejected_in_context"]

    lines = [
        "# Gate 2 MVP decision matrix — provisional H3 resolution",
        "",
        f"_Run `{result['run_id']}`. Owner-approved scope reduction: H3 is the provisional MVP family; "
        "this run decides the resolution only. It is NOT evidence that H3 is universally optimal — "
        "see `docs/gate2_mvp_decision.md`._",
        "",
        outcome,
        "",
        "## Scope",
        "",
        f"- family: `{result['scope']['family']}`; candidates: {', '.join(result['candidates_expected'])}",
        f"- AOIs: {', '.join(result['contexts_expected'])}",
        f"- candidate x AOI pairs: {result['candidate_aoi_pairs_present']} / {result['candidate_aoi_pairs_expected']}"
        + (f" — **missing: {result['missing_candidate_aoi_pairs']}**" if result["missing_candidate_aoi_pairs"] else ""),
        f"- lookup correctness/determinism failures: {result['lookup_failures_total']}",
        f"- deferred (not measured here): {', '.join(result['scope']['deferred'])}",
        "",
        "## Rule",
        "",
        f"For every resolution x AOI and each anchor ({', '.join(anchors)}; 1 km support), the median "
        f"within-cell sample-point range is divided by the between-cell IQR. An anchor triggers when the "
        f"ratio exceeds {thr}. A resolution is **rejected in a context** when at least {need} anchors trigger; "
        "it **passes** only if rejected in no MVP AOI.",
        "",
        "Selection order: " + " → ".join(f"`{c}`" for c in result["selection_order"]) +
        " (default, finer fallback, coarser alternative); the coarser alternative additionally needs lower "
        "projected nationwide unit count and storage than the default and no greater within-cell loss.",
        "",
        "## Anchors triggered per resolution x AOI",
        "",
        _fmt(pivot, "{:.0f}"),
        "## Loss ratios (within-cell median range / between-cell IQR)",
        "",
        _fmt(coarse[ratio_cols] if len(coarse) else coarse),
        "## Verdicts",
        "",
    ]
    for cand in result["selection_order"]:
        v = result["verdicts"][cand]
        lines.append(f"- `{cand}`: **{'PASS' if v['passes_all_contexts'] else 'FAIL'}** — "
                     f"rejected in {v['contexts_rejected'] or 'no context'}"
                     + (f"; missing contexts {v['contexts_missing']}" if v["contexts_missing"] else ""))
    cmp_ = result["coarser_alternative_comparison"]
    lines += [
        "",
        f"Coarser-alternative check (rule 3, recorded regardless of which rule fired): default/coarser "
        f"projected unit ratio {cmp_['units_ratio_default_over_coarser']:.3g}, storage ratio "
        f"{cmp_['storage_ratio_default_over_coarser']:.3g}; median loss ratio coarser "
        f"{cmp_['loss_coarser']:.3g} vs default {cmp_['loss_default']:.3g}; cheaper={cmp_['coarser_is_cheaper']}, "
        f"no_greater_loss={cmp_['coarser_has_no_greater_loss']}.",
        "",
        "## Candidate summary (medians across the four AOIs; nationwide figures are PROJECTIONS)",
        "",
        _fmt(summary),
        "## What this does and does not settle",
        "",
        "- It settles which H3 resolution the MVP atomic-feature layer is keyed to, provisionally.",
        "- It does not compare H3 with square grids or administrative units (deferred), does not validate "
        "nationwide (Gate 6), and does not test robustness to alternate sources or perturbations.",
        "- Nationwide unit counts and storage are extrapolations from four AOIs (~ 600 km2) to 331,212 km2.",
        "",
    ]
    path.write_text("\n".join(lines))
