"""Parse an AOI-clipped OSM PBF into POI, road, and area-category
GeoDataFrames using the canonical taxonomy (`config/poi_taxonomy.yaml`) and
road-class rules (`config/features.yaml`).

Road intersections are detected on a shared-node topology: for each
accepted driveable way, every node gets a degree contribution (1 for an
endpoint, 2 for an interior node) summed across all ways that reference it;
nodes with total degree >= `minimum_degree` are intersections. This never
counts a geometric crossing that does not share an OSM node, matching
`config/features.yaml`'s `count_geometric_crossings_without_shared_node:
false`. No divided-carriageway collapsing is performed (`collapse_
divided_carriageways: false`), so parallel one-way carriageways are kept
as separate ways/degree contributions -- a known, documented source of
inflated apparent intersection density where roads are divided.

Entity geometry (Gate 3 remediation F1):

- POLYGONS come from libosmium's area assembler (pyosmium `area` callback):
  closed ways AND `type=multipolygon` / `type=boundary` relations are
  assembled with their outer and inner rings, so a campus with a courtyard
  hole or a park in two pieces is one MultiPolygon entity, not a skipped
  relation. Assembly needs two passes over the file; pyosmium does that
  when the handler defines `area`.
- GROUPING relations (`type=site`, `type=public_transport`, ...) carrying a
  category tag are not polygons; they become one entity whose geometry is
  the union of their members' geometries, but only when EVERY member is in
  the extract. Member ids are collected in a relation-only pre-pass so the
  members can be retained on the main pass.
- OPEN ways carrying a category tag (bus platforms drawn as a line, a
  street tagged `tourism=attraction`) become LineString entities; the
  taxonomy's count representation is `point_on_surface`, which lies on the
  line, and distances go to the line itself.
- IDENTITY: a relation and one of its member ways that both carry the
  same category are the same place. The member is dropped as a duplicate
  (recorded, never silently) so the place is counted once.
- FAILURE is never silent. A relevant relation whose area libosmium could
  not build (typically a member way that lies entirely outside the halo
  clip), a grouping relation with a missing member, or a closed way that
  produced no area, is listed in `assembly.failed_entities` and counted per
  category in `assembly_failures_by_category`. The feature layer turns
  those counts into `entity_assembly_failed` statuses for every feature
  that reads the category, so a missing entity never becomes a zero.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import geopandas as gpd
import networkx as nx
import osmium
import shapely
import shapely.geometry as sgeom
from shapely.ops import unary_union

from .road_classes import classify_highway, load_road_classes
from .taxonomy_rules import (
    canonical_group,
    load_taxonomy,
    match_area_category,
    match_canonical_category,
)

WGS84 = "EPSG:4326"

# Relation types libosmium assembles into areas (outer/inner rings).
AREA_RELATION_TYPES = {"multipolygon", "boundary"}

POI_COLUMNS = ["osm_type", "osm_id", "category", "group", "name", "tag_count", "raw_tags", "geometry"]
AREA_COLUMNS = ["osm_type", "osm_id", "area_category", "name", "raw_tags", "geometry"]
ROAD_COLUMNS = ["osm_type", "osm_id", "highway", "is_major", "geometry"]


@dataclass
class _RelevantRelation:
    osm_id: int
    relation_type: str
    poi_category: str | None
    area_category: str | None
    tags: dict
    members: list[tuple[str, int, str]]   # (type: n/w/r, ref, role)


class _RelationPrePass(osmium.SimpleHandler):
    """First pass over relations only: which relations carry a category
    tag, and which members they reference."""

    def __init__(self, taxonomy: dict):
        super().__init__()
        self.taxonomy = taxonomy
        self.relevant: dict[int, _RelevantRelation] = {}
        self.relation_count = 0

    def relation(self, r):
        self.relation_count += 1
        tags = {t.k: t.v for t in r.tags}
        if not tags:
            return
        poi_cat = match_canonical_category(tags, self.taxonomy)
        area_cat = match_area_category(tags, self.taxonomy)
        if not (poi_cat or area_cat):
            return
        self.relevant[r.id] = _RelevantRelation(
            osm_id=r.id, relation_type=tags.get("type", ""), poi_category=poi_cat, area_category=area_cat,
            tags=dict(tags), members=[(m.type, m.ref, m.role) for m in r.members],
        )


class _OsmHandler(osmium.SimpleHandler):
    def __init__(self, taxonomy: dict, road_classes: dict, relevant_relations: dict[int, _RelevantRelation]):
        super().__init__()
        self.taxonomy = taxonomy
        self.road_classes = road_classes
        self.relevant_relations = relevant_relations
        self.wkb = osmium.geom.WKBFactory()
        self.poi_rows: list[dict] = []
        self.road_rows: list[dict] = []
        self.area_rows: list[dict] = []
        self.node_location: dict[int, tuple] = {}
        self.road_graph = nx.MultiGraph()
        self.seen_way_ids: set[int] = set()
        # Closed ways carrying a category: the area callback must deliver
        # exactly one area per entry, otherwise the way is a failed entity.
        self.closed_relevant_ways: dict[int, tuple[str | None, str | None]] = {}
        self.way_areas_seen: set[int] = set()
        # Member geometries of every relevant relation are retained: grouping
        # relations are built from them, and a failed area relation reports
        # the bounds of the members that ARE in the extract for audit.
        self.grouping_member_ways: set[int] = {ref for r in relevant_relations.values() for t, ref, _ in r.members if t == "w"}
        self.grouping_member_nodes: set[int] = {ref for r in relevant_relations.values() for t, ref, _ in r.members if t == "n"}
        self.member_way_geometry: dict[int, object] = {}
        self.member_node_geometry: dict[int, object] = {}
        self.open_way_entity_counts: dict[str, int] = defaultdict(int)
        self.failed_entities: list[dict] = []

    # --- nodes ---------------------------------------------------------------
    def node(self, n):
        if not n.tags and n.id not in self.grouping_member_nodes:
            return
        if not n.location.valid():
            return
        point = sgeom.Point(n.location.lon, n.location.lat)
        if n.id in self.grouping_member_nodes:
            self.member_node_geometry[n.id] = point
        tags = {t.k: t.v for t in n.tags}
        category = match_canonical_category(tags, self.taxonomy)
        if category:
            self.poi_rows.append(self._poi_row("node", n.id, category, tags, point))

    # --- ways ------------------------------------------------------------------
    def way(self, w):
        self.seen_way_ids.add(w.id)
        tags = {t.k: t.v for t in w.tags}
        highway = tags.get("highway")
        coords, valid_ids = [], []
        for nd in w.nodes:
            if nd.location.valid():
                lon, lat = nd.location.lon, nd.location.lat
                coords.append((lon, lat))
                valid_ids.append(nd.ref)

        if highway:
            is_driveable, is_major, _is_link = classify_highway(highway, self.road_classes)
            if is_driveable:
                for ref, ll in zip(valid_ids, coords):
                    self.node_location[ref] = ll
                if len(coords) >= 2:
                    self.road_rows.append({
                        "osm_type": "way", "osm_id": w.id, "highway": highway, "is_major": is_major,
                        "geometry": sgeom.LineString(coords),
                    })
                    # Shared-node topology: one graph edge per consecutive
                    # node pair actually present in this way (a MultiGraph,
                    # so two ways sharing the same edge are NOT collapsed --
                    # each way's contribution to degree is preserved, matching
                    # `count_geometric_crossings_without_shared_node: false`
                    # and giving no special handling to divided carriageways,
                    # per `collapse_divided_carriageways: false`).
                    for a, b in zip(valid_ids[:-1], valid_ids[1:]):
                        self.road_graph.add_edge(a, b, way_id=w.id, highway=highway, is_major=is_major)

        is_closed = w.is_closed() and len(w.nodes) >= 4 and len(coords) >= 4
        if w.id in self.grouping_member_ways and len(coords) >= 2:
            self.member_way_geometry[w.id] = (
                sgeom.Polygon(coords) if is_closed and sgeom.Polygon(coords).is_valid else sgeom.LineString(coords)
            )

        if not tags:
            return
        poi_cat = match_canonical_category(tags, self.taxonomy)
        area_cat = match_area_category(tags, self.taxonomy)
        if not (poi_cat or area_cat):
            return
        if is_closed:
            # Polygon geometry arrives through the area callback.
            self.closed_relevant_ways[w.id] = (poi_cat, area_cat)
            return
        # Open way with a category tag: a linear entity (bus platform drawn
        # as a line, a street that is an attraction).
        if poi_cat:
            if len(coords) >= 2:
                self.poi_rows.append(self._poi_row("way", w.id, poi_cat, tags, sgeom.LineString(coords)))
                self.open_way_entity_counts[poi_cat] += 1
            else:
                self._fail("way", w.id, poi_cat, "open_way_without_locations")
        if area_cat:
            # An area category on an unclosed way has no area; it cannot be
            # measured and is not silently ignored.
            self._fail("way", w.id, area_cat, "area_tag_on_open_way")

    # --- assembled areas (closed ways + multipolygon/boundary relations) --------
    def area(self, a):
        tags = {t.k: t.v for t in a.tags}
        if not tags:
            return
        poi_cat = match_canonical_category(tags, self.taxonomy)
        area_cat = match_area_category(tags, self.taxonomy)
        if not (poi_cat or area_cat):
            return
        osm_type = "way" if a.from_way() else "relation"
        osm_id = a.orig_id()
        if osm_type == "way":
            self.way_areas_seen.add(osm_id)
        geom = None
        outer_rings, _inner = a.num_rings()
        if outer_rings > 0:
            try:
                geom = shapely.from_wkb(bytes.fromhex(self.wkb.create_multipolygon(a)))
            except Exception:  # libosmium could not serialise the rings
                geom = None
        geom = self._sanitize_polygon(geom)
        if geom is None:
            for cat in (poi_cat, area_cat):
                if cat:
                    self._fail(osm_type, osm_id, cat, "assembler_empty_or_invalid")
            return
        if poi_cat:
            self.poi_rows.append(self._poi_row(osm_type, osm_id, poi_cat, tags, geom))
        if area_cat:
            self.area_rows.append({
                "osm_type": osm_type, "osm_id": osm_id, "area_category": area_cat,
                "name": tags.get("name"), "raw_tags": dict(tags), "geometry": geom,
            })

    # --- helpers ---------------------------------------------------------------
    def _poi_row(self, osm_type: str, osm_id: int, category: str, tags: dict, geometry) -> dict:
        return {
            "osm_type": osm_type, "osm_id": osm_id, "category": category,
            "group": canonical_group(category, self.taxonomy), "name": tags.get("name"),
            "tag_count": len(tags), "raw_tags": dict(tags), "geometry": geometry,
        }

    def _fail(self, osm_type: str, osm_id: int, category: str, reason: str) -> None:
        rec = {"osm_type": osm_type, "osm_id": osm_id, "category": category, "reason": reason,
               "partial_bounds_wgs84": None}
        if osm_type == "relation" and osm_id in self.relevant_relations:
            present = [self.member_way_geometry[ref] for t, ref, _ in self.relevant_relations[osm_id].members
                       if t == "w" and ref in self.member_way_geometry]
            present += [self.member_node_geometry[ref] for t, ref, _ in self.relevant_relations[osm_id].members
                        if t == "n" and ref in self.member_node_geometry]
            if present:
                rec["partial_bounds_wgs84"] = [float(v) for v in unary_union(present).bounds]
        self.failed_entities.append(rec)

    @staticmethod
    def _sanitize_polygon(geom):
        if geom is None or geom.is_empty:
            return None
        if not geom.is_valid:
            geom = geom.buffer(0)
        if geom.is_empty or geom.area <= 0:
            return None
        if geom.geom_type == "MultiPolygon" and len(geom.geoms) == 1:
            geom = geom.geoms[0]
        return geom


@dataclass
class OsmAoiExtract:
    poi_gdf: gpd.GeoDataFrame
    road_gdf: gpd.GeoDataFrame
    area_gdf: gpd.GeoDataFrame
    intersections_gdf: gpd.GeoDataFrame
    road_graph: nx.MultiGraph
    road_node_location: dict
    relation_count: int
    assembly: dict                       # per-category relation/way assembly report
    assembly_failures_by_category: dict  # category -> failed relevant entities
    member_duplicates: list[dict]        # relation/member pairs collapsed to one entity
    open_way_entity_counts: dict
    minimum_degree: int
    stats: dict = field(default_factory=dict)


def _finish_relations(handler: _OsmHandler) -> tuple[list[dict], list[dict]]:
    """Reconcile every relevant relation against what the assembler
    produced; build grouping-relation entities; drop member duplicates.
    Returns (extra_poi_rows, member_duplicates)."""
    assembled_rel_poi = {(r["osm_type"], r["osm_id"]): r for r in handler.poi_rows if r["osm_type"] == "relation"}
    assembled_rel_area = {(r["osm_type"], r["osm_id"]): r for r in handler.area_rows if r["osm_type"] == "relation"}
    extra_rows: list[dict] = []
    for rel in handler.relevant_relations.values():
        if rel.relation_type in AREA_RELATION_TYPES:
            for cat, table in ((rel.poi_category, assembled_rel_poi), (rel.area_category, assembled_rel_area)):
                if cat and ("relation", rel.osm_id) not in table:
                    already = any(f["osm_type"] == "relation" and f["osm_id"] == rel.osm_id and f["category"] == cat
                                  for f in handler.failed_entities)
                    if not already:
                        missing = [ref for t, ref, _ in rel.members if t == "w" and ref not in handler.seen_way_ids]
                        handler._fail("relation", rel.osm_id, cat,
                                      "members_missing_from_extract" if missing else "assembler_no_area")
            continue
        # Grouping relation: union of member geometries, all members required.
        geoms, missing, nested = [], [], []
        for t, ref, _role in rel.members:
            if t == "w":
                g = handler.member_way_geometry.get(ref)
                (geoms.append(g) if g is not None else missing.append(ref))
            elif t == "n":
                g = handler.member_node_geometry.get(ref)
                (geoms.append(g) if g is not None else missing.append(ref))
            else:
                nested.append(ref)
        reason = None
        if nested:
            reason = "nested_relation_member"
        elif missing:
            reason = "members_missing_from_extract"
        elif not geoms:
            reason = "no_members"
        if reason:
            for cat in (rel.poi_category, rel.area_category):
                if cat:
                    handler._fail("relation", rel.osm_id, cat, reason)
            continue
        geom = unary_union(geoms)
        if geom.is_empty:
            for cat in (rel.poi_category, rel.area_category):
                if cat:
                    handler._fail("relation", rel.osm_id, cat, "empty_union")
            continue
        if rel.poi_category:
            extra_rows.append(handler._poi_row("relation", rel.osm_id, rel.poi_category, rel.tags, geom))
        if rel.area_category:
            # A grouping relation is not an area; an area category on it
            # cannot be measured by intersection area.
            handler._fail("relation", rel.osm_id, rel.area_category, "area_category_on_grouping_relation")

    handler.poi_rows.extend(extra_rows)

    # Relation/member identity: a member carrying the same category as an
    # assembled relation is the same place -> keep the relation, drop the member.
    assembled = {("relation", r["osm_id"]) for r in handler.poi_rows if r["osm_type"] == "relation"} | \
                {("relation", r["osm_id"]) for r in handler.area_rows if r["osm_type"] == "relation"}
    drop_poi: dict[tuple, tuple] = {}
    drop_area: dict[tuple, tuple] = {}
    for rel in handler.relevant_relations.values():
        if ("relation", rel.osm_id) not in assembled:
            continue
        for t, ref, _role in rel.members:
            mtype = {"n": "node", "w": "way", "r": "relation"}[t]
            if rel.poi_category:
                drop_poi[(mtype, ref, rel.poi_category)] = ("relation", rel.osm_id)
            if rel.area_category:
                drop_area[(mtype, ref, rel.area_category)] = ("relation", rel.osm_id)
    duplicates: list[dict] = []

    def _filter(rows, key_cat, table):
        kept = []
        for r in rows:
            k = (r["osm_type"], r["osm_id"], r[key_cat])
            if k in table and r["osm_type"] != "relation":
                kept_type, kept_id = table[k]
                duplicates.append({"kept_osm_type": kept_type, "kept_osm_id": kept_id,
                                   "dropped_osm_type": r["osm_type"], "dropped_osm_id": r["osm_id"],
                                   "category": r[key_cat]})
            else:
                kept.append(r)
        return kept

    handler.poi_rows = _filter(handler.poi_rows, "category", drop_poi)
    handler.area_rows = _filter(handler.area_rows, "area_category", drop_area)

    # Closed ways that never produced an area (area=no, degenerate ring, ...).
    for way_id, (poi_cat, area_cat) in handler.closed_relevant_ways.items():
        if way_id in handler.way_areas_seen:
            continue
        for cat in (poi_cat, area_cat):
            if cat:
                handler._fail("way", way_id, cat, "closed_way_not_assembled")
    return extra_rows, duplicates


def _assembly_report(handler: _OsmHandler, duplicates: list[dict]) -> dict:
    rel_stats: dict[str, dict] = {}
    for rel in handler.relevant_relations.values():
        for cat in (rel.poi_category, rel.area_category):
            if cat:
                s = rel_stats.setdefault(cat, {"relevant": 0, "assembled": 0, "failed": 0, "failed_reasons": {}})
                s["relevant"] += 1
    for f in handler.failed_entities:
        if f["osm_type"] == "relation":
            s = rel_stats.setdefault(f["category"], {"relevant": 0, "assembled": 0, "failed": 0, "failed_reasons": {}})
            s["failed"] += 1
            s["failed_reasons"][f["reason"]] = s["failed_reasons"].get(f["reason"], 0) + 1
    for s in rel_stats.values():
        s["assembled"] = s["relevant"] - s["failed"]
    way_stats: dict[str, dict] = {}
    for _wid, (poi_cat, area_cat) in handler.closed_relevant_ways.items():
        for cat in (poi_cat, area_cat):
            if cat:
                s = way_stats.setdefault(cat, {"relevant": 0, "assembled": 0, "failed": 0})
                s["relevant"] += 1
    for f in handler.failed_entities:
        if f["osm_type"] == "way" and f["reason"] in ("closed_way_not_assembled", "assembler_empty_or_invalid"):
            s = way_stats.setdefault(f["category"], {"relevant": 0, "assembled": 0, "failed": 0})
            s["failed"] += 1
    for s in way_stats.values():
        s["assembled"] = s["relevant"] - s["failed"]
    dup_by_cat: dict[str, int] = defaultdict(int)
    for d in duplicates:
        dup_by_cat[d["category"]] += 1
    failures_by_cat: dict[str, int] = defaultdict(int)
    for f in handler.failed_entities:
        failures_by_cat[f["category"]] += 1
    return {
        "relations": rel_stats,
        "closed_ways": way_stats,
        "open_way_entities": dict(handler.open_way_entity_counts),
        "member_duplicates_dropped": dict(dup_by_cat),
        "failed_entities": list(handler.failed_entities),
        "failures_by_category": dict(failures_by_cat),
    }


def parse_osm_aoi(
    pbf_path: Path,
    minimum_degree: int = 3,
    taxonomy_path: Path = Path("config/poi_taxonomy.yaml"),
    features_path: Path = Path("config/features.yaml"),
    clip_bbox: tuple | None = None,
) -> OsmAoiExtract:
    """`clip_bbox` (west, south, east, north), if given, filters POI/road/
    area/intersection geometries to those intersecting the box. This is
    needed because `osmium extract --strategy complete_ways` can pull in
    the full length of any way that merely touches the requested bbox,
    which can extend well beyond it (observed for this AOI: a handful of
    long ways expanded the raw extract's bounds far past the acquisition
    box). The road graph itself is left unclipped so degree/connectivity
    reflect the true underlying topology; only the exported GeoDataFrames
    are clipped for AOI-scoped audit metrics. Assembly failures are never
    clipped away: a failed entity is reported wherever it lies.
    """
    taxonomy = load_taxonomy(taxonomy_path)
    road_classes = load_road_classes(features_path)

    pre = _RelationPrePass(taxonomy)
    pre.apply_file(str(pbf_path))
    handler = _OsmHandler(taxonomy, road_classes, pre.relevant)
    handler.apply_file(str(pbf_path), locations=True)
    _extra, duplicates = _finish_relations(handler)
    assembly = _assembly_report(handler, duplicates)

    def _frame(rows, columns):
        if rows:
            return gpd.GeoDataFrame(rows, geometry="geometry", crs=WGS84)
        return gpd.GeoDataFrame(columns=columns, geometry="geometry", crs=WGS84)

    poi_gdf = _frame(handler.poi_rows, POI_COLUMNS)
    road_gdf = _frame(handler.road_rows, ROAD_COLUMNS)
    area_gdf = _frame(handler.area_rows, AREA_COLUMNS)

    degree = dict(handler.road_graph.degree())
    intersection_ids = [nid for nid, deg in degree.items() if deg >= minimum_degree]
    intersection_rows = [
        {"node_id": nid, "degree": degree[nid], "geometry": sgeom.Point(*handler.node_location[nid])}
        for nid in intersection_ids
        if nid in handler.node_location
    ]
    intersections_gdf = _frame(intersection_rows, ["node_id", "degree", "geometry"])

    if clip_bbox is not None:
        west, south, east, north = clip_bbox
        box = sgeom.box(west, south, east, north)
        if len(poi_gdf):
            poi_gdf = poi_gdf[poi_gdf.intersects(box)].copy()
        if len(road_gdf):
            road_gdf = road_gdf[road_gdf.intersects(box)].copy()
        if len(area_gdf):
            area_gdf = area_gdf[area_gdf.intersects(box)].copy()
        if len(intersections_gdf):
            intersections_gdf = intersections_gdf[intersections_gdf.intersects(box)].copy()

    geom_types = poi_gdf.geometry.geom_type.value_counts().to_dict() if len(poi_gdf) else {}
    return OsmAoiExtract(
        poi_gdf=poi_gdf,
        road_gdf=road_gdf,
        area_gdf=area_gdf,
        intersections_gdf=intersections_gdf,
        road_graph=handler.road_graph,
        road_node_location=handler.node_location,
        relation_count=pre.relation_count,
        assembly=assembly,
        assembly_failures_by_category=assembly["failures_by_category"],
        member_duplicates=duplicates,
        open_way_entity_counts=dict(handler.open_way_entity_counts),
        minimum_degree=minimum_degree,
        stats={
            "poi_count": len(poi_gdf),
            "poi_geometry_types": {str(k): int(v) for k, v in geom_types.items()},
            "poi_from_relations": int((poi_gdf["osm_type"] == "relation").sum()) if len(poi_gdf) else 0,
            "road_way_count": len(road_gdf),
            "area_count": len(area_gdf),
            "area_from_relations": int((area_gdf["osm_type"] == "relation").sum()) if len(area_gdf) else 0,
            "intersection_count": len(intersections_gdf),
            "distinct_nodes_in_road_graph": handler.road_graph.number_of_nodes(),
            "relevant_relations": len(pre.relevant),
            "member_duplicates_dropped": len(duplicates),
            "failed_entities": len(handler.failed_entities),
        },
    )
