from __future__ import annotations

from typing import Any

from receipt_graft.evidence import stamp_fingerprint

COMPATIBILITY_SCHEMA = "receipt.graft.compatibility.v1"


def _callables(node: dict[str, Any]) -> list[dict[str, Any]]:
    contracts = node.get("contracts") if isinstance(node.get("contracts"), dict) else {}
    rows: list[dict[str, Any]] = []
    for fn in contracts.get("function_contracts") or []:
        if isinstance(fn, dict) and fn.get("name"):
            rows.append(
                {
                    "kind": "function",
                    "name": fn.get("name"),
                    "params": list(fn.get("params") or []),
                    "returns": fn.get("returns"),
                    "async": bool(fn.get("async")),
                }
            )
    for cls in contracts.get("classes") or []:
        if not isinstance(cls, dict) or not cls.get("name"):
            continue
        for method in cls.get("method_contracts") or []:
            if isinstance(method, dict) and method.get("name"):
                rows.append(
                    {
                        "kind": "method",
                        "class": cls.get("name"),
                        "name": method.get("name"),
                        "params": list(method.get("params") or []),
                        "returns": method.get("returns"),
                        "async": bool(method.get("async")),
                    }
                )
    return rows


def build_compatibility_report(graph: dict[str, Any]) -> dict[str, Any]:
    units: list[dict[str, Any]] = []
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        topology = node.get("topology") if isinstance(node.get("topology"), dict) else {}
        dependencies = node.get("dependencies") if isinstance(node.get("dependencies"), dict) else {}
        units.append(
            {
                "id": node.get("id"),
                "rel": node.get("rel"),
                "module_aliases": list(node.get("module_aliases") or []),
                "callables": _callables(node),
                "inheritance": list(topology.get("inheritance") or []),
                "external_requirements": sorted(dependencies.get("external") or []),
                "environment_requirements": sorted(
                    {
                        str(row.get("key"))
                        for row in topology.get("environment_reads") or []
                        if isinstance(row, dict) and row.get("key")
                    }
                ),
                "effects": list(topology.get("effects") or []),
                "dynamic_imports": list(topology.get("dynamic_imports") or []),
                "entrypoint": bool(node.get("has_main")),
            }
        )
    report = {
        "schema": COMPATIBILITY_SCHEMA,
        "purpose": (
            "Source-backed assembly compatibility evidence for downstream reasoning. "
            "This artifact describes callable and environmental requirements; it does not choose a composition."
        ),
        "grants_execution_authority": False,
        "implements_plan": False,
        "units": sorted(units, key=lambda row: str(row.get("rel") or "")),
    }
    return stamp_fingerprint(report)
