from __future__ import annotations

from pathlib import Path

from collector.collect import collect
from receipt_graft.graph import EXTERNAL_BRIDGE_SCHEMA, STOCK_GRAPH_SCHEMA, build_stock_graph


def _identity(path: str, sha: str) -> dict:
    return {
        "schema": "receipt.source_identity.v1",
        "kind": "github",
        "repository": "acme/widgets",
        "commit": "a" * 40,
        "path": path,
        "source_sha256": sha,
        "origin": f"/home/private/{path}",
    }


def test_stock_graph_reveals_relationships_without_collapsing_outcome() -> None:
    payload = {
        "source": {"kind": "github", "owner": "acme", "repo": "widgets", "sha": "a" * 40},
        "files": [
            {
                "rel": "src/widget/fetch.py",
                "source_sha256": "1" * 64,
                "normalized_sha256": "2" * 64,
                "source_identity": _identity("src/widget/fetch.py", "1" * 64),
                "contracts": {"classes": [], "functions": [{"name": "fetch"}]},
                "dependencies": {
                    "local": ["widget.parse"],
                    "relative": [],
                    "external": ["httpx"],
                    "stdlib": [],
                },
                "graft_refs": [
                    {
                        "schema": "receipt.graft_ref.v1",
                        "artifact": "external-pack.json",
                        "subject": "source:fetch",
                        "evidence": {"node": "n1"},
                        "grants_execution_authority": False,
                    }
                ],
            },
            {
                "rel": "src/widget/parse.py",
                "source_sha256": "3" * 64,
                "normalized_sha256": "4" * 64,
                "source_identity": _identity("src/widget/parse.py", "3" * 64),
                "contracts": {"classes": [], "functions": [{"name": "parse"}]},
                "dependencies": {
                    "local": [],
                    "relative": [".missing"],
                    "external": [],
                    "stdlib": ["json"],
                },
            },
        ],
    }

    graph = build_stock_graph(payload)

    assert graph["schema"] == STOCK_GRAPH_SCHEMA
    assert graph["outcome_authority"] == "not-determined"
    assert graph["grants_execution_authority"] is False
    assert graph["inventory"]["python_sources"] == 2
    assert graph["inventory"]["relationships"] == 1
    assert graph["inventory"]["unresolved_relationships"] == 1
    assert graph["indexes"]["external_dependencies"]["httpx"]
    assert graph["external_graft_bridge"]["schema"] == EXTERNAL_BRIDGE_SCHEMA
    assert len(graph["external_graft_bridge"]["refs"]) == 1
    assert all("origin" not in node["source_identity"] for node in graph["nodes"])
    assert graph["security"]["contains_machine_local_origin"] is False


def test_stock_graph_is_deterministic_for_same_evidence() -> None:
    payload = {
        "files": [
            {
                "rel": "a.py",
                "source_sha256": "1" * 64,
                "source_identity": _identity("a.py", "1" * 64),
                "contracts": {"classes": [], "functions": [{"name": "run"}]},
                "dependencies": {"local": [], "relative": [], "external": [], "stdlib": []},
            }
        ]
    }
    assert build_stock_graph(payload) == build_stock_graph(payload)


def test_receipt_can_reconstruct_its_own_stock_end_to_end() -> None:
    """Self-hosting smoke: collect this checkout, then reconstruct the whole stock graph."""
    repo_root = Path(__file__).resolve().parents[1]
    payload = collect(repo_root)
    graph = build_stock_graph(payload)

    assert graph["schema"] == STOCK_GRAPH_SCHEMA
    assert graph["inventory"]["python_sources"] >= 20
    assert graph["inventory"]["relationships"] > 0
    assert graph["inventory"]["symbols"] > 0
    assert graph["outcome_authority"] == "not-determined"
    assert graph["grants_execution_authority"] is False
    assert graph["security"]["contains_machine_local_origin"] is False
    assert all("origin" not in node["source_identity"] for node in graph["nodes"])
    assert any(node["rel"] == "compiler/compile.py" for node in graph["nodes"])
    assert any(node["rel"] == "receipt_cli/stack.py" for node in graph["nodes"])
