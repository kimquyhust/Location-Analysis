# Gate 3 Atomic Feature MVP — report

_Status: **four-AOI vertical slice re-executed after remediation; artifact verdict CONDITIONAL GO (§ 14).** Run `run_20260914T171148Z`, directory `data/gate3/run_20260914T171148Z/` (immutable; every output listed in `SHA256SUMS`), feature set **0.3.0**. Written 2026-09-14/15 for independent review. The 0.2.0 run `run_20260914T160806Z` is superseded and left byte-identical on disk (its `SHA256SUMS` still verifies); a three-AOI smoke run `run_20260914T171001Z` written during remediation is also on disk and is labelled `run_kind: smoke`. Gate 4 was not started; no customer/mobility data was used; `docs/architecture.md` is unchanged; no commits were made._

## 1. What changed since the 0.2.0 run (review findings F1–F4)

| finding | root cause (0.2.0) | remediation (0.3.0) | where |
|---|---|---|---|
| **F1** multipolygon relations skipped while statuses said `ok` | `src/poi/osm_extract.py` only counted `type=multipolygon` relations; `compute.py` set one shared `poi_count_status=ok` from `osm_ingest_status` + halo only | Entities are assembled with libosmium's area assembler (pyosmium `area` callback, two passes): closed ways and `multipolygon`/`boundary` relations with outer/inner rings → Polygon/MultiPolygon via WKB; grouping relations (`type=site`, …) → union of all members (pre-pass collects member ids; every member must be present); open tagged ways → LineString entities (14 Hanoi bus platforms, 3 + 4 linear attractions). A member way carrying the same category as its relation is dropped as a duplicate (3 in Hanoi). Every relevant relation is reconciled against what was assembled; failures are listed per AOI/category with reason and the bounds of the members that are present. `compute.py` turns a failure into `entity_assembly_failed` (null) for every feature that reads the category, for the whole AOI; each count feature now has its own status column. | `src/poi/osm_extract.py`, `src/features/compute.py`, `src/features/schema.py`, `config/poi_taxonomy.yaml` (0.3.0) |
| **F2** `np.clip` on `built_up_ratio` and `osm_industrial_site_area_ratio`; validation passed with a raw 1.02 | numerator (built-up m² over the whole cell / industrial polygon area) overlapped water that the WorldCover denominator excludes; the result was clipped to 1.0/`ok` | Numerators are measured **inside the land-support mask** used as denominator, as fractions of the cell in the raster's own CRS: industrial = unioned polygons ∩ cell ∩ land pixels (exact, WorldCover CRS); built-up = per 100 m pixel piece, built share × land-support area of the reprojected piece (uniform within a pixel). No clipping anywhere; float noise within 1e-9 of 0/1 is snapped on the published values, and any **published** ratio outside [0, 1] beyond that tolerance fails validation. Unmasked alternative ratios (`_built_up_ratio_unmasked`, `_industrial_ratio_unmasked`, with `_industrial_area_m2_raw`, `_industrial_area_m2_on_land_support`) may exceed 1 by construction and are retained only as QA diagnostics, summarised in `validation_summary.json → conservation` and `→ ratio_audit`; they are not public feature values and are not range-checked. | `src/features/compute.py`, `src/features/schema.py` (`validate_frame`), `config/features.yaml` → `semantics.ratios` |
| **F3** semantics changed, version still 0.2.0 | land-support floor, coverage floor, WorldCover legend/rollups, WorldPop NoData policy lived in the runner-only `config/gate3_mvp.yaml` | All formula/missing-semantics parameters moved to `config/features.yaml` → `semantics` (raster, ratios, distance, osm_entities, source_failure) under **`feature_set_version: 0.3.0`**; `config/gate3_mvp.yaml` (1.1.0) keeps run/AOI/source-availability/status vocabulary only. `run_manifest.json` and `feature_manifest.json` carry the full `feature_semantics` block plus per-config SHA-256s; every row carries `feature_set_version=0.3.0`, `poi_taxonomy_version=0.3.0`. Old run untouched. | `config/features.yaml`, `config/gate3_mvp.yaml`, `docs/feature_dictionary.md`, `src/features/run_gate3_mvp.py` |
| **F4** OSM source failure did not reach distances/counts/industrial | only road lengths/densities were nulled; distances and counts were still computed from the input frames | When `osm_ingest_status != ok`, `vector_block` computes nothing from the frames: all 27 OSM-derived features (roads, intersections, major-road distance, every count, richness/total, every POI/park/hub/transit/industrial distance, industrial ratio) are null with `source_unavailable` and `osm_query_complete=false`. `validate_frame` independently checks this consistency. The runner now reads `ingest_status` from the source index. | `src/features/compute.py`, `src/features/schema.py`, `src/features/run_gate3_mvp.py` |

Also fixed: `docs/gate3_mvp_report.md` 0.2.0 stated "Every zero … is a mapped zero" and "21 % of `major_road` values … truncated"; the correct figures are in § 9–10 (the truncated `major_road` share is 610 / 5,681 = 10.7 %, unchanged between runs).

## 2. Scope

| | |
|---|---|
| Pipeline | pinned raw inputs (Gate 1/2 per-AOI clips) → H3 units → atomic features under `config/features.yaml` **0.3.0** → one immutable run |
| Spatial unit | H3, resolution **9** read from `config/spatial.yaml` (`decision_status: provisional_mvp`, [`gate2_mvp_decision.md`](gate2_mvp_decision.md)); `spatial_unit_id` is the H3 cell id; area is the actual polygon area in the AOI's UTM zone |
| Test geography | the four Gate 2 MVP AOIs: `hanoi_core` (dense urban), `hoi_an` (tourism/coastal), `mu_cang_chai` (rural mountain), `dong_thap_rural` (rural delta) |
| Boundary policy | full H3 cells intersecting the AOI polygon; features computed on the whole cell from the 3.5 km halo clips. `aoi_id`, `aoi_overlap_fraction` carried; the four AOIs do not overlap |
| Inputs | `data/gate2/aoi_sources/gate2_source_index.json`, each AOI through its own acquisition manifest (`source_manifest_20260914T102150Z.json`); every file hashed against index and manifest before computation (`source_coverage.parquet`, 16 rows, `checksum_verified = True`); source files identical to the 0.2.0 run |
| Config hash | `f1b1948188b66f4d…` over `config/gate3_mvp.yaml` (`08e0a65a…`) + `spatial.yaml` (`1cdba55d…`, unchanged) + `features.yaml` (`515ac315…`) + `poi_taxonomy.yaml` (`0f180924…`); `feature_semantics` embedded verbatim in `run_manifest.json` |
| Code / env | `59fe994+dirty` (Gate 2/3 code uncommitted, labelled as such); Python 3.12.13, GeoPandas 1.1.4, Shapely 2.1.2, rasterio 1.5.1, h3 4.5.0, pyosmium 4.3.1 / libosmium 2.23.1, macOS 15.6 arm64 |
| Not done | normalisation, percentiles, `log1p`, semantic scores, square/admin comparison, nationwide processing, feature store/API/lookup demo, Overture union, UCDB/admin acquisition, git commits |

Source policy is unchanged from 0.2.0: POI `osm_only_gate3_mvp_v1` (Overture Places not unioned); roads `osm_only_canonical` (shared-node intersections, degree ≥ 3, no divided-carriageway collapse); WorldPop 2025 constrained 100 m, GHS-BUILT-S E2020 100 m (Mollweide native), ESA WorldCover 2021 v200 10 m on their native grids; GHSL UCDB R2024A not acquired → `distance_nearest_urban_centre_km` null `source_not_acquired`; province geometry not pinned → `admin_province_code` null `source_not_acquired`; commune blocked → `admin_commune_code` null `blocked_no_qualified_geometry`.

## 3. WorldPop NoData — evidence for the exact release and the policy kept

Evidence pinned in `config/features.yaml → semantics.raster.worldpop.evidence`:

1. **Global Demographic Data, Public release R2025A V1** (worldpop.org, September 2025; `https://data.worldpop.org/repo/prj/Global_2015_2030/R2025A/doc/Global2_Release_Statement_R2025A_v1.pdf`, SHA-256 `1a23e31f49102b599026f29a8a36d62b5507d36131bd37b66ba834b5ad24f243`, retrieved 2026-09-14). It states that the only product type in this release is `CN = Constrained`; that the mastergrid "recodes oceans and major inland waterbodies as NoData" and omits "coastline pixels with greater than 75 % water share"; that an annual **binary built-settlement** layer (GHS-BUILT-S/V + Google Open Buildings V3 + Microsoft footprints + World Settlement Footprint) was developed "for input into the RF model" — i.e. as an input/covariate of the random-forest dasymetric model, which the statement does not itself describe as the constraint mask onto which population is allocated; and that national totals are aligned to UN WPP 2024 at a 1 January reference date.
2. **The pinned Vietnam raster** `vnm_pop_2025_CN_100m_R2025A_v1.tif` (SHA-256 `21f403884d5a…`, NoData −99999, `STATISTICS_VALID_PERCENT 8.107`): 12,811,650 valid pixels of 158,035,807 in the window (≈ 106,000 km², about one third of Vietnam's 331,000 km² land area) sum to **101,300,081 persons**, the WPP-2024-aligned national total for 2025 (UNFPA/WPP 2024 mid-2025 ≈ 101.6 M; the file's 1 January reference is ~0.3 % lower, as expected). Hence the whole modelled national count is carried by valid pixels, and a publisher-NoData pixel inside the national domain holds no modelled population in this pinned raster. 4,159 valid pixels are exactly 0, so the product distinguishes "valid, zero people" from "publisher NoData".

The policy *publisher NoData inside the window = 0 persons* is therefore supported for the four MVP AOIs by the combination of (1) the exact release statement pinned by hash, (2) the pinned raster's 12,811,650 valid pixels, (3) the valid-pixel sum of 101,300,081 persons equalling the modelled national count, and (4) the four AOIs lying deep inside the national domain, far from any international boundary. None of these alone proves what a land-side NoData pixel "means"; together they establish that such a pixel carries no modelled population here. The policy is **not** generalised to nationwide or border processing until a boundary/domain check exists, and land-side NoData is described below as a land-side publisher mask (no modelled population in the pinned raster), not as a proven "unsettled" classification.

Three cases are separated in the artifact:

| case | treatment | where visible |
|---|---|---|
| publisher NoData over **land** (land-side publisher mask: no modelled population in the pinned raster) | 0 persons, `population_count_status = ok` | `population_nodata_area_fraction` per row; `validation_summary.json → conservation.<aoi>.worldpop_nodata.share_land_unsettled_mask` (field name kept as written by the runner; read it as "land-side publisher mask") |
| publisher NoData over **water** (mastergrid) | 0 persons, `ok` | `…worldpop_nodata.share_water` (WorldCover class 80 under the NoData pixel centre) |
| **technical non-coverage** (unit outside the raster window) | null, `coverage_incomplete` | `population_coverage_fraction < 0.999` |

Decomposition in this run (NoData pixel centres sampled on WorldCover): `hanoi_core` 13.3 % NoData of window, 77 % water / 22 % land; `hoi_an` 43.4 %, 77 % / 22 %; `dong_thap_rural` 28.1 %, 25 % / 75 %; `mu_cang_chai` 88.6 %, 0.1 % water / **99.6 % land-side publisher mask**. No unit is outside the raster window (`population_coverage_fraction` ≥ 0.99999999999 everywhere). Being inside the national model domain is asserted only for these four AOIs: all halos lie inside the national raster window and tens of km from any international boundary; nationwide or border use must add an explicit boundary/domain check before applying this policy. Tests: `test_worldpop_publisher_nodata_is_zero_persons_but_window_gaps_are_missing` (all-NoData unit → 0/`ok`; unit past the window → `coverage_incomplete`; the alternative policy switch is live).

## 4. Implementation (modules)

| module | responsibility (0.3.0 changes in bold) |
|---|---|
| `poi/osm_extract.py` | **relation pre-pass; area callback (libosmium assembler) for closed ways + multipolygon/boundary relations; grouping relations as member unions; open tagged ways as lines; relation/member duplicate removal; per-category assembly report with failure reasons and partial bounds** |
| `features/raster.py` | exact area-weighted pixel aggregation, measured coverage, class-area fractions (unchanged) |
| `features/roads.py` | clipped road length per unit, major-road length, intersection points, nearest-line distance (unchanged) |
| `features/poi.py` | buffer counts on `point_on_surface`, richness, nearest distance to original geometry, cap + extract-completeness status, industrial union intersection, park geometry set (unchanged) |
| `features/compute.py` | `compute_aoi_features`: **semantics read from `features.yaml`; masked ratio numerators in the raster CRS, no clipping; per-feature count statuses; `entity_assembly_failed` propagation; full `source_unavailable` propagation; `osm_query_complete` false on source failure** |
| `features/schema.py` | contract columns; **per-count status columns; `validate_frame` with numerical invariants (ratios/fractions in [0, 1], integer non-negative counts, non-negative lengths/densities/distances, major ≤ total road length, land support ≤ valid ≤ cell, richness ≤ total, ok distances ≤ cap and ≤ complete radius, source-failure consistency, valid H3 ids at the config resolution, uniform run/config/feature versions)** |
| `features/provenance.py` | source resolution and checksum verification (unchanged) |
| `features/run_gate3_mvp.py` | CLI; **assembly stats and `ingest_status` wired through; `ratio_audit` and `entity_assembly` in the validation summary; WorldPop NoData decomposition; semantics in both manifests; `latest_full_run()` (skips smoke directories)** |

## 5. Feature coverage

| disposition | features |
|---|---|
| **implemented** (34) | `population_count`, `population_density`, `built_up_ratio`, `tree_cover_ratio`, `grass_shrub_ratio`, `cropland_ratio`, `water_wetland_ratio`, `road_length_km`, `road_density_km_per_km2`, `major_road_length_km`, `intersection_density_per_km2`, `distance_nearest_major_road_m`, `transit_stop_count_1km`, `distance_nearest_transit_stop_m`, `distance_nearest_transport_hub_m`, `school_count_1km`, `higher_education_count_3km`, `distance_nearest_higher_education_m`, `hospital_count_3km`, `clinic_count_1km`, `pharmacy_count_1km`, `distance_nearest_hospital_m`, `food_drink_count_1km`, `retail_count_1km`, `marketplace_count_1km`, `mall_count_3km`, `lodging_count_1km`, `attraction_culture_count_3km`, `park_recreation_count_1km`, `distance_nearest_park_m`, `osm_industrial_site_area_ratio`, `distance_nearest_osm_industrial_site_m`, `poi_total_count_1km`, `poi_category_richness_1km` |
| **null by contract, source not acquired** (1) | `distance_nearest_urban_centre_km` (GHSL UCDB R2024A) |
| **null in one AOI, `entity_assembly_failed`** (6, `hanoi_core` only) | `park_recreation_count_1km`, `distance_nearest_park_m`, `osm_industrial_site_area_ratio`, `distance_nearest_osm_industrial_site_m`, `poi_total_count_1km`, `poi_category_richness_1km` — see § 7 |
| **metadata null by contract** | `admin_province_code` (`source_not_acquired`), `admin_commune_code` (`blocked_no_qualified_geometry`) |

All 35 `mvp_features`, 12 `required_metadata`, 7 `required_source_status` columns are present; 31 per-feature status columns (one per distance, count, ratio/density family) and 14 audit columns; 99 public columns in total. Geometry is the GeoParquet companion `spatial_units.parquet` (EPSG:4326) keyed by `spatial_unit_id`. Gate 2 anchors are not emitted.

## 6. Rows, entities, relation assembly

| AOI | cells | fully inside | canonical POIs raw → dedup | of which from relations / linear | area records (from relations) | road ways | intersections |
|---|---:|---:|---|---|---:|---:|---:|
| hanoi_core | 356 | 272 | 12,938 → 12,916 (−22 cross-geometry, after −3 relation/member) | 34 / 18 | 1,101 (33) | 39,436 | 39,799 |
| hoi_an | 1,317 | 1,151 | 2,442 → 2,436 (−6) | 3 / 4 | 391 (7) | 8,689 | 9,931 |
| mu_cang_chai | 2,053 | 1,843 | 45 → 45 | 0 / 0 | 1 (1) | 1,993 | 1,928 |
| dong_thap_rural | 1,955 | 1,751 | 248 → 246 (−2) | 0 / 0 | 95 (1) | 4,271 | 2,931 |
| **total** | **5,681** | | | | | | |

Relevant relations (relation carries a taxonomy category) — relevant / assembled / failed, from `validation_summary.json → entity_assembly`:

| AOI | category | relevant | assembled | failed | reason |
|---|---|---:|---:|---:|---|
| hanoi_core | higher_education | 8 | 8 | 0 | |
| | hospital | 3 | 3 | 0 | (2 member outer ways with `amenity=hospital` dropped as duplicates of r19207810) |
| | mall | 3 | 3 | 0 | |
| | marketplace | 3 | 3 | 0 | incl. 1 `type=site` night market (union of 4 street segments) |
| | civic_service, lodging | 3 + 3 | 3 + 3 | 0 | |
| | attraction_culture, early_childhood, manufacturing | 2 + 2 + 2 | all | 0 | (1 manufacturing inner member way dropped as duplicate of r16755483) |
| | school, retail_other | 1 + 1 | all | 0 | |
| | park_recreation / park_area | 4 / 3 | 3 / 2 | **1 / 1** | r10069606, `members_missing_from_extract` (5 of 10 member ways outside the halo; present part at lon 105.7877–105.7910, the halo's west edge is 105.7891) |
| | industrial_site | 2 | 1 | **1** | r16749852, `members_missing_from_extract` (1 of 2 outer ways outside; present part at lon 105.9137–105.9157, halo east edge 105.915) |
| | water_body | 36 | 30 | 6 | audit-only category, feeds no feature |
| hoi_an | attraction_culture 2, park_recreation 1, park_area 1, water_body 6 | 10 | 10 | 0 | |
| mu_cang_chai | water_body | 1 | 1 | 0 | |
| dong_thap_rural | water_body | 2 | 1 | 1 | audit-only |

No closed way failed to assemble in any AOI (0 of 3,817 relevant closed ways in Hanoi). Open-way entities: Hanoi 14 `transport_bus_stop` platforms + 3 `attraction_culture`; Hội An 4 `attraction_culture`. Effect on counts vs 0.2.0 (Hanoi): `higher_education_count_3km` +694 over 193 cells (max +7), `mall_count_3km` +605 / 307 cells, `hospital_count_3km` +420 / 264 cells, `attraction_culture_count_3km` +2,535 / 787 cells (both AOIs), `transit_stop_count_1km` +159 / 59 cells, `marketplace_count_1km` +54, `lodging_count_1km` +42.

## 7. The two Hanoi assembly failures and what they null

Both failed relations straddle the 3.5 km halo edge, outside the AOI polygon; their present members are ≥ 3,197 m (park) and ≥ 3,272 m (industrial) from every Hanoi representative point, so **no** cell's 1 km/3 km buffer reaches the part of either entity that is in the extract. Their true extent inside the halo, however, cannot be bounded from the extract (the missing outer ways lie entirely outside it), so the contract policy `semantics.osm_entities.assembly_failure_policy: null_affected_features_for_aoi` applies: in `hanoi_core` the six features listed in § 5 are null with `entity_assembly_failed` on all 356 rows. This is the price of the Gate 2 `complete_ways` clip strategy at 3.5 km; the remedy (an extract strategy that completes relations, e.g. `osmium extract --strategy smart`, or a wider clip) changes source checksums and is therefore a re-acquisition decision for the owner / Gate 6, not made in this session.

## 8. Conservation, ratio audit, denominators (`validation_summary.json`)

| AOI | population Σcells vs Σunion (rel. err.) | built-up native m²: rel. err. | unmasked built-up ratio max / cells > 1 | unmasked industrial ratio max / cells > 1 | published max built-up / industrial |
|---|---:|---:|---|---|---|
| hanoi_core | 4.0 × 10⁻¹² | 1.4 × 10⁻¹⁶ | 0.919 / 0 | **1.01995 / 1** (cell `89415cb40a3ffff`) | 0.720 / — (null, § 7) |
| hoi_an | 4.3 × 10⁻¹² | 0 | 0.884 / 0 | 0.99999999999850 / 0 | 0.551 / 1.000 |
| mu_cang_chai | 4.3 × 10⁻¹² | 0 | 0.070 / 0 | 0 / 0 | 0.070 / 0 |
| dong_thap_rural | 4.2 × 10⁻¹² | 1.2 × 10⁻¹⁶ | 0.664 / 0 | 0.746 / 0 | 0.535 / 0.746 |

The reviewed cell `89415cb40a3ffff` (`hanoi_core`, land support 2,790.08 m² = 2.4 % of the cell): raw industrial polygon ∩ cell = 2,845.75 m² (unmasked ratio **1.01995**; the reviewer's 1.0200160 was measured in UTM, this one as a fraction in the WorldCover CRS), of which 2,266.40 m² lie on land-support pixels (masked ratio 0.8123). Both numbers are in `ratio_audit.cells`; the published value for this cell is null because Hanoi's industrial category failed assembly (§ 7), not 1.0.

Population sums over cells: Hanoi 889,070; Hội An 185,272; Đồng Tháp 268,490; Mù Cang Chải 17,804 — identical to 0.2.0 (the population path did not change). WorldCover rollups never exceed the valid area (max sum 1.0000000000000002); land support ≤ cell area everywhere (max fraction 1 + 2.7 × 10⁻¹²). Coverage fractions are 1.000 for every cell on every raster.

Denominator statuses (`population_density_status`; identical for `built_up_ratio`, road/intersection density; for the industrial ratio in Hanoi all 356 are `entity_assembly_failed`):

| AOI | ok | denominator_zero (open water) | denominator_below_minimum (< 1 % land) |
|---|---:|---:|---:|
| hanoi_core | 327 | 24 | 5 |
| hoi_an | 1,100 | 208 | 9 |
| mu_cang_chai | 2,053 | 0 | 0 |
| dong_thap_rural | 1,855 | 90 | 10 |

**`built_up_ratio` vs 0.2.0.** All 5,335 comparable cells are ≤ the 0.2.0 value (masking only removes). Fully-land cells (4,048) differ by −0.45 % to −0.70 % relative: 0.2.0 divided GHS-BUILT-S m² (Mollweide, spherical) by a UTM (ellipsoidal) land-support area; 0.3.0 divides the built fraction of the cell by the land fraction of the cell, each measured in its raster's own CRS (the UTM/Mollweide area ratio of these cells is 0.993–0.9955). Partial-land cells (1,287): 373 differ by > 0.01, 79 by > 0.05, 12 by > 0.2 — the latter all with < 13 % land support, where the uniform-within-pixel mask attributes most of a 100 m pixel's built-up to water. That is the documented limitation of the chosen semantic (§ 11); the unmasked value is retained in QA.

## 9. Zero / null rates and medians by AOI

null = null rate, 0 = zero rate (status `ok`), med = median of non-null values. Hanoi / Hội An / Đồng Tháp / Mù Cang Chải.

| feature | null | zero | median |
|---|---|---|---|
| population_count | 0 / 0 / 0 / 0 | .06 / .17 / .05 / .47 | 2,495 / 44 / 46 / 0.06 |
| population_density (/km²) | .08 / .16 / .05 / 0 | .01 / .01 / .01 / .47 | 26,840 / 811 / 461 / 0.5 |
| built_up_ratio | .08 / .16 / .05 / 0 | .04 / .06 / .06 / .93 | 0.43 / 0.08 / 0.03 / 0.00 |
| tree_cover_ratio | 0 | .09 / .26 / .08 / 0 | 0.09 / 0.04 / 0.36 / 0.83 |
| cropland_ratio | 0 | .73 / .36 / .21 / .62 | 0 / 0.01 / 0.13 / 0 |
| water_wetland_ratio | 0 | .49 / .45 / .61 / 1.0 | 0 / 0.02 / 0 / 0 |
| road_length_km | 0 | .10 / .25 / .31 / .69 | 2.83 / 0.65 / 0.36 / 0 |
| road_density_km_per_km2 | .08 / .16 / .05 / 0 | .02 / .08 / .26 / .69 | 27.5 / 8.4 / 3.2 / 0 |
| major_road_length_km | 0 | .46 / .84 / .84 / .96 | 0.15 / 0 / 0 / 0 |
| intersection_density_per_km2 | .08 / .16 / .05 / 0 | .06 / .21 / .68 / .86 | 270 / 30 / 0 / 0 |
| distance_nearest_major_road_m | 0 / .01 / 0 / .29 | 0 | 176 / 789 / 740 / 2,294 |
| transit_stop_count_1km | 0 | .04 / .73 / .90 / 1.0 | 29 / 0 / 0 / 0 |
| school_count_1km | 0 | .06 / .71 / .91 / 1.0 | 12 / 0 / 0 / 0 |
| hospital_count_3km | 0 | 0 / .73 / .59 / .96 | 29 / 0 / 0 / 0 |
| food_drink_count_1km | 0 | .05 / .48 / .94 / .97 | 80 / 1 / 0 / 0 |
| retail_count_1km | 0 | .01 / .57 / .83 / .97 | 86 / 0 / 0 / 0 |
| lodging_count_1km | 0 | .04 / .57 / .92 / .94 | 10 / 0 / 0 / 0 |
| attraction_culture_count_3km | 0 | 0 / .03 / .85 / .59 | 86.5 / 6 / 0 / 0 |
| park_recreation_count_1km | **1.0** / 0 / 0 / 0 | — / .70 / .93 / 1.0 | — / 0 / 0 / 0 |
| osm_industrial_site_area_ratio | **1.0** / .16 / .05 / 0 | — / .82 / .95 / 1.0 | — / 0 / 0 / 0 |
| poi_total_count_1km | **1.0** / 0 / 0 / 0 | — / .26 / .60 / .88 | — / 4 / 0 / 0 |
| poi_category_richness_1km | **1.0** / 0 / 0 / 0 | — / .26 / .60 / .88 | — / 3 / 0 / 0 |
| distance_nearest_urban_centre_km | 1.0 (source_not_acquired) | — | — |

Full per-feature quantiles per AOI are in `validation_summary.json → per_aoi`; global status counts per feature in `feature_manifest.json`.

**Reading the zeros.** A zero in this table means: the OSM extract ingested (`osm_ingest_status = ok`), the buffer was inside the extract (`osm_query_complete = True`, minimum complete radius 3,307 m ≥ 3,000 m), every relevant relation/way of the categories the feature reads was assembled (no `entity_assembly_failed`), and no canonical entity was found. It is a **mapped** zero — OSM's mapped state, not proven real-world absence; in Mù Cang Chải OSM holds 45 canonical POIs in the 22 × 22 km halo (0 transit stops, 0 schools, 0 pharmacies) and 88 % of cells have no POI within 1 km. Where the extract could not be trusted (Hanoi park/industrial) the value is null, not zero.

## 10. Distance features: ok / truncated counts

`ok` = nearest found within both the cap and the complete-search radius; `trunc` = `search_truncated_by_extract` (null); `eaf` = `entity_assembly_failed`. `not_found_within_cap`: 0 everywhere (unreachable with 3.5 km halos against 50–100 km caps).

| feature | hanoi_core | hoi_an | mu_cang_chai | dong_thap_rural |
|---|---|---|---|---|
| major road | 356 ok | 1,305 / 12 trunc | 1,455 / 598 | 1,955 / 0 |
| transit stop | 356 | 1,237 / 80 | 0 / 2,053 | 1,310 / 645 |
| transport hub | 356 | 1,093 / 224 | 317 / 1,736 | 1,589 / 366 |
| higher education | 356 | 969 / 348 | 0 / 2,053 | 1,121 / 834 |
| hospital | 356 | 885 / 432 | 467 / 1,586 | 1,451 / 504 |
| park | 356 eaf | 1,156 / 161 | 0 / 2,053 | 1,285 / 670 |
| industrial site | 356 eaf | 985 / 332 | 0 / 2,053 | 1,363 / 592 |
| urban centre | 356 `source_not_acquired` | 1,317 | 2,053 | 1,955 |

`major_road` is truncated on 610 of 5,681 rows (10.7 %), 598 of them in Mù Cang Chải. Every `ok` distance is ≤ its cap and ≤ the row's complete-search radius (validator check and independent recompute). Assembled relations moved some nearest distances (e.g. `distance_nearest_hospital_m` changed by up to 163 m in Hanoi where a hospital multipolygon is now the nearest geometry).

## 11. Limitations

1. **Two halo-truncated relations null six features in `hanoi_core`** (§ 7). Removing this needs an extract that completes relations or a wider clip — a source change, deferred to the owner/Gate 6.
2. **OSM POI coverage is uneven by an order of magnitude** (12,916 canonical POIs in Hanoi's halo vs 45 in Mù Cang Chải); rural zeros are mapped zeros. Overture augmentation deferred; no completeness claim.
3. **Distances are truncated by the halo**: 10.7 % of `major_road` rows and up to 100 % of park/industrial/higher-education/transit distances in Mù Cang Chải are null with `search_truncated_by_extract`.
4. **Masked built-up on slivers**: for cells with < ~10 % land support the uniform-within-pixel mask can understate built-up that is really on the bank (12 cells changed by > 0.2 vs 0.2.0). The unmasked value is retained as QA; no better sub-pixel information exists in a 100 m product.
5. **Population is a modelled dasymetric estimate** (WorldPop R2025A, alpha release per its own statement; `CONDITIONAL GO` in Gate 1); publisher NoData = 0 persons on the combined evidence in § 3, asserted for these four AOIs only (inside the national domain, away from borders); not generalised nationwide without a domain check. No same-epoch validation exists.
6. **Mixed raster resolutions at water edges**: the 1 % land-support floor nulls 24 cells (0.4 %) rather than publishing unstable densities.
7. **Intersection density inflates on divided carriageways** (no collapse in 0.3.0, per config).
8. **Grouping relations** are unions of members; a `type=site` relation whose members are streets (the Hanoi night market) is a MultiLineString entity — a faithful but unusual geometry; `point_on_surface` lies on it.
9. **Land support = WorldCover valid minus permanent water** — not an authoritative coastline; Hội An's 208 open-water cells inherit that.
10. **Four AOIs ≈ 600 km²**; nothing here is nationwide-ready.
11. **Code is uncommitted** (`59fe994+dirty`).

## 12. Runtime, memory, storage

| | |
|---|---|
| wall time | 68.4 s total (OSM parse incl. two-pass assembly 19.7 s, features 47.1 s, checks 0.6 s); 0.2.0 was 49.1 s — the extra cost is the second libosmium pass and the per-piece mask on 1,287 water-edge cells |
| peak RSS | 0.52 GB |
| storage | `atomic_features.parquet` 1.11 MB (5,681 rows × 99 columns), `spatial_units.parquet` 0.44 MB, `source_coverage.parquet` 15 KB |
| determinism | `compute_aoi_features` is bit-identical on rerun (test); a full rerun differs only in `run_id`/`computed_at_utc` |

## 13. Tests and checks

`tests/test_osm_extract.py` — 10 tests (7 new on a pyosmium-written synthetic PBF): multipolygon with hole + second outer assembled as a valid MultiPolygon with the exact area; relation/member same-category duplicate dropped and then node/polygon collapsed by cross-geometry dedup; relation entity counted by `point_on_surface` (3 km yes, 100 m no) and measured to the edge (200 m, not the centroid); industrial multipolygon intersection excludes the hole; a relation with a member outside the file is reported `members_missing_from_extract` with its partial bounds and survives bbox clipping; a `type=site` relation and an open platform way become linear entities; a park relation feeds both tables once.

`tests/test_gate3_features.py` — 33 tests (7 new): industrial ratio over water is masked (exactly 1.0 where the polygon covers the cell, unmasked 1/land-fraction > 1 recorded, water cells stay `denominator_zero`); ratios/fractions/counts/lengths/richness/distance caps/H3 ids/version outside their invariants fail `validate_frame`, 1 + 1e-12 does not; OSM source failure nulls all 27 OSM-derived features with `source_unavailable`, `osm_query_complete=false`, raster features untouched, and the validator catches a leaked value; assembly failure nulls exactly the affected categories (`entity_assembly_failed`) and nothing else; semantic parameters/versions live in `features.yaml` 0.3.0 (and the 0.2.0 run still verifies at 0.2.0); the WorldPop NoData policy (all-NoData unit → 0/`ok`, outside-window → `coverage_incomplete`, switch live); `latest_full_run` skips a newer smoke directory; the real full run verifies (checksums, contract with spatial config, 0.3.0 lineage in rows/manifests, assembly report, ratios in range).

```
.venv/bin/python -m pytest tests/test_osm_extract.py tests/test_gate3_features.py -v   # 43 passed
.venv/bin/python -m pytest tests/ -v                                                   # 294 passed (280 before + 14)
.venv/bin/python -m compileall -q src tests                                            # ok
git diff --check                                                                       # ok
( cd data/gate3/run_20260914T171148Z && shasum -a 256 -c SHA256SUMS )                 # 8 × OK (8 artifact entries; SHA256SUMS does not list itself)
```

Independent recomputation outside `src/features` (rasterio.mask, a minimal pyosmium pass, shapely): population per AOI bracketed by the `all_touched` upper bound and within 0.04 % of the pixel-centre estimate, Σcells = Σunion to 4 × 10⁻¹²; the reviewed cell's raw industrial area 2,845.79 m² / land support 2,790.10 m² = 1.01996 and masked 2,266.41 m² (runner: 2,845.75 / 2,790.08 / 2,266.40); relation recount 72 relevant area relations in Hanoi, 64 assembled, failures {water 6, park 1, industrial 1} = runner; every invariant of § 8/§ 10 holds on the parquet; source, config and artifact SHA-256s match index, manifest and disk; no absolute paths.

## 14. Verdict

**CONDITIONAL GO** for the 0.3.0 Gate 3 artifact as an atomic-feature MVP over the four AOIs.

Met: no known mapped OSM relation is dropped while an affected status reads `ok` (every relevant relation is assembled or reported and propagated); no clipping anywhere; public ratios follow the dictionary formula with numerator ⊂ denominator and are in [0, 1]; any published ratio outside [0, 1] beyond tolerance fails validation (tested), while unmasked alternative ratios may exceed 1 by construction and are retained only as QA diagnostics — the 1.01995 diagnostic for cell `89415cb40a3ffff` sits in `ratio_audit`, is not a public value, and does not fail the run; OSM source failure reaches every OSM-derived feature; semantics are versioned (0.3.0) and pinned in config hash, both manifests and every row, with the 0.2.0 run untouched; the WorldPop NoData policy rests on the exact-release statement plus the pinned raster's national-total identity; the new four-AOI run passes the strengthened validator and the independent recomputation; tests/compile/diff/checksums pass; no Gate 4/5/nationwide/customer logic; no commits.

Conditions (why not an unqualified GO): (a) six features are null in `hanoi_core` because two relations are cut by the halo (§ 7) — a source-clip decision; (b) `distance_nearest_urban_centre_km` and two admin fields are null pending UCDB/admin acquisition; (c) distance features are truncated by the halo in the rural AOIs; (d) the masked built-up semantic understates on thin land slivers (§ 11.4); (e) code is uncommitted.

## 15. Next smallest steps (not started)

1. Owner decision on the OSM clip: re-acquire the four AOIs with a relation-completing extract strategy (same 3.5 km halo) and re-run this pipeline unchanged; expected to clear condition (a) with no code change.
2. Acquire and pin GHSL UCDB R2024A and OCHA COD-AB 2025 ADM1; re-run to fill condition (b).
3. Gate 4 (contextual normalisation) only after independent review of this run.

## 16. Reproduction

```bash
# prerequisites: the four AOI source bundles from Gate 2 (offline once present)
#   .venv/bin/python -m src.ingestion.acquire_gate2 --aoi hanoi_core --aoi hoi_an --aoi mu_cang_chai --aoi dong_thap_rural

# smoke (writes a partial run labelled run_kind=smoke; never selected as the latest full run)
.venv/bin/python -m src.features.run_gate3_mvp --aoi hanoi_core --aoi hoi_an --aoi mu_cang_chai

# full four-AOI run -> data/gate3/run_<UTC timestamp>/  (~70 s)
.venv/bin/python -m src.features.run_gate3_mvp

# verify this run directory
( cd data/gate3/run_20260914T171148Z && shasum -a 256 -c SHA256SUMS )

# tests
.venv/bin/python -m pytest tests/test_osm_extract.py tests/test_gate3_features.py -v
.venv/bin/python -m pytest tests/ -v
.venv/bin/python -m compileall -q src tests
git diff --check
```
