"""Gate 4 contract: config validation, output column naming, and
`validate_outputs` for the contextual tables.

The contract is `config/gate4_mvp.yaml`. This module checks that the
config is internally consistent with the atomic contract
(`config/features.yaml` and `src/features/schema.py`) BEFORE anything is
computed, names every output column deterministically, and validates a
finished run: unique keys identical to the Gate 3 input, no bare null,
finite values, percentiles in [0, 1], non-negative log outputs, statuses
from the declared vocabulary, missingness never lower than the atomic
input (nothing imputed), no forbidden Gate 5 / customer / mobility column,
and every cohort referenced by a row present in the manifest.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import yaml

try:  # pragma: no cover - import root differs between CLI and tests
    from ..features.schema import DISTANCE_FEATURES, RATIO_FEATURES, STATUS_COLUMN_OF, STATUS_VOCABULARY
    from .transforms import REFERENCE_STATISTICS, TIE_METHODS
except ImportError:  # pragma: no cover
    from features.schema import DISTANCE_FEATURES, RATIO_FEATURES, STATUS_COLUMN_OF, STATUS_VOCABULARY
    from normalization.transforms import REFERENCE_STATISTICS, TIE_METHODS

DEFAULT_GATE4_CONFIG = Path("config/gate4_mvp.yaml")

GATE4_LINEAGE = ["normalization_version", "normalization_run_id", "gate3_run_id", "computed_at_utc"]
NEIGHBORHOOD_COLUMNS = ["neighborhood_k_ring", "neighborhood_neighbor_count", "neighborhood_neighbors_present",
                        "neighborhood_complete"]


class ConfigError(ValueError):
    pass


def load_gate4_config(path: Path = DEFAULT_GATE4_CONFIG) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def gate4_status_vocabulary(cfg: dict) -> set[str]:
    sv = cfg["status_vocabulary"]
    return set(sv["atomic_passthrough"]) | set(sv["gate4"].values())


def resolve_group(cfg: dict, names: Iterable[str]) -> list[str]:
    """Expand feature-group names (and plain feature names) in order,
    without duplicates."""
    groups = cfg["feature_groups"]
    out: list[str] = []
    for n in names:
        members = groups[n] if n in groups else [n]
        out += [m for m in members if m not in out]
    return out


def validate_config(cfg: dict, features_cfg: dict) -> None:
    """Fail before computing anything if the Gate 4 contract is not
    consistent with the atomic contract or with itself."""
    mvp = list(features_cfg["mvp_features"])
    if str(cfg["input"]["feature_set_version"]) != str(features_cfg["feature_set_version"]):
        raise ConfigError(f"gate4 input.feature_set_version {cfg['input']['feature_set_version']} != "
                          f"features.yaml {features_cfg['feature_set_version']}")
    if features_cfg.get("contextual_features", {}).get("enabled", False):
        raise ConfigError("features.yaml contextual_features.enabled must stay false until Gate 4 is reviewed")
    for name, members in cfg["feature_groups"].items():
        unknown = [m for m in members if m not in mvp]
        if unknown:
            raise ConfigError(f"feature_groups.{name}: not atomic MVP features: {unknown}")
        if any(m not in STATUS_COLUMN_OF for m in members):
            raise ConfigError(f"feature_groups.{name}: a member has no atomic status column")
    t = cfg["transforms"]
    # log1p: never a bounded ratio, never a distance.
    log_feats = resolve_group(cfg, t["log1p"]["candidates"])
    bad = [f for f in log_feats if f in RATIO_FEATURES or f in DISTANCE_FEATURES]
    if bad:
        raise ConfigError(f"log1p candidates must be non-negative counts/densities/lengths, not {bad}")
    rules = t["log1p"]["rules"]
    if not (rules["zero_maps_to_zero"] and rules["null_stays_null"] and rules["negative_input"] == "fail"
            and rules["impute"] is False and rules["clip_or_winsorize"] is False):
        raise ConfigError("log1p rules deviate from the Gate 4 contract")
    if float(t["log1p"]["publish_rule"]["minimum_raw_skewness"]) < 0:
        raise ConfigError("minimum_raw_skewness must be >= 0")
    # percentile
    p = t["percentile"]
    pct_feats = resolve_group(cfg, p["candidates"])
    bad = [f for f in pct_feats if f in DISTANCE_FEATURES]
    if bad:
        raise ConfigError(f"percentile candidates exclude truncated distances: {bad}")
    if p["tie_method"] not in TIE_METHODS:
        raise ConfigError(f"tie_method must be one of {TIE_METHODS}")
    if any(m not in TIE_METHODS for m in p.get("tie_sensitivity_methods", [])):
        raise ConfigError("tie_sensitivity_methods outside the implemented set")
    if int(p["minimum_cohort_size"]) < 2:
        raise ConfigError("minimum_cohort_size must be >= 2")
    if p["constant_cohort_policy"] != "null_with_status":
        raise ConfigError("constant_cohort_policy must be null_with_status")
    if list(p["range"]) != [0.0, 1.0]:
        raise ConfigError("percentile range must be [0, 1]")
    for cid, c in p["cohorts"].items():
        if "national_percentile" in c["output_name"]:
            raise ConfigError(f"{cid}: national_percentile is not a permitted name")
        if "{feature}" not in c["output_name"]:
            raise ConfigError(f"{cid}: output_name must contain {{feature}}")
    if int(p["cohorts"]["peer_percentile"]["minimum_aois_per_peer_group"]) < 2:
        raise ConfigError("peer_percentile.minimum_aois_per_peer_group must be >= 2")
    if p["cohorts"]["mvp_pooled_percentile"]["disposition"] != "diagnostic" \
            or p["cohorts"]["within_aoi_percentile"]["disposition"] != "diagnostic":
        raise ConfigError("pooled and within-AOI percentiles are diagnostics in this gate")
    # local ratio
    lr = t["local_ratio"]
    unknown = [f for f in lr["candidates"] if f not in mvp]
    if unknown:
        raise ConfigError(f"local_ratio candidates not atomic MVP features: {unknown}")
    bad = [f for f in lr["candidates"] if f in DISTANCE_FEATURES or f in RATIO_FEATURES]
    if bad:
        raise ConfigError(f"local_ratio candidates must be counts/densities, not {bad}")
    nb = lr["neighborhood"]
    if nb["method"] != "h3_grid_disk" or int(nb["k"]) < 1 or not nb["exclude_centre"]:
        raise ConfigError("local_ratio.neighborhood must be an H3 grid disk with k >= 1 and the centre excluded")
    if nb["reference_statistic"] not in REFERENCE_STATISTICS:
        raise ConfigError(f"reference_statistic must be one of {REFERENCE_STATISTICS}")
    if not nb["require_all_neighbors_present"] or int(nb["minimum_valid_neighbors"]) < 1:
        raise ConfigError("local_ratio requires a complete ring and >= 1 valid neighbor")
    if lr["denominator_zero_policy"] != "null_with_status":
        raise ConfigError("denominator_zero_policy must be null_with_status (no epsilon)")
    if not 0 < float(lr["publish_rule"]["minimum_finite_share_of_eligible"]) <= 1:
        raise ConfigError("minimum_finite_share_of_eligible must be in (0, 1]")
    # source-defined class
    sd = t["source_defined_ghs_smod_class"]
    if sd["enabled"] or sd["substitute_with_custom_threshold"]:
        raise ConfigError("source_defined_ghs_smod_class has no acquired source; it cannot be enabled or substituted")
    # vocabulary must cover the atomic vocabulary
    if not STATUS_VOCABULARY <= set(cfg["status_vocabulary"]["atomic_passthrough"]):
        raise ConfigError("atomic_passthrough vocabulary does not cover the Gate 3 status vocabulary")


# --- naming --------------------------------------------------------------------

def log1p_name(cfg: dict, feature: str) -> str:
    return cfg["transforms"]["log1p"]["output_name"].format(feature=feature)


def percentile_name(cfg: dict, cohort_key: str, feature: str) -> str:
    return cfg["transforms"]["percentile"]["cohorts"][cohort_key]["output_name"].format(feature=feature)


def local_ratio_name(cfg: dict, feature: str) -> str:
    k = int(cfg["transforms"]["local_ratio"]["neighborhood"]["k"])
    return cfg["transforms"]["local_ratio"]["output_name"].format(k=k, feature=feature)


def status_name(column: str) -> str:
    return f"{column}_status"


def forbidden_columns(columns: Iterable[str], cfg: dict) -> list[str]:
    pats = [p.lower() for p in cfg["forbidden_column_patterns"]]
    return [c for c in columns if any(p in c.lower() for p in pats)]


# --- validation of a finished table ------------------------------------------

def validate_outputs(table: pd.DataFrame, atomic: pd.DataFrame, cfg: dict, column_specs: dict,
                     cohort_ids_in_manifest: set[str], table_name: str) -> dict:
    """Contract checks on one Gate 4 table against the Gate 3 input.
    `column_specs` maps every value column of the table to its spec
    (source_feature, transform, cohort_id or cohort_id_column, ...)."""
    report: dict = {"table": table_name, "rows": int(len(table)), "problems": [], "checks": {}}
    problems = report["problems"]
    vocab = gate4_status_vocabulary(cfg)

    def check(name: str, ok: bool, detail: str = "") -> None:
        report["checks"][name] = bool(ok)
        if not ok:
            problems.append(f"{table_name}:{name}: {detail}" if detail else f"{table_name}:{name}")

    key = cfg["input"]["join_key"]
    check("key_non_null", not table[key].isna().any(), "null key")
    check("key_unique", table[key].is_unique, "duplicate key")
    check("key_set_equals_gate3", set(table[key].astype(str)) == set(atomic[key].astype(str)), "key set differs")
    check("row_count_equals_gate3", len(table) == len(atomic), f"{len(table)} != {len(atomic)}")
    check("key_order_equals_gate3", list(table[key].astype(str)) == list(atomic[key].astype(str)), "row order differs")
    for col in cfg["lineage_columns"] + GATE4_LINEAGE:
        check(f"{col}_present", col in table.columns, "missing lineage column")
    for col in ("normalization_version", "normalization_run_id", "gate3_run_id", "feature_set_version", "computed_at_utc"):
        if col in table.columns:
            check(f"{col}_uniform", table[col].nunique(dropna=False) == 1 and not table[col].isna().any(), "")
    if "gate3_run_id" in table.columns and len(table):
        check("gate3_run_id_matches_config", str(table["gate3_run_id"].iloc[0]) == str(cfg["input"]["gate3_run_id"]), "")
    if "normalization_version" in table.columns and len(table):
        check("normalization_version_matches_config",
              str(table["normalization_version"].iloc[0]) == str(cfg["normalization_version"]), "")
    aoi_expected = set(cfg["input"]["aoi_ids"])
    check("all_aois_present", set(table["aoi_id"].astype(str)) == aoi_expected if "aoi_id" in table.columns else False,
          "AOI coverage differs from config")
    fb = forbidden_columns(table.columns, cfg)
    check("no_forbidden_columns", not fb, f"{fb}")

    unspecified = [c for c in table.columns
                   if c not in cfg["lineage_columns"] + GATE4_LINEAGE + NEIGHBORHOOD_COLUMNS
                   and c not in column_specs and not c.endswith("_status")
                   and c not in ("within_aoi_cohort_id", "mvp_pooled_cohort_id")]
    check("every_value_column_has_a_spec", not unspecified, f"{unspecified}")

    atomic_by_key = atomic.set_index(atomic[key].astype(str))
    for col, spec in column_specs.items():
        if col not in table.columns:
            problems.append(f"{table_name}:{col}: specified but absent")
            continue
        st_col = status_name(col)
        if st_col not in table.columns:
            problems.append(f"{table_name}:{col}: no status column")
            continue
        st = table[st_col]
        v = table[col].to_numpy(dtype="float64", na_value=np.nan)
        bad_vocab = set(st.dropna().astype(str).unique()) - vocab
        if bad_vocab:
            problems.append(f"{table_name}:{st_col}: outside vocabulary {sorted(bad_vocab)}")
        if st.isna().any():
            problems.append(f"{table_name}:{st_col}: null status")
        ok = (st == "ok").to_numpy()
        isnull = np.isnan(v)
        if (ok & isnull).any():
            problems.append(f"{table_name}:{col}: {int((ok & isnull).sum())} bare null(s)")
        if (~ok & ~isnull).any():
            problems.append(f"{table_name}:{col}: {int((~ok & ~isnull).sum())} value(s) with a failure status")
        if not np.isfinite(v[~isnull]).all():
            problems.append(f"{table_name}:{col}: non-finite values")
        # never fewer nulls than the atomic input: nothing was imputed
        src = spec["source_feature"]
        src_null = atomic_by_key.loc[table[key].astype(str), src].to_numpy(dtype="float64", na_value=np.nan)
        src_null = np.isnan(src_null)
        if (src_null & ~isnull).any():
            problems.append(f"{table_name}:{col}: value where the atomic input is null (imputation)")
        # atomic status preserved where the atomic input failed
        src_st = atomic_by_key.loc[table[key].astype(str), STATUS_COLUMN_OF[src]].to_numpy()
        failed = src_st != "ok"
        if (st.to_numpy()[failed] != src_st[failed]).any():
            problems.append(f"{table_name}:{col}: atomic failure status not propagated verbatim")
        tr = spec["transform"]
        if tr == "log1p":
            if (v[~isnull] < 0).any():
                problems.append(f"{table_name}:{col}: negative log1p output")
            src_v = atomic_by_key.loc[table[key].astype(str), src].to_numpy(dtype="float64", na_value=np.nan)
            z = ~isnull & (src_v == 0)
            if (v[z] != 0).any():
                problems.append(f"{table_name}:{col}: log1p(0) != 0")
        elif tr == "percentile":
            lo, hi = cfg["transforms"]["percentile"]["range"]
            if ((v[~isnull] < lo) | (v[~isnull] > hi)).any():
                problems.append(f"{table_name}:{col}: percentile outside [{lo}, {hi}]")
            cid_col = spec.get("cohort_id_column")
            cids = set(table[cid_col].astype(str)) if cid_col else {spec["cohort_id"]}
            missing = cids - cohort_ids_in_manifest
            if missing:
                problems.append(f"{table_name}:{col}: cohort ids not in manifest {sorted(missing)}")
        elif tr == "local_ratio":
            if (v[~isnull] < 0).any():
                problems.append(f"{table_name}:{col}: negative ratio")
            if "neighborhood_complete" in table.columns:
                inc = ~table["neighborhood_complete"].astype(bool).to_numpy()
                if (~isnull & inc).any():
                    problems.append(f"{table_name}:{col}: value on an incomplete neighborhood")
        if spec.get("disposition") == "publishable" and table_name != cfg["publish"]["publishable_table"]:
            problems.append(f"{table_name}:{col}: publishable column in the wrong table")
        if spec.get("disposition") != "publishable" and table_name == cfg["publish"]["publishable_table"]:
            problems.append(f"{table_name}:{col}: non-publishable column in the publishable table")
    report["passed"] = not problems
    return report
