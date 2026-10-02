from __future__ import annotations

from typing import Any

from receipt_graft.evidence import stamp_fingerprint

RUNTIME_RECONCILIATION_SCHEMA = "receipt.graft.runtime_reconciliation.v1"


def build_runtime_reconciliation(
    *,
    impact_report: dict[str, Any],
    build_reconciliation: dict[str, Any],
    roster: dict[str, Any],
    build_manifest_fingerprint: str,
    stock_graph_fingerprint: str,
) -> dict[str, Any]:
    runtime = roster.get("runtime") if isinstance(roster.get("runtime"), dict) else {}
    units = [row for row in runtime.get("units") or [] if isinstance(row, dict)]

    declared = {tuple(row) for row in runtime.get("declared_local_edges") or [] if len(row) == 2}
    observed = {tuple(row) for row in runtime.get("observed_local_edges") or [] if len(row) == 2}
    import_failures = [
        {"id": row.get("id"), "status": row.get("status"), "error": row.get("error")}
        for row in units
        if row.get("status") != "ok"
    ]
    contradictions: list[dict[str, Any]] = []
    for source, target in sorted(declared - observed):
        contradictions.append(
            {
                "kind": "declared_edge_not_observed_on_import",
                "from": source,
                "to": target,
                "note": "Import-time observation is incomplete evidence; lazy/runtime-only edges may be valid.",
            }
        )
    for source, target in sorted(observed - declared):
        contradictions.append(
            {
                "kind": "observed_edge_not_declared",
                "from": source,
                "to": target,
            }
        )
    for failure in import_failures:
        contradictions.append({"kind": "unit_import_failed", **failure})

    report: dict[str, Any] = {
        "schema": RUNTIME_RECONCILIATION_SCHEMA,
        "purpose": (
            "Reconcile Receipt stock/build evidence with explicit runtime import observations. "
            "Runtime observations are evidence and do not grant execution or change authority."
        ),
        "status": "confirmed" if roster.get("ready") and not import_failures else "contradicted",
        "grants_execution_authority": False,
        "implements_plan": False,
        "change_authority": "not-determined",
        "evidence_chain": {
            "stock_graph_fingerprint": stock_graph_fingerprint,
            "impact_fingerprint": impact_report.get("fingerprint"),
            "build_manifest_fingerprint": build_manifest_fingerprint,
            "build_reconciliation_fingerprint": build_reconciliation.get("fingerprint"),
        },
        "runtime": {
            "ready": bool(roster.get("ready")),
            "accounted": bool(roster.get("accounted")),
            "local_graph_ok": bool(roster.get("local_graph_ok")),
            "units": units,
            "declared_local_edges": [list(row) for row in sorted(declared)],
            "observed_local_edges": [list(row) for row in sorted(observed)],
            "import_failures": import_failures,
        },
        "contradictions": contradictions,
    }
    return stamp_fingerprint(report)
