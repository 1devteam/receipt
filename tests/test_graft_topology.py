from __future__ import annotations

import json
from pathlib import Path

from collector.collect import collect, collect_to
from collector.inspect import inspect_source
from receipt_graft.graph import build_stock_graph


def test_inspect_extracts_contract_and_behavior_facts() -> None:
    info = inspect_source(
        """
import importlib
import os
import widget.util as util
from widget.parse import Parser

class Service(Parser):
    async def run(self, value: str) -> int:
        return util.helper(value)

def load_plugin():
    return importlib.import_module("widget.plugin")

TOKEN = os.getenv("TOKEN")
"""
    )

    service = info["classes"][0]
    assert service["name"] == "Service"
    assert service["bases"] == ["Parser"]
    assert service["methods"][0]["returns"] == "int"
    assert service["methods"][0]["async"] is True

    topology = info["topology"]
    assert {row["binding"]: row["target"] for row in topology["import_bindings"]}["util"] == "widget.util"
    assert {row["binding"]: row["target"] for row in topology["import_bindings"]}["Parser"] == "widget.parse.Parser"
    assert any(row["target"] == "util.helper" for row in topology["calls"])
    assert topology["inheritance"][0]["base"] == "Parser"
    assert topology["dynamic_imports"][0]["module_literal"] == "widget.plugin"
    assert any(row["key"] == "TOKEN" for row in topology["environment_reads"])


def _write_stock(root: Path) -> None:
    pkg = root / "src" / "widget"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "parse.py").write_text(
        "class Parser:\n    def parse(self, value: str) -> str:\n        return value\n",
        encoding="utf-8",
    )
    (pkg / "util.py").write_text(
        "def helper(value: str) -> str:\n    return value.strip()\n",
        encoding="utf-8",
    )
    (pkg / "plugin.py").write_text(
        "def activate() -> bool:\n    return True\n",
        encoding="utf-8",
    )
    (pkg / "service.py").write_text(
        """import importlib
import os
import requests
import widget.util as util
from widget.parse import Parser

class Service(Parser):
    def run(self, value: str) -> str:
        requests.get("https://example.com")
        return util.helper(value)

def load_plugin():
    return importlib.import_module("widget.plugin")

TOKEN = os.getenv("TOKEN")
""",
        encoding="utf-8",
    )


def test_graph_resolves_behavioral_edges_and_exposes_impact_ready_indexes(tmp_path: Path) -> None:
    _write_stock(tmp_path)
    graph = build_stock_graph(collect(tmp_path))

    service = next(node for node in graph["nodes"] if node["rel"] == "src/widget/service.py")
    util = next(node for node in graph["nodes"] if node["rel"] == "src/widget/util.py")
    parser = next(node for node in graph["nodes"] if node["rel"] == "src/widget/parse.py")
    plugin = next(node for node in graph["nodes"] if node["rel"] == "src/widget/plugin.py")

    edge_triples = {(edge["from"], edge["to"], edge["kind"]) for edge in graph["edges"]}
    assert (service["id"], util["id"], "calls") in edge_triples
    assert (service["id"], parser["id"], "inherits") in edge_triples
    assert (service["id"], plugin["id"], "dynamic_import") in edge_triples
    assert graph["indexes"]["environment_reads"]["TOKEN"] == [service["id"]]
    assert any(row["source_node"] == service["id"] for row in graph["indexes"]["effects"]["network"])
    assert util["id"] in graph["indexes"]["adjacency"]["downstream"][service["id"]]
    assert graph["inventory"]["relationship_kinds"]["calls"] >= 1
    assert graph["inventory"]["relationship_kinds"]["inherits"] >= 1
    assert graph["inventory"]["dynamic_import_sites"] >= 1


def test_catalog_persists_topology_sidecar(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "unit.py").write_text(
        "import os\n\ndef run():\n    return os.getenv('MODE')\n",
        encoding="utf-8",
    )
    catalog = tmp_path / "catalog"
    payload = collect_to(source, catalog)
    rec = payload["files"][0]

    topology_path = catalog / rec["topology_path"]
    assert topology_path.is_file()
    persisted = json.loads(topology_path.read_text(encoding="utf-8"))
    assert persisted["environment_reads"][0]["key"] == "MODE"
