# Gate 2 MVP Decision — provisional H3 resolution

_Status: **complete, provisional selection recorded.** Owner-approved scope reduction dated 2026-09-14. This document is the decision record `config/spatial.yaml` `spatial_unit.decision_record` points to. Measured artifacts: `data/gate2/mvp_run_20260914T150714Z/` (immutable, every output checksummed in `SHA256SUMS`)._

## 1. Owner override — what changed and why

The owner reduced Gate 2 from the research-grade spatial-unit study specified in [`spatial_unit_decision.md`](spatial_unit_decision.md) and the 805-line remediation in [`gate2_remediation_design.md`](gate2_remediation_design.md) to a lean MVP resolution decision. The constraints the owner supplied, recorded verbatim in intent:

1. **H3 is the owner-approved provisional spatial-unit family for the MVP.** Gate 2 no longer needs to prove H3 superior to square grids or administrative units.
2. **Gate 2 now evaluates resolution only:** which of H3 r8, r9, r10 the MVP uses.
3. **This is an MVP engineering decision, not a claim that H3 or the chosen resolution is optimal for every location in Vietnam.**
4. **The square/administrative comparison is deferred** until after the atomic-feature MVP, preferably Gate 6, together with origin-shift, jitter, alternate-source sensitivity, semantic mixing, neighbourhood representation, MAUP, the Pareto/feasibility machinery, the 82-figure visualisation contract, and the run state machine.
5. **Full nationwide validation remains Gate 6.**
6. **The previous full run `run_20260914T091321Z` is diagnostic only**, because two of its raster clips were truncated at tile boundaries (§ 3). Its metric tables are left on disk unchanged and are not used for this decision.
7. **Time-to-MVP is prioritised over research-grade completeness.**

Nothing in this document invents a budget, latency target, or business requirement; none was provided. `docs/architecture.md` is unchanged.

## 2. Decision boundary of this run

| | |
|---|---|
| Question | Which provisional H3 resolution does the MVP use: r8, r9 or r10? |
| Family | H3 v4 only (`h3` 4.5.0). No square, area-control, origin-shift, administrative or r7 candidate was generated. |
| Test geography | The four representative AOIs defined in `config/spatial.yaml`: `hanoi_core` (dense urban, 6×6 km), `hoi_an` (tourism/coastal, 12×12 km), `mu_cang_chai` (rural mountain, 15×15 km), `dong_thap_rural` (rural delta, 15×15 km). The other four AOIs are deferred validation contexts. |
| Sources | Identical per-AOI clipped snapshots as Gate 1/2 (OSM Geofabrik `vietnam-260913`, WorldPop 2025 constrained 100 m, ESA WorldCover 2021 v200, GHS-BUILT-S E2020 R2023A), re-acquired for these four AOIs with the fixed multi-tile clip: manifest `data/manifests/source_manifest_20260914T102150Z.json`. |
| Rule | The pre-registered too-coarse rule, unchanged, restricted to three anchors (§ 4). |
| Config | `config/gate2_mvp.yaml`; config hash `fc94f522ab8c50dd…` over it and `config/spatial.yaml` as they were at run time (updating the run pointer in `spatial.yaml` afterwards changed that hash — expected). |
| Code | `59fe994+dirty` — the Gate 2 code is still uncommitted; the tree state is labelled, not implied away. |
| Environment | Apple arm64, 8 logical CPUs, 16 GB, macOS 15.6, Python 3.12.13, GeoPandas 1.1.4, Shapely 2.1.2, rasterio 1.5.1, h3 4.5.0, GDAL 3.13.3. |

## 3. Acquisition defects fixed before measuring

Both defects named in the remediation design (F3a, F3b) were confirmed by inspection and fixed in `src/ingestion/acquire_gate2.py`:

| AOI | product | defect in `run_20260914T091321Z` | fix |
|---|---|---|---|
| `hanoi_core` | ESA WorldCover | halo spans 20.9689–21.0871 N; only `N21E105` (the tile under the centre) was clipped, so the bottom 374 rows (3.4 km) of the 1,511×1,420 window were NoData | VRT mosaic of `N18E105` + `N21E105`, then `gdal_translate -projwin`; the clip is 1,511×1,420 with **0** NoData pixels |
| `mu_cang_chai` | GHS-BUILT-S | halo spans x = 9,955,082–9,984,184 m Mollweide across the `R7_C28`/`R7_C29` seam at 9,959,000; only `C29` was clipped, so the 40 westernmost columns (9,640 pixels) were NoData | VRT mosaic of `R7_C28` + `R7_C29`; the clip is 292×241 with **0** NoData pixels |

Tiles are now selected from the halo **extent** (`worldcover_tiles_for_bbox`, `ghsl_tiles_for_bbox`), never from the centre. The mosaic is a VRT over tiles that share one global grid, followed by a windowed clip — no resampling, no reprojection; pixel size and grid alignment are preserved. Every clip now carries a coverage proof in its sidecar and in `source_coverage.parquet` (`window_inside_tile_union`, `source_tiles`): every required tile is present, the requested window lies inside the union of the source tile extents, the clip opens with the source CRS/NoData, and the clip's own bounds cover the window to within one pixel. A clip that fails any of these raises `TileCoverageError` before it is recorded. Tests: `tests/test_gate2_tile_coverage.py` (13 tests, including one that reproduces the exact single-tile failure and asserts it is refused).

The two clips were regenerated at identical dimensions, so the difference is purely the previously-missing pixels. The other two MVP AOIs were served by a single tile each and their clips are byte-for-byte reproductions.

Independent review found one further provenance defect in the first MVP run (`mvp_run_20260914T102642Z`): when the source index referenced both the original and partial re-acquisition manifests, `_load_acquisition_manifest` kept the first entry for a repeated derived `source_id`. Its metric inputs were the corrected files, but two `source_coverage.parquet` rows carried the old one-tile checksums. The loader now treats each AOI's own manifest as authoritative, rejects a named source missing from that manifest, and has regression tests. The final decision run is therefore `mvp_run_20260914T150714Z`; its Hanoi WorldCover and Mù Cang Chải GHS-BUILT-S coverage checksums match both the source index and the actual corrected files. Its coverage artifact also records both source-union containment and produced-clip containment, plus the full-NoData edge-band diagnostic (zero on every raster edge in all four AOIs). Superseded runs remain unchanged on disk.

## 4. The MVP resolution rule (applied mechanically)

For every resolution × AOI and each of three anchors on a 1 km support — `poi_count_1km`, `population_1km`, `road_length_1km_m` — sample five deterministic interior points in each of 400 seeded cells, take the median within-cell range, and divide by the between-cell IQR of the same anchor at every cell's representative point. An anchor **triggers** when the ratio exceeds **0.25**; a resolution is **rejected in a context** when **≥ 2** anchors trigger; it **passes** only if rejected in no MVP AOI and measured in all four. Both thresholds are the pre-registered values in `config/gate2.yaml` / `config/spatial.yaml`; no threshold was added (`tests/test_gate2_mvp.py::test_the_rule_uses_no_threshold_beyond_the_pre_registered_ones`). `builtup_fraction_1km` was dropped from the anchor set by the owner's scope reduction, not because it measured anything wrong.

Selection order (owner-stated, `config/gate2_mvp.yaml: selection`):

1. if **r9** passes in all four AOIs → select r9;
2. else if **r10** passes → select r10;
3. **r8** only if it passes all four AOIs, is cheaper than r9 on projected nationwide unit count and storage, and shows no greater within-cell loss than r9 ("materially greater" is evaluated as "greater"; the comparison values are recorded so a reviewer can see how close it was rather than a new tolerance being introduced);
4. otherwise **NO DECISION** and Gate 3 does not start.

Implementation: `src/spatial/mvp_decision.py` (`coarse_table`, `select_resolution`), pure functions of the measured tables, tested on synthetic inputs for each branch.

## 5. Result

**h3_r9 passes in all four AOIs → selection rule 1 fired → `h3_r9` selected, status `provisional_mvp`.**

Anchors triggered (reject at ≥ 2):

| resolution | dong_thap_rural | hanoi_core | hoi_an | mu_cang_chai | verdict |
|---|---:|---:|---:|---:|---|
| h3_r8 | **2** | **3** | **3** | **2** | FAIL (rejected in all four) |
| h3_r9 | 0 | 0 | 0 | 1 | **PASS** |
| h3_r10 | 0 | 0 | 0 | 1 | PASS |

Loss ratios (median within-cell range / between-cell IQR; bold = triggered):

| resolution | AOI | POI 1 km | population 1 km | road length 1 km |
|---|---|---:|---:|---:|
| h3_r8 | dong_thap_rural | 0.000 | **0.436** | **0.482** |
| h3_r9 | dong_thap_rural | 0.000 | 0.169 | 0.209 |
| h3_r10 | dong_thap_rural | 0.000 | 0.050 | 0.078 |
| h3_r8 | hanoi_core | **0.305** | **0.276** | **0.405** |
| h3_r9 | hanoi_core | 0.152 | 0.122 | 0.197 |
| h3_r10 | hanoi_core | 0.049 | 0.042 | 0.078 |
| h3_r8 | hoi_an | **0.267** | **0.428** | **0.479** |
| h3_r9 | hoi_an | 0.105 | 0.187 | 0.219 |
| h3_r10 | hoi_an | 0.053 | 0.075 | 0.077 |
| h3_r8 | mu_cang_chai | **1.179** | 0.083 | **0.254** |
| h3_r9 | mu_cang_chai | **0.925** | 0.033 | 0.089 |
| h3_r10 | mu_cang_chai | **0.450** | 0.012 | 0.031 |

Rule 3 inputs, recorded although rule 1 fired: r9/r8 projected unit ratio 6.66, storage ratio 4.68 (r8 is cheaper); median loss ratio r8 0.355 vs r9 0.160 (r8's loss is greater), so r8 would not have qualified under rule 3 even had rules 1 and 2 not fired.

This agrees with the diagnostic full run, in which r9 and r10 survived the four-anchor gate in every one of eight contexts and r8 was rejected in all of them.

## 6. Measured metrics (3 resolutions × 4 AOIs = 12 pairs, all complete)

### 6.1 Actual cell area and unit count

Median actual area (km², polygon area in the AOI's UTM zone) and cells intersecting the AOI. p05/p95 are within ±0.1 % of the median in every AOI (H3 area varies negligibly across a 15 km window); full quantiles are in `candidate_metrics.parquet`.

| resolution | nominal km² | dong_thap_rural | hanoi_core | hoi_an | mu_cang_chai | actual/nominal |
|---|---:|---:|---:|---:|---:|---:|
| h3_r8 | 0.7373 | 0.8506 (302) | 0.8043 (61) | 0.8182 (209) | 0.8087 (321) | 1.09–1.15 |
| h3_r9 | 0.1053 | 0.1215 (1,955) | 0.1149 (356) | 0.1169 (1,317) | 0.1155 (2,053) | 1.09–1.15 |
| h3_r10 | 0.01505 | 0.0174 (13,233) | 0.0164 (2,303) | 0.0167 (8,849) | 0.0165 (13,907) | 1.09–1.15 |

Vietnamese cells are 9–15 % larger than the published global averages, uniformly across resolutions and varying by latitude (largest at Đồng Tháp, 10.5 N). Any density feature must divide by measured area, never nominal.

### 6.2 Nationwide projections — labelled as projections

Extrapolated from each AOI's effective land area per land-intersecting cell to 331,212 km² (GSO national area), and from each AOI's Parquet bytes per cell. Ranges are across the four AOIs; medians drive the rule-3 comparison.

| resolution | projected cells (M) | projected storage, geometry (GB) | projected storage, features (GB) | projected total (GB) |
|---|---:|---:|---:|---:|
| h3_r8 | 0.41–0.50 | 0.04–0.11 | 0.03–0.10 | 0.07–0.21 |
| h3_r9 | 2.87–3.41 | 0.19–0.28 | 0.16–0.31 | 0.35–0.59 |
| h3_r10 | 19.8–22.3 | 1.25–1.45 | 0.94–1.53 | 2.20–2.98 |

These are **projections from ~600 km² of AOI to the whole country**, with rural and urban contexts weighted equally; they bound the order of magnitude, not the value. The feature bytes are for the seven diagnostic columns written here, not for the Gate 3 feature vector.

### 6.3 Sparsity (every zero is a mapped zero from a successfully ingested source)

| resolution | POI = 0, footprint | POI = 0, 1 km support | population = 0 | median population | road length = 0 | median road length (m) |
|---|---|---|---|---|---|---|
| h3_r8 | 0.05 / 0.55 / 0.83 / 0.96 | 0.00 / 0.14 / 0.33 / 0.48 | 0.02 / 0.14 / 0.01 / 0.18 | 15,610 / 573 / 463 / 6.5 | 0.02 / 0.15 / 0.06 / 0.50 | 19,203 / 5,331 / 2,770 / 17 |
| h3_r9 | 0.23 / 0.81 / 0.95 / 0.99 | 0.00 / 0.12 / 0.31 / 0.48 | 0.10 / 0.19 / 0.07 / 0.58 | 2,462 / 44 / 44 / 0 | 0.10 / 0.25 / 0.31 / 0.69 | 2,835 / 652 / 357 / 0 |
| h3_r10 | 0.48 / 0.93 / 0.99 / 1.00 | 0.00 / 0.12 / 0.31 / 0.46 | 0.18 / 0.31 / 0.18 / 0.83 | 293 / 2.7 / 3.9 / 0 | 0.19 / 0.45 / 0.62 / 0.84 | 367 / 51 / 0 / 0 |

Order within each cell: hanoi_core / hoi_an / dong_thap_rural / mu_cang_chai. POI sparsity on a 1 km support is nearly identical across resolutions in every AOI — it is a property of the location, not of the cell footprint — which is why the storage/index unit and the feature support remain separate concepts for Gate 3. At r9 in Mù Cang Chải the median cell holds no population pixel and no road; at r10 that is also true in Đồng Tháp for roads.

### 6.4 Engineering

| resolution | runtime, 4 AOIs (s) | peak RSS (GB) | single lookup p50 / p95 (µs) | batch lookup p50 (µs/query) | lookup correctness failures | non-deterministic repeats |
|---|---:|---:|---:|---:|---:|---:|
| h3_r8 | 1.7 | 0.71 | 1.85 / 2.06 | 0.57 | 0 of 8,000 interior + 7,932 boundary | 0 |
| h3_r9 | 2.3 | 0.71 | 1.92 / 2.12 | 0.61 | 0 of 8,000 + 9,600 | 0 |
| h3_r10 | 6.0 | 0.71 | 1.92 / 2.10 | 0.64 | 0 of 8,000 + 9,600 | 0 |

Runtime is generation + point assignment + road clipping + zonal statistics + anchor sampling + neighbour construction + within-cell loss + storage write + lookup benchmark, per `benchmark_runs.parquet`. Lookup latency is resolution-independent (H3 indexes lat/lon directly). Population conservation error is 0.0 for all 12 pairs; raster processing coverage is 1.000 for all 12 source rows.

## 7. What is written to `config/spatial.yaml`

```yaml
spatial_unit:
  method: h3
  h3_resolution: 9
  decision_status: provisional_mvp
  nationwide_validation_pending: true
  full_family_comparison_deferred: true
  decision_record: docs/gate2_mvp_decision.md
```

plus a `gate2_mvp` block naming the run, config, manifest, AOIs, candidates, verdicts and the deferred items. The historical `gate2_experiment` block is retained with status `executed_no_decision_diagnostic_only` and its two known clip defects listed. `config/gate2.yaml` (the full experiment design) is unchanged.

## 8. Limitations — read before treating r9 as settled

1. **Four contexts, not eight, and not the nation.** `hcmc_core`, `thu_duc_east`, `binh_duong_industrial`, `phu_quoc_coast` were not measured here. In the diagnostic full run r9 also passed in those four, but that run's evidence is not relied on.
2. **Resolution only.** No square-grid or administrative candidate ran. Nothing here says a hexagon is better than a square of matched area; the diagnostic run found matched-area squares slightly better on within-unit loss and storage and H3 better on circular-buffer fidelity and single-point lookup — all deferred.
3. **Three anchors.** `builtup_fraction_1km` is not in the rule. With four anchors the diagnostic run reached the same r8/r9/r10 verdicts.
4. **The POI anchor is unstable in the rural mountain context.** It triggers for r9 (0.93) and r10 (0.45) in Mù Cang Chải and reads 0.000 in Đồng Tháp: with very few mapped POIs the between-cell IQR is tiny (or the within-cell range is), so the ratio is dominated by a handful of cells. A single anchor cannot reject, so this does not change the verdict, but it is the anchor to watch in Gate 6.
5. **No robustness or sensitivity evidence.** Jitter, origin shift (structurally n/a for H3), alternate population/built-up sources and perturbation of the 25 % threshold were not run. The verdict margin for r9 is comfortable (its largest non-POI ratio is 0.219 against the 0.25 threshold) but that is an observation, not a sensitivity test.
6. **Sampled, discretised loss.** 400 cells × 5 interior points per resolution × AOI; anchor fields on a 100 m reference grid with a 1 km disk kernel (~1 % area error). Identical for every resolution, so it cannot bias one against another, but it bounds precision.
7. **Nationwide numbers are projections** (§ 6.2), and storage bytes are for diagnostic columns, not the Gate 3 feature vector.
8. **Land is ESA WorldCover minus classes 0 and 80**, not an authoritative coastline; Hội An's land-intersecting count inherits that.
9. **Code is uncommitted.** Every artifact records `59fe994+dirty`.

## 9. Deferred research (explicit, not omitted by accident)

Square-grid family and matched-area controls (at measured Vietnamese H3 areas: sides 131/347/918 m); administrative family (blocked on a qualifying post-2025 commune package, [`gate2_admin_qualification.md`](gate2_admin_qualification.md)); H3 r7; origin-shift and jitter robustness; alternate population (GHS-POP, WorldPop 2020) and built-up (WorldCover class 50) sensitivity; semantic mixing, neighbourhood representation, MAUP; the too-fine gate; Pareto/feasibility selection and budget breakpoints; the visualisation contract; the run state machine and code-snapshot reproducibility framework; nationwide validation of the r9 choice across all eight AOIs and beyond (Gate 6).

## 10. Reproduction

```bash
# 1. Re-acquire the four MVP AOIs (offline if the national tiles are present; multi-tile mosaics)
.venv/bin/python -m src.ingestion.acquire_gate2 --aoi hanoi_core --aoi hoi_an --aoi mu_cang_chai --aoi dong_thap_rural

# 2. The MVP run (≈ 30 s on the hardware above); writes data/gate2/mvp_run_<run_id>/
.venv/bin/python -m src.spatial.run_gate2_mvp

# 3. Verify a run directory
( cd data/gate2/mvp_run_20260914T150714Z && shasum -a 256 -c SHA256SUMS )

# 4. Tests
.venv/bin/python -m pytest tests/ -v
```

`config/spatial.yaml` is never written by the runner; the selection in § 7 was recorded by hand from `decision.json`, and `tests/test_gate2_mvp.py::test_recorded_selection_follows_the_stated_rule` recomputes the verdicts from the measured tables and checks both agree.
