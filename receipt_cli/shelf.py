from __future__ import annotations

import os
from pathlib import Path

from collector.find import find_symbol
from common.io import ReceiptIOError, read_json


DEFAULT_CATALOGS = Path(
    os.environ.get("RECEIPT_CATALOGS", str(Path.home() / "projects" / "catalogs"))
).expanduser()


class ShelfError(ValueError):
    """Catalog / shelf lookup failure."""


def default_catalog(explicit: str | Path | None = None) -> Path:
    if explicit is not None:
        path = Path(explicit).expanduser().resolve()
        _require_catalog(path)
        return path
    env = os.environ.get("RECEIPT_CATALOG")
    if env:
        path = Path(env).expanduser().resolve()
        _require_catalog(path)
        return path
    evolved = DEFAULT_CATALOGS / "evolved"
    if _is_catalog(evolved):
        return evolved.resolve()
    raise ShelfError(
        "no catalog selected; pass -c/--catalog, set RECEIPT_CATALOG, "
        f"or create {evolved}"
    )


def _is_catalog(path: Path) -> bool:
    return path.is_dir() and (path / "receipts.json").is_file()


def _require_catalog(path: Path) -> None:
    if not _is_catalog(path):
        raise ShelfError(f"not a catalog (need receipts.json): {path}")


def list_catalogs(root: Path | None = None) -> list[dict]:
    root = (root or DEFAULT_CATALOGS).expanduser().resolve()
    if not root.is_dir():
        return []
    rows = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if not _is_catalog(child):
            continue
        rows.append(catalog_summary(child))
    return rows


def load_receipts(catalog: Path) -> dict:
    catalog = catalog.resolve()
    _require_catalog(catalog)
    try:
        data = read_json(catalog / "receipts.json")
    except ReceiptIOError as exc:
        raise ShelfError(str(exc)) from exc
    if not isinstance(data, dict):
        raise ShelfError(f"invalid receipts.json: {catalog / 'receipts.json'}")
    return data


def catalog_summary(catalog: Path) -> dict:
    data = load_receipts(catalog)
    files = data.get("files") or []
    copies_dir = catalog / "copies"
    contracts_dir = catalog / "contracts"
    deps_dir = catalog / "dependencies"
    index_path = catalog / "index.json"
    symbols = 0
    if index_path.is_file():
        try:
            index = read_json(index_path)
            symbols = len(index) if isinstance(index, dict) else 0
        except ReceiptIOError:
            symbols = 0

    with_contracts = sum(
        1
        for f in files
        if (f.get("contracts") or {}).get("classes")
        or (f.get("contracts") or {}).get("functions")
        or f.get("classes")
        or f.get("functions")
    )
    with_external = sum(
        1 for f in files if (f.get("dependencies") or {}).get("external")
    )

    return {
        "name": catalog.name,
        "path": str(catalog.resolve()),
        "root": data.get("root"),
        "collected_at": data.get("collected_at"),
        "onboard": data.get("onboard"),
        "files": len(files),
        "syntax_ok": sum(1 for f in files if f.get("syntax_ok")),
        "with_main": sum(1 for f in files if f.get("has_main")),
        "ownership_stripped": sum(1 for f in files if f.get("ownership_stripped")),
        "with_contracts": with_contracts,
        "with_external_deps": with_external,
        "symbols": symbols,
        "has_index": index_path.is_file(),
        "has_copies": copies_dir.is_dir(),
        "has_contract_sidecars": contracts_dir.is_dir(),
        "has_dependency_sidecars": deps_dir.is_dir(),
        "copies": len(list(copies_dir.glob("*.py"))) if copies_dir.is_dir() else 0,
        "contract_sidecars": (
            len(list(contracts_dir.glob("*.json"))) if contracts_dir.is_dir() else 0
        ),
        "dependency_sidecars": (
            len(list(deps_dir.glob("*.json"))) if deps_dir.is_dir() else 0
        ),
    }


def list_receipts(catalog: Path, query: str | None = None, limit: int | None = None) -> list[dict]:
    data = load_receipts(catalog)
    files = data.get("files") or []
    q = (query or "").strip().lower()
    rows = []
    for rec in files:
        rel = rec.get("rel") or ""
        contracts = rec.get("contracts") or {}
        class_names = [c.get("name", "") for c in contracts.get("classes") or rec.get("classes") or []]
        func_names = [f.get("name", "") for f in contracts.get("functions") or rec.get("functions") or []]
        if q and q not in rel.lower() and q not in (rec.get("sha256") or "").lower():
            if q not in " ".join(class_names).lower() and q not in " ".join(func_names).lower():
                continue
        deps = rec.get("dependencies") or {}
        rows.append(
            {
                "rel": rel,
                "sha256": rec.get("sha256"),
                "bytes": rec.get("bytes"),
                "syntax_ok": rec.get("syntax_ok"),
                "has_main": rec.get("has_main"),
                "ownership_stripped": rec.get("ownership_stripped"),
                "classes": class_names,
                "functions": func_names,
                "external_deps": deps.get("external") or [],
                "local_deps": deps.get("local") or [],
                "copy": rec.get("copy"),
            }
        )
    rows.sort(key=lambda r: r["rel"] or "")
    if limit is not None:
        rows = rows[: max(0, limit)]
    return rows


def _load_sidecar(catalog: Path, rel: str | None, embedded: dict | None) -> dict:
    if embedded:
        return embedded
    if not rel:
        return {}
    path = catalog / rel
    if not path.is_file():
        return {}
    try:
        data = read_json(path)
        return data if isinstance(data, dict) else {}
    except ReceiptIOError:
        return {}


def show_receipt(catalog: Path, key: str) -> dict:
    data = load_receipts(catalog)
    key = key.strip()
    files = data.get("files") or []
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
    if not matches:
        raise ShelfError(f"no receipt matching {key!r} in {catalog}")
    if len(matches) > 1 and not any(rec.get("rel") == key for rec in matches):
        rels = [rec.get("rel") for rec in matches]
        raise ShelfError(f"ambiguous key {key!r}; matches: {rels}")
    rec = next((r for r in matches if r.get("rel") == key), matches[0])
    copy_rel = rec.get("copy")
    copy_path = (catalog / copy_rel).resolve() if copy_rel else None

    contracts = _load_sidecar(catalog, rec.get("contracts_path"), rec.get("contracts"))
    dependencies = _load_sidecar(
        catalog, rec.get("dependencies_path"), rec.get("dependencies")
    )
    if not contracts:
        contracts = {
            "classes": rec.get("classes") or [],
            "functions": rec.get("functions") or [],
        }

    return {
        "catalog": str(catalog.resolve()),
        "rel": rec.get("rel"),
        "sha256": rec.get("sha256"),
        "origin": rec.get("abs"),
        "origin_exists": bool(rec.get("abs") and Path(rec["abs"]).is_file()),
        "copy_path": str(copy_path) if copy_path and copy_path.is_file() else None,
        "syntax_ok": rec.get("syntax_ok"),
        "ownership_stripped": rec.get("ownership_stripped"),
        "has_main": rec.get("has_main"),
        "contracts": contracts,
        "dependencies": dependencies,
        "contracts_path": rec.get("contracts_path"),
        "dependencies_path": rec.get("dependencies_path"),
        "onboard_note": (
            "APIs stay in the .py copy. Contracts/deps are extracted sidecars. "
            "__main__ and ownership stamps/headers are stripped from the shelf copy."
        ),
    }


def search_symbols(catalog: Path, query: str) -> list[dict]:
    _require_catalog(catalog)
    try:
        return find_symbol(catalog, query)
    except ReceiptIOError as exc:
        raise ShelfError(str(exc)) from exc


def read_copy(catalog: Path, key: str, *, max_chars: int = 100_000) -> dict:
    shown = show_receipt(catalog, key)
    copy_path = shown.get("copy_path")
    if not copy_path:
        raise ShelfError(f"no shelf copy for {key!r}")
    path = Path(copy_path)
    text = path.read_text(encoding="utf-8", errors="replace")
    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars]
    return {
        "rel": shown.get("rel"),
        "sha256": shown.get("sha256"),
        "copy_path": copy_path,
        "truncated": truncated,
        "chars": len(text),
        "source": text,
    }
