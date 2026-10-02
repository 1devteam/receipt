from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_fingerprint(payload: Any) -> str:
    """Fingerprint JSON-compatible evidence with any top-level fingerprint excluded."""
    if isinstance(payload, dict):
        payload = {key: value for key, value in payload.items() if key != "fingerprint"}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def stamp_fingerprint(payload: dict[str, Any]) -> dict[str, Any]:
    payload["fingerprint"] = canonical_fingerprint(payload)
    return payload
