# Feature Dictionary — Atomic MVP v0.3

_Gate 1 reviewed definition. The spatial unit remains a Gate 2 decision. The complete disposition of the original draft is in [`gate1_technical_review.md`](gate1_technical_review.md). No customer mobility data or semantic scores are used._

## Shared contract

- **Grain:** one row per selected spatial unit. Identifiers and admin labels are metadata, not model features.
- **Version:** `feature_set_version=0.3.0` (2026-09-14). A formula or zero/null-semantics change requires a new version; every such parameter is in `config/features.yaml` → `semantics` and is hashed into each run manifest. 0.2.0 (run `run_20260914T160806Z`) is superseded, not back-edited: it clipped two ratios silently, kept the land-support floor / coverage floor / WorldPop NoData policy outside the contract, and skipped OSM multipolygon relations while reporting `ok`.
- **Normalization:** none in the atomic layer. Log transforms, percentiles, peer comparisons, and local ratios are Gate 4 experiments.
- **Metric operations:** use a locally suitable metric/equal-area CRS; store representative coordinates and output geometry in EPSG:4326.
- **Entities:** a canonical entity is an OSM node, a closed way, an assembled `type=multipolygon`/`boundary` relation (outer and inner rings, MultiPolygon when several outers), a grouping relation (`type=site`, …) as the union of its members, or an open way carrying a category tag (a bus platform drawn as a line). A member way that carries the same category as its relation is the same place and is dropped as a duplicate; node/polygon pairs are collapsed by the cross-geometry rule in `config/poi_taxonomy.yaml` (v0.3.0).
- **POI counts:** include a canonical entity when its point, or the `point_on_surface` of its polygon/line, is in the buffer around the unit representative point. Never count raw OSM elements.
- **Distances:** measure from the unit representative point to original geometry, never to a polygon centroid.
- **Entity assembly failure:** a relevant relation whose geometry cannot be built from the extract (typically a member way that lies entirely outside the halo clip), a grouping relation with a missing member, or a closed way that yields no area is reported per AOI/category in `validation_summary.json → entity_assembly`, and every feature that reads that category — its count, `poi_total_count_1km`, `poi_category_richness_1km`, its distance, the industrial ratio/distance — is null with `entity_assembly_failed` for the whole AOI. Missing entities never become zeros. Each count feature carries its own `<feature>_status` column.
- **Raster aggregation:** use area-conserving/area-weighted aggregation over the unit footprint and record valid coverage.
- **Zero vs missing:** `0` is allowed only after a successful complete query with no matches and no assembly failure in the categories read. Missing tiles, technical non-coverage, and failed ingestion produce `null` plus source status; when `osm_ingest_status != ok` every OSM-derived feature is null with `source_unavailable` and `osm_query_complete` is false. OSM zero means zero mapped entities, not proven real-world absence.
- **Ratios:** public ratios are defined on [0, 1] and are never clipped. The numerator of `built_up_ratio` and `osm_industrial_site_area_ratio` is measured inside the valid land-support mask that is their denominator (built-up surface or industrial polygon over WorldCover permanent water/NoData is excluded; uniform-within-pixel for the 100 m built-up raster, exact intersection for polygons), so the ratio is ≤ 1 by construction. Both numerator and denominator are fractions of the cell measured in the raster's own CRS. Unmasked numerators are QA columns and audited in `validation_summary.json → ratio_audit`; any public ratio outside [0, 1] beyond `semantics.ratios.unit_interval_tolerance` (1e-9) fails validation.
- **Distance not found:** return `null` plus `not_found_within_cap`; source failure is `source_unavailable`. Search caps come from `config/spatial.yaml` and are not substituted as feature values.
- **Refresh:** recompute when a pinned source, taxonomy, formula, or spatial representation changes.

Required metadata/source-status fields are in `config/features.yaml`. Detailed lineage lives in manifests keyed by `run_id` and `source_manifest_id`.

## Population and physical environment

| Feature | Unit | Source | Calculation / scope | Missing policy | Main limitation |
|---|---|---|---|---|---|
| `population_count` | people | WorldPop Global 2 R2025A v1, 2025, 100 m constrained count | Area-conserving sum over unit footprint; boundary pixels apportioned by overlap. Publisher NoData inside the raster window = 0 persons (constrained settlement mask / mastergrid water; evidence pinned in `config/features.yaml` → `semantics.raster.worldpop.evidence`: Global2 Release Statement R2025A v1 and the national raster, whose 12.8 M valid pixels (8.1 % of the window, ≈ one third of Vietnam's land) sum to 101,300,081 persons — the WPP-2024-aligned national total); the NoData share is reported per row (`population_nodata_area_fraction`) and decomposed per AOI into water vs unsettled land | Null (`coverage_incomplete`) only when the unit is not fully inside the raster window | Modeled dasymetric estimate, not direct census; policy valid only inside Vietnam's national model domain |
| `population_density` | people/km² | Derived | `population_count / valid_land_support_area_km2` | Null if count missing or denominator zero | Sensitive to population model and land mask |
| `built_up_ratio` | ratio [0,1] | GHS-BUILT-S R2023A 100 m, E2020 | Built-up surface inside the valid land-support mask / valid unit land-support area (both as fractions of the cell; pixel built share × piece area on land, uniform within a 100 m pixel) | Null if coverage incomplete / denominator zero or below the 1 % floor | Modeled; the uniform-within-pixel mask understates built-up concentrated on a river/coast sliver (cells with < ~10 % land support) — the unmasked value is kept in QA |
| `tree_cover_ratio` | ratio [0,1] | ESA WorldCover 2021 v200 | Tree-cover class area / valid classified raster area in unit | Null if coverage incomplete | Global classifier; plantation/natural forest not distinguished |
| `grass_shrub_ratio` | ratio [0,1] | ESA WorldCover 2021 v200 | Grassland plus shrubland area / valid classified area in unit | Null if coverage incomplete | Combines two explicit but distinct legend classes |
| `cropland_ratio` | ratio [0,1] | ESA WorldCover 2021 v200 | Cropland area / valid classified area in unit | Null if coverage incomplete | Crop type and season not represented |
| `water_wetland_ratio` | ratio [0,1] | ESA WorldCover 2021 v200 | Permanent-water, herbaceous-wetland, and mangrove area / valid classified area | Null if coverage incomplete | Combined rollup must also retain class-level QA |

## Roads, accessibility, and transport

| Feature | Unit | Source | Calculation / scope | Missing policy | Main limitation |
|---|---|---|---|---|---|
| `road_length_km` | km | Dated Geofabrik OSM PBF | Sum length of accepted driveable-road centerlines clipped to unit | Null on source/query failure; otherwise zero allowed | Rural/minor roads may be unmapped |
| `road_density_km_per_km2` | km/km² | Derived | `road_length_km / valid_land_support_area_km2` | Null if numerator missing or denominator zero | Road class policy materially affects value |
| `major_road_length_km` | km | Geofabrik OSM | Clipped length for motorway, trunk, primary, and secondary classes, including links only when configured | Null on failure; otherwise zero allowed | OSM road hierarchy varies by mapper/context |
| `intersection_density_per_km2` | intersections/km² | OSM shared-node road graph | Unique OSM nodes with accepted-road edge degree ≥3 / valid land area; geometric crossings without a shared node do not intersect; no divided-carriageway collapse in v0.2 | Null on graph failure; otherwise zero allowed | Sensitive to source topology and divided-road representation |
| `distance_nearest_major_road_m` | m | Geofabrik OSM | Metric distance to nearest accepted major-road line, search cap 50 km | Null plus distance status | Road-class consistency |
| `distance_nearest_urban_centre_km` | km | GHS Urban Centre Database R2024A, pinned release | Distance to nearest approved urban-centre geometry/representative point, cap 300 km | Null plus distance status | Global urban-centre definition may omit locally important towns |
| `transit_stop_count_1km` | count | Canonical OSM bus/rail stop entities (nodes, closed ways, platforms drawn as lines) | Deduplicated stop count in 1 km buffer | Zero only after successful complete query | Nationwide OSM transit completeness is unknown |
| `distance_nearest_transit_stop_m` | m | Canonical OSM bus/rail stop entities | Distance to nearest stop geometry, cap 50 km | Null plus distance status | Same completeness risk |
| `distance_nearest_transport_hub_m` | m | Canonical OSM bus stations, rail stations, airports, ports/ferry terminals | Distance to nearest hub geometry, cap 100 km | Null plus distance status | Hubs have heterogeneous functions; keep leaf class in QA |

## Service and activity POIs

| Feature | Unit | Source category | Calculation / scope | Missing policy | Main limitation |
|---|---|---|---|---|---|
| `school_count_1km` | count | OSM `school` | Canonical entity count in 1 km buffer | Zero only after successful query | Does not identify school level reliably |
| `higher_education_count_3km` | count | OSM `higher_education` | Canonical entity count in 3 km buffer | Same | Campuses require entity conflation |
| `distance_nearest_higher_education_m` | m | OSM `higher_education` | Distance to original geometry, cap 100 km | Null plus distance status | Mapping completeness |
| `hospital_count_3km` | count | OSM `hospital` | Canonical entity count in 3 km buffer | Zero only after successful query | Hospital/clinic tagging may vary |
| `clinic_count_1km` | count | OSM `clinic` | Canonical entity count in 1 km buffer | Same | Informal/private care under-mapping |
| `pharmacy_count_1km` | count | OSM `pharmacy` | Canonical entity count in 1 km buffer | Same | Strong informal/rural under-mapping risk |
| `distance_nearest_hospital_m` | m | OSM `hospital` | Distance to original geometry, cap 100 km | Null plus distance status | Mapping completeness |
| `food_drink_count_1km` | count | OSM `food_drink` | Canonical entity count in 1 km buffer | Zero only after successful query | Street/informal vendors under-mapped |
| `retail_count_1km` | count | OSM convenience + supermarket + `retail_other` | Disjoint rollup in 1 km; excludes mall and marketplace | Same | Generic shop mapping is uneven |
| `marketplace_count_1km` | count | OSM `marketplace` | Canonical entity count in 1 km buffer | Same | Traditional-market tagging completeness unknown |
| `mall_count_3km` | count | OSM `mall` | Canonical entity count in 3 km buffer | Same | Large complexes require deduplication |
| `lodging_count_1km` | count | OSM `lodging` | Canonical entity count in 1 km buffer | Same | Homestay/guesthouse mapping varies |
| `attraction_culture_count_3km` | count | OSM `attraction_culture` | Canonical entity count in 3 km buffer | Same | Attraction labeling is subjective |
| `park_recreation_count_1km` | count | OSM `park_recreation` | Canonical entity count in 1 km buffer | Same | Entity count ignores park size; polygons remain available for QA |
| `distance_nearest_park_m` | m | OSM park polygons/points | Distance to original geometry, cap 50 km | Null plus distance status | Small green spaces often unmapped |

## Industrial and cross-POI features

| Feature | Unit | Source | Calculation / scope | Missing policy | Main limitation |
|---|---|---|---|---|---|
| `osm_industrial_site_area_ratio` | ratio [0,1] | OSM `landuse=industrial` polygons and assembled multipolygons | Area of the unioned polygons ∩ unit ∩ valid land-support mask / valid unit land-support area | Null on source failure or `entity_assembly_failed`; zero after successful query | Explicitly mapped industrial land, not authoritative zoning |
| `distance_nearest_osm_industrial_site_m` | m | OSM `landuse=industrial` polygons | Distance to original polygon geometry, cap 100 km | Null plus distance status | Same mapped-data limitation |
| `poi_total_count_1km` | count | All enabled canonical count categories | Count of unique canonical entities in 1 km buffer, once per entity | Zero only after successful complete query | Category inclusion/version affects totals |
| `poi_category_richness_1km` | represented leaf categories | Same | Number of enabled leaf categories with at least one canonical entity in 1 km | Zero only after successful complete query | Richness depends on total count and source completeness |

## Deferred from the atomic MVP

- Custom `urban_rural_class`: use raw/source-defined context first; validate any custom thresholds in Gate 4.
- `building_density`: validate Overture/GHSL/OSM footprint completeness by context before use.
- `bank_count_1km`, `factory_count_3km`: taxonomy/completeness do not justify MVP cost.
- `poi_diversity`: richness is the simple diagnostic; entropy/evenness needs a pre-registered formula and small-count policy.
- `poi_density_peer_percentile`, `local_poi_density_ratio`, all `log1p`/percentile features: Gate 4 only.
- Residential, commercial, education, tourism, and industrial scores: optional Gate 5 only.

## Radius policy

The MVP uses one provisional neighborhood radius (1 km) for common local services and one regional radius (3 km) for rarer destinations. Gate 2 may compute diagnostic alternatives, but Gate 3 must not publish a family of 500 m/1 km/3 km variants unless stability and downstream requirements justify each added column.

## Gate 3 MVP implementation notes (v0.3.0, run `data/gate3/run_20260914T171148Z`)

Implementation policies that qualify the definitions above. Full account in [`gate3_mvp_report.md`](gate3_mvp_report.md); semantics in `config/features.yaml` → `semantics`, execution parameters in `config/gate3_mvp.yaml`.

- **Spatial unit:** H3 r9, `provisional_mvp` (`config/spatial.yaml`); full cells intersecting the AOI; actual cell area in the AOI's UTM zone.
- **`valid_land_support_area_km2`** = cell area × (valid classified WorldCover fraction − permanent-water fraction, class 80). Wetland and mangrove remain land support. Reported per row.
- **Denominator floor** (`semantics.raster.worldcover.minimum_land_support_fraction: 0.01`): land support below 1 % of the cell area → `denominator_below_minimum` (zero → `denominator_zero`) for `population_density`, `built_up_ratio`, `road_density_km_per_km2`, `intersection_density_per_km2`, `osm_industrial_site_area_ratio`; numerators still reported.
- **Raster aggregation:** exact area-weighted (boundary pixels by intersection area); coverage floor 0.999 (`semantics.raster.minimum_coverage_fraction`). WorldPop publisher NoData = 0 persons per the R2025A evidence above; NoData share per row.
- **Ratio numerators** inside the land-support mask; no clipping (see *Ratios* above).
- **OSM entities:** libosmium area assembly for closed ways and multipolygon/boundary relations; grouping relations as member unions; open tagged ways as lines; relation/member duplicates dropped; failures → `entity_assembly_failed` per AOI/category. In this run `hanoi_core` has two multipolygon relations truncated by the 3.5 km halo (park r10069606, industrial site r16749852), so its `park_recreation_count_1km`, `distance_nearest_park_m`, `osm_industrial_site_area_ratio`, `distance_nearest_osm_industrial_site_m`, `poi_total_count_1km` and `poi_category_richness_1km` are null with that status.
- **Distance completeness:** the OSM inputs are halo clips, so a nearest search is complete only to `distance_search_complete_radius_m`; beyond it the value is null with `search_truncated_by_extract`. `not_found_within_cap` applies only when the search was complete to the cap.
- **POI source policy:** `osm_only_gate3_mvp_v1`; Overture Places not unioned; commercial augmentation deferred.
- **Null by contract in this run:** `distance_nearest_urban_centre_km` (`source_not_acquired`), `admin_province_code` (`source_not_acquired`), `admin_commune_code` (`blocked_no_qualified_geometry`).
- **Not emitted:** the Gate 2 diagnostic anchors (`poi_count_1km`, `population_1km`, `road_length_1km_m`).

## Contextual features — Gate 4 normalization v0.1.0 (run `data/gate4/run_20260914T175737Z`)

_Separate layer and version (`normalization_version: 0.1.0`, `config/gate4_mvp.yaml`); the atomic layer above is unchanged at 0.3.0. Full account, sensitivities and verdict (CONDITIONAL GO) in [`gate4_normalization_report.md`](gate4_normalization_report.md). Both Gate 4 tables join 1:1 to `atomic_features.parquet` on `spatial_unit_id`; they carry the Gate 3 `run_id`, `feature_set_version`, `source_manifest_id` and their own `normalization_version`, `normalization_run_id`, `gate3_run_id`._

Shared contract: the atomic value is never imputed, clipped or winsorized; a non-`ok` atomic status is copied verbatim and the value is null; every column has `<column>_status`; a value exists iff the status is `ok`. Gate 4 statuses: `cohort_too_small`, `cohort_degenerate`, `cohort_not_fitted`, `peer_cohort_insufficient`, `neighborhood_incomplete`, `neighborhood_insufficient_valid`, `neighborhood_reference_zero`, `source_not_acquired`. `aoi_context` in the tables is Gate 2 experiment metadata, not a settlement class.

| Feature | Unit | Source | Grain / scope | Calculation | Missing policy | Normalization policy | Disposition | Main limitation |
|---|---|---|---|---|---|---|---|---|
| `log1p_<f>` for the 15 count features and `population_count`, `population_density`, `road_length_km`, `road_density_km_per_km2`, `major_road_length_km`, `intersection_density_per_km2` (21 columns) | log(1 + unit of `f`) | Gate 3 atomic `f` | per cell; no neighborhood, no cohort | `ln(1 + x)`; `0 → 0`; reversible by `expm1` | null with the atomic status; negative input fails the run | pre-registered rule: pooled raw skew ≥ 1 and skew reduced (all 21 met) | **publishable** (`contextual_features.parquet`) | zero mass is unchanged (8 columns are 84–94 % zero); ratios on [0, 1] and distances are never candidates |
| `local_ratio_k1_population_density`, `local_ratio_k1_road_density_km_per_km2` | dimensionless | Gate 3 atomic feature of the cell and its 6 H3 k=1 neighbors | cell vs. its k=1 ring (centre excluded, ≈ 0.6 km² reference) | `x / median(x over ok neighbors)`; all 6 neighbors must be in the table and ≥ 4 must be `ok` | `neighborhood_incomplete` (run extent), `neighborhood_insufficient_valid`, `neighborhood_reference_zero` (median 0; no epsilon), or the atomic status | pre-registered rule: finite for ≥ 50 % of eligible rows (0.84 / 0.71 met) | **publishable** with limitations | unbounded right tail where the neighborhood median is tiny (p95 18 in Mù Cang Chải); null for 41–62 % of mountain cells; null at the four-AOI extent |
| `local_ratio_k1_intersection_density_per_km2`, `…_poi_total_count_1km`, `…_food_drink_count_1km` | dimensionless | same | same | same | same | finite share 0.39 / 0.41 / 0.22 < 0.5 | diagnostic (`diagnostic_features.parquet`) | reference-zero dominates in rural AOIs |
| `<f>_mvp_pooled_percentile` (27 features: the 21 above + 6 ratios) | percentile [0, 1] in the cohort | Gate 3 atomic `f` | cohort `mvp_pooled::0.1.0::gate3_20260914T171148Z` = all 5,681 rows, cell-weighted | midrank ECDF `(W_below + 0.5·W_equal) / W_total` from `cohort_statistics.parquet` | atomic status; `cohort_too_small` (< 30 valid), `cohort_degenerate` (1 distinct value) | fit/apply separated; tie policy configured; AOI-equal weighting, min/max tie methods and leave-one-AOI-out measured | diagnostic — **not a national percentile** | value depends on which AOIs are in the table (mean shift up to 0.18 when one AOI is removed; up to 0.13 between weightings); zeros get 0.5 × zero share |
| `<f>_within_aoi_percentile` (27) | percentile [0, 1] in the AOI | same | cohort `within_aoi::<aoi_id>::…`, cell-weighted | same | same; 11 fits degenerate (all-zero AOI/feature), 4 too small (Hanoi assembly failures) | same | diagnostic | not comparable across AOIs (every AOI's median is 0.5) |
| `<f>_peer_percentile` | — | — | peer group = `aoi_context`, needs ≥ 2 AOIs per context | — | `peer_cohort_insufficient` | — | **blocked**, no column | one AOI per context in the input |
| `source_defined_ghs_smod_class` | — | GHS-SMOD R2023A | — | — | `source_not_acquired` | — | **blocked**, no column | source not acquired; no threshold substitute |
| any transform of a distance feature | — | — | — | — | — | — | deferred | distances are right-censored by the halo (`search_truncated_by_extract` on 41–59 % of rows); fitting on observed values would fit the near half |
