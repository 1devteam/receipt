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

    class_rows = []
    for item in classes:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        method_rows = []
        for method in item.get("methods") or []:
            if not isinstance(method, dict) or not method.get("name"):
                continue
            method_rows.append(
                {
                    "name": method.get("name"),
                    "params": list(method.get("params") or []),
                    "returns": method.get("returns"),
                    "decorators": list(method.get("decorators") or []),
                    "async": bool(method.get("async")),
                }
            )
        class_rows.append(
            {
                "name": item.get("name"),
                "methods": [row["name"] for row in method_rows],
                "method_contracts": method_rows,
                "bases": list(item.get("bases") or []),
                "decorators": list(item.get("decorators") or []),
            }
        )

    function_rows = []
    for item in functions:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        function_rows.append(
            {
                "name": item.get("name"),
                "params": list(item.get("params") or []),
                "returns": item.get("returns"),
                "decorators": list(item.get("decorators") or []),
                "async": bool(item.get("async")),
            }
        )

    return {
        "classes": class_rows,
        "functions": [row["name"] for row in function_rows],
        "function_contracts": function_rows,
    }


def _topology_summary(rec: dict[str, Any]) -> dict[str, Any]:
    topology = rec.get("topology") if isinstance(rec.get("topology"), dict) else {}
    return {
        "import_bindings": list(topology.get("import_bindings") or []),
        "calls": list(topology.get("calls") or []),
        "inheritance": list(topology.get("inheritance") or []),
        "dynamic_imports": list(topology.get("dynamic_imports") or []),
        "environment_reads": list(topology.get("environment_reads") or []),
        "effects": list(topology.get("effects") or []),
    }


def _edge_key(edge: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(edge.get("from") or ""),
        str(edge.get("to") or ""),
        str(edge.get("kind") or ""),
        str(edge.get("evidence") or ""),
        str(edge.get("symbol") or ""),
    )


def _module_targets(module_index: dict[str, set[str]], resolved_name: str) -> set[str]:
    """Resolve a module name without letting its package __init__ create false ambiguity."""
    exact = set(module_index.get(resolved_name) or set())
    if exact:
        return exact

    targets: set[str] = set()
    for module, ids in module_index.items():
        if module.startswith(resolved_name + ".") or resolved_name.startswith(module + "."):
            targets.update(ids)
    return targets


def _binding_map(topology: dict[str, Any]) -> dict[str, str]:
    rows: dict[str, set[str]] = {}
    for item in topology.get("import_bindings") or []:
        if not isinstance(item, dict):
            continue
        binding = str(item.get("binding") or "").strip()
        target = str(item.get("target") or "").strip()
        if binding and target:
            rows.setdefault(binding, set()).add(target)
    return {
        binding: next(iter(targets))
        for binding, targets in rows.items()
        if len(targets) == 1
    }


def _bound_reference(raw: str, rel: str, bindings: dict[str, str]) -> str | None:
    if not raw:
        return None
    first, dot, rest = raw.partition(".")
    bound = bindings.get(first)
    if not bound:
        return None
    resolved = _resolve_relative(bound, rel) if bound.startswith(".") else bound
    if not resolved:
        return None
    return f"{resolved}.{rest}" if dot and rest else resolved


def _module_symbol_target(
    reference: str,
    module_index: dict[str, set[str]],
    symbols_by_node: dict[str, set[str]],
) -> tuple[set[str], str | None, str | None]:
    """Resolve a bound reference to the longest known module prefix and optional symbol."""
    best_module = None
    best_ids: set[str] = set()
    for module, ids in module_index.items():
        if reference == module or reference.startswith(module + "."):
            if best_module is None or len(module) > len(best_module):
                best_module = module
                best_ids = set(ids)
    if best_module is None:
        return set(), None, None

    remainder = reference[len(best_module) :].lstrip(".")
    symbol = remainder.split(".", 1)[0] if remainder else None
    if symbol:
        symbol_ids = {node_id for node_id in best_ids if symbol in symbols_by_node.get(node_id, set())}
        if symbol_ids:
            best_ids = symbol_ids
    return best_ids, best_module, symbol


def _adjacency(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
    downstream: dict[str, set[str]] = {node["id"]: set() for node in nodes}
    upstream: dict[str, set[str]] = {node["id"]: set() for node in nodes}
    kinds_by_pair: dict[tuple[str, str], set[str]] = {}
    for edge in edges:
        source = str(edge.get("from") or "")
        target = str(edge.get("to") or "")
        if source not in downstream or target not in upstream or source == target:
            continue
        downstream[source].add(target)
        upstream[target].add(source)
        kinds_by_pair.setdefault((source, target), set()).add(str(edge.get("kind") or ""))

    return {
        "downstream": {node_id: sorted(targets) for node_id, targets in sorted(downstream.items()) if targets},
        "upstream": {node_id: sorted(sources) for node_id, sources in sorted(upstream.items()) if sources},
        "edge_kinds": {
            f"{source}->{target}": sorted(kind for kind in kinds if kind)
            for (source, target), kinds in sorted(kinds_by_pair.items())
        },
    }


def build_stock_graph(receipts: dict[str, Any]) -> dict[str, Any]:
    """Build Receipt's internal stock graph from catalog evidence only.

    Artifact construction is deterministic and evidence-strict. Outcome interpretation
    remains open: the graph reveals stock structure and behavior without deciding what
    application should be assembled from it.
    """
    if not isinstance(receipts, dict):
        raise ReceiptGraftError("receipts payload must be an object")

    files = receipts.get("files") or []
    if not isinstance(files, list):
        raise ReceiptGraftError("receipts files must be a list")

    nodes: list[dict[str, Any]] = []
    module_index: dict[str, set[str]] = {}
    symbol_index: dict[str, list[str]] = {}
    symbols_by_node: dict[str, set[str]] = {}
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
        node_symbols = {
            *[c["name"] for c in contracts["classes"] if c.get("name")],
            *contracts["functions"],
        }
        symbols_by_node[node_id] = {str(name) for name in node_symbols if name}
        for name in sorted(symbols_by_node[node_id]):
            symbol_index.setdefault(name, []).append(node_id)

        dependencies = (
            dict(rec.get("dependencies") or {})
            if isinstance(rec.get("dependencies"), dict)
            else {}
        )
        topology = _topology_summary(rec)
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
            "topology": topology,
        }
        nodes.append(node)

        for ref in rec.get("graft_refs") or []:
            if isinstance(ref, dict):
                external_bridge_refs.append({"source_node": node_id, "ref": dict(ref)})

    edges: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    external_dependencies: dict[str, list[str]] = {}
    environment_reads: dict[str, list[str]] = {}
    effects: dict[str, list[dict[str, Any]]] = {}
    dynamic_imports: list[dict[str, Any]] = []

    for node in nodes:
        rel = node["rel"]
        deps = node["dependencies"]
        topology = node["topology"]

        candidates: list[tuple[str, str]] = []
        candidates.extend(("local_import", raw) for raw in deps["local"])
        candidates.extend(("relative_import", raw) for raw in deps["relative"])

        for kind, raw in candidates:
            resolved_name = _resolve_relative(raw, rel) if raw.startswith(".") else raw
            target_ids = _module_targets(module_index, resolved_name) if resolved_name else set()

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

        bindings = _binding_map(topology)
        for call in topology.get("calls") or []:
            if not isinstance(call, dict):
                continue
            raw_target = str(call.get("target") or "")
            reference = _bound_reference(raw_target, rel, bindings)
            if not reference:
                continue
            target_ids, module, symbol = _module_symbol_target(reference, module_index, symbols_by_node)
            if len(target_ids) == 1:
                target = next(iter(target_ids))
                if target != node["id"]:
                    edges.append(
                        {
                            "from": node["id"],
                            "to": target,
                            "kind": "calls",
                            "evidence": raw_target,
                            "resolved_module": module,
                            "symbol": symbol,
                            "line": call.get("line"),
                            "provenance": "collector.topology.calls",
                        }
                    )
            elif target_ids:
                unresolved.append(
                    {
                        "source_node": node["id"],
                        "kind": "call_target",
                        "evidence": raw_target,
                        "resolved_reference": reference,
                        "candidate_nodes": sorted(target_ids),
                        "reason": "ambiguous_match",
                    }
                )

        for inherited in topology.get("inheritance") or []:
            if not isinstance(inherited, dict):
                continue
            base = str(inherited.get("base") or "")
            reference = _bound_reference(base, rel, bindings)
            if not reference:
                continue
            target_ids, module, symbol = _module_symbol_target(reference, module_index, symbols_by_node)
            if len(target_ids) == 1:
                target = next(iter(target_ids))
                if target != node["id"]:
                    edges.append(
                        {
                            "from": node["id"],
                            "to": target,
                            "kind": "inherits",
                            "evidence": base,
                            "resolved_module": module,
                            "symbol": symbol,
                            "line": inherited.get("line"),
                            "provenance": "collector.topology.inheritance",
                        }
                    )
            elif target_ids:
                unresolved.append(
                    {
                        "source_node": node["id"],
                        "kind": "inheritance_target",
                        "evidence": base,
                        "resolved_reference": reference,
                        "candidate_nodes": sorted(target_ids),
                        "reason": "ambiguous_match",
                    }
                )

        for row in topology.get("dynamic_imports") or []:
            if not isinstance(row, dict):
                continue
            literal = row.get("module_literal")
            record = {
                "source_node": node["id"],
                "module_literal": literal,
                "resolution": row.get("resolution"),
                "line": row.get("line"),
            }
            if isinstance(literal, str) and literal:
                targets = _module_targets(module_index, literal)
                if len(targets) == 1:
                    target = next(iter(targets))
                    record["target_node"] = target
                    if target != node["id"]:
                        edges.append(
                            {
                                "from": node["id"],
                                "to": target,
                                "kind": "dynamic_import",
                                "evidence": literal,
                                "resolved_module": literal,
                                "line": row.get("line"),
                                "provenance": "collector.topology.dynamic_imports",
                            }
                        )
                elif targets:
                    record["candidate_nodes"] = sorted(targets)
                    record["resolution"] = "ambiguous"
            dynamic_imports.append(record)

        for env in topology.get("environment_reads") or []:
            if not isinstance(env, dict):
                continue
            key = env.get("key")
            if isinstance(key, str) and key:
                environment_reads.setdefault(key, []).append(node["id"])

        for effect in topology.get("effects") or []:
            if not isinstance(effect, dict):
                continue
            kind = str(effect.get("kind") or "unknown")
            effects.setdefault(kind, []).append(
                {
                    "source_node": node["id"],
                    "target": effect.get("target"),
                    "line": effect.get("line"),
                    "evidence": effect.get("evidence"),
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
    adjacency = _adjacency(nodes, edges)

    edge_kind_counts: dict[str, int] = {}
    for edge in edges:
        kind = str(edge.get("kind") or "unknown")
        edge_kind_counts[kind] = edge_kind_counts.get(kind, 0) + 1

    return {
        "schema": STOCK_GRAPH_SCHEMA,
        "purpose": (
            "Receipt-internal G.R.A.F.T.+ stock reconstruction: reveal what is in "
            "stock, where it is, how source-backed relationships interoperate, what "
            "behavioral boundaries are visible, and where evidence stops. It does not "
            "choose an application outcome."
        ),
        "grants_execution_authority": False,
        "implements_plan": False,
        "outcome_authority": "not-determined",
        "source": receipts.get("source"),
        "inventory": {
            "python_sources": len(nodes),
            "relationships": len(edges),
            "relationship_kinds": dict(sorted(edge_kind_counts.items())),
            "unresolved_relationships": len(unresolved),
            "symbols": len(symbol_index),
            "external_dependencies": len(external_dependencies),
            "duplicate_symbols": len(duplicate_symbols),
            "environment_keys": len(environment_reads),
            "effect_kinds": len(effects),
            "dynamic_import_sites": len(dynamic_imports),
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
            "environment_reads": {
                name: sorted(set(ids)) for name, ids in sorted(environment_reads.items())
            },
            "effects": {
                kind: sorted(
                    rows,
                    key=lambda row: (
                        str(row.get("source_node") or ""),
                        int(row.get("line") or 0),
                        str(row.get("target") or ""),
                    ),
                )
                for kind, rows in sorted(effects.items())
            },
            "dynamic_imports": sorted(
                dynamic_imports,
                key=lambda row: (
                    str(row.get("source_node") or ""),
                    int(row.get("line") or 0),
                    str(row.get("module_literal") or ""),
                ),
            ),
            "adjacency": adjacency,
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
