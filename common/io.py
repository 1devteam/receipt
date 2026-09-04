from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ReceiptIOError(RuntimeError):
    """Readable JSON I/O failure with path context."""


def write_json(path: Path, data: Any) -> None:
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        raise ReceiptIOError(f"cannot write {path}: {exc}") from exc


def read_json(path: Path) -> Any:
    path = Path(path)
    if not path.is_file():
        raise ReceiptIOError(f"missing json: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ReceiptIOError(f"invalid json: {path}: {exc}") from exc
    except OSError as exc:
        raise ReceiptIOError(f"cannot read {path}: {exc}") from exc
