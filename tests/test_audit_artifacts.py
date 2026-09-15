"""Schema/shape tests for the manually-produced audit evidence CSVs
(`manual_confidence_spot_check.csv`, `unmatched_major_road_inspection.csv`).
These are hand-curated (web-search/API-verified) artifacts, not pipeline
output, but the review found the first version of one of them could not
even be parsed by pandas (an unescaped quote broke column alignment
partway through the file) -- these tests catch that class of regression by
actually loading the files with pandas (the same parser the report's own
summary tables are computed with) and checking their exact expected shape.
"""
from pathlib import Path

import pandas as pd
import pytest

AUDIT_DIR = Path("data/prototype/danang_hoian_halo/audit")


@pytest.mark.skipif(not (AUDIT_DIR / "manual_confidence_spot_check.csv").exists(), reason="audit artifact not present")
def test_manual_confidence_spot_check_has_16_rows_and_controlled_vocabulary():
    df = pd.read_csv(AUDIT_DIR / "manual_confidence_spot_check.csv")

    assert len(df) == 16
    assert list(df.columns) == [
        "category", "band", "overture_id", "name", "confidence",
        "has_website", "has_phone", "web_search_verdict", "notes",
    ]
    allowed_verdicts = {"corroborated", "corroborated_partial", "not_corroborated", "weak"}
    assert set(df["web_search_verdict"].unique()) <= allowed_verdicts
    assert set(df["band"].unique()) == {"high", "low"}
    assert (df.groupby("band").size() == 8).all()


@pytest.mark.skipif(not (AUDIT_DIR / "manual_confidence_spot_check.csv").exists(), reason="audit artifact not present")
def test_manual_confidence_spot_check_low_band_verdict_counts_match_review():
    # These exact counts were the specific numbers the review found
    # misreported in Revision 2's report text (5/1/2 instead of 3/2/2/1) --
    # pinned here so a future edit of this artifact can't silently drift
    # from what the report claims without a test noticing.
    df = pd.read_csv(AUDIT_DIR / "manual_confidence_spot_check.csv")
    low = df[df["band"] == "low"]
    counts = low["web_search_verdict"].value_counts().to_dict()

    assert counts.get("corroborated", 0) == 3
    assert counts.get("corroborated_partial", 0) == 2
    assert counts.get("not_corroborated", 0) == 2
    assert counts.get("weak", 0) == 1


@pytest.mark.skipif(not (AUDIT_DIR / "unmatched_major_road_inspection.csv").exists(), reason="audit artifact not present")
def test_unmatched_major_road_inspection_has_10_records_2_osm_8_overture():
    df = pd.read_csv(AUDIT_DIR / "unmatched_major_road_inspection.csv")

    assert len(df) == 10
    assert list(df.columns) == [
        "source", "id", "lat", "lon", "inspection_method", "source_url", "checked_at_utc", "finding",
    ]
    counts = df["source"].value_counts().to_dict()
    assert counts.get("osm", 0) == 2
    assert counts.get("overture", 0) == 8


@pytest.mark.skipif(not (AUDIT_DIR / "unmatched_major_road_inspection.csv").exists(), reason="audit artifact not present")
def test_unmatched_major_road_inspection_method_and_evidence_are_consistent():
    df = pd.read_csv(AUDIT_DIR / "unmatched_major_road_inspection.csv")

    assert set(df["inspection_method"].unique()) <= {"direct", "inferred", "not_checked"}
    direct = df[df["inspection_method"] == "direct"]
    # Every directly-inspected record must carry a source URL and a
    # checked-at timestamp -- that provenance is the whole point of the fix.
    assert direct["source_url"].notna().all()
    assert (direct["source_url"].str.len() > 0).all()
    assert direct["checked_at_utc"].notna().all()

    not_direct = df[df["inspection_method"] != "direct"]
    # Records that were NOT directly inspected must not carry a fabricated
    # source_url/checked_at.
    assert not_direct["source_url"].isna().all()
    assert not_direct["checked_at_utc"].isna().all()


@pytest.mark.skipif(not (AUDIT_DIR / "unmatched_major_road_inspection.csv").exists(), reason="audit artifact not present")
def test_overture_road_inspection_groups_are_mutually_exclusive_and_sum_to_eight():
    """§3.4's four inspection outcomes must partition the 8 Overture-only
    samples. A prior revision labelled the not-directly-confirmed group
    "3 of 8" while listing four records under it; these counts are pinned
    so the report's arithmetic cannot drift from the artifact again.
    """
    df = pd.read_csv(AUDIT_DIR / "unmatched_major_road_inspection.csv")
    ov = df[df["source"] == "overture"]
    assert len(ov) == 8

    direct = ov[ov["inspection_method"] == "direct"]
    construction = direct[direct["finding"].str.contains("highway=construction", regex=False)]
    non_construction = direct[~direct["finding"].str.contains("highway=construction", regex=False)]

    confirmed_construction = len(construction)
    confirmed_non_construction = len(non_construction)
    inferred = int((ov["inspection_method"] == "inferred").sum())
    not_checked = int((ov["inspection_method"] == "not_checked").sum())

    assert confirmed_construction == 3
    assert confirmed_non_construction == 2
    assert inferred == 2
    assert not_checked == 1
    assert confirmed_construction + confirmed_non_construction + inferred + not_checked == 8

    # The two directly-confirmed non-construction roads are one
    # unclassified and one tertiary -- not a second construction pair.
    findings = " | ".join(non_construction["finding"])
    assert "highway=unclassified" in findings
    assert "highway=tertiary" in findings


@pytest.mark.skipif(not (AUDIT_DIR / "manual_confidence_spot_check.csv").exists(), reason="audit artifact not present")
def test_manual_sample_covers_only_food_drink_and_lodging():
    """The manual evidence is restricted to two leaf categories. Any group
    recommendation that claims manual support must be traceable to one of
    them (`food_drink` -> group commercial, `lodging` -> group tourism);
    retail, healthcare, and commercial_service have no manual record at
    all. Pinned here so a report edit cannot quietly widen the sample's
    apparent reach.
    """
    df = pd.read_csv(AUDIT_DIR / "manual_confidence_spot_check.csv")
    assert set(df["category"].unique()) == {"food_drink", "lodging"}
    assert (df.groupby("category").size() == 8).all()
    assert (df.groupby(["category", "band"]).size() == 4).all()
