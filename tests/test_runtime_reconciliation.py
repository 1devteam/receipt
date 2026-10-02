from __future__ import annotations

from pathlib import Path

from collector.collect import collect_to
from common.io import read_json
from receipt_cli.stack import stack


def test_runtime_reconciliation_chains_static_build_and_runtime_truth(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "pkg").mkdir(parents=True)
    (source / "pkg" / "core.py").write_text(
        "def core(value: str) -> str:\n    return value.upper()\n",
        encoding="utf-8",
    )
    (source / "pkg" / "service.py").write_text(
        "from pkg import core\n\n"
        "def run(value: str) -> str:\n"
        "    return core.core(value)\n",
        encoding="utf-8",
    )

    catalog = tmp_path / "catalog"
    collect_to(source, catalog)
    out = tmp_path / "built"
    result = stack(catalog, ["pkg/service.py"], name="demo", out=out, check=True)

    runtime_path = out / ".receipt" / "graft" / "runtime-reconciliation.v1.json"
    observations_path = out / ".receipt" / "runtime" / "import-observations.v1.json"
    assert runtime_path.is_file()
    assert observations_path.is_file()

    runtime = read_json(runtime_path)
    assert runtime["schema"] == "receipt.graft.runtime_reconciliation.v1"
    assert runtime["status"] == "confirmed"
    assert runtime["runtime"]["ready"] is True
    assert runtime["runtime"]["import_failures"] == []
    assert runtime["fingerprint"]
    chain = runtime["evidence_chain"]
    assert chain["stock_graph_fingerprint"]
    assert chain["impact_fingerprint"]
    assert chain["build_manifest_fingerprint"]
    assert chain["build_reconciliation_fingerprint"]
    assert result["runtime_reconciliation"]["status"] == "confirmed"
    assert result["execution"]["performed"] is True
