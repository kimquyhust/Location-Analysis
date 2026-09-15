import networkx as nx

from roads.topology import component_length_shares, induced_subgraph_within_bbox, intersection_nodes

BBOX = (0.0, 0.0, 10.0, 10.0)


def _graph_with_boundary_crossing_edge():
    # Node 1 and 2 are inside the bbox; node 3 is outside. Edge (2,3)
    # crosses the boundary.
    G = nx.MultiGraph()
    G.add_edge(1, 2)
    G.add_edge(2, 3)
    node_location = {1: (2.0, 2.0), 2: (8.0, 8.0), 3: (20.0, 20.0)}
    return G, node_location


def test_induced_subgraph_drops_out_of_scope_nodes():
    G, node_location = _graph_with_boundary_crossing_edge()
    sub, in_scope = induced_subgraph_within_bbox(G, node_location, BBOX)

    assert set(sub.nodes()) == {1, 2}
    assert set(in_scope.keys()) == {1, 2}


def test_induced_subgraph_drops_edge_with_one_endpoint_out_of_scope():
    G, node_location = _graph_with_boundary_crossing_edge()
    sub, _ = induced_subgraph_within_bbox(G, node_location, BBOX)

    # (1,2) is fully inside -- kept. (2,3) has an out-of-scope endpoint --
    # dropped entirely, never partially attributed.
    assert sub.has_edge(1, 2)
    assert not sub.has_edge(2, 3)
    assert sub.number_of_edges() == 1


def test_induced_subgraph_boundary_inclusive():
    # A node exactly on the bbox edge must be counted in-scope (inclusive
    # bounds), matching gpd.clip's convention for the length-based metrics.
    G = nx.MultiGraph()
    G.add_edge(1, 2)
    node_location = {1: (0.0, 0.0), 2: (10.0, 10.0)}
    sub, in_scope = induced_subgraph_within_bbox(G, node_location, BBOX)
    assert set(sub.nodes()) == {1, 2}


def test_eval_scope_is_subset_of_halo_scope_and_can_show_more_fragmentation():
    # A single physical road (1-2-3-4) where node 2 sits just inside the
    # eval box and node 3 just outside it, but both are inside a wider
    # halo box -- restricting to eval scope must cut the road into two
    # components even though the halo-scope graph sees one.
    G = nx.MultiGraph()
    G.add_edge(1, 2)
    G.add_edge(2, 3)
    G.add_edge(3, 4)
    node_location = {1: (1.0, 1.0), 2: (4.0, 4.0), 3: (6.0, 4.0), 4: (9.0, 4.0)}
    eval_bbox = (0.0, 0.0, 5.0, 10.0)
    halo_bbox = (0.0, 0.0, 10.0, 10.0)

    eval_sub, eval_xy = induced_subgraph_within_bbox(G, node_location, eval_bbox)
    halo_sub, halo_xy = induced_subgraph_within_bbox(G, node_location, halo_bbox)

    eval_conn = component_length_shares(eval_sub, eval_xy)
    halo_conn = component_length_shares(halo_sub, halo_xy)

    assert halo_conn["component_count"] == 1
    assert eval_conn["component_count"] == 1  # nodes 1,2 form their own single component
    assert set(eval_sub.nodes()) == {1, 2}
    assert set(halo_sub.nodes()) == {1, 2, 3, 4}


def test_intersection_nodes_unaffected_by_bbox_restriction_logic():
    G = nx.MultiGraph()
    G.add_edge(1, 2)
    G.add_edge(1, 3)
    G.add_edge(1, 4)
    assert intersection_nodes(G, minimum_degree=3) == [1]
    assert intersection_nodes(G, minimum_degree=4) == []
