from __future__ import annotations

from typing import Any

ADMISSION_SCHEMA = "receipt.stock.admission.v1"

_EXTERNAL_TAGS = {
    "requests": {"http-client", "network"},
    "httpx": {"http-client", "network"},
    "aiohttp": {"http-client", "network", "async"},
    "urllib3": {"http-client", "network"},
    "click": {"cli"},
    "typer": {"cli"},
    "argparse": {"cli"},
    "fastapi": {"web-api"},
    "flask": {"web-api"},
    "starlette": {"web-api"},
    "sqlalchemy": {"database"},
    "sqlite3": {"database"},
    "psycopg": {"database", "postgres"},
    "pydantic": {"validation", "data-modeling"},
    "attrs": {"data-modeling"},
    "attr": {"data-modeling"},
    "yaml": {"serialization"},
    "json": {"serialization"},
}


def _public_contract_count(rec: dict[str, Any]) -> int:
    contracts = rec.get("contracts") if isinstance(rec.get("contracts"), dict) else {}
    classes = contracts.get("classes") or []
    functions = contracts.get("functions") or []
    return len(classes) + len(functions)


def infer_capability_tags(rec: dict[str, Any], source_tags: list[str] | None = None) -> list[str]:
    tags = {str(tag).strip() for tag in (source_tags or []) if str(tag).strip()}
    deps = rec.get("dependencies") if isinstance(rec.get("dependencies"), dict) else {}
    for group in ("external", "stdlib"):
        for dep in deps.get(group) or []:
            root = str(dep).split(".", 1)[0]
            tags.update(_EXTERNAL_TAGS.get(root, set()))

    topology = rec.get("topology") if isinstance(rec.get("topology"), dict) else {}
    for effect in topology.get("effects") or []:
        if not isinstance(effect, dict):
            continue
        kind = str(effect.get("kind") or "").strip().lower()
        if kind:
            tags.add(kind)
        if "network" in kind or "http" in kind or "socket" in kind:
            tags.add("network")
        if "file" in kind or "path" in kind or "filesystem" in kind:
            tags.add("filesystem")
        if "subprocess" in kind or "process" in kind:
            tags.add("process")
        if "database" in kind or "sql" in kind:
            tags.add("database")
    if topology.get("environment_reads"):
        tags.add("environment")
    if topology.get("dynamic_imports"):
        tags.add("dynamic-loading")

    contracts = rec.get("contracts") if isinstance(rec.get("contracts"), dict) else {}
    callables = [*(contracts.get("functions") or [])]
    for cls in contracts.get("classes") or []:
        if isinstance(cls, dict):
            callables.extend(cls.get("methods") or [])
    if any(isinstance(item, dict) and item.get("async") for item in callables):
        tags.add("async")
    if rec.get("has_main"):
        tags.add("entrypoint")
    if _public_contract_count(rec):
        tags.add("public-api")
    return sorted(tags)


def evaluate_receipt(
    rec: dict[str, Any],
    *,
    source_tags: list[str] | None = None,
) -> dict[str, Any]:
    """Score one collected unit using only source-backed Receipt evidence.

    Hard gates reject evidence that cannot safely enter durable stock. Soft risks lower
    the score and can constrain a unit without pretending it is unusable.
    """
    hard_failures: list[str] = []
    constraints: list[str] = []
    score = 0

    if rec.get("syntax_ok"):
        score += 25
    else:
        hard_failures.append("syntax_invalid")

    identity = rec.get("source_identity") if isinstance(rec.get("source_identity"), dict) else {}
    if identity.get("source_sha256") and identity.get("path"):
        score += 20
    else:
        hard_failures.append("source_identity_missing")

    source_sha = rec.get("source_sha256") or rec.get("sha256")
    normalized_sha = rec.get("normalized_sha256")
    if source_sha:
        score += 10
    else:
        hard_failures.append("source_hash_missing")
    if normalized_sha:
        score += 15
    else:
        hard_failures.append("normalized_source_missing")

    dependencies = rec.get("dependencies") if isinstance(rec.get("dependencies"), dict) else None
    if dependencies is not None:
        score += 10
    else:
        hard_failures.append("dependency_evidence_missing")

    topology = rec.get("topology") if isinstance(rec.get("topology"), dict) else None
    if topology is not None:
        score += 10
    else:
        hard_failures.append("topology_evidence_missing")

    if _public_contract_count(rec):
        score += 10
    else:
        score += 4
        constraints.append("no_public_contract")

    if topology:
        dynamic_count = len(topology.get("dynamic_imports") or [])
        if dynamic_count:
            score -= min(10, dynamic_count * 2)
            constraints.append("dynamic_import_boundary")
        effect_kinds = sorted(
            {
                str(item.get("kind"))
                for item in topology.get("effects") or []
                if isinstance(item, dict) and item.get("kind")
            }
        )
        if effect_kinds:
            constraints.append("effect_bearing")

    external_count = len((dependencies or {}).get("external") or [])
    if external_count:
        score -= min(8, external_count)
        constraints.append("external_requirements")

    score = max(0, min(100, score))
    if hard_failures:
        decision = "rejected"
    elif score >= 75:
        decision = "accepted"
    elif score >= 50:
        decision = "constrained"
    else:
        decision = "rejected"

    return {
        "schema": ADMISSION_SCHEMA,
        "decision": decision,
        "score": score,
        "hard_failures": sorted(set(hard_failures)),
        "constraints": sorted(set(constraints)),
        "capability_tags": infer_capability_tags(rec, source_tags),
        "grants_execution_authority": False,
    }


def evaluate_catalog(
    payload: dict[str, Any],
    *,
    source_tags: list[str] | None = None,
) -> dict[str, Any]:
    files = payload.get("files") or []
    rows: list[dict[str, Any]] = []
    counts = {"accepted": 0, "constrained": 0, "rejected": 0}
    for rec in files:
        if not isinstance(rec, dict):
            continue
        admission = evaluate_receipt(rec, source_tags=source_tags)
        counts[admission["decision"]] += 1
        rows.append(
            {
                "rel": rec.get("rel"),
                "source_sha256": rec.get("source_sha256") or rec.get("sha256"),
                "admission": admission,
            }
        )
    return {
        "schema": ADMISSION_SCHEMA,
        "counts": counts,
        "files": rows,
        "grants_execution_authority": False,
    }
