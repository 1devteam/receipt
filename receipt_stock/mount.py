from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

from collector.onboard import modules_from_rels, onboard_source, tops_from_rels
from common.io import write_json


class StockMountError(ValueError):
    """Invalid stock package/module mount or catalog evidence."""


def _mounted_rel(mount: str, rel: str, *, mount_kind: str) -> str:
    rel = str(PurePosixPath(rel))
    if mount_kind == "module":
        return f"{mount}.py"
    if rel == mount or rel.startswith(mount + "/"):
        return rel
    return str(PurePosixPath(mount) / rel)


def _repo_path(subpath: str, original_rel: str, *, mount_kind: str) -> str:
    if mount_kind == "module":
        return str(PurePosixPath(subpath))
    base = PurePosixPath(subpath)
    rel = PurePosixPath(original_rel)
    if str(rel) == str(base) or str(rel).startswith(str(base) + "/"):
        return str(rel)
    return str(base / rel)


def _symbol_index(files: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    symbols: dict[str, list[dict[str, Any]]] = {}
    for rec in files:
        names: list[str] = []
        contracts = rec.get("contracts") if isinstance(rec.get("contracts"), dict) else {}
        for cls in contracts.get("classes") or rec.get("classes") or []:
            if isinstance(cls, dict) and cls.get("name"):
                names.append(str(cls["name"]))
            if isinstance(cls, dict):
                for method in cls.get("methods") or []:
                    if isinstance(method, dict) and method.get("name") and method.get("name") != "__init__":
                        names.append(str(method["name"]))
        for fn in contracts.get("functions") or rec.get("functions") or []:
            if isinstance(fn, dict) and fn.get("name"):
                names.append(str(fn["name"]))
        for name in names:
            symbols.setdefault(name, []).append(
                {"rel": rec.get("rel"), "sha256": rec.get("sha256"), "origin": rec.get("abs")}
            )
    return symbols


def mount_catalog_payload(
    payload: dict[str, Any],
    catalog: Path | str,
    source: dict[str, Any],
) -> dict[str, Any]:
    """Restore a source import root after GitHub subpath collection.

    Package sources are mounted below their logical package directory. Single-module
    sources are mounted directly as ``<module>.py`` so modules such as
    ``typing_extensions`` retain the same import identity they have when installed.
    """
    catalog = Path(catalog).expanduser().resolve()
    mount = str(source.get("mount") or "").strip().strip("/")
    mount_kind = str(source.get("mount_kind") or "package").strip()
    subpath = str(source.get("subpath") or "").strip().strip("/")
    if not mount:
        raise StockMountError(f"stock source has no import mount: {source.get('id')}")
    if mount_kind not in {"package", "module"}:
        raise StockMountError(f"unsupported stock mount kind: {mount_kind}")

    files = [rec for rec in payload.get("files") or [] if isinstance(rec, dict)]
    if mount_kind == "module" and len(files) != 1:
        raise StockMountError(
            f"single-module stock source must collect exactly one Python file: {source.get('id')}"
        )
    rel_map = {
        str(rec.get("rel") or ""): _mounted_rel(
            mount,
            str(rec.get("rel") or ""),
            mount_kind=mount_kind,
        )
        for rec in files
        if rec.get("rel")
    }
    if len(set(rel_map.values())) != len(rel_map):
        raise StockMountError(f"stock mount creates duplicate logical paths: {source.get('id')}")
    mounted_rels = list(rel_map.values())
    tops = tops_from_rels(mounted_rels)
    local_modules = modules_from_rels(mounted_rels)

    mounted: list[dict[str, Any]] = []
    for rec in files:
        original_rel = str(rec.get("rel") or "")
        if not original_rel:
            raise StockMountError(f"stock receipt missing rel: {source.get('id')}")
        item = dict(rec)
        item["stock_original_rel"] = original_rel
        item["rel"] = rel_map[original_rel]

        copy = item.get("copy") or item.get("normalized")
        if copy:
            normalized_path = catalog / str(copy)
            if not normalized_path.is_file():
                raise StockMountError(f"missing normalized stock source: {normalized_path}")
            normalized = normalized_path.read_text(encoding="utf-8", errors="replace")
            info = onboard_source(normalized, tops=tops, local_modules=local_modules)
            item["imports"] = info.get("imports") or []
            item["dependencies"] = info.get("dependencies") or {}
            item["topology"] = info.get("topology") or {}
            item["contracts"] = info.get("contracts") or item.get("contracts") or {}
            item["classes"] = info.get("classes") or item.get("classes") or []
            item["functions"] = info.get("functions") or item.get("functions") or []

        identity = item.get("source_identity")
        if isinstance(identity, dict):
            updated_identity = dict(identity)
            if updated_identity.get("kind") == "github":
                updated_identity["path"] = _repo_path(
                    subpath,
                    original_rel,
                    mount_kind=mount_kind,
                )
            else:
                updated_identity["path"] = item["rel"]
            item["source_identity"] = updated_identity
            bridge = item.get("evidence_bridge")
            if isinstance(bridge, dict):
                item["evidence_bridge"] = {**bridge, "source_identity": dict(updated_identity)}

        source_sha = str(item.get("source_sha256") or item.get("sha256") or "")
        if source_sha:
            write_json(catalog / "dependencies" / f"{source_sha}.json", item.get("dependencies") or {})
            write_json(catalog / "topology" / f"{source_sha}.json", item.get("topology") or {})
            write_json(catalog / "contracts" / f"{source_sha}.json", item.get("contracts") or {})
        mounted.append(item)

    write_json(catalog / "index.json", _symbol_index(mounted))
    return {
        **payload,
        "stock_mount": {
            "logical_root": mount,
            "kind": mount_kind,
            "source_subpath": subpath,
            "preserves_import_identity": True,
        },
        "files": mounted,
    }
