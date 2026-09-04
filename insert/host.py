from __future__ import annotations

import importlib
import inspect
import json
import sys
from pathlib import Path
from typing import Any

from insert.paths import COMPILED_ROOT, MANIFESTS, VAULT, ensure_vault


def _project_src_dirs() -> list[Path]:
    dirs: list[Path] = []
    if COMPILED_ROOT.exists():
        for manifest in sorted(COMPILED_ROOT.glob("*/manifest.json")):
            src = manifest.parent / "src"
            if src.is_dir():
                dirs.append(src)
    return dirs


def _ensure_path(*extra: Path) -> None:
    ensure_vault()
    for path in extra:
        s = str(path)
        if s not in sys.path:
            sys.path.insert(0, s)
    for src in _project_src_dirs():
        s = str(src)
        if s not in sys.path:
            sys.path.insert(0, s)
    vault = str(VAULT)
    if vault not in sys.path:
        sys.path.append(vault)


def list_manifests() -> list[dict]:
    _ensure_path()
    out = []
    if COMPILED_ROOT.exists():
        for path in sorted(COMPILED_ROOT.glob("*/manifest.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            data["_project"] = str(path.parent)
            out.append(data)
    seen = {m.get("package") for m in out}
    if MANIFESTS.exists():
        for path in sorted(MANIFESTS.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("package") in seen:
                continue
            data["_project"] = "vault"
            out.append(data)
    return out


def load_unit(insert_id: str, project: Path | None = None):
    extra = []
    if project is not None:
        extra.append(project / "src")
    _ensure_path(*extra)
    return importlib.import_module(insert_id)


def _resolve_target(module, spec: str):
    if "." in spec:
        cls_name, method_name = spec.split(".", 1)
        cls = getattr(module, cls_name)
        if inspect.isclass(cls):
            inst = cls()
            return getattr(inst, method_name)
        return getattr(cls, method_name)
    obj = getattr(module, spec)
    if inspect.isclass(obj):
        return obj()
    return obj


def call(insert_id: str, target: str, args: list[str], project: Path | None = None) -> Any:
    module = load_unit(insert_id, project=project)
    fn = _resolve_target(module, target)
    if not callable(fn):
        return fn
    return fn(*[_coerce(a) for a in args])


def _coerce(value: str) -> Any:
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    if value.isdigit() or (value.startswith("-") and value[1:].isdigit()):
        return int(value)
    return value


def exports(insert_id: str, project: Path | None = None) -> list[str]:
    module = load_unit(insert_id, project=project)
    names = []
    for name, obj in inspect.getmembers(module):
        if name.startswith("_") or name.startswith("INSERT_"):
            continue
        if inspect.isclass(obj) or inspect.isfunction(obj):
            names.append(name)
    return names
