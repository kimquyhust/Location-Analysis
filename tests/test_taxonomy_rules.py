from pathlib import Path

from poi.taxonomy_rules import (
    load_taxonomy,
    match_area_category,
    match_canonical_category,
)

TAXONOMY = load_taxonomy(Path("config/poi_taxonomy.yaml"))


def test_simple_match():
    assert match_canonical_category({"amenity": "school"}, TAXONOMY) == "school"
    assert match_canonical_category({"amenity": "hospital"}, TAXONOMY) == "hospital"


def test_no_match_returns_none():
    assert match_canonical_category({"highway": "residential"}, TAXONOMY) is None
    assert match_canonical_category({}, TAXONOMY) is None


def test_wildcard_shop_matches_retail_other():
    assert match_canonical_category({"shop": "florist"}, TAXONOMY) == "retail_other"


def test_exclude_if_matches_prevents_retail_other_for_convenience():
    # A shop=convenience node matches BOTH the wildcard retail_other rule
    # and the specific convenience rule -- precedence + exclude_if_matches
    # must resolve it to the specific category, never the generic one.
    assert match_canonical_category({"shop": "convenience"}, TAXONOMY) == "convenience"
    assert match_canonical_category({"shop": "supermarket"}, TAXONOMY) == "supermarket"
    assert match_canonical_category({"shop": "mall"}, TAXONOMY) == "mall"


def test_precedence_prefers_more_specific_transport_category():
    # A node tagged as both a bus stop and (hypothetically) matching a
    # lower-precedence rule should resolve to the higher-precedence one.
    tags = {"public_transport": "station", "bus": "yes"}
    assert match_canonical_category(tags, TAXONOMY) == "transport_bus_station"


def test_all_clause_requires_every_subclause():
    # transport_bus_stop's `all` clause requires public_transport=platform
    # AND bus=yes; supplying only one must not match.
    assert match_canonical_category({"public_transport": "platform"}, TAXONOMY) is None
    assert match_canonical_category({"public_transport": "platform", "bus": "yes"}, TAXONOMY) == "transport_bus_stop"


def test_area_category_industrial_site():
    assert match_area_category({"landuse": "industrial"}, TAXONOMY) == "industrial_site"
    assert match_area_category({"landuse": "residential"}, TAXONOMY) is None
