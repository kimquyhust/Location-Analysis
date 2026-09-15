# Spatial Unit Decision — Gate 2 Experiment Specification

> **Superseded for the MVP decision on 2026-09-14 by an owner-approved scope reduction — see [`gate2_mvp_decision.md`](gate2_mvp_decision.md).** H3 was selected by the owner as the provisional MVP family and Gate 2 was reduced to a resolution choice (H3 r9, `provisional_mvp`). The specification and measured results below are retained unchanged as the full experiment design and as diagnostics. The run reported here, `run_20260914T091321Z`, is **diagnostic only**: its `hanoi_core` WorldCover clip and `mu_cang_chai` GHS-BUILT-S clip were truncated at tile boundaries (the acquisition clipped only the tile under each halo's centre; fixed in `src/ingestion/acquire_gate2.py`). In particular, the 1.19 % "mountain-terrain NoData" attributed to GHS-BUILT-S in § Completeness below was that truncation, not a source characteristic. The square/administrative comparison and nationwide validation are deferred to Gate 6.

_Status: **experiment executed, decision open — explicit NO DECISION**. `config/spatial.yaml` stays `method: null`. The specification below is unchanged; measured results are in [§ Measured results](#measured-results-run-run_20260914t091321z) at the end. The full independent rationale is in [`gate1_technical_review.md`](gate1_technical_review.md); the administrative-source verdict is in [`gate2_admin_qualification.md`](gate2_admin_qualification.md)._

## Decision boundary

Gate 2 compares current administrative units, square grids, and H3. H3 is not assumed to be best. Administrative geometry may participate only if a licensed post-1-July-2025 nationwide commune/ward/special-zone package passes the qualification checks below. Stale districts are not a substitute.

The storage/index unit and feature support are different concepts. A feature may use the unit footprint, a 1 km buffer, or a 3 km buffer regardless of the key type. Every result must name both.

## Candidates

| Family | Variants | Purpose |
|---|---|---|
| Administrative | Current 3,321 commune-level units, conditional | Interpretability, administrative alignment, and area-variability baseline. |
| Square, operational | 250 m, 500 m, 1,000 m | Common engineering sizes. |
| Square, area controls | 125 m, 325 m, 850 m, 2,270 m | Approximate mean-area controls for H3 r10, r9, r8, and r7 to separate shape from scale. |
| H3 v4 | resolutions 7, 8, 9, 10 | r7/r10 are coarse/fine sentinels; r8/r9 are plausible, not preselected. |

H3 v4 average areas for r7–r10 are approximately 5.1613, 0.7373, 0.1053, and 0.01505 km²; average edge lengths are 1.4065, 0.5314, 0.2008, and 0.07586 km. Actual per-cell areas must be computed and reported. Source: [H3 v4 cell statistics](https://h3geo.org/docs/core-library/restable/).

Square grids use a documented, stable national origin. Metric construction/measurement uses a locally suitable projection per AOI; storage geometry remains EPSG:4326. Origin-shift replicates are part of the sensitivity test.

## Administrative-source qualification

Before the admin candidate is enabled, record:

- provider and authoritative lineage;
- effective/source date on or after 1 July 2025;
- expected 3,321 unit count and official unit codes;
- commercial reuse/redistribution terms;
- bulk access URI, format, byte count, and checksum;
- geometry validity, gaps/overlaps, CRS, and coastal/island treatment.

The current geoBoundaries API is not eligible: it reports Vietnam ADM1 as 2008 and ADM2 as 2020. If no source passes, record the candidate as `blocked` and do not claim a completed three-family comparison.

## Test geography

Use the coordinate-centered AOIs in `config/spatial.yaml`; persist exact GeoJSON and checksums. They cover replicated dense urban and tourism contexts plus suburban, rural delta, rural mountain, and industrial settings. Every enabled candidate uses every AOI and identical clipped source snapshots.

## Metrics

1. **Unit count:** full, land-intersecting, and nationwide projected units.
2. **Unit area:** actual area min/p05/median/mean/p95/max, coefficient of variation, and effective land area.
3. **POI sparsity:** mapped-zero proportion by leaf category and total, for footprint and 1 km buffer; source status is separate.
4. **Population sparsity:** zero-count share and p10/median population per unit.
5. **Road sparsity:** zero road-length share and zero-intersection share.
6. **Semantic mixing:** land-cover entropy, dominant-class share, and within-unit built-up variance.
7. **Within-unit location loss:** compute anchor features at centroid plus stratified interior points; compare within-unit range with between-unit IQR.
8. **Neighborhood representation:** neighbor-degree distribution and the area/Jaccard error of grid-ring approximations to 1 km and 3 km circles.
9. **Boundary sensitivity:** square-origin shifts, point jitter, assignment changes, and feature rank stability.
10. **MAUP stability:** adjacent-resolution Spearman rank, median absolute percent change, and top-decile membership stability.
11. **Computation:** wall time and peak RSS by generation, point assignment, road clipping, raster zonal stats, POI buffer aggregation, and neighbor construction.
12. **Storage:** Parquet geometry/features bytes, bytes per unit, and nationwide projections.
13. **Lookup:** correctness on boundary/coastal cases and p50/p95 single/batch latency for 10,000 lat/lon queries; admin reverse lookup is timed separately.

## Required outputs

- `candidate_inventory.parquet`
- `candidate_metrics.parquet`
- `benchmark_runs.parquet`
- `lookup_benchmark.parquet`
- `source_coverage.parquet`
- `decision_matrix.md`
- Faceted maps for unit boundaries, sparsity, semantic mixing, within-unit loss, and grid-origin sensitivity
- Plots for sparsity/mixing/representation error vs area and unit count vs storage/runtime

Each benchmark row includes AOI, candidate, source release, config hash, code commit, hardware/software versions, row counts, wall time, peak RSS, and bytes.

## Acceptance rules

1. **Completeness:** all required candidate × AOI metrics exist. Raster processing coverage is at least 99.9% of expected valid pixels and vector ingest has no technical failures. Mapped absence remains a zero with a source caveat.
2. **Current admin:** the administrative candidate runs only after all qualification checks pass.
3. **Too coarse:** reject a candidate in a context when at least two anchor features have a median within-unit sample-point range greater than 25% of their between-unit IQR. Also flag a candidate whose dominant land-cover share degrades against both adjacent finer scales without material feasibility benefit.
4. **Too fine:** reject a finer candidate if it costs over 2× the next coarser candidate while improving both semantic-mixing and location-loss errors by less than 5%, or when more than 80% of neighbor pairs have indistinguishable anchor vectors within declared tolerance.
5. **Robustness:** a selected candidate may not reverse rank in more than one context under origin shifts, point jitter, or alternate population/built-up source sensitivity.
6. **Feasibility:** evaluate against a hardware/runtime/storage budget recorded before execution. If the owner provides no budget, report the Pareto frontier rather than inventing one best option.
7. **Selection:** choose only among candidates that pass hard gates and are Pareto-nondominated. Ties go to lower nationwide storage/runtime, then simpler deterministic lat/lon lookup. H3 receives no convenience bonus.

## Gate 2 completion

Gate 2 ends with measured results, a documented selected unit (or an explicit no-decision), a source/parameter sensitivity analysis, and an evidence-backed update to `config/spatial.yaml`. It does not end when candidate geometries have merely been generated.

---

# Measured results (run `run_20260914T091321Z`)

_Executed 2026-09-14. Artifacts: `data/gate2/run_20260914T091321Z/`. Code version `59fe994+dirty` (the tree carried uncommitted Gate 2 work; that is recorded on every benchmark row rather than implied away). Config hash `dde7c4a1b884b8e8` over `config/gate2.yaml` + `config/spatial.yaml`. Hardware: Apple arm64, 8 logical CPUs, 16 GB RAM, macOS 15.6, Python 3.12.13, GeoPandas 1.1.4, Shapely 2.1.2, rasterio 1.5.1, h3 4.5.0._

## Outcome

**NO DECISION.** `config/spatial.yaml` `spatial_unit.method` remains `null`.

Every metric and acceptance rule in this document was implemented and measured. All 88 required candidate × AOI pairs completed, every hard gate that *could* be evaluated was evaluated, and no metric is missing. The decision is nonetheless withheld, for two reasons that are properties of the evidence available rather than of the measurement:

1. **The administrative family is `blocked`** — no qualifying post-1-July-2025 nationwide commune package exists that this project can use. Three sources were tested and all failed; see [`gate2_admin_qualification.md`](gate2_admin_qualification.md). This is therefore a **two-family comparison**, not the three-family comparison the decision boundary calls for.
2. **No feasibility budget exists.** `PROJECT_BRIEF.md` supplies no hardware, runtime, or storage budget, so acceptance rule 6 cannot be evaluated. Per that rule, a Pareto frontier is reported and no single "best" candidate is manufactured.

## Scope actually measured

| | |
|---|---|
| AOIs | **8 / 8** — hanoi_core, hcmc_core, thu_duc_east, dong_thap_rural, mu_cang_chai, binh_duong_industrial, hoi_an, phu_quoc_coast |
| Candidates | **11 / 11** enabled — 7 square (3 operational + 4 area controls), 4 H3 |
| Candidate × AOI pairs | **88 / 88** |
| Units generated and measured | **186,761** |
| Administrative candidate | **blocked**, 0 units |

## Sources

Identical clipped snapshots per AOI, shared by every candidate. Acquisition manifest `data/manifests/source_manifest_20260914T083224Z.json` (`status: complete`, 46 entries: 11 national assets + 35 per-AOI derived subsets, each with parent checksum and exact transform).

| Role | Product | Release | Licence | CRS at use |
|---|---|---|---|---|
| POI + roads | Geofabrik Vietnam OSM PBF | `vietnam-260913` | ODbL-1.0 | EPSG:4326 |
| Population | WorldPop Global 2 R2025A v1, 100 m constrained count | 2025 | CC-BY-4.0 | EPSG:4326 |
| Land cover | ESA WorldCover 10 m | `2021_v200` (6 tiles) | CC-BY-4.0 | EPSG:4326 |
| Built-up | GHS-BUILT-S R2023A 100 m | `E2020` (3 tiles) | CC-BY-4.0 | ESRI:54009 |

Roads are **OSM only**. Overture Transportation was not used and the two networks were never unioned — the Gate 1 decision stands and nothing measured here overturns it. No raster was resampled or reprojected at any point: units are reprojected onto each raster's native grid instead, so published pixel values reach the metrics unaltered.

## Completeness and correctness

| Check | Required | Measured |
|---|---|---|
| Candidate × AOI pairs present | 88 | **88** |
| Raster processing coverage | ≥ 0.999 | **1.000** (population, land cover, built-up; all 8 AOIs) |
| Zonal processing coverage | ≥ 0.999 | **1.000** (all 88 pairs) |
| Vector ingest failures | 0 | **0** |
| Population count conservation | exact | **0.0 relative error**, all 88 pairs |
| Lookup correctness, interior points | 0 failures | **0** |
| Lookup correctness, on-boundary points | 0 failures | **0** |
| Lookup determinism | 0 errors | **0** |

`processing_coverage` counts **publisher-valid** pixels, not window pixels. GHS-BUILT-S is NoData over up to **1.19%** of in-unit pixels in Mù Cang Chải's mountain terrain; that is reported separately as `builtup_nodata_share_in_units` and is a source characteristic, not unprocessed data. Mapped zeros carry `source_status: ingested_ok` and are real measurements of mapped absence throughout.

## Headline table — median across the 8 AOIs

Ordered by measured area. `act/nom` is measured median area over the candidate's nominal area.

| candidate | area km² | act/nom | nat. units (M) | nat. GB | POI=0 (footprint) | POI=0 (1 km) | pop=0 | road=0 | LC entropy | dominant LC | built-up var | loss (POI) | ring-1 km J | ring-3 km J | jitter | origin flip | indist. | runtime s | lookup 1 (µs) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| square_125m | 0.0156 | 1.000 | 21.90 | 2.606 | 0.942 | 0.180 | 0.186 | 0.421 | 0.407 | 0.923 | 0.0002 | 0.016 | 0.841 | 0.841 | 0.126 | **0.0002** | 0.219 | 12.6 | 12.0 |
| h3_r10 | 0.0172 | **1.143** | 19.96 | 2.892 | 0.940 | 0.181 | 0.179 | 0.419 | 0.409 | 0.921 | 0.0001 | 0.047 | **0.898** | **0.926** | 0.117 | n/a | 0.226 | 11.5 | **1.9** |
| square_250m | 0.0625 | 1.000 | 5.56 | 0.788 | 0.872 | 0.180 | 0.115 | 0.252 | 0.668 | 0.850 | 0.0020 | 0.062 | 0.835 | 0.835 | 0.122 | 0.0006 | 0.069 | 6.0 | 12.0 |
| square_325m | 0.1056 | 1.000 | 3.32 | 0.501 | 0.841 | 0.181 | 0.094 | 0.198 | 0.779 | 0.823 | 0.0037 | 0.086 | 0.795 | 0.841 | 0.124 | 0.0011 | 0.037 | 4.8 | 11.9 |
| h3_r9 | 0.1204 | **1.143** | 2.90 | 0.525 | 0.827 | 0.184 | 0.083 | 0.198 | 0.771 | 0.819 | 0.0039 | 0.115 | 0.740 | **0.908** | 0.119 | n/a | 0.037 | 5.0 | **1.9** |
| square_500m | 0.2500 | 1.000 | 1.42 | 0.242 | 0.749 | 0.187 | 0.051 | 0.131 | 0.897 | 0.786 | 0.0078 | 0.128 | 0.733 | 0.841 | 0.121 | 0.0024 | 0.013 | 4.0 | 12.0 |
| square_850m | 0.7225 | 1.000 | 0.50 | 0.113 | 0.623 | 0.216 | 0.005 | 0.054 | 1.157 | 0.698 | 0.0104 | 0.265 | 0.460 | 0.818 | 0.123 | 0.0060 | 0.003 | 3.8 | 12.0 |
| h3_r8 | 0.8427 | **1.143** | 0.42 | 0.112 | 0.599 | 0.190 | 0.013 | 0.041 | 1.161 | 0.708 | 0.0109 | 0.306 | 0.528 | **0.895** | 0.114 | n/a | 0.002 | 3.6 | **1.9** |
| square_1000m | 1.0000 | 1.000 | 0.36 | 0.094 | 0.568 | 0.204 | 0.004 | 0.033 | 1.239 | 0.662 | 0.0115 | 0.310 | 0.338 | 0.795 | 0.124 | 0.0083 | 0.001 | 3.4 | 11.9 |
| square_2270m | 5.1529 | 1.000 | 0.071 | 0.052 | 0.293 | 0.213 | 0.000 | 0.000 | 1.390 | 0.619 | 0.0150 | 0.739 | 0.294 | 0.601 | 0.119 | 0.0359 | 0.000 | 3.0 | 11.9 |
| h3_r7 | 5.8989 | **1.143** | 0.062 | 0.047 | 0.268 | 0.190 | 0.000 | 0.000 | 1.489 | 0.616 | 0.0149 | 0.829 | 0.294 | 0.675 | 0.117 | n/a | 0.093 | 3.1 | **1.9** |

The four **anchor features** (`poi_count_1km`, `population_1km`, `road_length_1km_m`, `builtup_fraction_1km`, defined in `config/gate2.yaml`) are **diagnostic instruments for this experiment, not Gate 3 features**. They exist to make within-unit loss, MAUP stability, and neighbour distinguishability measurable at an arbitrary point, and they are deliberately **not** added to `docs/feature_dictionary.md`: doing so would commit the feature layer to definitions Gate 3 has not designed and this gate never validated.

`loss` is `within_unit_range_over_between_unit_iqr` for the `poi_count_1km` anchor; `indist.` is the share of adjacent unit pairs whose anchor vectors are indistinguishable within a 5% relative tolerance. `origin flip` is the share of point pairs whose same-unit relation changes under a half-cell origin shift. **n/a is not a pass** — see below. Peak RSS was 0.60–0.68 GB for every candidate; it did not discriminate between them.

## Finding 1 — H3 cells in Vietnam are 14.3% larger than the published global averages

Measured actual area over nominal is **1.1430** for r10, r9, and r8 and **1.1429** for r7, with a within-AOI coefficient of variation of ~0.0003. The deviation is uniform across resolutions because H3 subdivision preserves the local distortion, and it is not a projection artefact (UTM scale distortion at these latitudes is ~0.08%, in the opposite direction).

This has a direct consequence for this experiment's own design. The square **area controls were sized against the published global H3 averages** (125 m for r10, 325 m for r9, 850 m for r8, 2,270 m for r7) and are therefore **~12.5–14.3% smaller in area than the H3 cells they were meant to control for**. The shape-versus-scale separation still works — `square_325m` at 0.1056 km² against `h3_r9` at 0.1204 km² is a close pairing — but every square-versus-H3 comparison below carries a systematic scale offset in the square's favour, and is read with that in mind rather than as a clean matched-area result. This is exactly the failure mode the instruction to measure actual areas rather than trust nominal ones exists to catch.

## Finding 2 — the too-coarse gate is decided by the rural and tourism contexts

A candidate passes only if it is rejected in **no** context. Anchor features triggered (rejection at ≥ 2):

| candidate | binh_duong | dong_thap | hanoi | hcmc | hoi_an | mu_cang_chai | phu_quoc | thu_duc |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| square_125m | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 |
| h3_r10 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 |
| square_250m | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 |
| square_325m | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 |
| h3_r9 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 |
| square_500m | 0 | 0 | 0 | 0 | **3** | 1 | 0 | 0 |
| square_850m | **4** | **3** | **3** | **2** | **3** | 1 | 0 | **2** |
| h3_r8 | **4** | **3** | **4** | **4** | **4** | **2** | **2** | **4** |
| square_1000m | **4** | **3** | **4** | **4** | **4** | 1 | 0 | **3** |
| square_2270m | **4** | **4** | **4** | **4** | **4** | **3** | **4** | **4** |
| h3_r7 | **4** | **4** | **4** | **4** | **4** | **3** | **4** | **4** |

**Survivors across all eight contexts: `square_125m`, `h3_r10`, `square_250m`, `square_325m`, `h3_r9`.**

Two context-specific results matter more than the aggregate. `square_500m` passes in seven contexts and fails only in **hoi_an**, where coastline and dense tourism attractions put three anchors over threshold — a single tourism AOI is what disqualifies the most conventional operational size. And `phu_quoc_coast` rejects only the two coarsest candidates, because so much of its area is water that between-unit IQR is wide and within-unit range is comparatively small; that is a property of a mostly-empty AOI, not evidence that coarse units work well there.

## Finding 3 — sparsity is context-dependent by an order of magnitude

Share of units with zero mapped OSM POIs, unit footprint:

| candidate | hcmc | hanoi | thu_duc | hoi_an | phu_quoc | binh_duong | dong_thap | mu_cang_chai |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| square_125m | 0.407 | 0.487 | 0.841 | 0.931 | 0.954 | 0.986 | 0.990 | **0.999** |
| h3_r9 | 0.118 | 0.230 | 0.469 | 0.806 | 0.849 | 0.931 | 0.954 | 0.993 |
| square_1000m | 0.000 | 0.000 | 0.059 | 0.491 | 0.645 | 0.722 | 0.820 | 0.957 |
| h3_r7 | 0.000 | 0.000 | 0.026 | 0.184 | 0.417 | 0.351 | 0.500 | 0.860 |

Every one of these is a **mapped zero** from a successfully ingested source, never a missing input. At 125 m in Mù Cang Chải, 99.9% of units contain no mapped POI at all. Widening to the 1 km buffer collapses the spread almost entirely (0.18–0.22 across every candidate and context), which is the clearest single result in this run: **POI sparsity at fine resolutions is a property of the unit footprint, not of the location** — a feature computed on a 1 km support is nearly insensitive to which of these eleven units it is keyed to. This is why the storage/index unit and the feature support must stay separate concepts.

## Finding 4 — where each family actually wins

At matched nominal scale, on the three axes the acceptance rules turn on, the square area controls **dominate** their H3 counterparts:

| pair | nat. storage | within-unit loss | mixing error (1 − dominant LC) |
|---|---|---|---|
| square_125m vs h3_r10 | 2.606 GB vs 2.892 GB | 0.016 vs 0.047 | 0.0767 vs 0.0795 |
| square_325m vs h3_r9 | 0.501 GB vs 0.525 GB | 0.086 vs 0.115 | 0.1774 vs 0.1812 |

Some of that margin is the 14.3% scale offset in Finding 1, and it should not be read as a pure shape effect.

H3 wins decisively and for structural reasons on two other axes:

- **Circular-neighbourhood approximation.** Best ring-versus-circle Jaccard at 3 km: **0.926 / 0.908 / 0.895** for r10/r9/r8 against **0.841 / 0.841 / 0.818** for their square controls. A square ring cannot exceed roughly 0.84 against a circle at any scale; that is a geometric ceiling, and `square_125m` and `square_250m` sit on it at both radii. Every feature defined on a circular buffer inherits this.
- **Lookup latency.** **1.9 µs** single-query against **12.0 µs** for every square candidate. The gap is the WGS84 → national-grid projection a projected square grid necessarily performs; H3 indexes lat/lon directly. Batched, both families are ~0.6 µs per query and the difference disappears.

H3 is also structurally immune to grid-origin choice. **That is recorded as `not_applicable`, not as a pass** — the origin-shift replicate cannot be constructed for H3 at all, so H3 is not scored on it. Among squares the sensitivity is real but small at operational sizes: a half-cell origin shift flips the same-unit relation for 0.018% of point pairs at 125 m, 0.24% at 500 m, and 3.6% at 2,270 m. Point jitter at 10% of cell width moved 11.4–12.6% of assignments for every candidate in both families, discriminating between none of them.

## Finding 5 — MAUP stability degrades toward coarser scales, and faster for H3

Spearman rank correlation of the value a location receives under adjacent resolutions of the same family:

| pair | POI density | population density | top-decile Jaccard |
|---|---:|---:|---:|
| square_125m → square_250m | 0.645 | 0.887 | 0.522 |
| square_250m → square_325m | 0.664 | 0.865 | 0.558 |
| square_325m → square_500m | 0.686 | 0.833 | 0.526 |
| square_500m → square_850m | 0.692 | 0.809 | 0.490 |
| square_850m → square_1000m | 0.748 | 0.841 | 0.460 |
| square_1000m → square_2270m | 0.662 | 0.729 | 0.300 |
| h3_r10 → h3_r9 | 0.526 | 0.851 | 0.466 |
| h3_r9 → h3_r8 | 0.598 | 0.800 | 0.437 |
| h3_r8 → h3_r7 | 0.557 | 0.729 | 0.313 |

Population density is far more scale-stable than POI density everywhere (0.73–0.89 against 0.53–0.75), which is expected of a modelled continuous surface against discrete mapped points. Top-decile membership is never better than ~56% stable between adjacent scales in either family: **which locations rank in the top 10% is substantially an artefact of the chosen resolution**, in both families, at every scale tested. Any downstream feature that thresholds on a top decile must pin the resolution as part of its definition.

## Acceptance rules — results

| Gate | Result |
|---|---|
| 1. Completeness | **PASS.** 88/88 pairs, 1.000 raster and zonal coverage, 0 vector ingest failures. |
| 2. Current admin | **BLOCKED.** No qualifying source; the candidate did not run. See [`gate2_admin_qualification.md`](gate2_admin_qualification.md). |
| 3. Too coarse | **Applied.** Rejects `square_500m` (hoi_an), `square_850m`, `h3_r8`, `square_1000m`, `square_2270m`, `h3_r7` in at least one context. Survivors in all eight: `square_125m`, `h3_r10`, `square_250m`, `square_325m`, `h3_r9`. |
| 4. Too fine | **Applied, no rejections.** No candidate both costs more than 2× the next coarser one and improves both error terms by under 5%; every step improves within-unit loss by 19–66%. Highest indistinguishable-neighbour share is 0.226 (h3_r10), well under the 0.80 ceiling. |
| 5. Robustness | **PASS for all.** No candidate moved more than two rank positions from its median rank in more than one context under origin shift or jitter. |
| 6. Feasibility | **NOT EVALUABLE.** No owner budget. Pareto frontier reported instead, per the rule. |
| 7. Selection | **NOT EXERCISED.** Selection requires gates 2 and 6. |

## Pareto frontier

All ten objectives (lower is better on each): **every candidate is non-dominated.** With ten objectives that is close to guaranteed and is a property of the measurement, not a selection.

Reduced to the three axes the acceptance rules turn on — projected nationwide storage, within-unit location loss, semantic-mixing error — the frontier is:

**`square_125m`, `square_250m`, `square_325m`, `square_500m`, `square_850m`, `square_1000m`, `square_2270m`, `h3_r8`, `h3_r7`**

`h3_r10` and `h3_r9` are dominated **on those three axes only** by `square_125m` and `square_325m` respectively (Finding 4). They are not dominated overall: both are strictly better on circular-neighbourhood approximation and single-query lookup latency, and both survive the too-coarse gate in all eight contexts. Reading the three-axis frontier as a ranking would discard exactly the evidence that separates the families.

**Intersecting the too-coarse survivors with the trade-off surface leaves `square_125m`, `square_250m`, `square_325m`, `h3_r10`, and `h3_r9` as the live region** — roughly 0.015–0.12 km². That is the finding this run supports. It is not a selection.

## Why no method is written to `config/spatial.yaml`

Naming a unit now would require choosing between `square_325m` and `h3_r9` (or their finer counterparts) on grounds the evidence does not supply:

- Whether ~3.3 M national units at 0.50 GB or ~2.9 M at 0.52 GB is affordable is a **budget question with no answer on file**.
- Whether 6× faster single-point lookup matters depends on a **latency requirement `PROJECT_BRIEF.md` does not state**.
- Whether hexagonal circular-buffer fidelity matters depends on **which Gate 3 features use circular supports**, which is not yet decided.
- The **administrative option was never on the table**, so no interpretability trade-off was ever measured against the grids.

Each is an owner input, not a measurement. `spatial_unit.method` stays `null`.

## Limitations of this run

1. **Two families, not three.** The administrative candidate is blocked; no interpretability or administrative-alignment evidence exists.
2. **Area controls are ~14% off** their intended H3 match (Finding 1). Re-running the controls at the measured Vietnamese H3 areas — square sides of **131 m (r10), 347 m (r9), 918 m (r8), 2,429 m (r7)** — would sharpen every square-versus-H3 comparison.
3. **Square-grid scale distortion.** The national grid is VN-2000 / UTM 48N (central meridian 105°E); at Hội An (108.33°E) this carries ~0.24% areal distortion. Measured and small, but present.
4. **Anchor fields are discretised to 100 m.** The 1 km disk is approximated on a 100 m reference grid, accurate to ~1% in area. All candidates sample the identical fields, so this cannot bias one against another, but it bounds the precision of the loss and MAUP numbers.
5. **Within-unit loss is sampled**, not exhaustive: 400 units per candidate × AOI with 5 deterministic interior points. Between-unit IQR uses every unit.
6. **Ring-versus-circle overlap is lattice-sampled** (60 × 60 points, 40 units per candidate × AOI) rather than computed by polygon union.
7. **Land is defined from ESA WorldCover**, excluding classes 0 (NoData) and 80 (permanent water). This is not an authoritative coastline, and "land-intersecting unit" counts inherit that.
8. **Nationwide projections are projections**, extrapolated from 8 AOIs totalling ~1,100 km² against a 331,212 km² national land area. Urban AOIs are over-represented relative to Vietnam as a whole.
9. **No sensitivity run against an alternate population or built-up source.** Acceptance rule 5 names this; only origin-shift and jitter sensitivity were executed.

## Architectural implications — recommendations for later review only

`docs/architecture.md` is **unchanged** (SHA-256 `bd9b5ab71e95e75705676ecf00e8532584fec1ec11e9c9e9a12915c1164cfa15`, verified before and after this work). Five measured results bear on it and are recorded here for a later architecture review to accept or reject; none has been applied.

1. **Spatial support belongs in the feature schema, not in prose.** Finding 3: POI sparsity on the unit footprint ranges 0.27–0.94 across candidates, while the same measurement on a 1 km support sits at 0.18–0.22 for *every* candidate in *every* context. A feature row that does not state its support is ambiguous by an order of magnitude. Recommend `spatial_support` as a required column alongside `spatial_method` and `resolution`.
2. **A unit key must carry its candidate.** Square IDs are namespaced (`square_500m|col_row`) so keys from different resolutions cannot collide; H3 IDs are globally unique by construction. Any store holding more than one resolution needs the namespace, or a resolution column, to stay joinable.
3. **Percentile and top-decile features must pin their resolution.** Finding 5: top-decile membership is at most ~56% stable between adjacent resolutions in either family. "Top 10% of locations" is not resolution-independent and should not be defined as if it were.
4. **Online single-point lookup has a projection cost.** A projected national square grid needs a WGS84 → grid transform per query (12.0 µs vs H3's 1.9 µs); batched, the difference vanishes (~0.6 µs both). If a synchronous per-request lookup path exists, that is an architecture input; if lookups are batched, it is not.
5. **Normalise by measured area, never nominal.** Finding 1: H3 cells in Vietnam are 14.3% larger than the published global averages, uniformly across r7–r10. Any density feature dividing by a published average area would be systematically 14.3% low nationwide.

## Reproduction

```bash
# 1. Administrative-source qualification (network; re-derives the blocked verdict)
python -m src.spatial.qualify_admin --out data/gate2/admin_qualification.json

# 2. Acquire the per-AOI Gate 2 source subsets (network; idempotent, checksum-verified)
python -m src.ingestion.acquire_gate2

# 3. Smoke test on the prototype AOI
python -m src.spatial.run_gate2 --aoi hanoi_core

# 4. Full experiment, all eight AOIs
python -m src.spatial.run_gate2

# 5. Tests
python -m pytest tests/ -v
```

## Next smallest action

Two, in either order, both blocked on inputs rather than on work:

1. **Owner:** record a hardware/runtime/storage budget and a lat/lon lookup latency requirement in `PROJECT_BRIEF.md`. That alone converts this frontier into a decision between `square_325m` and `h3_r9`.
2. **Acquisition:** obtain the official 3,321-unit commune register with codes and geometry. Until it exists, re-running Gate 2 adds no administrative evidence — only a new source does.

A cheap improvement available now, needing neither: re-run the square area controls at the **measured** Vietnamese H3 areas — sides of 131, 347, 918, and 2,429 m instead of the global-nominal 125, 325, 850, and 2,270 m — removing the systematic offset in Finding 1.
