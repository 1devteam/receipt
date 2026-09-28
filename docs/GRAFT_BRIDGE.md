# Receipt internal G.R.A.F.T.+ and external bridge

Receipt now owns a specialized internal G.R.A.F.T.+ stock graph in addition to its source, normalization, catalog, compiler, producer, and explicit runtime-check responsibilities.

The internal graph is deliberately Receipt-specific. Its job is to reveal the stock with high factual resolution: what Python units are present, where they came from, which contracts and symbols they expose, which local imports connect them, which external packages they depend on, where relationships are ambiguous or unresolved, and which source identities anchor every node.

It does **not** choose a final application topology. Artifact construction is deterministic and evidence-backed; downstream outcomes remain open so an LLM can reason from the same stock toward different user-requested programs.

## Internal stock artifact

Collection emits a `receipt.graft.stock.v1` artifact.

For catalog-directory output the canonical location is:

`graft/stock-graph.v1.json`

For direct `receipts.json` output the sidecar is:

`receipts.graft.json`

The graph carries:

- content-addressed source nodes;
- source identity without machine-local absolute paths;
- module aliases;
- class/function contract surfaces;
- local and relative import relationships;
- unresolved or ambiguous local relationships;
- external and standard-library dependency indexes;
- duplicate-symbol visibility;
- explicit non-authority fields.

It intentionally contains neither raw nor normalized source text. Those remain in Receipt's provenance store.

`grants_execution_authority` is always false, `implements_plan` is false, and `outcome_authority` is `not-determined`.

## External G.R.A.F.T.+ collaboration bridge

Receipt's internal graph does not replace the universal external G.R.A.F.T.+ engine. The existing bridge remains so the two graphs can collaborate on larger projects.

Every collected receipt carries `source_identity` using `receipt.source_identity.v1`.

For GitHub-backed shelves the identity is pinned to:

- `repository` (`owner/repo`)
- resolved commit SHA
- repository-relative path
- original source SHA-256

For local-only shelves, repository and commit remain `null`; Receipt does not invent repository provenance.

The internal stock graph exposes `external_graft_bridge` using `receipt.graft.external_bridge.v1`. Existing `receipt.graft_ref.v1` references remain identity/evidence links into external G.R.A.F.T.+ artifacts.

The preferred cross-graph join is exact repository + commit + path + source SHA-256. A bridge consumer must not treat a path-only or branch-only match as equivalent to a commit-pinned identity when stronger evidence is available.

Neither graph inherits execution, credential, merge, or side-effect authority from the other.

## Design rule

Receipt internal G.R.A.F.T.+ should grow only when additional evidence makes the stock materially more revealing to the compiler's supervising LLM.

It is not intended to become an exponentially expanding semantic application graph. It should preserve hard facts, relationship evidence, unresolved boundaries, and provenance while leaving possible application outcomes open.

That separation is intentional:

- Receipt owns stock and deterministic compilation.
- Receipt internal G.R.A.F.T.+ owns stock revelation and relationship topology.
- External G.R.A.F.T.+ may contribute broader project architecture and blast-radius evidence through the bridge.
- The receiving LLM reasons across those artifacts for the requested outcome.
