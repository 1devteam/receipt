from __future__ import annotations

import importlib
import inspect
import sys
from pathlib import Path
from typing import Any

from common.io import ReceiptIOError, read_json


class CallError(ValueError):
    """Director call failure."""


def load_unit(project: Path, unit_id: str):
    src = str((project / "src").resolve())
    if src not in sys.path:
        sys.path.insert(0, src)
    if unit_id in sys.modules:
        return importlib.reload(sys.modules[unit_id])
    return importlib.import_module(unit_id)


def _coerce(value: str) -> Any:
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    if value.isdigit() or (value.startswith("-") and value[1:].isdigit()):
        return int(value)
    return value


def _init_needs_args(cls) -> bool:
    try:
        params = inspect.signature(cls.__init__).parameters
    except (TypeError, ValueError):
        return False
    required = [
        name
        for name, param in params.items()
        if name != "self"
        and param.default is inspect.Parameter.empty
        and param.kind
        in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        )
    ]
    return bool(required)


def _resolve(module, spec: str):
    if "." in spec:
        cls_name, method_name = spec.split(".", 1)
        cls = getattr(module, cls_name)
        if inspect.isclass(cls):
            if _init_needs_args(cls):
                raise CallError(
                    f"{cls_name}.__init__ requires arguments; cannot auto-instantiate for {spec}"
                )
            return getattr(cls(), method_name)
        return getattr(cls, method_name)
    obj = getattr(module, spec)
    if inspect.isclass(obj):
        if _init_needs_args(obj):
            raise CallError(f"{spec}.__init__ requires arguments; cannot auto-instantiate")
        return obj()
    return obj


def call_unit(project: Path, unit_id: str, target: str, args: list[str]) -> Any:
    project = Path(project).resolve()
    try:
        manifest = read_json(project / "manifest.json")
    except ReceiptIOError as exc:
        raise CallError(str(exc)) from exc

    known = {u.get("id") for u in manifest.get("units") or []}
    if unit_id not in known:
        raise CallError(f"unknown unit_id {unit_id!r}; not in {project / 'manifest.json'}")

    try:
        module = load_unit(project, unit_id)
        fn = _resolve(module, target)
    except CallError:
        raise
    except AttributeError as exc:
        raise CallError(f"cannot resolve {unit_id}:{target}: {exc}") from exc
    except ImportError as exc:
        raise CallError(f"cannot import {unit_id}: {exc}") from exc

    if not callable(fn):
        return fn
    try:
        return fn(*[_coerce(a) for a in args])
    except TypeError as exc:
        raise CallError(f"call failed {unit_id}:{target}: {exc}") from exc
