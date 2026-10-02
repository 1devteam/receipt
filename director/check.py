from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from common.io import read_json, write_json

TRACE_PREFIX = "__RECEIPT_RUNTIME_TRACE__="


def _local_ok(dep: str, unit_ids: set[str]) -> bool:
    if dep in unit_ids:
        return True
    prefix = dep + "."
    return any(uid.startswith(prefix) for uid in unit_ids)


def _trace_import(src: Path, uid: str, package: str, timeout: float) -> dict:
    script = (
        "import importlib,json,sys;"
        f"sys.path.insert(0,{str(src)!r});"
        f"importlib.import_module({uid!r});"
        f"mods=sorted(m for m in sys.modules if m=={package!r} or m.startswith({(package + '.')!r}));"
        f"print({TRACE_PREFIX!r}+json.dumps({{'loaded_modules':mods}},sort_keys=True))"
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {
            "id": uid,
            "status": "timeout",
            "returncode": None,
            "loaded_modules": [],
            "error": f"import timed out after {timeout}s",
        }

    trace = None
    for line in reversed((proc.stdout or "").splitlines()):
        if line.startswith(TRACE_PREFIX):
            try:
                trace = json.loads(line[len(TRACE_PREFIX) :])
            except json.JSONDecodeError:
                trace = None
            break

    if proc.returncode == 0:
        return {
            "id": uid,
            "status": "ok",
            "returncode": 0,
            "loaded_modules": sorted(set((trace or {}).get("loaded_modules") or [])),
            "error": None,
        }

    err = (proc.stderr or proc.stdout or "import failed").strip().splitlines()
    return {
        "id": uid,
        "status": "import_error",
        "returncode": proc.returncode,
        "loaded_modules": sorted(set((trace or {}).get("loaded_modules") or [])),
        "error": err[-1] if err else "import failed",
    }


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

    runtime_units = []
    ok = []
    import_error = []
    for unit in manifest["units"]:
        uid = unit["id"]
        observation = _trace_import(src, uid, package, timeout)
        runtime_units.append(observation)
        if observation["status"] == "ok":
            ok.append(uid)
        else:
            import_error.append({"id": uid, "error": observation["error"]})

    externals: set[str] = set()
    for deps in dependencies.values():
        externals.update(deps.get("external") or [])

    declared_local_edges = sorted(
        {
            (uid, dep)
            for uid, deps in dependencies.items()
            for dep in deps.get("local") or []
        }
    )
    observed_local_edges = sorted(
        {
            (row["id"], module)
            for row in runtime_units
            if row.get("status") == "ok"
            for module in row.get("loaded_modules") or []
            if module != row["id"] and module in unit_ids
        }
    )

    roster = {
        "project": str(project),
        "package": package,
        "units": len(manifest["units"]),
        "ok": ok,
        "import_error": import_error,
        "missing_local": missing_local,
        "external": sorted(externals),
        "runtime": {
            "units": runtime_units,
            "declared_local_edges": [list(edge) for edge in declared_local_edges],
            "observed_local_edges": [list(edge) for edge in observed_local_edges],
        },
        "accounted": len(ok) + len(import_error) == len(manifest["units"]),
        "local_graph_ok": not missing_local,
        "ready": not missing_local and len(ok) == len(manifest["units"]) and len(manifest["units"]) > 0,
    }
    write_json(project / "roster.json", roster)
    write_json(
        project / ".receipt" / "runtime" / "import-observations.v1.json",
        {
            "schema": "receipt.runtime.import_observations.v1",
            "package": package,
            "units": runtime_units,
            "declared_local_edges": [list(edge) for edge in declared_local_edges],
            "observed_local_edges": [list(edge) for edge in observed_local_edges],
            "grants_execution_authority": False,
        },
    )
    return roster
