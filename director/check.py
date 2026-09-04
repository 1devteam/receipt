from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from common.io import read_json, write_json


def _local_ok(dep: str, unit_ids: set[str]) -> bool:
    if dep in unit_ids:
        return True
    prefix = dep + "."
    return any(uid.startswith(prefix) for uid in unit_ids)


def check_project(project: Path, timeout: float = 8.0) -> dict:
    project = project.resolve()
    manifest = read_json(project / "manifest.json")
    dependencies = read_json(project / "dependencies.json")
    package = manifest["package"]
    src = project / "src"
    unit_ids = {u["id"] for u in manifest["units"]}

    missing_local = []
    for uid, deps in dependencies.items():
        absent = [d for d in deps.get("local") or [] if not _local_ok(d, unit_ids)]
        if absent:
            missing_local.append({"id": uid, "missing": absent})

    ok = []
    import_error = []
    for unit in manifest["units"]:
        uid = unit["id"]
        try:
            proc = subprocess.run(
                [sys.executable, "-c", f"import sys; sys.path.insert(0, {str(src)!r}); import {uid}"],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            import_error.append({"id": uid, "error": f"import timed out after {timeout}s"})
            continue
        if proc.returncode == 0:
            ok.append(uid)
        else:
            err = (proc.stderr or proc.stdout or "import failed").strip().splitlines()
            import_error.append({"id": uid, "error": err[-1] if err else "import failed"})

    externals: set[str] = set()
    for deps in dependencies.values():
        externals.update(deps.get("external") or [])

    roster = {
        "project": str(project),
        "package": package,
        "units": len(manifest["units"]),
        "ok": ok,
        "import_error": import_error,
        "missing_local": missing_local,
        "external": sorted(externals),
        "accounted": len(ok) + len(import_error) == len(manifest["units"]),
        "local_graph_ok": not missing_local,
        # Ready means every unit imports and the local graph is closed.
        "ready": not missing_local and len(ok) == len(manifest["units"]) and len(manifest["units"]) > 0,
    }
    write_json(project / "roster.json", roster)
    return roster
