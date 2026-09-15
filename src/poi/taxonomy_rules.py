"""Rule engine for `config/poi_taxonomy.yaml`.

Maps a raw OSM tag dict to at most one canonical leaf category, honoring
`category_precedence` (first match wins, most-specific categories listed
first) and `exclude_if_matches` (belt-and-suspenders exclusion even where
precedence order should already prevent the conflict). Pure function, no
I/O in the matching path -- testable in isolation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

DEFAULT_TAXONOMY_PATH = Path("config/poi_taxonomy.yaml")


def load_taxonomy(path: Path = DEFAULT_TAXONOMY_PATH) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def _clause_matches(clause: dict, tags: dict) -> bool:
    if "all" in clause:
        return all(_clause_matches(c, tags) for c in clause["all"])
    key = clause["key"]
    values = clause["values"]
    if key not in tags:
        return False
    if "*" in values:
        return True
    return tags[key] in values


def _category_matches(cat_def: dict, tags: dict) -> bool:
    return any(_clause_matches(clause, tags) for clause in cat_def.get("match_any", []))


def match_canonical_category(tags: dict, taxonomy: dict) -> Optional[str]:
    """Return the highest-precedence canonical leaf category matching
    `tags`, or None if no rule matches."""
    if not tags:
        return None
    categories = taxonomy["canonical_categories"]
    precedence = taxonomy["entity_policy"]["category_precedence"]
    for cat_name in precedence:
        cat_def = categories.get(cat_name)
        if cat_def is None or not _category_matches(cat_def, tags):
            continue
        excludes = cat_def.get("exclude_if_matches", [])
        if excludes and any(
            other in categories and _category_matches(categories[other], tags)
            for other in excludes
        ):
            continue
        return cat_name
    return None


def match_area_category(tags: dict, taxonomy: dict) -> Optional[str]:
    """Match against `area_categories` (industrial_site, park_area, ...),
    which sit outside the point-count taxonomy and are measured by area/
    distance to geometry rather than counted as entities."""
    if not tags:
        return None
    for name, cat_def in taxonomy.get("area_categories", {}).items():
        if _category_matches(cat_def, tags):
            return name
    return None


def canonical_group(category: str, taxonomy: dict) -> Optional[str]:
    cat_def = taxonomy["canonical_categories"].get(category)
    return cat_def["group"] if cat_def else None


def all_canonical_categories(taxonomy: dict) -> list[str]:
    return list(taxonomy["canonical_categories"].keys())
