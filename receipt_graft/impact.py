from __future__ import annotations

import hashlib
import json
from collections import deque
from pathlib import Path
from typing import Any, Iterable

from common.io import write_json

IMPACT_REPORT_SCHEMA = "receipt.graft.impact.v1"


class ReceiptGraftImpactError(ValueError):
    """Invalid seed or graph for Receipt G.R.A.F.T.+ impact analysis."""


def _node_map(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(node.get("id")): node
        for node in graph.get("nodes") or []
        if isinstance(node, dict) and node.get("id")
    }


def _edge_rows(graph: dict[str, Any]) -> list[dict[str, Any]]:
    return [edge for edge in graph.get("edges") or [] if isinstance(edge, dict)]


def _selectors_for_node(node: dict[str, Any]) -> set[str]:
    selectors = {str(node.get("id") or ""), str(node.get("rel") or "")}
    selectors.update(str(alias) for alias in node.get("module_aliases") or [] if alias)
    contracts = node.get("contracts") if isinstance(node.get("contracts"), dict) else {}
    selectors.update(str(name) for name in contracts.get("functions") or [] if name)
    for cls in contracts.get("classes") or []:
        if isinstance(cls, dict) and cls.get("name"):
            selectors.add(str(cls["name"]))
    return {selector for selector in selectors if selector}


def resolve_seed_nodes(graph: dict[str, Any], seeds: Iterable[str]) -> list[str]:
    nodes = _node_map(graph)
    by_selector: dict[str, set[str]] = {}
    for node_id, node in nodes.items():
        for selector in _selectors_for_node(node):
            by_selector.setdefault(selector, set()).add(node_id)

    resolved: list[str] = []
    for raw in seeds:
        seed = str(raw).strip()
        if not seed:
            continue
        candidates = set(by_selector.get(seed) or set())
        if not candidates:
            candidates.update(
                node_id
                for node_id, node in nodes.items()
                if str(node.get("rel") or "").endswith(seed)
            )
        if not candidates:
            raise ReceiptGraftImpactError(f"impact seed not found: {seed}")
        if len(candidates) != 1:
            rels = sorted(str(nodes[node_id].get("rel") or node_id) for node_id in candidates)
            raise ReceiptGraftImpactError(
                f"impact seed is ambiguous: {seed} -> {', '.join(rels)}"
            )
        node_id = next(iter(candidates))
        if node_id not in resolved:
            resolved.append(node_id)
    if not resolved:
        raise ReceiptGraftImpactError("at least one impact seed is required")
    return resolved


def _adjacency(edges: list[dict[str, Any]]) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    downstream: dict[str, set[str]] = {}
    upstream: dict[str, set[str]] = {}
    for edge in edges:
        source = str(edge.get("from") or "")
        target = str(edge.get("to") or "")
        if not source or not target or source == target:
            continue
        downstream.setdefault(source, set()).add(target)
        upstream.setdefault(target, set()).add(source)
    return downstream, upstream


def _walk(start: Iterable[str], adjacency: dict[str, set[str]]) -> tuple[set[str], dict[str, int]]:
    visited = set(start)
    depth = {node_id: 0 for node_id in start}
    queue = deque(start)
    while queue:
        current = queue.popleft()
        for neighbor in sorted(adjacency.get(current) or set()):
            if neighbor in visited:
                continue
            visited.add(neighbor)
            depth[neighbor] = depth[current] + 1
            queue.append(neighbor)
    return visited, depth


def _is_test(node: dict[str, Any]) -> bool:
    rel = str(node.get("rel") or "")
    parts = Path(rel).parts
    name = Path(rel).name
    return "tests" in parts or name.startswith("test_") or name.endswith("_test.py")


def _compact_node(node: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": node.get("id"),
        "rel": node.get("rel"),
        "source_identity": node.get("source_identity"),
        "module_aliases": list(node.get("module_aliases") or []),
        "contracts": node.get("contracts") or {},
        "dependencies": node.get("dependencies") or {},
        "topology": node.get("topology") or {},
    }


def _sort_edges(edges: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        edges,
        key=lambda edge: (
            str(edge.get("from") or ""),
            str(edge.get("to") or ""),
            str(edge.get("kind") or ""),
            str(edge.get("evidence") or ""),
            int(edge.get("line") or 0),
        ),
    )


def build_impact_report(graph: dict[str, Any], seeds: Iterable[str]) -> dict[str, Any]:
    """Derive a deterministic blast-radius/proof slice from a Receipt stock graph.

    Reachability is evidence, not an instruction to modify every reachable source.
    """
    if not isinstance(graph, dict):
        raise ReceiptGraftImpactError("graph payload must be an object")

    nodes = _node_map(graph)
    edges = _edge_rows(graph)
    seed_ids = resolve_seed_nodes(graph, seeds)
    downstream, upstream = _adjacency(edges)

    downstream_ids, downstream_depth = _walk(seed_ids, downstream)
    upstream_ids, upstream_depth = _walk(seed_ids, upstream)
    affected_ids = downstream_ids | upstream_ids

    affected_edges = [
        edge
        for edge in edges
        if str(edge.get("from") or "") in affected_ids
        and str(edge.get("to") or "") in affected_ids
    ]
    unresolved = [
        row
        for row in graph.get("unresolved") or []
        if isinstance(row, dict) and str(row.get("source_node") or "") in affected_ids
    ]

    proof_ids = {
        node_id
        for node_id in affected_ids
        if node_id in nodes and _is_test(nodes[node_id])
    }
    for edge in edges:
        source = str(edge.get("from") or "")
        target = str(edge.get("to") or "")
        if source in nodes and _is_test(nodes[source]) and target in affected_ids:
            proof_ids.add(source)

    touched_effects: dict[str, list[dict[str, Any]]] = {}
    environment_reads: dict[str, list[str]] = {}
    external_dependencies: dict[str, list[str]] = {}
    for node_id in sorted(affected_ids):
        node = nodes.get(node_id)
        if not node:
            continue
        topology = node.get("topology") if isinstance(node.get("topology"), dict) else {}
        for effect in topology.get("effects") or []:
            if not isinstance(effect, dict):
                continue
            kind = str(effect.get("kind") or "unknown")
            touched_effects.setdefault(kind, []).append({"source_node": node_id, **effect})
        for env in topology.get("environment_reads") or []:
            if isinstance(env, dict):
                name = str(env.get("name") or "").strip()
            else:
                name = str(env).strip()
            if name:
                environment_reads.setdefault(name, []).append(node_id)
        dependencies = node.get("dependencies") if isinstance(node.get("dependencies"), dict) else {}
        for package in dependencies.get("external") or []:
            external_dependencies.setdefault(str(package), []).append(node_id)

    relationship_counts: dict[str, int] = {}
    for edge in affected_edges:
        kind = str(edge.get("kind") or "unknown")
        relationship_counts[kind] = relationship_counts.get(kind, 0) + 1

    seed_set = set(seed_ids)
    direct_upstream = sorted({n for seed in seed_ids for n in upstream.get(seed, set())})
    direct_downstream = sorted({n for seed in seed_ids for n in downstream.get(seed, set())})

    report = {
        "schema": IMPACT_REPORT_SCHEMA,
        "purpose": (
            "Receipt-internal G.R.A.F.T.+ blast-radius and proof-selection artifact. "
            "Reachability is evidence, not an instruction to modify every affected node."
        ),
        "grants_execution_authority": False,
        "implements_plan": False,
        "change_authority": "not-determined",
        "seeds": [
            {"id": node_id, "rel": nodes[node_id].get("rel")}
            for node_id in seed_ids
            if node_id in nodes
        ],
        "impact": {
            "affected_count": len(affected_ids),
            "upstream_count": len(upstream_ids - seed_set),
            "downstream_count": len(downstream_ids - seed_set),
            "direct_upstream": direct_upstream,
            "direct_downstream": direct_downstream,
            "upstream": sorted(upstream_ids - seed_set),
            "downstream": sorted(downstream_ids - seed_set),
            "depth": {
                "upstream": {
                    key: upstream_depth[key]
                    for key in sorted(upstream_depth)
                    if key not in seed_set
                },
                "downstream": {
                    key: downstream_depth[key]
                    for key in sorted(downstream_depth)
                    if key not in seed_set
                },
            },
            "relationship_counts": dict(sorted(relationship_counts.items())),
        },
        "proof": {
            "candidate_tests": [
                {"id": node_id, "rel": nodes[node_id].get("rel")}
                for node_id in sorted(proof_ids)
                if node_id in nodes
            ],
            "unresolved_boundaries": sorted(
                unresolved,
                key=lambda row: (
                    str(row.get("source_node") or ""),
                    str(row.get("kind") or ""),
                    str(row.get("evidence") or ""),
                ),
            ),
            "external_dependencies": {
                name: sorted(set(ids)) for name, ids in sorted(external_dependencies.items())
            },
            "environment_reads": {
                name: sorted(set(ids)) for name, ids in sorted(environment_reads.items())
            },
            "effects": {
                kind: sorted(
                    rows,
                    key=lambda row: (
                        str(row.get("source_node") or ""),
                        int(row.get("line") or 0),
                    ),
                )
                for kind, rows in sorted(touched_effects.items())
            },
        },
        "slice": {
            "nodes": [
                _compact_node(nodes[node_id])
                for node_id in sorted(affected_ids)
                if node_id in nodes
            ],
            "edges": _sort_edges(affected_edges),
        },
    }
    report["fingerprint"] = hashlib.sha256(
        json.dumps(report, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return report


def write_impact_report(graph: dict[str, Any], seeds: Iterable[str], path: Path) -> dict[str, Any]:
    report = build_impact_report(graph, seeds)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, report)
    return report
