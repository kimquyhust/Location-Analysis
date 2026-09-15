"""Gate 2 faceted maps and diagnostic plots.

Matplotlib only, non-interactive backend, deterministic output. Every
figure states the spatial support it was computed on, because a sparsity
number on the unit footprint and the same number on a 1 km buffer are
different measurements.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

DPI = 130


def _series(metrics: pd.DataFrame, metric: str, support: str | None = None,
            dimension: str | None = None) -> pd.DataFrame:
    sel = metrics[metrics["metric"] == metric]
    if support is not None:
        sel = sel[sel["spatial_support"] == support]
    if dimension is not None:
        sel = sel[sel["dimension"] == dimension]
    return sel


def _order(metrics: pd.DataFrame) -> list[str]:
    area = _series(metrics, "unit_area_km2_median").groupby(["candidate_id", "family"])["value"].median()
    return [c for c, _ in sorted(area.index, key=lambda k: (k[1], area.loc[k]))]


def _facet_map(ax, inventory: pd.DataFrame, column: str, title: str, cmap: str = "viridis") -> None:
    sub = inventory.dropna(subset=[column])
    if not len(sub):
        ax.set_axis_off()
        ax.set_title(f"{title}\n(no data)", fontsize=7)
        return
    sc = ax.scatter(sub["rep_lon"], sub["rep_lat"], c=sub[column], s=1.5, cmap=cmap,
                    linewidths=0, rasterized=True)
    ax.set_title(title, fontsize=7)
    ax.set_xticks([]); ax.set_yticks([])
    ax.set_aspect("equal")
    plt.colorbar(sc, ax=ax, fraction=0.046, pad=0.02).ax.tick_params(labelsize=5)


def _unit_boundary_facets(out_dir: Path, inventory: pd.DataFrame, aoi_id: str) -> Path:
    sub = inventory[inventory["aoi_id"] == aoi_id]
    cands = sorted(sub["candidate_id"].unique())
    cols = 4
    rows = int(np.ceil(len(cands) / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(3.0 * cols, 3.0 * rows), squeeze=False)
    for ax, cand in zip(axes.ravel(), cands):
        s = sub[sub["candidate_id"] == cand]
        ax.scatter(s["rep_lon"], s["rep_lat"], s=0.6, c="#1f3a5f", linewidths=0, rasterized=True)
        ax.set_title(f"{cand}\n{len(s):,} units", fontsize=7)
        ax.set_xticks([]); ax.set_yticks([]); ax.set_aspect("equal")
    for ax in axes.ravel()[len(cands):]:
        ax.set_axis_off()
    fig.suptitle(f"Unit centres at identical extent — {aoi_id} (support: unit footprint)", fontsize=10)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    path = out_dir / f"map_unit_boundaries_{aoi_id}.png"
    fig.savefig(path, dpi=DPI); plt.close(fig)
    return path


def _sparsity_facets(out_dir: Path, inventory: pd.DataFrame, aoi_id: str, column: str,
                     label: str, support: str) -> Path:
    sub = inventory[inventory["aoi_id"] == aoi_id]
    cands = sorted(sub["candidate_id"].unique())
    cols = 4
    rows = int(np.ceil(len(cands) / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(3.0 * cols, 3.0 * rows), squeeze=False)
    for ax, cand in zip(axes.ravel(), cands):
        _facet_map(ax, sub[sub["candidate_id"] == cand], column, cand)
    for ax in axes.ravel()[len(cands):]:
        ax.set_axis_off()
    fig.suptitle(f"{label} — {aoi_id} (support: {support})", fontsize=10)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    path = out_dir / f"map_{column}_{aoi_id}.png"
    fig.savefig(path, dpi=DPI); plt.close(fig)
    return path


def _scatter_vs_area(out_dir: Path, metrics: pd.DataFrame, metric: str, label: str,
                     support: str | None, filename: str, dimension: str | None = None) -> Path | None:
    area = _series(metrics, "unit_area_km2_median").groupby(["candidate_id", "family", "aoi_id"])["value"].median()
    vals = _series(metrics, metric, support, dimension).groupby(["candidate_id", "family", "aoi_id"])["value"].median()
    df = pd.concat([area.rename("area_km2"), vals.rename("value")], axis=1).dropna().reset_index()
    if not len(df):
        return None
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for family, grp in df.groupby("family"):
        ax.scatter(grp["area_km2"], grp["value"], s=22, label=family, alpha=0.75)
    ax.set_xscale("log")
    ax.set_xlabel("median actual unit area (km², log scale)")
    ax.set_ylabel(label)
    ax.set_title(f"{label} vs unit area (support: {support or 'unit_footprint'})", fontsize=10)
    ax.legend(fontsize=8, title="family")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    path = out_dir / filename
    fig.savefig(path, dpi=DPI); plt.close(fig)
    return path


def _count_vs_cost(out_dir: Path, metrics: pd.DataFrame) -> Path | None:
    counts = _series(metrics, "unit_count_total").groupby(["candidate_id", "family"])["value"].sum()
    storage = _series(metrics, "storage_nationwide_projected_bytes").groupby(["candidate_id", "family"])["value"].median()
    df = pd.concat([counts.rename("units"), storage.rename("bytes")], axis=1).dropna().reset_index()
    if not len(df):
        return None
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for family, grp in df.groupby("family"):
        ax.scatter(grp["units"], grp["bytes"] / 1e9, s=26, label=family)
        for _, r in grp.iterrows():
            ax.annotate(r["candidate_id"], (r["units"], r["bytes"] / 1e9), fontsize=6,
                        xytext=(3, 3), textcoords="offset points")
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("units generated across all AOIs (log)")
    ax.set_ylabel("projected nationwide storage (GB, log)")
    ax.set_title("Unit count vs projected nationwide storage", fontsize=10)
    ax.legend(fontsize=8); ax.grid(alpha=0.25, which="both")
    fig.tight_layout()
    path = out_dir / "plot_unit_count_vs_storage.png"
    fig.savefig(path, dpi=DPI); plt.close(fig)
    return path


def _origin_sensitivity(out_dir: Path, metrics: pd.DataFrame) -> Path | None:
    origin = _series(metrics, "origin_shift_copartition_flip_share")
    jitter = _series(metrics, "jitter_assignment_change_share")
    if not len(jitter):
        return None
    fig, ax = plt.subplots(figsize=(8, 4.5))
    order = _order(metrics)
    x = np.arange(len(order))
    jm = jitter.groupby("candidate_id")["value"].median().reindex(order)
    om = origin.groupby("candidate_id")["value"].median().reindex(order)
    ax.bar(x - 0.2, jm.to_numpy(), width=0.4, label="point jitter (10% of cell width)")
    ax.bar(x + 0.2, np.nan_to_num(om.to_numpy()), width=0.4,
           label="half-cell origin shift (co-partition flip)")
    for i, cand in enumerate(order):
        if pd.isna(om.get(cand)):
            ax.annotate("n/a", (i + 0.2, 0.01), ha="center", fontsize=6, rotation=90)
    ax.set_xticks(x); ax.set_xticklabels(order, rotation=45, ha="right", fontsize=7)
    ax.set_ylabel("share of test points whose unit assignment changed")
    ax.set_title("Boundary sensitivity — 'n/a' marks H3, which has no grid origin to shift\n"
                 "(not applicable is not a passing score)", fontsize=9)
    ax.legend(fontsize=8); ax.grid(alpha=0.25, axis="y")
    fig.tight_layout()
    path = out_dir / "plot_boundary_origin_sensitivity.png"
    fig.savefig(path, dpi=DPI); plt.close(fig)
    return path


def _maup_plot(out_dir: Path, metrics: pd.DataFrame) -> Path | None:
    sel = _series(metrics, "maup_spearman")
    if not len(sel):
        return None
    sel = sel.copy()
    sel["pair"] = sel["dimension"].str.split("|").str[-1]
    piv = sel.groupby(["pair", "family"])["value"].median().reset_index()
    fig, ax = plt.subplots(figsize=(8, 4.5))
    for family, grp in piv.groupby("family"):
        ax.barh(grp["pair"], grp["value"], label=family, alpha=0.85)
    ax.set_xlabel("Spearman rank correlation between adjacent resolutions")
    ax.set_title("MAUP stability between adjacent resolutions of the same family", fontsize=10)
    ax.legend(fontsize=8); ax.grid(alpha=0.25, axis="x")
    ax.tick_params(labelsize=7)
    fig.tight_layout()
    path = out_dir / "plot_maup_adjacent_resolution_stability.png"
    fig.savefig(path, dpi=DPI); plt.close(fig)
    return path


def write_plots(out_dir: Path, metrics: pd.DataFrame, inventory: pd.DataFrame, config: dict) -> list[Path]:
    plot_dir = out_dir / "figures"
    plot_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    for aoi_id in sorted(inventory["aoi_id"].unique()):
        paths.append(_unit_boundary_facets(plot_dir, inventory, aoi_id))
        paths.append(_sparsity_facets(plot_dir, inventory, aoi_id, "poi_count",
                                      "Mapped OSM POI count per unit", "unit_footprint"))
        paths.append(_sparsity_facets(plot_dir, inventory, aoi_id, "population",
                                      "WorldPop 2025 population per unit", "unit_footprint"))
        paths.append(_sparsity_facets(plot_dir, inventory, aoi_id, "land_fraction",
                                      "Land fraction (ESA WorldCover)", "unit_footprint"))

    for metric, label, support, fname, dim in [
        ("poi_zero_share", "share of units with zero mapped POIs", "unit_footprint",
         "plot_poi_sparsity_vs_area.png", "all_categories"),
        ("population_zero_share", "share of units with zero population", "unit_footprint",
         "plot_population_sparsity_vs_area.png", None),
        ("road_zero_length_share", "share of units with zero road length", "unit_footprint",
         "plot_road_sparsity_vs_area.png", None),
        ("landcover_entropy_median", "median land-cover entropy (bits)", "unit_footprint",
         "plot_semantic_mixing_vs_area.png", None),
        ("landcover_dominant_share_median", "median dominant land-cover share", "unit_footprint",
         "plot_dominant_landcover_vs_area.png", None),
        ("within_unit_range_over_between_unit_iqr",
         "median within-unit range / between-unit IQR", "buffer_1km",
         "plot_within_unit_loss_vs_area.png", None),
        ("ring_circle_jaccard_median", "best ring-vs-1 km-circle Jaccard", "buffer_1km",
         "plot_neighborhood_error_1km_vs_area.png", None),
        ("ring_circle_jaccard_median", "best ring-vs-3 km-circle Jaccard", "buffer_3km",
         "plot_neighborhood_error_3km_vs_area.png", None),
        ("builtup_fraction_variance_median", "median within-unit built-up variance", "unit_footprint",
         "plot_builtup_variance_vs_area.png", None),
    ]:
        p = _scatter_vs_area(plot_dir, metrics, metric, label, support, fname, dim)
        if p:
            paths.append(p)

    for fn in (_count_vs_cost, _origin_sensitivity, _maup_plot):
        p = fn(plot_dir, metrics)
        if p:
            paths.append(p)
    return paths
