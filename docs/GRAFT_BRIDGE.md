# Receipt ↔ G.R.A.F.T.+ bridge

Receipt and G.R.A.F.T.+ remain separate engines.

Receipt owns source possession, normalization, dependency closure, reconstruction, and optional explicit runtime checking.

G.R.A.F.T.+ owns architectural facts, relationships, evidence anchors, completeness, and blast-radius analysis.

The bridge is identity-only. Receipt does not copy G.R.A.F.T.+ graph semantics into its dependency engine, and G.R.A.F.T.+ does not gain authority to mutate or execute Receipt stacks.

## Source identity

Every collected receipt carries `source_identity` using `receipt.source_identity.v1`.

For GitHub-backed shelves the identity is pinned to:

- `repository` (`owner/repo`)
- resolved commit SHA
- repository-relative path
- original source SHA-256

For local-only shelves, repository and commit remain `null`; Receipt does not invent repository provenance.

## Evidence references

`graft_refs` is a list of optional `receipt.graft_ref.v1` references. A reference names a G.R.A.F.T.+ artifact and subject and may carry bounded evidence coordinates.

Bridge construction validates reference schema and rejects any reference that attempts to grant execution authority. Both individual references and the bridge envelope require `grants_execution_authority=false`.

## Matching rule

The preferred cross-tool join is exact repository + commit + path. `source_sha256` provides content confirmation and remains useful when paths move or local mirrors are involved.

A bridge consumer must not treat a path-only or branch-only match as equivalent to a commit-pinned identity when stronger evidence is available.

## Non-goals

This bridge does not:

- make Receipt a graph engine;
- authorize reconstruction based on a G.R.A.F.T.+ conclusion;
- grant merge, runtime, credential, or side-effect authority;
- infer G.R.A.F.T.+ subjects when no evidence reference exists;
- make local-only source look repository-proven.
