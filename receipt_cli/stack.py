"""Selective restack: pick shelf units, close local deps, compile → produce → check."""

from __future__ import annotations

import tempfile
from pathlib import Path, PurePosixPath

from common.io import write_json
from compiler.compile import compile_receipts
from director.check import check_project
from producer.produce import produce
from receipt_cli.shelf import load_receipts


class StackError(ValueError):
    """Selection / restack failure."""


def _match_key(files: list[dict], key: str) -> list[dict]:
    key = key.strip()
    matches = [
        rec
        for rec in files
        if rec.get("rel") == key
        or rec.get("sha256") == key
        or (rec.get("sha256") or "").startswith(key)
        or (rec.get("rel") or "").endswith("/" + key)
        or (rec.get("rel") or "") == key
    ]
    if not matches and "/" not in key:
        matches = [rec for rec in files if Path(rec.get("rel") or "").name == key]
    if not matches and "." not in key and not key.endswith(".py"):
        # class / symbol name via basename stem or contracts
        soft = []
        for rec in files:
            stem = Path(rec.get("rel") or "").stem
            if stem == key:
                soft.append(rec)
                continue
            classes = (rec.get("contracts") or {}).get("classes") or rec.get("classes") or []
            if any(c.get("name") == key for c in classes):
                soft.append(rec)
        matches = soft
    return matches


def resolve_seeds(catalog: Path, keys: list[str]) -> list[dict]:
    data = load_receipts(catalog)
    files = data.get("files") or []
    selected: list[dict] = []
    seen: set[str] = set()
    for key in keys:
        matches = _match_key(files, key)
        if not matches:
            raise StackError(f"no receipt matching seed {key!r}")
        if len(matches) > 1 and not any(m.get("rel") == key for m in matches):
            rels = [m.get("rel") for m in matches]
            raise StackError(f"ambiguous seed {key!r}; matches: {rels}")
        rec = next((m for m in matches if m.get("rel") == key), matches[0])
        sha = rec.get("sha256") or rec.get("rel")
        if sha in seen:
            continue
        seen.add(sha)
        selected.append(rec)
    return selected


def _module_candidates(module: str) -> tuple[str, str]:
    base = module.replace(".", "/")
    return base + ".py", base + "/__init__.py"


def _receipts_for_local_dep(files: list[dict], module: str) -> list[dict]:
    module = module.strip()
    if not module or module == ".":
        return []
    candidates = _module_candidates(module)
    exact = [f for f in files if f.get("rel") in candidates]
    if exact:
        return exact
    ended = [
        f
        for f in files
        if any((f.get("rel") or "").endswith("/" + candidate) for candidate in candidates)
    ]
    if len(ended) == 1:
        return ended
    stem = module.split(".")[-1]
    by_stem = [
        f
        for f in files
        if Path(f.get("rel") or "").stem == stem
        or (
            Path(f.get("rel") or "").name == "__init__.py"
            and Path(f.get("rel") or "").parent.name == stem
        )
    ]
    if len(by_stem) == 1:
        return by_stem
    if ended:
        return ended
    return by_stem


def _relative_target(rel: str, module: str) -> str | None:
    """Resolve a dotted relative import against a receipt path.

    ``.foo`` means sibling ``foo``; ``..foo`` ascends one package level.
    The returned value is a repository-relative module path without extension.
    """
    dots = len(module) - len(module.lstrip("."))
    if dots <= 0:
        return None
    tail = module[dots:]
    parent = list(PurePosixPath(rel).parent.parts)
    ascend = dots - 1
    if ascend > len(parent):
        return None
    if ascend:
        parent = parent[:-ascend]
    if tail:
        parent.extend(part for part in tail.split(".") if part)
    if not parent:
        return None
    return "/".join(parent)


def _receipts_for_relative_dep(files: list[dict], from_rel: str, module: str) -> list[dict]:
    target = _relative_target(from_rel, module)
    if not target:
        return []
    candidates = (target + ".py", target + "/__init__.py")
    return [f for f in files if f.get("rel") in candidates]


def close_local_deps(catalog: Path, seeds: list[dict]) -> dict:
    """Expand selection along extracted local and relative dependency edges only."""
    data = load_receipts(catalog)
    files = data.get("files") or []
    by_sha = {f.get("sha256"): f for f in files if f.get("sha256")}

    selected: dict[str, dict] = {}
    missing: list[dict] = []
    ambiguous: list[dict] = []
    queue: list[dict] = []

    for rec in seeds:
        sha = rec.get("sha256")
        if not sha:
            continue
        selected[sha] = rec
        queue.append(rec)

    def include_or_record(rec: dict, module: str, hits: list[dict], *, kind: str) -> None:
        if not hits:
            missing.append({"from": rec.get("rel"), "module": module, "kind": kind})
            return
        if len(hits) > 1:
            already = [h for h in hits if h.get("sha256") in selected]
            if len(already) == 1:
                hits = already
            else:
                ambiguous.append(
                    {
                        "from": rec.get("rel"),
                        "module": module,
                        "kind": kind,
                        "candidates": [h.get("rel") for h in hits],
                    }
                )
                return
        hit = hits[0]
        sha = hit.get("sha256")
        if not sha or sha in selected:
            return
        selected[sha] = by_sha.get(sha, hit)
        queue.append(selected[sha])

    while queue:
        rec = queue.pop(0)
        deps = rec.get("dependencies") or {}
        for module in deps.get("local") or []:
            include_or_record(
                rec,
                module,
                _receipts_for_local_dep(files, module),
                kind="local",
            )
        for module in deps.get("relative") or []:
            include_or_record(
                rec,
                module,
                _receipts_for_relative_dep(files, rec.get("rel") or "", module),
                kind="relative",
            )

    units = sorted(selected.values(), key=lambda r: r.get("rel") or "")
    return {
        "catalog": str(Path(catalog).resolve()),
        "root": data.get("root"),
        "seeds": [s.get("rel") for s in seeds],
        "units": [
            {
                "rel": u.get("rel"),
                "sha256": u.get("sha256"),
                "classes": [
                    c.get("name")
                    for c in (u.get("contracts") or {}).get("classes") or u.get("classes") or []
                ],
                "local_deps": (u.get("dependencies") or {}).get("local") or [],
                "relative_deps": (u.get("dependencies") or {}).get("relative") or [],
                "external_deps": (u.get("dependencies") or {}).get("external") or [],
            }
            for u in units
        ],
        "count": len(units),
        "missing_local": missing,
        "ambiguous_local": ambiguous,
        "external": sorted(
            {
                dep
                for u in units
                for dep in (u.get("dependencies") or {}).get("external") or []
            }
        ),
        "note": (
            "Closure follows extracted local and relative Python dependency edges only. "
            "Ambiguous/missing locals are reported, not invented."
        ),
    }


def plan(catalog: Path, keys: list[str]) -> dict:
    seeds = resolve_seeds(catalog, keys)
    return close_local_deps(catalog, seeds)


def _selection_receipts_payload(catalog: Path, plan_data: dict) -> dict:
    data = load_receipts(catalog)
    wanted = {u["sha256"] for u in plan_data["units"]}
    files = [f for f in (data.get("files") or []) if f.get("sha256") in wanted]
    return {
        "root": data.get("root"),
        "collected_at": data.get("collected_at"),
        "catalog": str(Path(catalog).resolve()),
        "onboard": data.get("onboard"),
        "selection": {
            "seeds": plan_data["seeds"],
            "count": plan_data["count"],
        },
        "files": files,
        "skipped": [],
    }


def stack(
    catalog: Path,
    keys: list[str],
    *,
    name: str,
    out: Path,
    work: Path | None = None,
    check: bool = True,
    force: bool = False,
) -> dict:
    plan_data = plan(catalog, keys)
    if plan_data["count"] == 0:
        raise StackError("selection is empty")
    gaps = (plan_data.get("missing_local") or []) + (plan_data.get("ambiguous_local") or [])
    if gaps and not force:
        raise StackError(
            "plan has unresolved local deps "
            f"(missing={len(plan_data.get('missing_local') or [])}, "
            f"ambiguous={len(plan_data.get('ambiguous_local') or [])}); "
            "fix seeds or pass force=True / --force"
        )

    out = Path(out).resolve()
    owns_work = work is None
    if work is None:
        tmp = tempfile.TemporaryDirectory(prefix="receipt-stack-")
        work_path = Path(tmp.name)
    else:
        tmp = None
        work_path = Path(work).resolve()
        work_path.mkdir(parents=True, exist_ok=True)

    try:
        receipts_path = work_path / "receipts.json"
        compile_dir = work_path / "compile"
        payload = _selection_receipts_payload(catalog, plan_data)
        write_json(receipts_path, payload)
        write_json(work_path / "plan.json", plan_data)

        meta = compile_receipts(receipts_path, name, compile_dir)
        if not meta["units"]:
            raise StackError("compile produced no units")
        project = produce(compile_dir, out)
        roster = check_project(out) if check else None

        return {
            "plan": plan_data,
            "project": project.get("project") if isinstance(project, dict) else str(out),
            "package": meta.get("package"),
            "compiled_units": len(meta.get("units") or []),
            "compile_errors": meta.get("errors") or [],
            "roster": (
                {
                    "ready": roster.get("ready"),
                    "ok": len(roster.get("ok") or []),
                    "import_error": len(roster.get("import_error") or []),
                    "missing_local": len(roster.get("missing_local") or []),
                    "accounted": roster.get("accounted"),
                    "local_graph_ok": roster.get("local_graph_ok"),
                }
                if roster
                else None
            ),
        }
    finally:
        if owns_work and tmp is not None:
            tmp.cleanup()
