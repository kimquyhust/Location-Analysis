"""Gate 2 MVP resolution decision: candidate set, deterministic H3
generation and actual area, lookup determinism, the selection rule on
synthetic inputs, and -- when an MVP run directory exists -- that the
recorded selection follows the rule, the checksums verify, and no deferred
family crept into the run.

The rule tests run on hand-built metric tables so they stay meaningful
without any run on disk; the run-dependent ones skip cleanly otherwise.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from spatial.aoi import build_aoi
from spatial.candidates import H3Grid
from spatial.mvp_decision import candidate_summary, coarse_table, select_resolution
from spatial.run_gate2 import _load_acquisition_manifest
from spatial.run_gate2_mvp import (REQUIRED_OUTPUTS, build_mvp_candidates, load_config, mvp_aois,
                                   verify_checksums, write_checksums)

GATE2_ROOT = Path("data/gate2")
HANOI = {"id": "t_hanoi", "context": "dense_urban", "lat": 21.028, "lon": 105.852,
         "width_km": 2, "height_km": 2}


@pytest.fixture(scope="module")
def config():
    return load_config()


@pytest.fixture(scope="module")
def aoi():
    return build_aoi(HANOI)


def _latest_mvp_run():
    if not GATE2_ROOT.exists():
        return None
    runs = sorted(r for r in GATE2_ROOT.glob("mvp_run_*") if (r / "SHA256SUMS").exists())
    return runs[-1] if runs else None


requires_mvp_run = pytest.mark.skipif(_latest_mvp_run() is None, reason="no Gate 2 MVP run present")


def test_partial_reacquisition_uses_each_aois_authoritative_manifest(tmp_path):
    """A corrected clip reuses its stable source id. Its AOI-specific new
    manifest must override the stale entry retained by the old manifest."""
    old = tmp_path / "old.json"
    new = tmp_path / "new.json"
    old.write_text(json.dumps({"sources": [
        {"source_id": "gate2_hanoi_core_worldcover", "sha256": "old-one-tile"},
        {"source_id": "gate2_hoi_an_worldcover", "sha256": "unchanged"},
    ]}))
    new.write_text(json.dumps({"sources": [
        {"source_id": "gate2_hanoi_core_worldcover", "sha256": "new-two-tile"},
    ]}))
    index = {
        "manifest_path": str(new),
        "aois": {
            "hanoi_core": {
                "manifest_path": str(new),
                "land_cover": {"source_id": "gate2_hanoi_core_worldcover"},
            },
            "hoi_an": {
                "manifest_path": str(old),
                "land_cover": {"source_id": "gate2_hoi_an_worldcover"},
            },
        },
    }

    entries = _load_acquisition_manifest(index)
    assert entries["gate2_hanoi_core_worldcover"]["sha256"] == "new-two-tile"
    assert entries["gate2_hoi_an_worldcover"]["sha256"] == "unchanged"


def test_partial_reacquisition_rejects_a_source_missing_from_its_manifest(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"sources": []}))
    index = {
        "manifest_path": str(manifest),
        "aois": {"hanoi_core": {
            "manifest_path": str(manifest),
            "land_cover": {"source_id": "gate2_hanoi_core_worldcover"},
        }},
    }
    with pytest.raises(RuntimeError, match="absent from its acquisition manifest"):
        _load_acquisition_manifest(index)


# --- candidate set --------------------------------------------------------

def test_mvp_candidates_are_exactly_the_three_h3_resolutions(config):
    cands = build_mvp_candidates(config)
    assert [c.id for c in cands] == ["h3_r8", "h3_r9", "h3_r10"]
    assert all(c.family == "h3" for c in cands)


def test_mvp_candidates_refuse_any_other_family(config):
    bad = dict(config, candidates=dict(config["candidates"], family="square"))
    with pytest.raises(ValueError, match="h3 family only"):
        build_mvp_candidates(bad)


def test_mvp_aois_are_the_four_representative_contexts(config):
    aois = mvp_aois(config)
    assert [a.id for a in aois] == ["hanoi_core", "hoi_an", "mu_cang_chai", "dong_thap_rural"]
    assert {a.context for a in aois} == {"dense_urban", "tourism", "rural_mountain", "rural_delta"}
    with pytest.raises(ValueError, match="not MVP AOIs"):
        mvp_aois(config, ["hcmc_core"])


# --- deterministic generation, actual area, lookup ------------------------

@pytest.mark.parametrize("resolution", [8, 9, 10])
def test_h3_generation_is_deterministic_at_every_mvp_resolution(aoi, resolution):
    grid = H3Grid(resolution=resolution)
    a = grid.units(aoi.polygon, aoi.metric_crs)
    b = grid.units(aoi.polygon, aoi.metric_crs)
    assert len(a) > 0
    assert a["unit_id"].tolist() == b["unit_id"].tolist()
    np.testing.assert_array_equal(a["area_m2"].to_numpy(), b["area_m2"].to_numpy())
    assert a["unit_id"].is_unique


@pytest.mark.parametrize("resolution", [8, 9, 10])
def test_h3_actual_area_is_measured_and_close_to_but_not_equal_to_nominal(aoi, resolution):
    """Vietnamese cells run ~14% larger than the published global average;
    the measured area must be the polygon area, never the nominal."""
    grid = H3Grid(resolution=resolution)
    units = grid.units(aoi.polygon, aoi.metric_crs)
    actual = units["area_m2"].to_numpy() / 1e6
    assert np.all(actual > 0)
    ratio = np.median(actual) / grid.nominal_area_km2
    assert 1.05 < ratio < 1.25
    assert not np.allclose(actual, grid.nominal_area_km2)


@pytest.mark.parametrize("resolution", [8, 9, 10])
def test_h3_lookup_is_deterministic_and_agrees_with_generated_cells(aoi, resolution):
    import h3

    grid = H3Grid(resolution=resolution)
    units = grid.units(aoi.polygon, aoi.metric_crs)
    known = set(units["unit_id"])
    rng = np.random.default_rng(11)
    w, s, e, n = aoi.polygon.bounds
    lon = rng.uniform(w, e, 300); lat = rng.uniform(s, n, 300)
    first = grid.lookup(lat, lon)
    second = grid.lookup(lat, lon)
    assert list(first) == list(second)
    assert all(uid in known for uid in first), "a point inside the AOI must land in a generated cell"
    assert all(h3.get_resolution(uid) == resolution for uid in first)


# --- the selection rule on synthetic inputs ---------------------------------

AOIS = ["hanoi_core", "hoi_an", "mu_cang_chai", "dong_thap_rural"]
ANCHORS = ["poi_count_1km", "population_1km", "road_length_1km_m"]


def _metrics(ratios: dict[str, dict[str, list[float]]]) -> pd.DataFrame:
    """ratios[candidate][aoi] = [poi, pop, road] loss ratios."""
    rows = []
    for cand, per_aoi in ratios.items():
        for aoi_id, values in per_aoi.items():
            for anchor, v in zip(ANCHORS, values):
                rows.append({"run_id": "t", "aoi_id": aoi_id, "context": "c", "candidate_id": cand,
                             "family": "h3", "role": "operational",
                             "metric": "within_unit_range_over_between_unit_iqr", "dimension": anchor,
                             "spatial_support": "buffer_1km", "value": v, "unit": "ratio",
                             "source_status": "ingested_ok", "notes": ""})
    return pd.DataFrame(rows)


def _summary(config, **loss):
    """A candidate summary in which r8 is always cheaper than r9."""
    metrics = _metrics({c: {a: [0.1, 0.1, 0.1] for a in AOIS} for c in ("h3_r8", "h3_r9", "h3_r10")})
    s = candidate_summary(metrics, pd.DataFrame(), pd.DataFrame(), config).set_index("candidate_id")
    s.loc["h3_r8", "nationwide_units_projected"], s.loc["h3_r9", "nationwide_units_projected"] = 5e5, 3e6
    s.loc["h3_r8", "nationwide_storage_bytes_projected"], s.loc["h3_r9", "nationwide_storage_bytes_projected"] = 1e8, 5e8
    for c, v in loss.items():
        s.loc[c, "within_cell_loss_ratio_median"] = v
    return s.reset_index()


def _uniform(r8, r9, r10):
    return {"h3_r8": {a: r8 for a in AOIS}, "h3_r9": {a: r9 for a in AOIS}, "h3_r10": {a: r10 for a in AOIS}}


def test_an_anchor_triggers_only_above_25_percent_and_rejection_needs_two(config):
    metrics = _metrics({"h3_r9": {"hanoi_core": [0.26, 0.10, 0.10],     # one anchor: not rejected
                                  "hoi_an": [0.26, 0.26, 0.10],         # two anchors: rejected
                                  "mu_cang_chai": [0.25, 0.25, 0.25],   # exactly 25%: not over
                                  "dong_thap_rural": [np.nan, 0.3, 0.1]}})  # NaN never triggers
    table = coarse_table(metrics, config).set_index("aoi_id")
    assert table.loc["hanoi_core", "anchors_triggered"] == 1 and not table.loc["hanoi_core", "rejected_in_context"]
    assert table.loc["hoi_an", "anchors_triggered"] == 2 and table.loc["hoi_an", "rejected_in_context"]
    assert table.loc["mu_cang_chai", "anchors_triggered"] == 0
    assert table.loc["dong_thap_rural", "anchors_triggered"] == 1
    assert table.loc["dong_thap_rural", "anchors_evaluable"] == 2


def test_rule_1_selects_r9_when_it_passes_everywhere(config):
    metrics = _metrics(_uniform([0.4, 0.4, 0.4], [0.1, 0.1, 0.1], [0.05, 0.05, 0.05]))
    out = select_resolution(coarse_table(metrics, config), _summary(config), config, AOIS)
    assert out["decision"] == "select"
    assert out["selected_candidate"] == "h3_r9" and out["selected_h3_resolution"] == 9
    assert out["selection_rule_fired"] == 1
    assert out["decision_status"] == "provisional_mvp"


def test_rule_1_still_prefers_r9_over_a_passing_r10(config):
    """r9 is the practical default; a finer resolution that also passes
    does not displace it."""
    metrics = _metrics(_uniform([0.4, 0.4, 0.4], [0.2, 0.2, 0.2], [0.01, 0.01, 0.01]))
    out = select_resolution(coarse_table(metrics, config), _summary(config), config, AOIS)
    assert out["selected_candidate"] == "h3_r9"


def test_rule_2_selects_r10_when_r9_fails_in_any_single_aoi(config):
    ratios = _uniform([0.4, 0.4, 0.4], [0.1, 0.1, 0.1], [0.05, 0.05, 0.05])
    ratios["h3_r9"]["mu_cang_chai"] = [0.3, 0.3, 0.1]   # two anchors in one context is enough
    out = select_resolution(coarse_table(_metrics(ratios), config), _summary(config), config, AOIS)
    assert out["selected_candidate"] == "h3_r10" and out["selection_rule_fired"] == 2
    assert out["verdicts"]["h3_r9"]["contexts_rejected"] == ["mu_cang_chai"]


def test_rule_3_selects_r8_only_when_it_passes_and_is_cheaper_with_no_greater_loss(config):
    # r9 and r10 both fail; r8 passes and is cheaper with lower loss.
    ratios = _uniform([0.1, 0.1, 0.1], [0.3, 0.3, 0.1], [0.3, 0.3, 0.1])
    summary = _summary(config, h3_r8=0.1, h3_r9=0.3)
    out = select_resolution(coarse_table(_metrics(ratios), config), summary, config, AOIS)
    assert out["selected_candidate"] == "h3_r8" and out["selection_rule_fired"] == 3
    # Same verdicts, but r8's loss is greater than r9's: not selected.
    summary = _summary(config, h3_r8=0.35, h3_r9=0.3)
    out = select_resolution(coarse_table(_metrics(ratios), config), summary, config, AOIS)
    assert out["decision"] == "no_decision" and out["selected_candidate"] is None


def test_no_decision_when_nothing_passes(config):
    metrics = _metrics(_uniform([0.4, 0.4, 0.4], [0.3, 0.3, 0.3], [0.3, 0.3, 0.3]))
    out = select_resolution(coarse_table(metrics, config), _summary(config), config, AOIS)
    assert out["decision"] == "no_decision"
    assert out["selected_candidate"] is None and out["selected_h3_resolution"] is None
    assert out["selection_rule_fired"] is None and out["decision_status"] is None


def test_a_missing_context_is_not_a_pass(config):
    """A smoke run over one AOI must never select anything."""
    metrics = _metrics({c: {"hanoi_core": [0.1, 0.1, 0.1]} for c in ("h3_r8", "h3_r9", "h3_r10")})
    out = select_resolution(coarse_table(metrics, config), _summary(config), config, AOIS)
    assert out["decision"] == "no_decision"
    assert set(out["verdicts"]["h3_r9"]["contexts_missing"]) == set(AOIS) - {"hanoi_core"}


def test_the_rule_uses_no_threshold_beyond_the_pre_registered_ones(config):
    acc = config["acceptance"]
    assert acc["coarse_within_unit_range_fraction_of_between_unit_iqr"] == 0.25
    assert acc["coarse_minimum_anchor_features_triggered"] == 2
    full = yaml.safe_load(open("config/gate2.yaml"))["acceptance"]
    for key in acc:
        assert acc[key] == full[key], f"MVP threshold {key} differs from the pre-registered value"
    assert [a["id"] for a in config["anchor_features"]] == ANCHORS


# --- checksums --------------------------------------------------------------

def test_checksums_are_written_relative_and_verify_then_detect_tampering(tmp_path):
    (tmp_path / "sub").mkdir()
    a = tmp_path / "a.txt"; a.write_text("alpha")
    b = tmp_path / "sub" / "b.txt"; b.write_text("beta")
    sums = write_checksums(tmp_path, [b, a])
    lines = sums.read_text().splitlines()
    assert [l.split("  ")[1] for l in lines] == ["a.txt", "sub/b.txt"]
    assert verify_checksums(tmp_path) == []
    b.write_text("changed")
    assert verify_checksums(tmp_path) == ["sub/b.txt"]
    a.unlink()
    assert set(verify_checksums(tmp_path)) == {"a.txt", "sub/b.txt"}


# --- the real MVP run -------------------------------------------------------

@requires_mvp_run
def test_every_required_mvp_output_exists_and_is_checksummed():
    run = _latest_mvp_run()
    listed = {line.split("  ")[1] for line in (run / "SHA256SUMS").read_text().splitlines()}
    for rel in REQUIRED_OUTPUTS:
        assert (run / rel).exists(), rel
        assert rel in listed, f"{rel} is not checksummed"
    assert verify_checksums(run) == [], "an MVP run directory must be immutable"


@requires_mvp_run
def test_no_square_or_admin_candidate_appears_in_the_mvp_run():
    run = _latest_mvp_run()
    for name in ("candidate_inventory", "candidate_metrics", "lookup_benchmark"):
        df = pd.read_parquet(run / f"{name}.parquet")
        assert set(df["candidate_id"]) == {"h3_r8", "h3_r9", "h3_r10"}, name
    bench = pd.read_parquet(run / "benchmark_runs.parquet")
    assert set(bench["candidate_id"]) - {""} == {"h3_r8", "h3_r9", "h3_r10"}
    manifest = json.loads((run / "run_manifest.json").read_text())
    assert {c["family"] for c in manifest["candidates"]} == {"h3"}
    assert not any(u.startswith(("square", "admin")) for u in pd.read_parquet(run / "units" / "hanoi_core" / "h3_r9_geometry.parquet")["unit_id"].head(5))


@requires_mvp_run
def test_recorded_selection_follows_the_stated_rule(config):
    """Recompute the verdicts from the measured tables and check that
    decision.json -- and config/spatial.yaml -- say the same thing."""
    run = _latest_mvp_run()
    metrics = pd.read_parquet(run / "candidate_metrics.parquet")
    bench = pd.read_parquet(run / "benchmark_runs.parquet")
    lookup = pd.read_parquet(run / "lookup_benchmark.parquet")
    decision = json.loads((run / "decision.json").read_text())
    expected_aois = list(config["aoi"]["mvp_aoi_ids"])

    recomputed = select_resolution(coarse_table(metrics, config),
                                   candidate_summary(metrics, bench, lookup, config), config, expected_aois)
    assert decision["selected_candidate"] == recomputed["selected_candidate"]
    assert decision["selection_rule_fired"] == recomputed["selection_rule_fired"]
    assert decision["decision"] == recomputed["decision"]
    assert decision["missing_candidate_aoi_pairs"] == [] and decision["lookup_failures_total"] == 0

    spatial = yaml.safe_load(open("config/spatial.yaml"))["spatial_unit"]
    if decision["decision"] == "select":
        assert spatial["method"] == "h3"
        assert spatial["h3_resolution"] == decision["selected_h3_resolution"]
        assert spatial["decision_status"] == "provisional_mvp"
    else:
        assert spatial["method"] is None


@requires_mvp_run
def test_mvp_run_source_clips_carry_the_tile_coverage_proof():
    coverage = pd.read_parquet(_latest_mvp_run() / "source_coverage.parquet")
    raster = coverage[coverage["source_role"].isin(["land_cover", "built_up", "population"])]
    assert len(raster) == 12
    assert raster["window_inside_tile_union"].astype(bool).all()
    assert raster["window_covered_by_clip"].astype(bool).all()
    assert raster["edge_full_nodata"].notna().all()
    tiles = {(r.aoi_id, r.source_role): json.loads(r.source_tiles) for r in raster.itertuples()}
    assert len(tiles[("hanoi_core", "land_cover")]) == 2
    assert len(tiles[("mu_cang_chai", "built_up")]) == 2


@requires_mvp_run
def test_mvp_source_provenance_matches_the_index_and_actual_clip_bytes():
    """A valid checksum is not enough if it describes a superseded clip.
    Every run coverage row must pin the exact bytes selected for that AOI."""
    import hashlib

    run = _latest_mvp_run()
    manifest = json.loads((run / "run_manifest.json").read_text())
    index_path = Path(manifest["acquisition_source_index"]["path"])
    index = json.loads(index_path.read_text())
    coverage = pd.read_parquet(run / "source_coverage.parquet")
    role_key = {"poi_roads": "roads_poi", "population": "population",
                "land_cover": "land_cover", "built_up": "built_up"}

    for row in coverage.itertuples():
        source = index["aois"][row.aoi_id][role_key[row.source_role]]
        assert row.source_id == source["source_id"]
        assert row.sha256 == source["sha256"]
        digest = hashlib.sha256(Path(source["path"]).read_bytes()).hexdigest()
        assert row.sha256 == digest


@requires_mvp_run
def test_mvp_run_measured_every_required_metric_for_every_pair(config):
    metrics = pd.read_parquet(_latest_mvp_run() / "candidate_metrics.parquet")
    required = {"unit_count_total", "unit_area_km2_median", "unit_area_km2_p05", "unit_area_km2_p95",
                "unit_count_nationwide_projected", "storage_nationwide_projected_bytes",
                "storage_geometry_nationwide_projected_bytes", "storage_feature_nationwide_projected_bytes",
                "poi_zero_share", "population_zero_share", "population_median",
                "road_zero_length_share", "road_length_median_m",
                "within_unit_range_over_between_unit_iqr", "population_conservation_relative_error"}
    have = metrics.groupby(["aoi_id", "candidate_id"])["metric"].apply(set)
    assert len(have) == 12
    for key, value in have.items():
        assert required <= value, (key, sorted(required - value))
    err = metrics[metrics["metric"] == "population_conservation_relative_error"]["value"]
    assert err.max() < 1e-9
