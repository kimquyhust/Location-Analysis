# Normalization module (Gate 4)

Contextual transforms of the Gate 3 atomic features. The contract is
`config/gate4_mvp.yaml` (`normalization_version`), separate from the atomic
contract in `config/features.yaml` (`feature_set_version`, unchanged).
Report: `docs/gate4_normalization_report.md`.

| file | responsibility |
|---|---|
| `transforms.py` | pure functions, no I/O, inputs never mutated: `log1p_transform`; `fit_ecdf` / `apply_ecdf` (percentile from a persisted ECDF table; `midrank_ecdf`, `min_ecdf`, `max_ecdf`); `neighborhoods` + `local_ratio` (k-ring ratio, no epsilon); `aoi_equal_weights`; `peer_groups_are_sufficient`; `skewness` |
| `schema.py` | `validate_config` (Gate 4 config vs the atomic contract, before anything runs); output column naming; `validate_outputs` (keys = Gate 3, no bare null, finite, ranges, status vocabulary, statuses propagated verbatim, missingness ≥ atomic, cohort ids in manifest, forbidden columns, disposition ↔ table) |
| `run_gate4_mvp.py` | verifies the pinned Gate 3 input (run id, version, SHA-256s, its `SHA256SUMS`), fits cohorts, applies transforms, measures sensitivities, writes one immutable `data/gate4/run_<UTC>/` |

Rules every transform follows:

- a non-`ok` atomic status is copied verbatim and the value stays null; nothing is imputed, clipped or winsorized;
- transform-specific failures use the vocabulary in the config (`cohort_too_small`, `cohort_degenerate`, `cohort_not_fitted`, `peer_cohort_insufficient`, `neighborhood_incomplete`, `neighborhood_insufficient_valid`, `neighborhood_reference_zero`, `source_not_acquired`);
- fit and apply are separate; `apply_ecdf` reads only `cohort_statistics.parquet`;
- publish/diagnostic disposition comes from the pre-registered rules in the config, never from looking at the output;
- no `national_percentile`, no peer percentile with fewer than `minimum_aois_per_peer_group` AOIs per context, no custom urban/rural class in place of GHS-SMOD;
- no scores, no weights, no customer/trip/mobility data.

Artifacts per run: `contextual_features.parquet` (publishable columns only),
`diagnostic_features.parquet`, `cohort_statistics.parquet`,
`normalization_manifest.json`, `validation_summary.json`,
`benchmark_runs.parquet`, `run_manifest.json`, `SHA256SUMS`. Both tables
join 1:1 to `atomic_features.parquet` on `spatial_unit_id`.

```bash
.venv/bin/python -m src.normalization.run_gate4_mvp
.venv/bin/python -m src.normalization.run_gate4_mvp --output-root /tmp/check   # determinism check
.venv/bin/python -m pytest tests/test_normalization.py -v
```
