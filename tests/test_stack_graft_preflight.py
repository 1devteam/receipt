from __future__ import annotations

from pathlib import Path

from collector.collect import collect_to
from common.io import read_json
from receipt_cli.stack import stack


def test_stack_persists_full_shelf_graft_preflight(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "pkg").mkdir(parents=True)
    (source / "tests").mkdir()

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
    (source / "tests" / "test_service.py").write_text(
        "from pkg import service\n\n"
        "def test_run():\n"
        "    assert service.run('a') == 'A'\n",
        encoding="utf-8",
    )

    catalog = tmp_path / "catalog"
    collect_to(source, catalog)

    out = tmp_path / "built"
    result = stack(
        catalog,
        ["pkg/service.py"],
        name="demo",
        out=out,
        check=False,
    )

    preflight = result["graft_preflight"]
    assert preflight["grants_execution_authority"] is False
    assert preflight["implements_plan"] is False
    assert preflight["change_authority"] == "not-determined"
    assert preflight["impact"]["affected_count"] >= 3
    assert any(row["rel"] == "tests/test_service.py" for row in preflight["candidate_tests"])

    artifact = out / ".receipt" / "graft" / "impact.v1.json"
    assert artifact.is_file()
    report = read_json(artifact)
    assert report["fingerprint"] == preflight["fingerprint"]
    assert any(node["rel"] == "pkg/core.py" for node in report["slice"]["nodes"])
    assert any(node["rel"] == "tests/test_service.py" for node in report["slice"]["nodes"])
    assert result["execution"] == {
        "requested": False,
        "performed": False,
        "boundary": "explicit",
    }
