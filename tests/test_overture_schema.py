"""Offline schema-assumption tests for Overture Places/Transportation
loading code -- no network access, a tiny synthetic local GeoParquet
fixture stands in for a real AOI subset. These catch a code change that
silently stops reading a field the audits depend on (e.g. `basic_category`,
`sources`, `confidence`) without needing a live S3 fetch.
"""

from pathlib import Path

import duckdb

from ingestion.acquire_overture import REQUIRED_COLUMNS
from poi.overture_places import load_overture_places, provider_summary


def _build_places_fixture(path: Path):
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    con.execute(f"""
        COPY (
            SELECT * FROM (VALUES
                (
                    'id-1', 'restaurant',
                    {{'primary': 'restaurant', 'hierarchy': ['restaurant'], 'alternates': []}},
                    0.8,
                    {{'primary': 'Pho Place', 'common': MAP {{}}, 'rules': []}},
                    [
                        {{'property': NULL, 'dataset': 'meta', 'license': NULL, 'record_id': NULL,
                          'update_time': NULL, 'confidence': 0.8, 'between': NULL,
                          'provider': 'meta', 'resource': NULL, 'version': NULL}},
                        {{'property': NULL, 'dataset': 'microsoft', 'license': NULL, 'record_id': NULL,
                          'update_time': NULL, 'confidence': 0.7, 'between': NULL,
                          'provider': 'microsoft', 'resource': NULL, 'version': NULL}}
                    ],
                    ['https://example.com'], CAST([] AS VARCHAR[]), CAST([] AS VARCHAR[]),
                    ST_Point(108.2, 16.0),
                    {{'xmin': 108.2, 'xmax': 108.2, 'ymin': 16.0, 'ymax': 16.0}}
                ),
                (
                    'id-2', NULL,
                    {{'primary': NULL, 'hierarchy': CAST([] AS VARCHAR[]), 'alternates': CAST([] AS VARCHAR[])}},
                    0.2,
                    {{'primary': 'Unnamed Place', 'common': MAP {{}}, 'rules': []}},
                    [
                        {{'property': NULL, 'dataset': 'meta', 'license': NULL, 'record_id': NULL,
                          'update_time': NULL, 'confidence': 0.2, 'between': NULL,
                          'provider': 'meta', 'resource': NULL, 'version': NULL}}
                    ],
                    CAST([] AS VARCHAR[]), CAST([] AS VARCHAR[]), CAST([] AS VARCHAR[]),
                    ST_Point(108.21, 16.01),
                    {{'xmin': 108.21, 'xmax': 108.21, 'ymin': 16.01, 'ymax': 16.01}}
                )
            ) AS t(id, basic_category, taxonomy, confidence, names, sources, websites, phones, socials, geometry, bbox)
        ) TO '{path}' (FORMAT PARQUET)
    """)
    con.close()


def test_places_fixture_has_all_required_columns(tmp_path):
    path = tmp_path / "places.parquet"
    _build_places_fixture(path)
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    cols = {row[0] for row in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{path}')").fetchall()}
    con.close()
    required = REQUIRED_COLUMNS["places"]["place"]
    assert required.issubset(cols), f"missing: {required - cols}"


def test_load_overture_places_reads_synthetic_fixture(tmp_path):
    parquet_path = tmp_path / "places.parquet"
    _build_places_fixture(parquet_path)

    crosswalk_path = tmp_path / "crosswalk.yaml"
    crosswalk_path.write_text("mapping:\n  food_drink: [restaurant]\n")
    taxonomy_path = Path("config/poi_taxonomy.yaml")

    gdf = load_overture_places(parquet_path, taxonomy_path=taxonomy_path, crosswalk_path=crosswalk_path)

    assert len(gdf) == 2
    row1 = gdf[gdf["id"] == "id-1"].iloc[0]
    assert row1["canonical_category"] == "food_drink"
    assert row1["contributing_provider_count"] == 2
    assert row1["is_multi_provider"]
    assert set(row1["contributing_providers"]) == {"meta", "microsoft"}
    assert row1["has_website"]
    assert not row1["has_phone"]

    row2 = gdf[gdf["id"] == "id-2"].iloc[0]
    assert row2["missing_category"]
    assert row2["contributing_provider_count"] == 1


def test_provider_summary_counts_multi_provider_records(tmp_path):
    parquet_path = tmp_path / "places.parquet"
    _build_places_fixture(parquet_path)
    crosswalk_path = tmp_path / "crosswalk.yaml"
    crosswalk_path.write_text("mapping:\n  food_drink: [restaurant]\n")

    gdf = load_overture_places(parquet_path, crosswalk_path=crosswalk_path)
    summary = provider_summary(gdf)

    assert summary["total_records"] == 2
    assert summary["multi_provider_record_count"] == 1
    assert summary["multi_provider_rate"] == 0.5
    assert summary["provider_appearance_counts"]["meta"] == 2
    assert summary["provider_appearance_counts"]["microsoft"] == 1
