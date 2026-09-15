"""The four comparison figures of the Gate 2 MVP run.

Matplotlib only, non-interactive backend, deterministic output. Every
figure states the spatial support it was computed on, and nationwide
numbers are labelled as projections in the title, not just the caption.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

DPI = 130
COLORS = {"h3_r8": "#7a5195", "h3_r9": "#ef5675", "h3_r10": "#ffa600"}


def _pick(metrics: pd.DataFrame, metric: str, support: str | None = None,
          dimension: str | None = None) -> pd.DataFrame:
    sel = metrics[metrics["metric"] == metric]
    if support is not None:
        sel = sel[sel["spatial_support"] == support]
    if dimension is not None:
        sel = sel[sel["dimension"] == dimension]
    return sel


def _cands(metrics: pd.DataFrame) -> list[str]:
    return sorted(metrics["candidate_id"].unique(), key=lambda c: int(c.split("_r")[1]))


def _grouped_bars(ax, table: pd.DataFrame, cands: list[str], ylabel: str, title: str,
                  log: bool = False) -> None:
    """`table` is AOI x candidate."""
    aois = list(table.index)
    x = np.arange(len(aois))
    width = 0.8 / max(1, len(cands))
    for i, c in enumerate(cands):
        ax.bar(x + (i - (len(cands) - 1) / 2) * width, table[c].to_numpy(), width,
               label=c, color=COLORS.get(c, None))
    ax.set_xticks(x); ax.set_xticklabels(aois, rotation=20, ha="right", fontsize=7)
    ax.set_ylabel(ylabel, fontsize=8); ax.set_title(title, fontsize=9)
    ax.tick_params(labelsize=7)
    if log:
        ax.set_yscale("log")


def _table(metrics: pd.DataFrame, metric: str, cands: list[str], **kw) -> pd.DataFrame:
    sel = _pick(metrics, metric, **kw)
    return sel.pivot_table(index="aoi_id", columns="candidate_id", values="value").reindex(columns=cands)


def fig_units_storage(out_dir: Path, metrics: pd.DataFrame) -> Path:
    cands = _cands(metrics)
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.6))
    _grouped_bars(axes[0], _table(metrics, "unit_count_total", cands), cands,
                  "cells intersecting the AOI", "Cell count per AOI (measured)", log=True)
    _grouped_bars(axes[1], _table(metrics, "unit_count_nationwide_projected", cands) / 1e6, cands,
                  "million cells", "Nationwide cell count (PROJECTION from each AOI)", log=True)
    _grouped_bars(axes[2], _table(metrics, "storage_nationwide_projected_bytes", cands) / 1e9, cands,
                  "GB (geometry + features Parquet)", "Nationwide storage (PROJECTION from each AOI)", log=True)
    axes[0].legend(fontsize=7)
    fig.suptitle("Unit count and storage by H3 resolution — nationwide values are projections, not measurements",
                 fontsize=9)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    path = out_dir / "fig_unit_count_storage.png"
    fig.savefig(path, dpi=DPI); plt.close(fig)
    return path


def fig_sparsity(out_dir: Path, metrics: pd.DataFrame) -> Path:
    cands = _cands(metrics)
    fig, axes = plt.subplots(2, 3, figsize=(12, 6.4))
    _grouped_bars(axes[0, 0], _table(metrics, "poi_zero_share", cands, support="unit_footprint",
                                     dimension="all_categories"), cands,
                  "share of cells", "POI mapped-zero share (cell footprint)")
    _grouped_bars(axes[0, 1], _table(metrics, "poi_zero_share", cands, support="buffer_1km",
                                     dimension="all_categories"), cands,
                  "share of cells", "POI mapped-zero share (1 km support)")
    _grouped_bars(axes[0, 2], _table(metrics, "population_zero_share", cands), cands,
                  "share of cells", "Population zero share (cell footprint)")
    _grouped_bars(axes[1, 0], _table(metrics, "population_median", cands), cands,
                  "persons", "Median population per cell (cell footprint)", log=True)
    _grouped_bars(axes[1, 1], _table(metrics, "road_zero_length_share", cands), cands,
                  "share of cells", "Zero-road-length share (cell footprint)")
    _grouped_bars(axes[1, 2], _table(metrics, "road_length_median_m", cands), cands,
                  "metres", "Median road length per cell (cell footprint)", log=True)
    for ax in axes.ravel():
        if ax.get_yscale() != "log":
            ax.set_ylim(0, 1)
    axes[0, 0].legend(fontsize=7)
    fig.suptitle("Sparsity by resolution and AOI — every zero is a mapped zero from an ingested source",
                 fontsize=9)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    path = out_dir / "fig_sparsity.png"
    fig.savefig(path, dpi=DPI); plt.close(fig)
    return path


def fig_within_cell_loss(out_dir: Path, metrics: pd.DataFrame, config: dict) -> Path:
    cands = _cands(metrics)
    anchors = [a["id"] for a in config["anchor_features"]]
    thr = float(config["acceptance"]["coarse_within_unit_range_fraction_of_between_unit_iqr"])
    fig, axes = plt.subplots(1, len(anchors), figsize=(4 * len(anchors), 3.6), squeeze=False)
    for ax, anchor in zip(axes[0], anchors):
        _grouped_bars(ax, _table(metrics, "within_unit_range_over_between_unit_iqr", cands,
                                 dimension=anchor), cands,
                      "median within-cell range / between-cell IQR", anchor)
        ax.axhline(thr, color="black", linestyle="--", linewidth=0.8, label=f"trigger threshold {thr}")
    axes[0, 0].legend(fontsize=7)
    fig.suptitle("Within-cell location loss per anchor (1 km support) — an anchor triggers above the dashed line",
                 fontsize=9)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    path = out_dir / "fig_within_cell_loss.png"
    fig.savefig(path, dpi=DPI); plt.close(fig)
    return path


def fig_runtime_lookup(out_dir: Path, bench: pd.DataFrame, lookup: pd.DataFrame) -> Path:
    ok = bench[(bench["status"] == "ok") & (bench["candidate_id"] != "")]
    cands = sorted(ok["candidate_id"].unique(), key=lambda c: int(c.split("_r")[1]))
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.6))
    runtime = ok.pivot_table(index="aoi_id", columns="candidate_id", values="wall_time_s",
                             aggfunc="sum").reindex(columns=cands)
    _grouped_bars(axes[0], runtime, cands, "seconds (all stages)", "Runtime per AOI (generation + measurement)")
    rss = ok.pivot_table(index="aoi_id", columns="candidate_id", values="peak_rss_bytes",
                         aggfunc="max").reindex(columns=cands) / 1e9
    _grouped_bars(axes[1], rss, cands, "GB", "Peak RSS per AOI")
    single = lookup[lookup["lookup_mode"] == "single"]
    p50 = single.pivot_table(index="aoi_id", columns="candidate_id", values="p50_latency_us").reindex(columns=cands)
    p95 = single.pivot_table(index="aoi_id", columns="candidate_id", values="p95_latency_us").reindex(columns=cands)
    x = np.arange(len(p50.index)); width = 0.8 / max(1, len(cands))
    for i, c in enumerate(cands):
        off = (i - (len(cands) - 1) / 2) * width
        axes[2].bar(x + off, p50[c].to_numpy(), width, color=COLORS.get(c), label=f"{c} p50")
        axes[2].scatter(x + off, p95[c].to_numpy(), color="black", s=8, zorder=3,
                        label="p95" if i == 0 else None)
    axes[2].set_xticks(x); axes[2].set_xticklabels(list(p50.index), rotation=20, ha="right", fontsize=7)
    axes[2].set_ylabel("microseconds per query", fontsize=8)
    axes[2].set_title("Single lat/lon lookup latency (bar p50, dot p95)", fontsize=9)
    axes[2].tick_params(labelsize=7)
    axes[0].legend(fontsize=7); axes[2].legend(fontsize=6)
    fig.suptitle("Engineering cost by resolution", fontsize=9)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    path = out_dir / "fig_runtime_lookup.png"
    fig.savefig(path, dpi=DPI); plt.close(fig)
    return path


def write_mvp_figures(out_dir: Path, metrics: pd.DataFrame, bench: pd.DataFrame,
                      lookup: pd.DataFrame, config: dict) -> list[Path]:
    fig_dir = out_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    return [
        fig_units_storage(fig_dir, metrics),
        fig_sparsity(fig_dir, metrics),
        fig_within_cell_loss(fig_dir, metrics, config),
        fig_runtime_lookup(fig_dir, bench, lookup),
    ]
