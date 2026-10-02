from __future__ import annotations

import argparse
import json
import shutil
from collections import Counter
from pathlib import Path

from collector.collect import collect_to
from common.io import write_json
from receipt_cli.stack import StackError, stack
from receipt_graft.compatibility import build_compatibility_report
from receipt_graft.evidence import canonical_fingerprint
from receipt_graft.graph import build_stock_graph
from receipt_graft.impact import build_impact_report
from receipt_graft.proof import build_proof_plan


def _is_test(rel: str) -> bool:
    path = Path(rel)
    return "tests" in path.parts or path.name.startswith("test_") or path.name.endswith("_test.py")


def _choose_seed(graph: dict) -> str:
    degree: Counter[str] = Counter()
    for edge in graph.get("edges") or []:
        source = str(edge.get("from") or "")
        target = str(edge.get("to") or "")
        if source:
            degree[source] += 1
        if target:
            degree[target] += 1
    nodes = [node for node in graph.get("nodes") or [] if isinstance(node, dict)]
    candidates = [node for node in nodes if node.get("rel") and not _is_test(str(node.get("rel")))] or nodes
    candidates.sort(key=lambda node: (-degree[str(node.get("id") or "")], str(node.get("rel") or "")))
    if not candidates:
        raise RuntimeError("real-stock trial produced no graph nodes")
    return str(candidates[0]["rel"])


def run_trial(source: Path, *, label: str, commit: str, out: Path) -> dict:
    source = source.resolve()
    out = out.resolve()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    catalog = out / "catalog"
    receipts = collect_to(source, catalog)
    graph = build_stock_graph(receipts)
    inventory = graph.get("inventory") or {}
    if int(inventory.get("python_sources") or 0) < 10:
        raise RuntimeError(f"{label}: insufficient Python stock: {inventory}")
    if int(inventory.get("relationships") or 0) < 1:
        raise RuntimeError(f"{label}: graph found no relationships")

    seed = _choose_seed(graph)
    impact = build_impact_report(graph, [seed])
    proof = build_proof_plan(graph, impact)
    compatibility = build_compatibility_report(graph)

    stack_result: dict
    try:
        built = out / "built"
        result = stack(catalog, [seed], name=f"trial_{label.replace('/', '_').replace('-', '_')}", out=built, force=True, check=False)
        stack_result = {
            "status": "produced",
            "compiled_units": result.get("compiled_units"),
            "compile_errors": result.get("compile_errors") or [],
            "compiler_contract_violations": (result.get("compiler_contracts") or {}).get("violations") or [],
            "build_reconciliation": result.get("graft_reconciliation"),
        }
    except (StackError, SystemExit, OSError, ValueError) as exc:
        stack_result = {"status": "not_produced", "error": str(exc)}

    report = {
        "schema": "receipt.validation.real_stock.v1",
        "label": label,
        "commit": commit,
        "source": str(source),
        "seed": seed,
        "inventory": inventory,
        "graph_fingerprint": canonical_fingerprint(graph),
        "impact": {
            "fingerprint": impact.get("fingerprint"),
            "affected_count": (impact.get("impact") or {}).get("affected_count"),
            "upstream_count": (impact.get("impact") or {}).get("upstream_count"),
            "downstream_count": (impact.get("impact") or {}).get("downstream_count"),
            "candidate_tests": len((impact.get("proof") or {}).get("candidate_tests") or []),
            "unresolved_boundaries": len((impact.get("proof") or {}).get("unresolved_boundaries") or []),
        },
        "proof": {
            "fingerprint": proof.get("fingerprint"),
            "direct_tests": len(proof.get("direct_tests") or []),
            "indirect_tests": len(proof.get("indirect_tests") or []),
            "uncovered_affected_stock": len(proof.get("uncovered_affected_stock") or []),
            "effect_bearing_paths": len(proof.get("effect_bearing_paths") or []),
            "dynamic_boundaries": len(proof.get("dynamic_boundaries") or []),
        },
        "compatibility": {
            "fingerprint": compatibility.get("fingerprint"),
            "units": len(compatibility.get("units") or []),
        },
        "stack": stack_result,
        "grants_execution_authority": False,
    }
    write_json(out / "real-stock-report.v1.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Exercise Receipt/G.R.A.F.T.+ against pinned real Python stock")
    parser.add_argument("source")
    parser.add_argument("--label", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    report = run_trial(Path(args.source), label=args.label, commit=args.commit, out=Path(args.out))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
