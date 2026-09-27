# Receipt execution boundary

Receipt has two materially different responsibilities:

1. **Build** — collect, plan, compile, and produce source artifacts.
2. **Execute/check** — import or invoke produced Python code through Director.

The target contract is fail-safe: building a Receipt stack must not execute repository-controlled Python code unless the caller explicitly crosses the execution boundary.

## Required behavior

- `receipt stack` builds without importing produced modules by default.
- Runtime validation requires an explicit `--check` request.
- Dashboard stack requests default to `check=false`; callers must opt in.
- Pipeline builds follow the same rule.
- `direct check` and `direct call` remain explicit execution surfaces.
- Build results report whether execution was requested and performed.
- Hosted/public use must place Director execution inside a sandbox; this repository's local subprocess isolation is not a public-hosting security boundary.

## Non-goals

This boundary does not weaken dependency closure, provenance, compile validation, or produced-project structure. It only separates artifact construction from executing code supplied by the collected source tree.
