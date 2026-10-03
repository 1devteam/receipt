from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path, PurePosixPath
from typing import Any

BOOTSTRAP_SCHEMA = "receipt.stock.bootstrap.v1"
MOUNT_KINDS = {"package", "module"}


class StockManifestError(ValueError):
    """Invalid stock bootstrap manifest."""


def _default_mount(subpath: str, mount_kind: str) -> str:
    name = PurePosixPath(subpath).name
    if mount_kind == "module" and name.endswith(".py"):
        return name[:-3]
    return name


def _validate_mount(value: str, *, source_id: str, mount_kind: str) -> str:
    mount = str(value or "").strip().strip("/")
    parts = PurePosixPath(mount).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise StockManifestError(f"invalid {mount_kind} mount for {source_id}: {value!r}")
    if mount_kind == "module" and len(parts) != 1:
        raise StockManifestError(f"module mount must be one import root for {source_id}: {value!r}")
    if mount.endswith(".py"):
        raise StockManifestError(f"mount names import identity, not a .py path: {source_id}")
    return "/".join(parts)


def _validate_source(source: dict[str, Any]) -> dict[str, Any]:
    required = ("id", "repository", "commit", "subpath", "license", "capabilities")
    missing = [key for key in required if not source.get(key)]
    if missing:
        raise StockManifestError(
            f"stock source missing {', '.join(missing)}: {source.get('id') or '<unnamed>'}"
        )
    source_id = str(source["id"]).strip()
    repository = str(source["repository"]).strip()
    commit = str(source["commit"]).strip()
    subpath = str(source["subpath"]).strip().strip("/")
    if repository.count("/") != 1:
        raise StockManifestError(f"repository must be owner/name: {repository}")
    if len(commit) < 12:
        raise StockManifestError(f"commit must be pinned, not a branch/tag: {source_id}")
    mount_kind = str(source.get("mount_kind") or ("module" if subpath.endswith(".py") else "package")).strip()
    if mount_kind not in MOUNT_KINDS:
        raise StockManifestError(f"mount_kind must be package or module: {source_id}")
    if mount_kind == "module" and not subpath.endswith(".py"):
        raise StockManifestError(f"module stock source must select a .py file: {source_id}")
    capabilities = sorted({str(item).strip() for item in source["capabilities"] if str(item).strip()})
    if not capabilities:
        raise StockManifestError(f"source has no capabilities: {source_id}")
    mount = _validate_mount(
        source.get("mount") or _default_mount(subpath, mount_kind),
        source_id=source_id,
        mount_kind=mount_kind,
    )
    return {
        **source,
        "id": source_id,
        "repository": repository,
        "commit": commit,
        "subpath": subpath,
        "mount": mount,
        "mount_kind": mount_kind,
        "license": str(source["license"]).strip(),
        "capabilities": capabilities,
    }


def validate_bootstrap_manifest(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise StockManifestError("stock manifest must be an object")
    if payload.get("schema") != BOOTSTRAP_SCHEMA:
        raise StockManifestError(
            f"stock manifest schema must be {BOOTSTRAP_SCHEMA}, got {payload.get('schema')!r}"
        )
    raw_sources = payload.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise StockManifestError("stock manifest requires at least one source")
    sources = [_validate_source(item) for item in raw_sources if isinstance(item, dict)]
    if len(sources) != len(raw_sources):
        raise StockManifestError("every stock source must be an object")
    ids = [item["id"] for item in sources]
    if len(ids) != len(set(ids)):
        raise StockManifestError("stock source ids must be unique")
    return {
        **payload,
        "schema": BOOTSTRAP_SCHEMA,
        "sources": sources,
        "grants_execution_authority": False,
    }


def load_bootstrap_manifest(path: Path | str | None = None) -> dict[str, Any]:
    if path is None:
        text = files("receipt_stock").joinpath("bootstrap.v1.json").read_text(encoding="utf-8")
    else:
        text = Path(path).expanduser().read_text(encoding="utf-8")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise StockManifestError(f"invalid stock manifest JSON: {exc}") from exc
    return validate_bootstrap_manifest(payload)


def github_spec(source: dict[str, Any]) -> str:
    return f"github:{source['repository']}@{source['commit']}:{source['subpath']}"
