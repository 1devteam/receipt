from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any

from common.io import write_json

STOCK_GRAPH_SCHEMA = "receipt.graft.stock.v1"
EXTERNAL_BRIDGE_SCHEMA = "receipt.graft.external_bridge.v1"


class ReceiptGraftError(ValueError):
    """Invalid Receipt stock data for internal G.R.A.F.T.+ reconstruction."""


def _stable_id(identity: dict[str, Any]) -> str:
    key = {
        "kind": identity.get("kind"),
        "repository": identity.get("repository"),
        "commit": identity.get("commit"),
        "path": identity.get("path"),
        "source_sha256": identity.get("source_sha256"),
    }
    digest = hashlib.sha256(
        json.dumps(key, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"receipt-source:{digest[:24]}"


def _safe_identity(identity: dict[str, Any]) -> dict[str, Any]:
    """Strip machine-local origin while preserving stable source identity."""
    return {
        "schema": identity.get("schema"),
        "kind": identity.get("kind"),
        "repository": identity.get("repository"),
        "commit": identity.get("commit"),
        "path": identity.get("path"),
        "source_sha256": identity.get("source_sha256"),
    }


def _module_aliases(rel: str) -> set[str]:
    parts = list(PurePosixPath(rel).parts)
    if not parts or not parts[-1].endswith(".py"):
        return set()
    stem = Path(parts[-1]).stem
    module_parts = parts[:-1] if stem == "__init__" else [*parts[:-1], stem]
    aliases: set[str] = set()
    if module_parts:
        aliases.add(".".join(module_parts))
        if module_parts[0] in {"src", "lib"} and len(module_parts) > 1:
            aliases.add(".".join(module_parts[1:]))
    return aliases


def _package_for(rel: str) -> list[str]:
    parts = list(PurePosixPath(rel).parts)
    if not parts:
        return []
    stem = Path(parts[-1]).stem
    module_parts = parts[:-1] if stem == "__init__" else [*parts[:-1], stem]
    if not module_parts:
        return []
    if module_parts[0] in {"src", "lib"} and len(module_parts) > 1:
        module_parts = module_parts[1:]
    return module_parts if stem == "__init__" else module_parts[:-1]


def _resolve_relative(raw: str, rel: str) -> str | None:
    if not raw.startswith("."):
        return raw
    level = len(raw) - len(raw.lstrip("."))
    tail = raw[level:]
    package = _package_for(rel)
    climb = max(level - 1, 0)
    if climb > len(package):
        return None
    base = package[: len(package) - climb] if climb else package
    if tail:
        base = [*base, *tail.split(".")]
    return ".".join(part for part in base if part) or None


def _contract_summary(rec: dict[str, Any]) -> dict[str, Any]:
    contracts = rec.get("contracts") if isinstance(rec.get("contracts"), dict) else {}
    classes = contracts.get("classes") or rec.get("classes") or []
    functions = contracts.get("functions") or rec.get("functions") or []
    return {
        "classes": [
            {
                "name": item.get("name"),
                "methods": [
                    method.get("name")
                    for method in (item.get("methods") or [])
                    if method.get("name")
                ],
            }
            for item in classes
            if isinstance(item, dict) and item.get("name")
        ],
        "functions": [
            item.get("name")
            for item in functions
            if isinstance(item, dict) and item.get("name")
        ],
    }


def _edge_key(edge: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(edge.get("from") or ""),
        str(edge.get("to") or ""),
        str(edge.get("kind") or ""),
        str(edge.get("evidence") or ""),
    )


def build_stock_graph(receipts: dict[str, Any]) -> dict[str, Any]:
    """Build Receipt's internal stock graph from catalog evidence only.

    The graph is deliberately architecture-revealing and outcome-neutral. It
    records source-backed relationships and unresolved boundaries without
    deciding what application should be assembled from the stock.
    """
    if not isinstance(receipts, dict):
        raise ReceiptGraftError("receipts payload must be an object")

    files = receipts.get("files") or []
    if not isinstance(files, list):
        raise ReceiptGraftError("receipts files must be a list")

    nodes: list[dict[str, Any]] = []
    module_index: dict[str, set[str]] = {}
    symbol_index: dict[str, list[str]] = {}
    external_bridge_refs: list[dict[str, Any]] = []

    for rec in files:
        if not isinstance(rec, dict):
            continue
        rel = str(rec.get("rel") or "").strip()
        identity = rec.get("source_identity")
        if not rel or not isinstance(identity, dict):
            continue

        node_id = _stable_id(identity)
        aliases = sorted(_module_aliases(rel))
        for alias in aliases:
            module_index.setdefault(alias, set()).add(node_id)

        contracts = _contract_summary(rec)
        for name in [
            *[c["name"] for c in contracts["classes"] if c.get("name")],
            *contracts["functions"],
        ]:
            symbol_index.setdefault(str(name), []).append(node_id)

        dependencies = (
            dict(rec.get("dependencies") or {})
            if isinstance(rec.get("dependencies"), dict)
            else {}
        )
        node = {
            "id": node_id,
            "kind": "python_source",
            "rel": rel,
            "source_identity": _safe_identity(identity),
            "source_sha256": rec.get("source_sha256") or rec.get("sha256"),
            "normalized_sha256": rec.get("normalized_sha256"),
            "syntax_ok": rec.get("syntax_ok"),
            "has_main": bool(rec.get("has_main")),
            "module_aliases": aliases,
            "contracts": contracts,
            "dependencies": {
                "local": sorted(dependencies.get("local") or []),
                "relative": sorted(dependencies.get("relative") or []),
                "external": sorted(dependencies.get("external") or []),
                "stdlib": sorted(dependencies.get("stdlib") or []),
            },
        }
        nodes.append(node)

        for ref in rec.get("graft_refs") or []:
            if isinstance(ref, dict):
                external_bridge_refs.append({"source_node": node_id, "ref": dict(ref)})

    edges: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    external_dependencies: dict[str, list[str]] = {}

    for node in nodes:
        rel = node["rel"]
        deps = node["dependencies"]

        candidates: list[tuple[str, str]] = []
        candidates.extend(("local_import", raw) for raw in deps["local"])
        candidates.extend(("relative_import", raw) for raw in deps["relative"])

        for kind, raw in candidates:
            resolved_name = _resolve_relative(raw, rel) if raw.startswith(".") else raw
            target_ids: set[str] = set()
            if resolved_name:
                for module, ids in module_index.items():
                    if (
                        module == resolved_name
                        or module.startswith(resolved_name + ".")
                        or resolved_name.startswith(module + ".")
                    ):
                        target_ids.update(ids)

            if len(target_ids) == 1:
                target = next(iter(target_ids))
                if target != node["id"]:
                    edges.append(
                        {
                            "from": node["id"],
                            "to": target,
                            "kind": kind,
                            "evidence": raw,
                            "resolved_module": resolved_name,
                            "provenance": "collector.dependencies",
                        }
                    )
            else:
                unresolved.append(
                    {
                        "source_node": node["id"],
                        "kind": kind,
                        "evidence": raw,
                        "resolved_module": resolved_name,
                        "candidate_nodes": sorted(target_ids),
                        "reason": "no_match" if not target_ids else "ambiguous_match",
                    }
                )

        for package in deps["external"]:
            external_dependencies.setdefault(package, []).append(node["id"])

    edges = sorted({_edge_key(edge): edge for edge in edges}.values(), key=_edge_key)
    unresolved.sort(
        key=lambda item: (
            str(item.get("source_node") or ""),
            str(item.get("kind") or ""),
            str(item.get("evidence") or ""),
        )
    )
    nodes.sort(key=lambda item: item["rel"])

    duplicate_symbols = {
        name: sorted(set(ids))
        for name, ids in sorted(symbol_index.items())
        if len(set(ids)) > 1
    }

    return {
        "schema": STOCK_GRAPH_SCHEMA,
        "purpose": (
            "Receipt-internal G.R.A.F.T.+ stock reconstruction: reveal what is in "
            "stock, where it is, how source-backed relationships interoperate, and "
            "where evidence stops. It does not choose an application outcome."
        ),
        "grants_execution_authority": False,
        "implements_plan": False,
        "outcome_authority": "not-determined",
        "source": receipts.get("source"),
        "inventory": {
            "python_sources": len(nodes),
            "relationships": len(edges),
            "unresolved_relationships": len(unresolved),
            "external_dependencies": len(external_dependencies),
            "duplicate_symbols": len(duplicate_symbols),
        },
        "nodes": nodes,
        "edges": edges,
        "unresolved": unresolved,
        "indexes": {
            "modules": {name: sorted(ids) for name, ids in sorted(module_index.items())},
            "symbols": {name: sorted(set(ids)) for name, ids in sorted(symbol_index.items())},
            "duplicate_symbols": duplicate_symbols,
            "external_dependencies": {
                name: sorted(set(ids))
                for name, ids in sorted(external_dependencies.items())
            },
        },
        "external_graft_bridge": {
            "schema": EXTERNAL_BRIDGE_SCHEMA,
            "purpose": (
                "Identity/evidence bridge to external G.R.A.F.T.+ artifacts. "
                "External and Receipt-internal graphs may collaborate through stable "
                "source identity without either graph inheriting execution authority."
            ),
            "refs": external_bridge_refs,
            "join_keys": [
                "source_identity.repository",
                "source_identity.commit",
                "source_identity.path",
                "source_identity.source_sha256",
            ],
            "grants_execution_authority": False,
        },
        "security": {
            "contains_raw_source": False,
            "contains_normalized_source": False,
            "contains_machine_local_origin": False,
            "content_addressed": True,
        },
    }


def write_stock_graph(receipts: dict[str, Any], path: Path) -> dict[str, Any]:
    graph = build_stock_graph(receipts)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, graph)
    return graph
