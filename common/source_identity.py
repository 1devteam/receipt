from __future__ import annotations

from typing import Any

SOURCE_IDENTITY_SCHEMA = "receipt.source_identity.v1"
GRAFT_REF_SCHEMA = "receipt.graft_ref.v1"


class SourceIdentityError(ValueError):
    """Invalid source identity or G.R.A.F.T.+ evidence reference."""


def build_source_identity(
    *,
    rel: str,
    source_sha256: str,
    source: dict[str, Any] | None = None,
    origin: str | None = None,
) -> dict[str, Any]:
    """Build a stable identity that another evidence system can reference.

    GitHub-backed identities are commit-pinned. Local identities retain only
    path/content identity and do not pretend to have repository provenance.
    """
    rel = str(rel or "").strip().replace("\\", "/")
    source_sha256 = str(source_sha256 or "").strip()
    if not rel:
        raise SourceIdentityError("source identity requires rel path")
    if not source_sha256:
        raise SourceIdentityError("source identity requires source_sha256")

    identity: dict[str, Any] = {
        "schema": SOURCE_IDENTITY_SCHEMA,
        "kind": "local",
        "repository": None,
        "commit": None,
        "path": rel,
        "source_sha256": source_sha256,
    }

    if isinstance(source, dict) and source.get("kind") == "github":
        owner = str(source.get("owner") or "").strip()
        repo = str(source.get("repo") or "").strip()
        commit = str(source.get("sha") or "").strip()
        if not owner or not repo or not commit:
            raise SourceIdentityError(
                "github source identity requires owner, repo, and resolved commit sha"
            )
        identity.update(
            {
                "kind": "github",
                "repository": f"{owner}/{repo}",
                "commit": commit,
            }
        )

    if origin:
        identity["origin"] = str(origin)
    return identity


def graft_ref(
    *,
    artifact: str,
    subject: str,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a non-authoritative reference into a G.R.A.F.T.+ artifact."""
    artifact = str(artifact or "").strip()
    subject = str(subject or "").strip()
    if not artifact or not subject:
        raise SourceIdentityError("graft reference requires artifact and subject")
    return {
        "schema": GRAFT_REF_SCHEMA,
        "artifact": artifact,
        "subject": subject,
        "evidence": dict(evidence or {}),
        "grants_execution_authority": False,
    }


def _validate_graft_ref(ref: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(ref, dict):
        raise SourceIdentityError("graft reference must be an object")
    if ref.get("schema") != GRAFT_REF_SCHEMA:
        raise SourceIdentityError("invalid graft reference schema")
    if not str(ref.get("artifact") or "").strip():
        raise SourceIdentityError("graft reference requires artifact")
    if not str(ref.get("subject") or "").strip():
        raise SourceIdentityError("graft reference requires subject")
    if ref.get("grants_execution_authority") is not False:
        raise SourceIdentityError("graft reference may not grant execution authority")
    evidence = ref.get("evidence")
    if evidence is not None and not isinstance(evidence, dict):
        raise SourceIdentityError("graft reference evidence must be an object")
    return dict(ref)


def bridge_payload(
    source_identity: dict[str, Any],
    graft_refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return the Receipt↔G.R.A.F.T.+ bridge envelope.

    The bridge carries identity/evidence references only. It does not copy graph
    semantics into Receipt and never grants execution authority.
    """
    if not isinstance(source_identity, dict):
        raise SourceIdentityError("source identity must be an object")
    if source_identity.get("schema") != SOURCE_IDENTITY_SCHEMA:
        raise SourceIdentityError("invalid source identity schema")
    refs = [_validate_graft_ref(ref) for ref in (graft_refs or [])]
    return {
        "source_identity": dict(source_identity),
        "graft_refs": refs,
        "grants_execution_authority": False,
    }
