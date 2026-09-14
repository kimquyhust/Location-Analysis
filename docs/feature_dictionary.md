# Feature Dictionary — Atomic MVP v0.2

_Gate 1 reviewed definition. The spatial unit remains a Gate 2 decision. The complete disposition of the original draft is in [`gate1_technical_review.md`](gate1_technical_review.md). No customer mobility data or semantic scores are used._

## Shared contract

- **Grain:** one row per selected spatial unit. Identifiers and admin labels are metadata, not model features.
- **Version:** `feature_set_version=0.2.0`; a formula change requires a new version.
- **Normalization:** none in the atomic layer. Log transforms, percentiles, peer comparisons, and local ratios are Gate 4 experiments.
- **Metric operations:** use a locally suitable metric/equal-area CRS; store representative coordinates and output geometry in EPSG:4326.
- **POI counts:** include a canonical entity when its point or polygon `point_on_surface` is in the buffer around the unit representative point. Never count raw OSM elements.
- **Distances:** measure from the unit representative point to original geometry, never to a polygon centroid.
- **Raster aggregation:** use area-conserving/area-weighted aggregation over the unit footprint and record valid coverage.
- **Zero vs missing:** `0` is allowed only after a successful complete query with no matches. Missing tiles, technical non-coverage, and failed ingestion produce `null` plus source status. OSM zero means zero mapped entities, not proven real-world absence.
- **Distance not found:** return `null` plus `not_found_within_cap`; source failure is `source_unavailable`. Search caps come from `config/spatial.yaml` and are not substituted as feature values.
- **Refresh:** recompute when a pinned source, taxonomy, formula, or spatial representation changes.

Required metadata/source-status fields are in `config/features.yaml`. Detailed lineage lives in manifests keyed by `run_id` and `source_manifest_id`.

## Population and physical environment

| Feature | Unit | Source | Calculation / scope | Missing policy | Main limitation |
|---|---|---|---|---|---|
| `population_count` | people | WorldPop Global 2 R2025A v1, pinned year, 100 m constrained count | Area-conserving sum over unit footprint; boundary pixels apportioned by overlap | Null if raster coverage is incomplete | Modeled dasymetric estimate, not direct census |
| `population_density` | people/km² | Derived | `population_count / valid_land_support_area_km2` | Null if count missing or denominator zero | Sensitive to population model and land mask |
| `built_up_ratio` | ratio [0,1] | GHS-BUILT-S R2023A 100 m, pinned epoch | Sum built-up surface m² / valid unit land-support m² | Null if coverage incomplete/denominator zero | Modeled; R2023A 100 m is not the separate 10 m E2018 product |
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
| `transit_stop_count_1km` | count | Canonical OSM bus/rail stop entities | Deduplicated stop count in 1 km buffer | Zero only after successful complete query | Nationwide OSM transit completeness is unknown |
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
| `osm_industrial_site_area_ratio` | ratio [0,1] | OSM `landuse=industrial` polygons | Polygon intersection area / valid unit land-support area | Null on source failure; zero after successful query | Explicitly mapped industrial land, not authoritative zoning |
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
