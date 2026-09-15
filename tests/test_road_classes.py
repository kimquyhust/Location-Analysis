from pathlib import Path

from poi.road_classes import classify_highway, load_road_classes

ROAD_CLASSES = load_road_classes(Path("config/features.yaml"))


def test_basic_driveable_and_major():
    is_driveable, is_major, is_link = classify_highway("motorway", ROAD_CLASSES)
    assert is_driveable and is_major and not is_link

    is_driveable, is_major, is_link = classify_highway("residential", ROAD_CLASSES)
    assert is_driveable and not is_major and not is_link


def test_non_driveable_class_rejected():
    is_driveable, is_major, is_link = classify_highway("footway", ROAD_CLASSES)
    assert not is_driveable
    assert not is_major


def test_link_variant_included_per_config():
    assert ROAD_CLASSES["include_link_variants"] is True
    is_driveable, is_major, is_link = classify_highway("motorway_link", ROAD_CLASSES)
    assert is_driveable and is_major and is_link

    is_driveable, is_major, is_link = classify_highway("residential_link", ROAD_CLASSES)
    # "residential_link" isn't a real OSM tag, but the base-class logic
    # should still resolve it via the same rule as motorway_link.
    assert is_driveable and not is_major and is_link


def test_link_variant_excluded_when_config_disables_it():
    disabled_classes = dict(ROAD_CLASSES)
    disabled_classes["include_link_variants"] = False
    is_driveable, is_major, is_link = classify_highway("motorway_link", disabled_classes)
    assert not is_driveable
    assert not is_major
    assert is_link
