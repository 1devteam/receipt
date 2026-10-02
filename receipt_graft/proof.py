from __future__ import annotations

from typing import Any

from receipt_graft.evidence import stamp_fingerprint

PROOF_PLAN_SCHEMA = "receipt.graft.proof_plan.v1"


def build_proof_plan(graph: dict[str, Any], impact: dict[str, Any]) -> dict[str, Any]:
    node_map = {
        str(node.get("id")): node
        for node in graph.get("nodes") or []
        if isinstance(node, dict) and node.get("id")
    }
    seed_ids = {str(row.get("id")) for row in impact.get("seeds") or [] if isinstance(row, dict)}
    affected_ids = {
        str(node.get("id"))
        for node in (impact.get("slice") or {}).get("nodes") or []
        if isinstance(node, dict) and node.get("id")
    }
    upstream_depth = ((impact.get("impact") or {}).get("depth") or {}).get("upstream") or {}
    tests = [row for row in (impact.get("proof") or {}).get("candidate_tests") or [] if isinstance(row, dict)]

    direct_tests = []
    indirect_tests = []
    for row in tests:
        node_id = str(row.get("id") or "")
        depth = int(upstream_depth.get(node_id) or 0)
        target = {"id": node_id, "rel": row.get("rel"), "distance": depth}
        if depth <= 1:
            direct_tests.append(target)
        else:
            indirect_tests.append(target)

    tested_targets: set[str] = set(seed_ids)
    edges = [edge for edge in (impact.get("slice") or {}).get("edges") or [] if isinstance(edge, dict)]
    test_ids = {str(row.get("id")) for row in tests}
    for edge in edges:
        if str(edge.get("from") or "") in test_ids:
            tested_targets.add(str(edge.get("to") or ""))

    uncovered = [
        {"id": node_id, "rel": node_map.get(node_id, {}).get("rel")}
        for node_id in sorted(affected_ids - test_ids - tested_targets)
    ]

    effect_paths = []
    dynamic_boundaries = []
    for node_id in sorted(affected_ids):
        node = node_map.get(node_id) or {}
        topology = node.get("topology") if isinstance(node.get("topology"), dict) else {}
        effects = list(topology.get("effects") or [])
        if effects:
            effect_paths.append({"id": node_id, "rel": node.get("rel"), "effects": effects})
        for row in topology.get("dynamic_imports") or []:
            if isinstance(row, dict) and row.get("resolution") != "literal":
                dynamic_boundaries.append({"id": node_id, "rel": node.get("rel"), **row})

    report = {
        "schema": PROOF_PLAN_SCHEMA,
        "purpose": (
            "Prioritize proof surfaces for affected Receipt stock. Selection is evidence-based guidance, "
            "not permission to execute tests or modify sources."
        ),
        "grants_execution_authority": False,
        "implements_plan": False,
        "impact_fingerprint": impact.get("fingerprint"),
        "direct_tests": sorted(direct_tests, key=lambda row: str(row.get("rel") or "")),
        "indirect_tests": sorted(indirect_tests, key=lambda row: str(row.get("rel") or "")),
        "uncovered_affected_stock": uncovered,
        "effect_bearing_paths": effect_paths,
        "dynamic_boundaries": dynamic_boundaries,
        "unresolved_boundaries": list((impact.get("proof") or {}).get("unresolved_boundaries") or []),
    }
    return stamp_fingerprint(report)
