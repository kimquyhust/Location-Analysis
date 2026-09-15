# Feature module (Gate 3 atomic MVP)

- `raster.py` — exact area-weighted pixel aggregation and measured coverage
- `roads.py` — clipped road length, major-road length, shared-node intersections, nearest line
- `poi.py` — buffer counts on `point_on_surface`, richness, nearest distance, industrial intersection, park set
- `compute.py` — `compute_aoi_features`: the contract as a pure function of an `AoiInputs` bundle; semantics from `config/features.yaml`
- `schema.py` — contract columns, status vocabulary, `validate_frame` (numerical invariants are hard checks)
- `provenance.py` — source resolution and checksum verification
- `run_gate3_mvp.py` — CLI runner writing one immutable run directory

No normalisation, scores, or customer data. See `docs/feature_dictionary.md` and `docs/gate3_mvp_report.md`.
