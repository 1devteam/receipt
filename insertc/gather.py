from __future__ import annotations

from pathlib import Path

from insertc.refuse import refused


def gather_py(root: Path) -> list[Path]:
    kept, _skipped = gather_py_with_skips(root)
    return kept


def gather_py_with_skips(root: Path) -> tuple[list[Path], list[dict]]:
    root = root.resolve()
    kept: list[Path] = []
    skipped: list[dict] = []
    if root.is_file():
        if root.suffix != ".py":
            return [], [{"path": str(root), "reason": "not-py"}]
        why = refused(root.name) or refused(str(root))
        if why:
            return [], [{"path": str(root), "reason": why}]
        return [root], []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        why = refused(rel) or refused(path.name)
        if why:
            skipped.append({"path": rel, "reason": why})
            continue
        kept.append(path)
    return kept, skipped


def batch_package_name(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name.strip())
    cleaned = cleaned.strip("_") or "batch"
    if cleaned[0].isdigit():
        cleaned = "i_" + cleaned
    if not cleaned.startswith("i_"):
        cleaned = "i_" + cleaned
    return cleaned
