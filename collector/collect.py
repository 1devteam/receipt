from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from collector.onboard import onboard_file, tops_from_rels
from common.io import write_json
from common.refuse import refused


class CollectError(ValueError):
    """Invalid collect inputs."""


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _candidates(root: Path) -> tuple[Path, list[Path]]:
    if root.is_file():
        if root.suffix != ".py":
            raise CollectError(f"tree file is not .py: {root}")
        return root.parent, [root]
    return root, sorted(root.rglob("*.py"))


def collect(root: Path) -> dict:
    root = Path(root)
    if not root.exists():
        raise CollectError(f"tree does not exist: {root}")

    root = root.resolve()
    base, candidates = _candidates(root)
    kept_paths: list[tuple[str, Path]] = []
    skipped: list[dict] = []

    for path in candidates:
        rel = path.name if root.is_file() else path.relative_to(base).as_posix()
        why = refused(rel) or refused(path.name)
        if why:
            skipped.append({"rel": rel, "reason": why})
            continue
        kept_paths.append((rel, path))

    tops = tops_from_rels([rel for rel, _ in kept_paths])
    files: list[dict] = []

    for rel, path in kept_paths:
        info = onboard_file(path, tops=tops)
        files.append(
            {
                "rel": rel,
                "abs": str(path),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
                "syntax_ok": info["syntax_ok"],
                "syntax_error": info["syntax_error"],
                "has_main": info["has_main"],
                "ownership_stripped": info["ownership_stripped"],
                # legacy flat fields (compat for find/index/tests)
                "classes": info["classes"],
                "functions": info["functions"],
                "imports": info["imports"],
                # lifted sidecars (APIs stay in the .py copy)
                "contracts": info["contracts"],
                "dependencies": info["dependencies"],
                "stripped": info["stripped"],
            }
        )

    return {
        "root": str(base),
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "onboard": {
            "strip": ["__main__", "ownership_stamps", "ownership_headers"],
            "extract": ["contracts", "dependencies"],
            "keep_in_source": ["apis", "imports"],
        },
        "files": files,
        "skipped": skipped,
    }


def _index(files: list[dict]) -> dict:
    symbols: dict[str, list[dict]] = {}
    for rec in files:
        names = [c["name"] for c in (rec.get("contracts") or {}).get("classes") or rec.get("classes") or []]
        for cls in (rec.get("contracts") or {}).get("classes") or rec.get("classes") or []:
            names.extend(m["name"] for m in cls.get("methods") or [] if m["name"] != "__init__")
        names.extend(
            f["name"]
            for f in (rec.get("contracts") or {}).get("functions") or rec.get("functions") or []
        )
        for name in names:
            symbols.setdefault(name, []).append(
                {"rel": rec["rel"], "sha256": rec["sha256"], "origin": rec["abs"]}
            )
    return symbols


def collect_to(root: Path, out: Path) -> dict:
    """Write receipts. If out is a directory (or has no .json suffix), write a catalog."""
    data = collect(root)
    out = Path(out).resolve()
    catalog_dir = out if out.suffix != ".json" else out.parent
    receipts_path = out if out.suffix == ".json" else out / "receipts.json"
    catalog_mode = out.suffix != ".json"

    if catalog_mode:
        copies = catalog_dir / "copies"
        contracts_dir = catalog_dir / "contracts"
        deps_dir = catalog_dir / "dependencies"
        copies.mkdir(parents=True, exist_ok=True)
        contracts_dir.mkdir(parents=True, exist_ok=True)
        deps_dir.mkdir(parents=True, exist_ok=True)

        for rec in data["files"]:
            body = rec.get("stripped")
            if body is not None:
                (copies / f"{rec['sha256']}.py").write_text(body, encoding="utf-8")
            write_json(contracts_dir / f"{rec['sha256']}.json", rec.get("contracts") or {})
            write_json(deps_dir / f"{rec['sha256']}.json", rec.get("dependencies") or {})

        write_json(catalog_dir / "index.json", _index(data["files"]))

    stored = []
    for rec in data["files"]:
        item = {k: v for k, v in rec.items() if k != "stripped"}
        if catalog_mode and rec.get("stripped") is not None:
            sha = rec["sha256"]
            item["copy"] = f"copies/{sha}.py"
            item["contracts_path"] = f"contracts/{sha}.json"
            item["dependencies_path"] = f"dependencies/{sha}.json"
        stored.append(item)

    payload = {**data, "files": stored}
    if catalog_mode:
        payload["catalog"] = str(catalog_dir)
    write_json(receipts_path, payload)
    return payload
