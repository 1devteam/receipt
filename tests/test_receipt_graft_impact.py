from __future__ import annotations

from receipt_graft.impact import (
    IMPACT_REPORT_SCHEMA,
    ReceiptGraftImpactError,
    build_impact_report,
)


def _node(node_id: str, rel: str, *, aliases=(), functions=(), effects=(), env=(), external=()):
    return {
        "id": node_id,
        "rel": rel,
        "source_identity": {
            "schema": "receipt.source_identity.v1",
            "kind": "github",
            "repository": "acme/widgets",
            "commit": "a" * 40,
            "path": rel,
            "source_sha256": (node_id[-1] * 64)[:64],
        },
        "module_aliases": list(aliases),
        "contracts": {
            "classes": [],
            "functions": list(functions),
            "function_contracts": [],
        },
        "dependencies": {
            "local": [],
            "relative": [],
            "external": list(external),
            "stdlib": [],
        },
        "topology": {
            "import_bindings": [],
            "calls": [],
            "inheritance": [],
            "dynamic_imports": [],
            "environment_reads": [{"name": name, "line": 1} for name in env],
            "effects": list(effects),
        },
    }


def _graph():
    return {
        "nodes": [
            _node("n1", "src/app/service.py", aliases=("app.service",), functions=("serve",), external=("httpx",)),
            _node(
                "n2",
                "src/app/store.py",
                aliases=("app.store",),
                functions=("save",),
                effects=({"kind": "database", "operation": "execute", "line": 8},),
                env=("DATABASE_URL",),
            ),
            _node("n3", "src/app/model.py", aliases=("app.model",), functions=("shape",)),
            _node("n4", "tests/test_service.py", aliases=("tests.test_service",), functions=("test_service",)),
        ],
        "edges": [
            {"from": "n1", "to": "n2", "kind": "calls", "evidence": "store.save", "line": 5},
            {"from": "n2", "to": "n3", "kind": "local_import", "evidence": "app.model"},
            {"from": "n4", "to": "n1", "kind": "calls", "evidence": "service.serve", "line": 4},
        ],
        "unresolved": [
            {
                "source_node": "n2",
                "kind": "dynamic_import",
                "evidence": "PLUGIN_MODULE",
                "reason": "runtime_value",
            }
        ],
    }


def test_impact_report_exposes_bidirectional_blast_radius_and_proof() -> None:
    report = build_impact_report(_graph(), ["src/app/service.py"])

    assert report["schema"] == IMPACT_REPORT_SCHEMA
    assert report["grants_execution_authority"] is False
    assert report["implements_plan"] is False
    assert report["change_authority"] == "not-determined"
    assert report["impact"]["affected_count"] == 4
    assert report["impact"]["direct_downstream"] == ["n2"]
    assert report["impact"]["direct_upstream"] == ["n4"]
    assert report["impact"]["downstream"] == ["n2", "n3"]
    assert report["impact"]["upstream"] == ["n4"]
    assert report["impact"]["relationship_counts"] == {"calls": 2, "local_import": 1}
    assert report["proof"]["candidate_tests"] == [{"id": "n4", "rel": "tests/test_service.py"}]
    assert report["proof"]["environment_reads"] == {"DATABASE_URL": ["n2"]}
    assert report["proof"]["external_dependencies"] == {"httpx": ["n1"]}
    assert report["proof"]["effects"]["database"][0]["source_node"] == "n2"
    assert report["proof"]["unresolved_boundaries"][0]["source_node"] == "n2"
    assert report["fingerprint"] == build_impact_report(_graph(), ["src/app/service.py"])["fingerprint"]


def test_impact_seed_can_resolve_module_or_symbol() -> None:
    by_module = build_impact_report(_graph(), ["app.store"])
    by_symbol = build_impact_report(_graph(), ["save"])
    assert by_module["seeds"] == [{"id": "n2", "rel": "src/app/store.py"}]
    assert by_symbol["seeds"] == by_module["seeds"]


def test_impact_refuses_ambiguous_symbol() -> None:
    graph = _graph()
    graph["nodes"][0]["contracts"]["functions"].append("save")
    try:
        build_impact_report(graph, ["save"])
    except ReceiptGraftImpactError as exc:
        assert "ambiguous" in str(exc)
    else:
        raise AssertionError("ambiguous impact seed should fail closed")
