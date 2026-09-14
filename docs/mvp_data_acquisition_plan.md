# MVP data acquisition plan

Verified on 2026-09-14. This document is limited to source acquisition. It does not change the system architecture, spatial-unit decision, or feature definitions.

## Acquisition decision

Acquire these five products for the first prototype:

1. OpenStreetMap Vietnam, dated Geofabrik PBF snapshot.
2. WorldPop Global 2, 2025 constrained population count at approximately 100 m.
3. ESA WorldCover 2021 v200 at 10 m.
4. GHSL GHS-BUILT-S R2023A, epoch 2020, 100 m.
5. GHSL Urban Centre Database R2024A, version 1.2.

Do not acquire an administrative-boundary product for the first run. The proposed post-2025 OCHA COD-AB asset could not be tied to a stable public package, direct asset, and explicit package licence during verification. Overture Divisions is not a substitute until its 34-province and 3,321-commune coverage is measured. Administrative codes remain nullable prototype metadata; no model feature depends on them.

Overture Places and Transportation are optional coverage-audit sources, not inputs to the first feature build. This avoids combining duplicate OSM-derived records before a conflation rule exists.

## First prototype area

Use the Da Nang–Hoi An corridor rather than starting with a homogeneous city-centre tile.

| Extent | WGS84 bounding box `(west, south, east, north)` | Purpose |
|---|---|---|
| Evaluation AOI | `(108.10, 15.75, 108.35, 16.15)` | The area on which prototype coverage and feature distributions are reported. |
| Acquisition AOI | `(108.07, 15.72, 108.38, 16.18)` | Evaluation AOI plus an approximately 3 km halo, matching the largest MVP neighbourhood buffer. |

Use EPSG:4326 for source clipping and EPSG:32649 (WGS 84 / UTM zone 49N) for metric checks. The corridor contains dense Da Nang, airport/port and major roads, suburban development, the coastal strip, Hoi An tourism, cropland, water, and upland edges. It therefore exercises every core source and both dense and sparse POI conditions in one manageable run.

## Feature-to-source matrix

| Dataset | Feature groups supported | Exact MVP features |
|---|---|---|
| Geofabrik OpenStreetMap PBF | Roads and topology | `road_length_km`, `road_density_km_per_km2`, `major_road_length_km`, `intersection_density_per_km2`, `distance_nearest_major_road_m` |
| Geofabrik OpenStreetMap PBF | Mapped transport nodes | `transit_stop_count_1km`, `distance_nearest_transit_stop_m`, `distance_nearest_transport_hub_m` |
| Geofabrik OpenStreetMap PBF | Education, health, retail, tourism, and recreation POIs | `school_count_1km`, `higher_education_count_3km`, `distance_nearest_higher_education_m`, `hospital_count_3km`, `clinic_count_1km`, `pharmacy_count_1km`, `distance_nearest_hospital_m`, `food_drink_count_1km`, `retail_count_1km`, `marketplace_count_1km`, `mall_count_3km`, `lodging_count_1km`, `attraction_culture_count_3km`, `park_recreation_count_1km`, `distance_nearest_park_m`, `poi_total_count_1km`, `poi_category_richness_1km` |
| Geofabrik OpenStreetMap PBF | Observed mapped industrial land use | `osm_industrial_site_area_ratio`, `distance_nearest_osm_industrial_site_m` |
| WorldPop 2025 constrained count | Population | `population_count`, `population_density` |
| ESA WorldCover 2021 v200 | Land cover | `tree_cover_ratio`, `grass_shrub_ratio`, `cropland_ratio`, `water_wetland_ratio` |
| GHSL GHS-BUILT-S E2020 | Built-up surface | `built_up_ratio` |
| GHSL UCDB R2024A V1.2 | Reproducible urban-centre geometry | `distance_nearest_urban_centre_km` |

WorldCover is land cover, not zoning. OSM `landuse=industrial` is a mapped observation, not an authoritative industrial-zone designation. OSM transport features are mapped stops and hubs, not schedules or service frequency.

## Pinned asset register

| Source ID | Exact product and asset | Verified access and expected format | Licence | MVP subset |
|---|---|---|---|---|
| `osm_geofabrik_vnm_20260913` | Geofabrik `vietnam-260913.osm.pbf`; OSM data through 2026-09-13 | [Direct PBF](https://download.geofabrik.de/asia/vietnam-260913.osm.pbf), 328,456,722 bytes; binary OSM PBF | ODbL 1.0 | Country file is already Vietnam-only; extract the acquisition AOI to another PBF. |
| `worldpop_vnm_2025_cn_100m_r2025a_v1` | WorldPop Global 2 R2025A v1, 2025 constrained population count | [Direct GeoTIFF](https://data.worldpop.org/GIS/Population/Global_2015_2030/R2025A/2025/VNM/v1/100m/constrained/vnm_pop_2025_CN_100m_R2025A_v1.tif), 75,215,955 bytes; WGS84 GeoTIFF, people per cell | [Catalogue](https://hub.worldpop.org/geodata/summary?id=75408) lists CC BY 4.0, but its general notice assigns ODbL to OSM/Microsoft-derived products; archive the product-specific terms and confirm applicability before redistribution | Asset is already Vietnam-only; window it to the acquisition AOI without resampling. |
| `worldcover_2021_v200_n15e108` | ESA WorldCover 2021 v200 tile `N15E108` | [Direct COG](https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_N15E108_Map.tif), 11,813,732 bytes; 10 m categorical COG in EPSG:4326 | CC BY 4.0; see [data access](https://esa-worldcover.org/en/data-access) | This one 3°×3° tile contains the acquisition AOI; crop it locally. For national processing, intersect the official tile grid with the Vietnam geometry and download every intersecting tile. |
| `ghsl_built_s_e2020_r2023a_100m_r8_c29` | `GHS_BUILT_S_E2020_GLOBE_R2023A_54009_100_V1_0_R8_C29.zip` | [Direct tile ZIP](https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_BUILT_S_GLOBE_R2023A/GHS_BUILT_S_E2020_GLOBE_R2023A_54009_100/V1-0/tiles/GHS_BUILT_S_E2020_GLOBE_R2023A_54009_100_V1_0_R8_C29.zip), 17,069,829 bytes; ZIP containing a 100 m GeoTIFF in World Mollweide (ESRI:54009) | CC BY 4.0 in the product `copyright.txt` | Tile R8_C29 contains the acquisition AOI; crop in the native equal-area grid. For national processing, intersect Vietnam with the official GHSL 1,000 km tile grid. |
| `ghsl_ucdb_r2024a_v1_2` | `GHS_UCDB_GLOBE_R2024A_V1_2.zip` | [Direct global ZIP](https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_UCDB_GLOBE_R2024A/GHS_UCDB_GLOBE_R2024A/V1-2/GHS_UCDB_GLOBE_R2024A_V1_2.zip), approximately 264 MB; archive contains tabular data and geospatial urban-centre boundaries, including GeoPackage content | CC BY 4.0 on the [JRC dataset record](https://data.jrc.ec.europa.eu/dataset/1a338be6-7eaf-480c-9664-3a8ade88cbcd) | No official Vietnam archive is exposed. Download once, inspect the archive, and spatially filter the urban-centre boundary layer to Vietnam or the prototype search area. |

The 2025 WorldPop layer is an estimate, not a census surface. GHS-BUILT-S uses epoch 2020 because its 2025 and 2030 epochs are projections. WorldCover 2021 is the newest stable WorldCover map and must not be described as current 2026 land cover.

## Download and subset procedure

These commands deliberately keep the provider asset unchanged under `data/raw` and write AOI subsets separately. Before running them, install `curl`, `osmium`, GDAL (`gdalinfo`, `gdal_translate`, `gdalwarp`, `ogrinfo`, `ogr2ogr`), and `unzip`.

### 1. Create acquisition directories

```bash
mkdir -p data/raw/osm data/raw/worldpop data/raw/worldcover data/raw/ghsl
mkdir -p data/prototype/danang_hoian_halo
```

### 2. OpenStreetMap

```bash
curl --fail --location --retry 3 \
  --output data/raw/osm/vietnam-260913.osm.pbf \
  https://download.geofabrik.de/asia/vietnam-260913.osm.pbf

osmium extract \
  --bbox 108.07,15.72,108.38,16.18 \
  --strategy complete_ways \
  --set-bounds \
  --output data/prototype/danang_hoian_halo/osm-260913.osm.pbf \
  data/raw/osm/vietnam-260913.osm.pbf
```

Use the same AOI PBF for roads, topology, POIs, transit nodes, parks, and industrial land-use polygons. Preserve OSM element IDs and all original tags before applying the canonical taxonomy.

### 3. WorldPop

```bash
curl --fail --location --retry 3 \
  --output data/raw/worldpop/vnm_pop_2025_CN_100m_R2025A_v1.tif \
  https://data.worldpop.org/GIS/Population/Global_2015_2030/R2025A/2025/VNM/v1/100m/constrained/vnm_pop_2025_CN_100m_R2025A_v1.tif

gdal_translate \
  -projwin 108.07 16.18 108.38 15.72 \
  -of COG -co COMPRESS=DEFLATE \
  data/raw/worldpop/vnm_pop_2025_CN_100m_R2025A_v1.tif \
  data/prototype/danang_hoian_halo/worldpop-2025-count.tif
```

`gdal_translate` windows the native grid and does not resample counts. Population density is derived later from summed population and the target unit's land area; do not average the count raster and call it density.

### 4. ESA WorldCover

```bash
curl --fail --location --retry 3 \
  --output data/raw/worldcover/ESA_WorldCover_10m_2021_v200_N15E108_Map.tif \
  https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_N15E108_Map.tif

gdal_translate \
  -projwin 108.07 16.18 108.38 15.72 \
  -of COG -co COMPRESS=DEFLATE \
  data/raw/worldcover/ESA_WorldCover_10m_2021_v200_N15E108_Map.tif \
  data/prototype/danang_hoian_halo/worldcover-2021-v200.tif
```

Use class 10 for tree cover, classes 20+30 for grass/shrub, class 40 for cropland, and classes 80+90+95 for water/wetland. Use nearest-neighbour if this categorical raster is ever reprojected.

### 5. GHSL built-up surface

```bash
curl --fail --location --retry 3 \
  --output data/raw/ghsl/GHS_BUILT_S_E2020_GLOBE_R2023A_54009_100_V1_0_R8_C29.zip \
  https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_BUILT_S_GLOBE_R2023A/GHS_BUILT_S_E2020_GLOBE_R2023A_54009_100/V1-0/tiles/GHS_BUILT_S_E2020_GLOBE_R2023A_54009_100_V1_0_R8_C29.zip

unzip -q \
  data/raw/ghsl/GHS_BUILT_S_E2020_GLOBE_R2023A_54009_100_V1_0_R8_C29.zip \
  -d data/raw/ghsl/built-s-e2020-r8-c29

gdalwarp \
  -te_srs EPSG:4326 -te 108.07 15.72 108.38 16.18 \
  -of COG -co COMPRESS=DEFLATE \
  data/raw/ghsl/built-s-e2020-r8-c29/GHS_BUILT_S_E2020_GLOBE_R2023A_54009_100_V1_0_R8_C29.tif \
  data/prototype/danang_hoian_halo/ghsl-built-s-e2020-100m.tif
```

The pixel value is built-up square metres within the 100 m cell. Expected valid values are 0–10,000 and NoData is 65,535. Keep the native equal-area grid for aggregation; do not treat the raw value as a percentage.

### 6. GHSL urban centres

```bash
curl --fail --location --retry 3 \
  --output data/raw/ghsl/GHS_UCDB_GLOBE_R2024A_V1_2.zip \
  https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_UCDB_GLOBE_R2024A/GHS_UCDB_GLOBE_R2024A/V1-2/GHS_UCDB_GLOBE_R2024A_V1_2.zip

unzip -l data/raw/ghsl/GHS_UCDB_GLOBE_R2024A_V1_2.zip
unzip -q data/raw/ghsl/GHS_UCDB_GLOBE_R2024A_V1_2.zip -d data/raw/ghsl/ucdb-r2024a-v1-2
```

Do not guess the internal layer name. Run `ogrinfo -ro -so` on the extracted GeoPackage, identify the 2025 urban-centre boundary layer, and record that resolved file and layer in the source manifest. For this prototype, retain all centres intersecting a 300 km buffer around the evaluation AOI; that matches the configured maximum search distance and prevents an edge-clipping false null. Save the result as `data/prototype/danang_hoian_halo/ghsl-ucdb-2025-search.gpkg`.

## Optional Overture coverage audit

The verified current release is `2026-08-19.0` with schema `v1.18.0`. It is available at `s3://overturemaps-us-west-2/release/2026-08-19.0/`; Overture retains public release files for at most 60 days. If the audit is run, use the pinned S3 path rather than a CLI command that silently selects “latest.”

Query only the acquisition AOI from:

- `theme=places/type=place/*` for an independent POI coverage comparison.
- `theme=transportation/type=segment/*` for a road-coverage comparison, while documenting its substantial OSM lineage.

Write results as GeoParquet. Overture remains QA-only until category mapping, duplicate rates, and incremental coverage are measured. The [official DuckDB guide](https://docs.overturemaps.org/getting-data/duckdb/) gives the bbox-pushdown query pattern.

## Acquisition validation and hand-off

The acquisition is complete only when all of the following are recorded for each asset:

- exact source ID, product, release/epoch, represented date, retrieval UTC, URL, byte count, SHA-256, licence, CRS, bounds, and local path;
- HTTP success and byte count matching the pinned register, or a documented provider revision;
- `osmium fileinfo` confirms the OSM snapshot timestamp and the AOI extract bounds;
- `gdalinfo` confirms CRS, resolution, bounds, band type, and NoData for every raster;
- WorldCover values are limited to documented class codes;
- GHSL built-up valid cells fall within 0–10,000 square metres;
- each raster covers at least 99.9% of the evaluation AOI after excluding documented source NoData;
- UCDB produces at least one plausible urban centre in or near the Da Nang–Hoi An corridor;
- OSM produces non-zero roads and at least one mapped POI in each broad group expected locally; zero categories are retained as coverage findings, not silently imputed.

Example checksum command:

```bash
shasum -a 256 \
  data/raw/osm/vietnam-260913.osm.pbf \
  data/raw/worldpop/vnm_pop_2025_CN_100m_R2025A_v1.tif \
  data/raw/worldcover/ESA_WorldCover_10m_2021_v200_N15E108_Map.tif \
  data/raw/ghsl/GHS_BUILT_S_E2020_GLOBE_R2023A_54009_100_V1_0_R8_C29.zip \
  data/raw/ghsl/GHS_UCDB_GLOBE_R2024A_V1_2.zip
```

## Stop conditions

Stop before feature computation if any core URL no longer resolves, a byte count changed without a release note, CRS/NoData differs from the expected metadata, licence text cannot be archived, or the AOI is not fully covered. Do not replace a failed product with its fallback silently; a fallback is a new pinned acquisition decision.
