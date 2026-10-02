from __future__ import annotations

import hashlib
import json
from typing import Any

BUILD_RECONCILIATION_SCHEMA = "receipt.graft.build_reconciliation.v1"


class ReceiptGraftReconcileError(ValueError):
    """Invalid build evidence for Receipt G.R.A.F.T.+ reconciliation."""


def _names(contracts: dict[str, Any] | None) -> dict[str, list[str]]:
    contracts = contracts if isinstance(contracts, dict) else {}
    classes = sorted(
        str(item.get("name"))
        for item in contracts.get("classes") or []
        if isinstance(item, dict) and item.get("name")
    )
    functions = sorted(
        str(item.get("name"))
        for item in contracts.get("functions") or []
        if isinstance(item, dict) and item.get("name")
    )
    return {"classes": classes, "functions": functions}


def build_reconciliation_report(
    impact_report: dict[str, Any],
    build_manifest: dict[str, Any],
    produced_contracts: dict[str, Any],
    produced_dependencies: dict[str, Any],
) -> dict[str, Any]:
    """Reconcile pre-build G.R.A.F.T.+ evidence with compiler/post-build facts.

    The report proves what survived or changed through compilation. It never decides
    whether a reachable source should have changed and grants no execution authority.
    """
    if not isinstance(impact_report, dict) or not isinstance(build_manifest, dict):
        raise ReceiptGraftReconcileError("impact report and build manifest must be objects")
    if not isinstance(produced_contracts, dict) or not isinstance(produced_dependencies, dict):
        raise ReceiptGraftReconcileError("post-build contracts/dependencies must be objects")

    manifest_units = [
        unit for unit in build_manifest.get("units") or [] if isinstance(unit, dict)
    ]
    preserved: list[dict[str, Any]] = []
    transformed: list[dict[str, Any]] = []
    divergences: list[dict[str, Any]] = []
    post_nodes: list[dict[str, Any]] = []
    post_edges: list[dict[str, Any]] = []

    for unit in manifest_units:
        unit_id = str(unit.get("id") or "")
        rel = str(unit.get("rel") or "")
        if not unit_id or not rel:
            divergences.append({"kind": "invalid_manifest_unit", "unit": unit})
            continue

        expected_output_contracts = unit.get("contracts", {}).get("output") or {}
        actual_contracts = _names(produced_contracts.get(unit_id))
        contract_match = expected_output_contracts == actual_contracts
        if not contract_match:
            divergences.append(
                {
                    "kind": "contract_projection_mismatch",
                    "id": unit_id,
                    "rel": rel,
                    "expected": expected_output_contracts,
                    "actual": actual_contracts,
                }
            )

        deps = produced_dependencies.get(unit_id)
        if not isinstance(deps, dict):
            divergences.append(
                {"kind": "missing_post_build_dependencies", "id": unit_id, "rel": rel}
            )
            deps = {"local": [], "external": []}

        transforms = list(unit.get("transforms") or [])
        rewritten = [
            item
            for item in transforms
            if isinstance(item, dict)
            and item.get("kind") in {"rewrite_import", "rewrite_from_import"}
        ]
        record = {
            "id": unit_id,
            "rel": rel,
            "source_sha256": (unit.get("source") or {}).get("source_sha256"),
            "output_sha256": (unit.get("output") or {}).get("sha256"),
            "contracts_preserved": bool(unit.get("contracts", {}).get("preserved"))
            and contract_match,
            "rewrite_count": len(rewritten),
        }
        (transformed if transforms else preserved).append(record)

        post_nodes.append(
            {
                "id": unit_id,
                "rel": rel,
                "contracts": actual_contracts,
                "dependencies": deps,
                "output_sha256": (unit.get("output") or {}).get("sha256"),
            }
        )
        for target in deps.get("local") or []:
            if target and target != unit_id:
                post_edges.append(
                    {
                        "from": unit_id,
                        "to": str(target),
                        "kind": "compiled_local_import",
                    }
                )

    rejected = [
        item for item in build_manifest.get("rejected") or [] if isinstance(item, dict)
    ]
    for item in rejected:
        divergences.append(
            {
                "kind": "compiler_rejected_unit",
                "id": item.get("id"),
                "rel": item.get("rel"),
                "reason": item.get("reason"),
            }
        )

    selected_rels = sorted(
        str(unit.get("rel")) for unit in manifest_units if unit.get("rel")
    )
    impact_rels = sorted(
        str(node.get("rel"))
        for node in (impact_report.get("slice") or {}).get("nodes") or []
        if isinstance(node, dict) and node.get("rel")
    )

    report: dict[str, Any] = {
        "schema": BUILD_RECONCILIATION_SCHEMA,
        "purpose": (
            "Reconcile Receipt stock/blast-radius evidence with compiler transformations "
            "and post-build topology. Facts are evidence for downstream reasoning, not a plan."
        ),
        "grants_execution_authority": False,
        "implements_plan": False,
        "change_authority": "not-determined",
        "status": "reconciled" if not divergences else "diverged",
        "pre_build": {
            "impact_schema": impact_report.get("schema"),
            "impact_fingerprint": impact_report.get("fingerprint"),
            "affected_count": (impact_report.get("impact") or {}).get("affected_count"),
            "affected_rels": impact_rels,
        },
        "compiler": {
            "manifest_schema": build_manifest.get("schema"),
            "package": build_manifest.get("package"),
            "selected_rels": selected_rels,
            "produced_units": len(manifest_units),
            "rejected_units": len(rejected),
            "preserved": preserved,
            "transformed": transformed,
        },
        "post_build": {
            "nodes": sorted(post_nodes, key=lambda row: str(row.get("rel") or "")),
            "edges": sorted(
                post_edges,
                key=lambda row: (
                    str(row.get("from") or ""),
                    str(row.get("to") or ""),
                    str(row.get("kind") or ""),
                ),
            ),
        },
        "divergences": divergences,
    }
    report["fingerprint"] = hashlib.sha256(
        json.dumps(report, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return report
