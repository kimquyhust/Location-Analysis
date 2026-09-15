"""Load an AOI Overture Places GeoParquet subset, map `basic_category` to
the same canonical categories used for OSM (config/poi_taxonomy.yaml), and
compute the per-record audit fields (confidence, ALL contributing
providers, contact-info presence, missing name/category) needed by
src/audit/poi_audit.py.

Provider analysis considers the FULL `sources[]` array, not just the first
non-Overture entry -- a record can carry multiple independent contributing
providers, and collapsing that down to "primary provider" hides genuine
multi-source corroboration (or the lack of it).
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import geopandas as gpd
import pandas as pd
import yaml

from .taxonomy_rules import canonical_group, load_taxonomy

DEFAULT_CROSSWALK_PATH = Path("config/overture_category_crosswalk.yaml")
WGS84 = "EPSG:4326"


def load_crosswalk(path: Path = DEFAULT_CROSSWALK_PATH) -> dict:
    with open(path) as f:
        cfg = yaml.safe_load(f)
    lookup = {}
    for canonical, basic_categories in cfg["mapping"].items():
        for bc in basic_categories:
            lookup[bc] = canonical
    return lookup


def _contributing_providers(sources) -> list[str]:
    """All DISTINCT non-"overture" providers listed in `sources[]` for a
    record (every record also carries an "overture" meta-provider entry,
    which is excluded here since it is not an independent data source)."""
    if sources is None or len(sources) == 0:
        return []
    seen = []
    for s in sources:
        p = s.get("provider")
        if p and p != "overture" and p not in seen:
            seen.append(p)
    return seen


def load_overture_places(
    parquet_path: Path,
    taxonomy_path: Path = Path("config/poi_taxonomy.yaml"),
    crosswalk_path: Path = DEFAULT_CROSSWALK_PATH,
) -> gpd.GeoDataFrame:
    taxonomy = load_taxonomy(taxonomy_path)
    crosswalk = load_crosswalk(crosswalk_path)

    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    df = con.execute(f"""
        SELECT
            id,
            basic_category,
            taxonomy.primary AS taxonomy_primary,
            confidence,
            names.primary AS name,
            sources,
            websites,
            phones,
            socials,
            ST_X(geometry) AS lon,
            ST_Y(geometry) AS lat
        FROM read_parquet('{parquet_path}')
    """).fetchdf()
    con.close()

    df["canonical_category"] = df["basic_category"].map(crosswalk)
    df["group"] = df["canonical_category"].apply(
        lambda c: canonical_group(c, taxonomy) if pd.notna(c) else None
    )
    df["contributing_providers"] = df["sources"].apply(_contributing_providers)
    df["contributing_provider_count"] = df["contributing_providers"].apply(len)
    df["is_multi_provider"] = df["contributing_provider_count"] > 1
    df["missing_name"] = df["name"].isna() | (df["name"].astype(str).str.strip() == "")
    df["missing_category"] = df["basic_category"].isna()

    def _nonempty_list(x):
        if x is None:
            return False
        try:
            if pd.isna(x):
                return False
        except (TypeError, ValueError):
            pass  # x is array-like (e.g. a real list/ndarray) -- isna would be elementwise; fall through
        return len(x) > 0

    df["has_website"] = df["websites"].apply(_nonempty_list)
    df["has_phone"] = df["phones"].apply(_nonempty_list)
    df["has_social"] = df["socials"].apply(_nonempty_list)
    df["has_any_contact_info"] = df["has_website"] | df["has_phone"] | df["has_social"]

    gdf = gpd.GeoDataFrame(
        df.drop(columns=["lon", "lat"]),
        geometry=gpd.points_from_xy(df["lon"], df["lat"]),
        crs=WGS84,
    )
    return gdf


def provider_appearance_counts(gdf: gpd.GeoDataFrame) -> pd.Series:
    """How many records EACH provider appears in (not mutually exclusive --
    a record with 2 providers counts toward both)."""
    exploded = gdf["contributing_providers"].explode()
    return exploded.value_counts()


def provider_summary(gdf: gpd.GeoDataFrame) -> dict:
    n = len(gdf)
    if n == 0:
        return {}
    appearance = provider_appearance_counts(gdf)
    multi = int(gdf["is_multi_provider"].sum())
    zero_provider = int((gdf["contributing_provider_count"] == 0).sum())
    single_provider_breakdown = (
        gdf[gdf["contributing_provider_count"] == 1]["contributing_providers"]
        .apply(lambda lst: lst[0]).value_counts().to_dict()
    )
    return {
        "total_records": n,
        "provider_appearance_counts": appearance.to_dict(),
        "provider_appearance_rate": (appearance / n).round(4).to_dict(),
        "multi_provider_record_count": multi,
        "multi_provider_rate": round(multi / n, 4),
        "zero_provider_record_count": zero_provider,
        "single_provider_breakdown": single_provider_breakdown,
    }
