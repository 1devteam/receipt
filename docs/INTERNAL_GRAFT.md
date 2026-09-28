# Receipt internal G.R.A.F.T.+

Receipt's internal G.R.A.F.T.+ is a stock-reconstruction layer, not a planner and not an execution engine.

Its contract is simple: build a deterministic, source-grounded artifact that makes Receipt's current Python stock maximally legible to a receiving LLM while preserving open-ended downstream use.

## Invariants

- Artifact construction is deterministic for the same catalog evidence.
- Evidence is source-identity anchored.
- Machine-local absolute origins are excluded from the graph artifact.
- Raw and normalized source text are not copied into the graph artifact.
- Local and relative imports become graph edges only when a unique target can be resolved.
- Missing or multiply-resolved relationships stay explicit in `unresolved`.
- External packages are indexed rather than pretended to be local nodes.
- Duplicate symbols are exposed without declaring them equivalent implementations.
- The graph never chooses the final program/application topology.
- The graph never grants execution, merge, credential, or side-effect authority.

## Outcome ambiguity

Ambiguity belongs to what may be built from the artifact, not to how the artifact is constructed.

The graph should be strict about facts and conservative about conclusions. A single stock artifact may support several valid future compositions depending on user intent. The receiving LLM performs that reasoning; the graph should not precompute an exponential semantic graph of hypothetical applications.

## External collaboration

`receipt.graft.external_bridge.v1` preserves the bridge to universal G.R.A.F.T.+. Large future builds can therefore combine Receipt's detailed stock topology with broader repository/project architecture evidence using commit-pinned source identities and SHA-256 confirmation.
