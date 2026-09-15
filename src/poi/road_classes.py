"""Road-class acceptance rules from `config/features.yaml` `parameters.road_classes`.

Values are never hardcoded in feature/audit code -- everything reads this
module's `load_road_classes()` output.
"""

from __future__ import annotations

from pathlib import Path

import yaml

DEFAULT_FEATURES_PATH = Path("config/features.yaml")

_LINK_SUFFIX = "_link"


def load_road_classes(path: Path = DEFAULT_FEATURES_PATH) -> dict:
    with open(path) as f:
        cfg = yaml.safe_load(f)
    return cfg["parameters"]["road_classes"]


def load_intersection_params(path: Path = DEFAULT_FEATURES_PATH) -> dict:
    with open(path) as f:
        cfg = yaml.safe_load(f)
    return cfg["parameters"]["intersections"]


def base_highway_class(highway_value: str) -> str:
    if highway_value.endswith(_LINK_SUFFIX):
        return highway_value[: -len(_LINK_SUFFIX)]
    return highway_value


def classify_highway(highway_value: str, road_classes: dict) -> tuple[bool, bool, bool]:
    """Return (is_driveable, is_major, is_link) for a raw OSM `highway=*`
    value, honoring `include_link_variants`."""
    is_link = highway_value.endswith(_LINK_SUFFIX)
    include_links = road_classes.get("include_link_variants", False)
    if is_link and not include_links:
        return False, False, True

    base = base_highway_class(highway_value) if is_link else highway_value
    is_driveable = base in road_classes["all_driveable"]
    is_major = base in road_classes["major"]
    return is_driveable, is_major, is_link
