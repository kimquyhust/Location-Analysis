"""Gate 4 contextual-normalization tests: pure transforms on synthetic
data, contract/config validation, and -- when the immutable four-AOI run
exists -- lineage, key agreement, determinism and forbidden-column checks
on the real artifact."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from features.schema import STATUS_COLUMN_OF, load_features_config  # noqa: E402
from normalization import run_gate4_mvp as runner  # noqa: E402
from normalization.schema import (ConfigError, forbidden_columns, load_gate4_config, validate_config)  # noqa: E402
from normalization.transforms import (COHORT_DEGENERATE, COHORT_NOT_FITTED, COHORT_TOO_SMALL,  # noqa: E402
                                      NEIGHBORHOOD_INCOMPLETE, NEIGHBORHOOD_INSUFFICIENT_VALID,
                                      NEIGHBORHOOD_REFERENCE_ZERO, NeighborhoodPolicy, TransformInputError,
                                      aoi_equal_weights, apply_ecdf, fit_ecdf, local_ratio, log1p_transform,
                                      neighborhoods, peer_groups_are_sufficient)

GATE4_CONFIG = ROOT / "config/gate4_mvp.yaml"
GATE3_RUN = ROOT / "data/gate3/run_20260914T171148Z"


def _cfg() -> dict:
    return load_gate4_config(GATE4_CONFIG)


def _features_cfg() -> dict:
    return load_features_config(ROOT / "config/features.yaml")


def _series(vals, status):
    return pd.Series(vals, dtype="float64"), pd.Series(status, dtype=object)


# ---------------------------------------------------------------------------
# A. log1p
# ---------------------------------------------------------------------------

def test_log1p_zero_is_exactly_zero_and_values_are_ln1p():
    v, s = _series([0.0, 1.0, np.e - 1], ["ok", "ok", "ok"])
    out, st = log1p_transform(v, s, "x")
    assert out.iloc[0] == 0.0
    assert out.iloc[1] == pytest.approx(np.log(2))
    assert out.iloc[2] == pytest.approx(1.0)
    assert list(st) == ["ok", "ok", "ok"]


def test_log1p_null_stays_null_with_atomic_status_and_is_never_imputed():
    v, s = _series([np.nan, 3.0, np.nan], ["entity_assembly_failed", "ok", "search_truncated_by_extract"])
    out, st = log1p_transform(v, s, "x")
    assert np.isnan(out.iloc[0]) and np.isnan(out.iloc[2])
    assert list(st) == ["entity_assembly_failed", "ok", "search_truncated_by_extract"]
    assert out.notna().sum() == 1


def test_failure_status_with_a_value_or_bare_null_is_a_contract_error():
    v, s = _series([5.0], ["source_unavailable"])
    with pytest.raises(TransformInputError, match="failure status"):
        log1p_transform(v, s, "x")
    v, s = _series([np.nan], ["ok"])
    with pytest.raises(TransformInputError, match="bare null"):
        log1p_transform(v, s, "x")


def test_log1p_negative_input_fails_instead_of_clipping():
    v, s = _series([1.0, -0.5], ["ok", "ok"])
    with pytest.raises(TransformInputError, match="negative"):
        log1p_transform(v, s, "x")


def test_log1p_does_not_mutate_input():
    v, s = _series([0.0, 2.0], ["ok", "ok"])
    v0, s0 = v.copy(), s.copy()
    log1p_transform(v, s, "x")
    pd.testing.assert_series_equal(v, v0)
    pd.testing.assert_series_equal(s, s0)


# ---------------------------------------------------------------------------
# B. percentiles
# ---------------------------------------------------------------------------

def test_percentile_in_unit_interval_and_monotone():
    rng = np.random.default_rng(0)
    x = np.round(rng.gamma(0.5, 10, 200), 1)
    x[:60] = 0.0
    v, s = _series(x, ["ok"] * 200)
    tab = fit_ecdf(v, s, None, "c", "f", "cell", minimum_cohort_size=30)
    p, st = apply_ecdf(v, s, tab, "c", "f", "cell", "midrank_ecdf")
    assert (st == "ok").all()
    assert p.between(0.0, 1.0).all()
    order = np.argsort(x, kind="stable")
    assert (np.diff(p.to_numpy()[order]) >= -1e-12).all()


def test_tie_handling_is_deterministic_and_matches_the_configured_formula():
    x = np.array([0, 0, 0, 0, 1, 2, 2, 5, 5, 5], dtype="float64")
    v, s = _series(x, ["ok"] * 10)
    tab = fit_ecdf(v, s, None, "c", "f", "cell", minimum_cohort_size=2)
    mid, _ = apply_ecdf(v, s, tab, "c", "f", "cell", "midrank_ecdf")
    lo, _ = apply_ecdf(v, s, tab, "c", "f", "cell", "min_ecdf")
    hi, _ = apply_ecdf(v, s, tab, "c", "f", "cell", "max_ecdf")
    # zeros: 4 of 10 -> midrank 0.2, min 0.0, max 0.4; equal inputs equal outputs
    assert mid.iloc[:4].nunique() == 1 and mid.iloc[0] == pytest.approx(0.2)
    assert lo.iloc[0] == 0.0 and hi.iloc[0] == pytest.approx(0.4)
    # the 2s: below 5, equal 2 -> (5 + 1)/10
    assert mid.iloc[5] == pytest.approx(0.6)
    # max value never reaches 1 under midrank, reaches 1 under max_ecdf
    assert mid.iloc[-1] == pytest.approx((7 + 1.5) / 10) and hi.iloc[-1] == 1.0
    # the same call twice is bit-identical
    again, _ = apply_ecdf(v, s, tab, "c", "f", "cell", "midrank_ecdf")
    assert np.array_equal(mid.to_numpy(), again.to_numpy())
    # an unseen value falls between fitted values and stays in [0, 1]
    q, _ = apply_ecdf(*_series([3.0, -1.0, 99.0], ["ok"] * 3), tab, "c", "f", "cell", "midrank_ecdf")
    assert q.iloc[0] == pytest.approx(0.7) and q.iloc[1] == 0.0 and q.iloc[2] == 1.0


def test_constant_and_too_small_cohorts_give_null_with_status_not_a_value():
    v, s = _series([2.0] * 40, ["ok"] * 40)
    tab = fit_ecdf(v, s, None, "c", "f", "cell", minimum_cohort_size=30)
    assert list(tab["fit_status"]) == [COHORT_DEGENERATE] and tab["n_distinct"].iloc[0] == 1
    p, st = apply_ecdf(v, s, tab, "c", "f", "cell", "midrank_ecdf")
    assert p.isna().all() and (st == COHORT_DEGENERATE).all()
    v, s = _series([1.0, 2.0, 3.0], ["ok"] * 3)
    tab = fit_ecdf(v, s, None, "c", "f", "cell", minimum_cohort_size=30)
    assert list(tab["fit_status"]) == [COHORT_TOO_SMALL]
    p, st = apply_ecdf(v, s, tab, "c", "f", "cell", "midrank_ecdf")
    assert p.isna().all() and (st == COHORT_TOO_SMALL).all()


def test_percentile_preserves_atomic_status_and_excludes_failed_rows_from_the_fit():
    v, s = _series([np.nan, 1.0, 2.0, 3.0, np.nan], ["denominator_zero", "ok", "ok", "ok", "coverage_incomplete"])
    tab = fit_ecdf(v, s, None, "c", "f", "cell", minimum_cohort_size=2)
    assert tab["n_obs"].iloc[0] == 3
    p, st = apply_ecdf(v, s, tab, "c", "f", "cell", "midrank_ecdf")
    assert np.isnan(p.iloc[0]) and st.iloc[0] == "denominator_zero"
    assert np.isnan(p.iloc[4]) and st.iloc[4] == "coverage_incomplete"
    assert p.iloc[1] == pytest.approx(0.5 / 3)


def test_fit_then_apply_from_persisted_cohort_statistics_matches_in_memory(tmp_path):
    rng = np.random.default_rng(1)
    v, s = _series(rng.poisson(3, 100).astype("float64"), ["ok"] * 100)
    tab = fit_ecdf(v, s, None, "cohort::1", "f", "cell", minimum_cohort_size=30)
    tab.to_parquet(tmp_path / "cohort_statistics.parquet", index=False)
    persisted = pd.read_parquet(tmp_path / "cohort_statistics.parquet")
    p_mem, _ = apply_ecdf(v, s, tab, "cohort::1", "f", "cell", "midrank_ecdf")
    p_disk, _ = apply_ecdf(v, s, persisted, "cohort::1", "f", "cell", "midrank_ecdf")
    assert np.array_equal(p_mem.to_numpy(), p_disk.to_numpy())
    # no persisted statistics for a cohort -> status, never an implicit refit
    p_none, st = apply_ecdf(v, s, persisted, "cohort::other", "f", "cell", "midrank_ecdf")
    assert p_none.isna().all() and (st == COHORT_NOT_FITTED).all()


def test_aoi_equal_weighting_differs_from_cell_weighting_when_one_aoi_dominates():
    # AOI a: 90 rows at 0..89 ; AOI b: 10 rows at 1000..1009
    x = np.concatenate([np.arange(90), 1000 + np.arange(10)]).astype("float64")
    aoi = pd.Series(["a"] * 90 + ["b"] * 10)
    v, s = _series(x, ["ok"] * 100)
    w = aoi_equal_weights(aoi)
    assert w[aoi == "a"].sum() == pytest.approx(1.0) and w[aoi == "b"].sum() == pytest.approx(1.0)
    cell = fit_ecdf(v, s, None, "c", "f", "cell", 30)
    aoiw = fit_ecdf(v, s, w, "c", "f", "aoi_equal", 30)
    p_cell, _ = apply_ecdf(v, s, cell, "c", "f", "cell", "midrank_ecdf")
    p_aoi, _ = apply_ecdf(v, s, aoiw, "c", "f", "aoi_equal", "midrank_ecdf")
    # the smallest b row: cell-weighted 0.905, AOI-weighted 0.5 + 0.05
    assert p_cell.iloc[90] == pytest.approx(0.905) and p_aoi.iloc[90] == pytest.approx(0.525)
    assert np.abs(p_cell - p_aoi).max() > 0.3


def test_peer_percentile_is_blocked_with_one_aoi_per_context():
    aoi = pd.Series(["hanoi_core", "hoi_an", "mu_cang_chai", "dong_thap_rural"])
    ctx = pd.Series(["dense_urban", "tourism", "rural_mountain", "rural_delta"])
    r = peer_groups_are_sufficient(aoi, ctx, 2)
    assert r["sufficient"] is False and set(r["aois_per_context"].values()) == {1}
    aoi2 = pd.concat([aoi, pd.Series(["hcmc_core", "phu_quoc_coast", "x", "y"])], ignore_index=True)
    ctx2 = pd.concat([ctx, pd.Series(["dense_urban", "tourism", "rural_mountain", "rural_delta"])], ignore_index=True)
    assert peer_groups_are_sufficient(aoi2, ctx2, 2)["sufficient"] is True


# ---------------------------------------------------------------------------
# C. local ratio
# ---------------------------------------------------------------------------

def _line_ring(cell: str, k: int) -> list[str]:
    i = int(cell[1:])
    return [f"c{j}" for j in range(i - k, i + k + 1)]


def _policy(**kw) -> NeighborhoodPolicy:
    base = dict(k=1, exclude_centre=True, reference_statistic="median", require_all_neighbors_present=True,
                minimum_valid_neighbors=2)
    base.update(kw)
    return NeighborhoodPolicy(**base)


def test_local_ratio_denominator_zero_is_null_with_status_and_no_epsilon():
    ids = pd.Series([f"c{i}" for i in range(5)])
    v, s = _series([0.0, 4.0, 0.0, 0.0, 0.0], ["ok"] * 5)
    nbh = neighborhoods(ids, 1, _line_ring)
    r, st, ref = local_ratio(v, s, ids, nbh, _policy(), "f")
    # c1: neighbors c0=0, c2=0 -> median 0 -> undefined
    assert np.isnan(r.iloc[1]) and st.iloc[1] == NEIGHBORHOOD_REFERENCE_ZERO and ref.iloc[1] == 0.0
    # c2: neighbors c1=4, c3=0 -> median 2 -> 0/2 = 0 (a real zero ratio)
    assert r.iloc[2] == 0.0 and st.iloc[2] == "ok"
    assert not np.isinf(r.dropna()).any()


def test_local_ratio_incomplete_or_insufficient_neighborhood_is_null_with_status():
    ids = pd.Series([f"c{i}" for i in range(4)])
    v, s = _series([1.0, 2.0, np.nan, 3.0], ["ok", "ok", "denominator_zero", "ok"])
    nbh = neighborhoods(ids, 1, _line_ring)
    assert list(nbh["neighborhood_complete"]) == [False, True, True, False]
    r, st, _ = local_ratio(v, s, ids, nbh, _policy(minimum_valid_neighbors=2), "f")
    assert st.iloc[0] == NEIGHBORHOOD_INCOMPLETE and np.isnan(r.iloc[0])
    assert st.iloc[3] == NEIGHBORHOOD_INCOMPLETE
    # c1 has neighbors c0 (ok) and c2 (failed) -> only 1 valid < 2
    assert st.iloc[1] == NEIGHBORHOOD_INSUFFICIENT_VALID and np.isnan(r.iloc[1])
    # the failed centre keeps its atomic status
    assert st.iloc[2] == "denominator_zero" and np.isnan(r.iloc[2])
    r2, st2, _ = local_ratio(v, s, ids, nbh, _policy(minimum_valid_neighbors=1), "f")
    assert st2.iloc[1] == "ok" and r2.iloc[1] == pytest.approx(2.0)


def test_local_ratio_policy_rejects_centre_inclusion_and_bad_statistic():
    with pytest.raises(ValueError):
        _policy(exclude_centre=False)
    with pytest.raises(ValueError):
        _policy(reference_statistic="p90")


# ---------------------------------------------------------------------------
# config / contract
# ---------------------------------------------------------------------------

def test_gate4_config_is_valid_and_pins_the_gate3_input():
    cfg, fc = _cfg(), _features_cfg()
    validate_config(cfg, fc)
    assert cfg["input"]["gate3_run_id"] == "20260914T171148Z"
    assert cfg["input"]["feature_set_version"] == fc["feature_set_version"] == "0.3.0"
    assert fc["contextual_features"]["enabled"] is False
    assert cfg["normalization_version"] == "0.1.0"


def test_config_rejects_ratio_log1p_distance_percentile_and_national_name():
    fc = _features_cfg()
    bad = copy.deepcopy(_cfg()); bad["transforms"]["log1p"]["candidates"].append("built_up_ratio")
    with pytest.raises(ConfigError, match="log1p"):
        validate_config(bad, fc)
    bad = copy.deepcopy(_cfg()); bad["transforms"]["percentile"]["candidates"].append("distance_nearest_park_m")
    with pytest.raises(ConfigError, match="distances"):
        validate_config(bad, fc)
    bad = copy.deepcopy(_cfg())
    bad["transforms"]["percentile"]["cohorts"]["mvp_pooled_percentile"]["output_name"] = "{feature}_national_percentile"
    with pytest.raises(ConfigError, match="national_percentile"):
        validate_config(bad, fc)
    bad = copy.deepcopy(_cfg()); bad["transforms"]["percentile"]["cohorts"]["peer_percentile"]["minimum_aois_per_peer_group"] = 1
    with pytest.raises(ConfigError, match="peer"):
        validate_config(bad, fc)
    bad = copy.deepcopy(_cfg()); bad["transforms"]["local_ratio"]["denominator_zero_policy"] = "epsilon"
    with pytest.raises(ConfigError, match="epsilon"):
        validate_config(bad, fc)
    bad = copy.deepcopy(_cfg()); bad["transforms"]["source_defined_ghs_smod_class"]["substitute_with_custom_threshold"] = True
    with pytest.raises(ConfigError, match="source"):
        validate_config(bad, fc)


def test_forbidden_columns_are_detected():
    cfg = _cfg()
    assert forbidden_columns(["log1p_x", "pickup_count", "commercial_score", "x_national_percentile", "trip_id"], cfg) == \
        ["pickup_count", "commercial_score", "x_national_percentile", "trip_id"]


@pytest.mark.skipif(not GATE3_RUN.exists(), reason="Gate 3 input not present")
def test_input_checksum_or_version_mismatch_fails_before_computing():
    fc = _features_cfg()
    bad = copy.deepcopy(_cfg()); bad["input"]["sha256"]["atomic_features.parquet"] = "0" * 64
    with pytest.raises(runner.InputMismatch, match="sha256"):
        runner.verify_gate3_input(bad, fc)
    bad = copy.deepcopy(_cfg()); bad["input"]["gate3_run_id"] = "20000101T000000Z"
    with pytest.raises(runner.InputMismatch, match="run_id"):
        runner.verify_gate3_input(bad, fc)
    bad = copy.deepcopy(_cfg()); bad["input"]["feature_set_version"] = "0.2.0"
    with pytest.raises(ConfigError):
        validate_config(bad, fc)
    bad = copy.deepcopy(_cfg()); bad["input"]["gate3_run_dir"] = "data/gate3/run_20260914T160806Z"  # the superseded 0.2.0 run
    with pytest.raises(runner.InputMismatch):
        runner.verify_gate3_input(bad, fc)


# ---------------------------------------------------------------------------
# the immutable four-AOI artifact
# ---------------------------------------------------------------------------

def _gate4_run() -> Path:
    run = runner.latest_full_run(ROOT / "data/gate4")
    if run is None:
        pytest.skip("no full Gate 4 run on disk")
    return run


def test_gate4_artifact_keys_lineage_and_checksums():
    run = _gate4_run()
    from spatial.run_gate2_mvp import verify_checksums
    assert verify_checksums(run) == []
    atomic = pd.read_parquet(GATE3_RUN / "atomic_features.parquet")
    pub = pd.read_parquet(run / "contextual_features.parquet")
    diag = pd.read_parquet(run / "diagnostic_features.parquet")
    for t in (pub, diag):
        assert len(t) == len(atomic) == 5681
        assert t["spatial_unit_id"].is_unique and not t["spatial_unit_id"].isna().any()
        assert list(t["spatial_unit_id"]) == list(atomic["spatial_unit_id"])
        assert set(t["aoi_id"]) == {"hanoi_core", "hoi_an", "mu_cang_chai", "dong_thap_rural"}
        assert (t["gate3_run_id"] == "20260914T171148Z").all()
        assert (t["feature_set_version"] == "0.3.0").all()
        assert (t["normalization_version"] == "0.1.0").all()
        assert forbidden_columns(t.columns, _cfg()) == []
        assert not any("peer_percentile" in c for c in t.columns)
    m = json.loads((run / "normalization_manifest.json").read_text())
    rm = json.loads((run / "run_manifest.json").read_text())
    assert m["input"]["sha256"]["atomic_features.parquet"] == _cfg()["input"]["sha256"]["atomic_features.parquet"]
    assert m["peer_percentile"]["disposition"] == "blocked"
    assert m["source_defined_ghs_smod_class"]["status"] == "source_not_acquired"
    assert rm["gate"] == 4 and rm["validation_passed"] is True
    # no absolute machine paths in any manifest
    for text in (json.dumps(m), json.dumps(rm)):
        assert "/Users/" not in text and "/home/" not in text
    # every column in the publishable table is specified as publishable and has a status column
    specs = m["tables"]["contextual_features.parquet"]["columns"]
    for c, sp in specs.items():
        assert sp["disposition"] == "publishable" and f"{c}_status" in pub.columns
    v = json.loads((run / "validation_summary.json").read_text())
    assert v["passed"] is True and v["schema"]["publishable"]["passed"] and v["schema"]["diagnostic"]["passed"]


def test_gate4_artifact_values_follow_the_contract_against_gate3():
    run = _gate4_run()
    atomic = pd.read_parquet(GATE3_RUN / "atomic_features.parquet")
    pub = pd.read_parquet(run / "contextual_features.parquet")
    m = json.loads((run / "normalization_manifest.json").read_text())
    for c, sp in m["tables"]["contextual_features.parquet"]["columns"].items():
        src = sp["source_feature"]
        x = atomic[src].to_numpy(dtype="float64", na_value=np.nan)
        y = pub[c].to_numpy(dtype="float64", na_value=np.nan)
        st = pub[f"{c}_status"].to_numpy()
        assert (np.isnan(y) == (st != "ok")).all(), c
        assert not (np.isnan(x) & ~np.isnan(y)).any(), f"{c}: value where the atomic input is null"
        failed = atomic[STATUS_COLUMN_OF[src]].to_numpy() != "ok"
        assert (st[failed] == atomic[STATUS_COLUMN_OF[src]].to_numpy()[failed]).all(), c
        if sp["transform"] == "log1p":
            ok = st == "ok"
            assert np.allclose(y[ok], np.log1p(x[ok])) and (y[ok & (x == 0)] == 0).all()
        if sp["transform"] == "local_ratio":
            assert (y[st == "ok"] >= 0).all() and not (~np.isnan(y) & ~pub["neighborhood_complete"].to_numpy()).any()


def test_gate4_rerun_is_identical_outside_run_metadata(tmp_path):
    run = _gate4_run()
    res = runner.run(_cfg(), GATE4_CONFIG, output_root=tmp_path)
    new = Path(res["out_dir"])
    for name in ("contextual_features.parquet", "diagnostic_features.parquet", "cohort_statistics.parquet"):
        a = pd.read_parquet(run / name).drop(columns=runner.RUN_METADATA_COLUMNS, errors="ignore")
        b = pd.read_parquet(new / name).drop(columns=runner.RUN_METADATA_COLUMNS, errors="ignore")
        pd.testing.assert_frame_equal(a, b, check_exact=True)
    m_old = json.loads((run / "normalization_manifest.json").read_text())
    m_new = json.loads((new / "normalization_manifest.json").read_text())
    for k in ("normalization_run_id", "config_hash", "config_sha256"):
        m_old.pop(k), m_new.pop(k)
    assert m_old["candidates"] == m_new["candidates"] and m_old["cohorts"] == m_new["cohorts"]
    assert m_old["publishable_columns"] == m_new["publishable_columns"]


def test_gate4_sensitivities_are_measured_and_reported():
    run = _gate4_run()
    v = json.loads((run / "validation_summary.json").read_text())
    s = v["percentile"]["sensitivity"]["population_density"]
    assert s["cell_vs_aoi_equal"]["max_abs_diff"] > 0 and s["pooled_vs_within"]["max_abs_diff"] > 0
    assert set(s["tie_methods"]) == {"midrank_ecdf", "min_ecdf", "max_ecdf"}
    assert set(s["leave_one_aoi_out"]) == {"hanoi_core", "hoi_an", "mu_cang_chai", "dong_thap_rural"}
    lr = v["local_ratio"]["completeness"]
    assert lr["pooled"]["ring_complete_share_interior"] == 1.0 and lr["pooled"]["ring_complete_share_edge"] < 0.5
    assert v["percentile"]["fit"]["peer_percentile"]["sufficient"] is False
