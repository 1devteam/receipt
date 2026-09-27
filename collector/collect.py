from __future__ import annotations

import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path

from collector.github import GitHubError, GitHubSpec, is_github_spec, snapshot_github
from collector.onboard import modules_from_rels, onboard_source, tops_from_rels
from common.io import ReceiptIOError, read_json, write_json
from common.refuse import refused


class CollectError(ValueError):
    """Invalid collect inputs."""


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return _sha256_bytes(text.encode("utf-8"))


def _candidates(root: Path) -> tuple[Path, list[Path]]:
    if root.is_file():
        if root.suffix != ".py":
            raise CollectError(f"tree file is not .py: {root}")
        return root.parent, [root]
    return root, sorted(root.rglob("*.py"))


def collect(root: Path | str, *, ref: str | None = None) -> dict:
    spec = str(root).strip()
    if is_github_spec(spec):
        cleanup: Path | None = None
        try:
            scan_root, gh, cleanup = snapshot_github(spec, ref=ref)
            data = _collect_local(scan_root)
            data["source"] = gh.as_meta()
            data["root"] = gh.page_url()
            for rec in data["files"]:
                rec["abs"] = gh.blob_url(rec["rel"])
            return data
        except GitHubError as exc:
            raise CollectError(str(exc)) from exc
        finally:
            if cleanup is not None:
                shutil.rmtree(cleanup, ignore_errors=True)

    path = Path(spec).expanduser()
    if not path.exists():
        raise CollectError(f"tree does not exist: {path}")
    return _collect_local(path.resolve())


def _collect_local(root: Path) -> dict:
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

    rels = [rel for rel, _ in kept_paths]
    tops = tops_from_rels(rels)
    local_modules = modules_from_rels(rels)
    files: list[dict] = []

    for rel, path in kept_paths:
        raw_bytes = path.read_bytes()
        source = raw_bytes.decode("utf-8", errors="replace")
        info = onboard_source(source, tops=tops, local_modules=local_modules)
        source_sha = _sha256_bytes(raw_bytes)
        normalized = info.get("stripped")
        normalized_sha = _sha256_text(normalized) if normalized is not None else None
        files.append(
            {
                "rel": rel,
                "abs": str(path),
                "bytes": len(raw_bytes),
                # sha256 remains the canonical source-content identity for compatibility.
                "sha256": source_sha,
                "source_sha256": source_sha,
                "normalized_sha256": normalized_sha,
                "normalization": {
                    "source_sha256": source_sha,
                    "normalized_sha256": normalized_sha,
                    "transforms": list(info.get("normalization_transforms") or []),
                },
                "syntax_ok": info["syntax_ok"],
                "syntax_error": info["syntax_error"],
                "has_main": info["has_main"],
                "ownership_stripped": info["ownership_stripped"],
                # legacy flat fields (compat for find/index/tests)
                "classes": info["classes"],
                "functions": info["functions"],
                "imports": info["imports"],
                # lifted sidecars (APIs stay in the normalized .py copy)
                "contracts": info["contracts"],
                "dependencies": info["dependencies"],
                # Transient persistence material; removed from receipts.json below.
                "raw_bytes": raw_bytes,
                "stripped": normalized,
            }
        )

    return {
        "root": str(base),
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "onboard": {
            "preserve": ["raw_source"],
            "normalize": ["ast_unparse", "remove_main_guard", "remove_ownership_metadata"],
            "extract": ["contracts", "dependencies"],
            "keep_in_normalized_source": ["apis", "imports"],
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


def _origin_key(source: dict | None) -> tuple:
    if not source or not isinstance(source, dict):
        return ("local",)
    if source.get("kind") == "github":
        return (
            "github",
            source.get("owner"),
            source.get("repo"),
            source.get("subpath") or "",
        )
    return (str(source.get("kind") or "unknown"),)


def _file_diff(old_files: list[dict], new_files: list[dict]) -> dict:
    old_by = {f.get("rel"): f.get("sha256") for f in old_files if f.get("rel")}
    new_by = {f.get("rel"): f.get("sha256") for f in new_files if f.get("rel")}
    added = sorted(rel for rel in new_by if rel not in old_by)
    removed = sorted(rel for rel in old_by if rel not in new_by)
    changed = sorted(rel for rel in new_by if rel in old_by and old_by[rel] != new_by[rel])
    unchanged = sum(1 for rel in new_by if rel in old_by and old_by[rel] == new_by[rel])
    return {
        "added": added,
        "removed": removed,
        "changed": changed,
        "unchanged": unchanged,
    }


def _prune_unreferenced(catalog_dir: Path, files: list[dict]) -> None:
    source_keep = {f.get("source_sha256") or f.get("sha256") for f in files}
    normalized_keep = {f.get("normalized_sha256") for f in files if f.get("normalized_sha256")}
    keep_by_folder = {
        "raw": source_keep,
        "normalized": normalized_keep,
        "contracts": source_keep,
        "dependencies": source_keep,
        # Legacy copies may exist after an in-place catalog upgrade. Keep only
        # still-referenced source identities; new receipts no longer point here.
        "copies": source_keep,
    }
    for sub, keep in keep_by_folder.items():
        folder = catalog_dir / sub
        if not folder.is_dir():
            continue
        glob = "*.json" if sub in {"contracts", "dependencies"} else "*.py"
        for path in folder.glob(glob):
            if path.stem not in keep:
                path.unlink(missing_ok=True)


def spec_from_source(source: dict) -> str:
    if not isinstance(source, dict) or source.get("kind") != "github":
        raise CollectError("catalog has no github source")
    owner = source.get("owner")
    repo = source.get("repo")
    if not owner or not repo:
        raise CollectError("github source missing owner/repo")
    spec = GitHubSpec(
        owner=str(owner),
        repo=str(repo),
        ref=source.get("ref") or None,
        subpath=source.get("subpath") or None,
        kind="blob" if str(source.get("subpath") or "").endswith(".py") else "tree",
    )
    return spec.spec_string()


def sync_catalog(
    catalog: Path,
    *,
    ref: str | None = None,
    force: bool = False,
) -> dict:
    """Re-fetch a GitHub-backed catalog and refresh receipts in place."""
    catalog = Path(catalog).expanduser().resolve()
    receipts_path = catalog / "receipts.json"
    if not receipts_path.is_file():
        raise CollectError(f"not a catalog (need receipts.json): {catalog}")
    try:
        previous = read_json(receipts_path)
    except ReceiptIOError as exc:
        raise CollectError(str(exc)) from exc
    if not isinstance(previous, dict):
        raise CollectError(f"invalid receipts.json: {receipts_path}")
    spec = spec_from_source(previous.get("source") or {})
    return collect_to(spec, catalog, ref=ref, update=True, force=force)


def collect_to(
    root: Path | str,
    out: Path,
    *,
    ref: str | None = None,
    update: bool = False,
    force: bool = False,
) -> dict:
    """Write receipts. If out is a directory (or has no .json suffix), write a catalog."""
    out = Path(out).expanduser().resolve()
    catalog_dir = out if out.suffix != ".json" else out.parent
    receipts_path = out if out.suffix == ".json" else out / "receipts.json"
    catalog_mode = out.suffix != ".json"

    previous: dict | None = None
    if catalog_mode and receipts_path.is_file():
        try:
            loaded = read_json(receipts_path)
        except ReceiptIOError as exc:
            raise CollectError(str(exc)) from exc
        if not isinstance(loaded, dict):
            raise CollectError(f"invalid receipts.json: {receipts_path}")
        previous = loaded
        if not update and not force:
            raise CollectError(
                f"catalog exists: {out} (pass --update to refresh or --force to replace)"
            )

    data = collect(root, ref=ref)
    if previous is not None and update and not force:
        old_key = _origin_key(previous.get("source") if isinstance(previous.get("source"), dict) else None)
        new_key = _origin_key(data.get("source") if isinstance(data.get("source"), dict) else None)
        if old_key != new_key:
            raise CollectError(
                f"catalog origin mismatch: {old_key} -> {new_key} (pass --force to switch origin)"
            )
    if previous is not None:
        data["diff"] = _file_diff(previous.get("files") or [], data.get("files") or [])
    elif catalog_mode:
        data["diff"] = {
            "added": [f["rel"] for f in data.get("files") or [] if f.get("rel")],
            "removed": [],
            "changed": [],
            "unchanged": 0,
        }

    # Remote origins vanish after the snapshot is deleted; persist both exact
    # source bytes and normalized compile input whenever a durable copy is needed.
    persist_copies = catalog_mode or bool(data.get("source"))

    if persist_copies:
        raw_dir = catalog_dir / "raw"
        normalized_dir = catalog_dir / "normalized"
        raw_dir.mkdir(parents=True, exist_ok=True)
        normalized_dir.mkdir(parents=True, exist_ok=True)
        if catalog_mode:
            contracts_dir = catalog_dir / "contracts"
            deps_dir = catalog_dir / "dependencies"
            contracts_dir.mkdir(parents=True, exist_ok=True)
            deps_dir.mkdir(parents=True, exist_ok=True)
        else:
            contracts_dir = None
            deps_dir = None

        for rec in data["files"]:
            source_sha = rec["source_sha256"]
            raw_dir.joinpath(f"{source_sha}.py").write_bytes(rec["raw_bytes"])
            body = rec.get("stripped")
            normalized_sha = rec.get("normalized_sha256")
            if body is not None and normalized_sha:
                (normalized_dir / f"{normalized_sha}.py").write_text(body, encoding="utf-8")
            if catalog_mode:
                write_json(contracts_dir / f"{source_sha}.json", rec.get("contracts") or {})
                write_json(deps_dir / f"{source_sha}.json", rec.get("dependencies") or {})

        if catalog_mode:
            write_json(catalog_dir / "index.json", _index(data["files"]))
        if catalog_mode and previous is not None:
            _prune_unreferenced(catalog_dir, data["files"])

    stored = []
    for rec in data["files"]:
        item = {k: v for k, v in rec.items() if k not in {"stripped", "raw_bytes"}}
        if persist_copies:
            source_sha = rec["source_sha256"]
            item["raw"] = f"raw/{source_sha}.py"
            normalized_sha = rec.get("normalized_sha256")
            if rec.get("stripped") is not None and normalized_sha:
                # `copy` remains the compile-source pointer for backward compatibility.
                item["copy"] = f"normalized/{normalized_sha}.py"
                item["normalized"] = item["copy"]
            if catalog_mode:
                item["contracts_path"] = f"contracts/{source_sha}.json"
                item["dependencies_path"] = f"dependencies/{source_sha}.json"
        stored.append(item)

    payload = {**data, "files": stored}
    if catalog_mode:
        payload["catalog"] = str(catalog_dir)
    write_json(receipts_path, payload)
    return payload
