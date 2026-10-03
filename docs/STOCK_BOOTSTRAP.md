# Receipt stock bootstrap

Receipt stock bootstrap turns a reviewed manifest of pinned Python source trees into durable Receipt catalogs. It is inventory acquisition, not application execution.

## Invariants

- every source is repository/commit/subpath pinned;
- license metadata is required in the manifest;
- source files are collected through Receipt's existing preservation/normalization path;
- every unit receives deterministic admission evidence and capability tags;
- hard evidence failures are rejected rather than silently admitted;
- dynamic imports, external requirements, and effect-bearing code are surfaced as constraints rather than erased;
- each source remains an independent catalog with its original provenance;
- an aggregate `receipt.stock.index.v1` joins the source catalogs without flattening their identities;
- bootstrapping does not import or execute collected third-party application code;
- no stock artifact grants execution authority.

## Admission

The admission artifact is `receipt.stock.admission.v1`.

Hard gates require syntax-valid normalized Python, stable source identity, source and normalized hashes, dependency evidence, and topology evidence. A hard-gate failure is rejected.

Soft evidence contributes to a deterministic score. Public contracts increase confidence; dynamic imports and external requirements reduce it and become explicit constraints. Units score as `accepted`, `constrained`, or `rejected`. The score is an ingestion-quality signal, not a claim that a unit is safe or appropriate for every future program.

## Capability tags

The bootstrap manifest provides broad source capabilities such as `cli`, `web-api`, `database`, `observability`, and `ai-client`. Receipt augments those with source-backed facts including environment access, dynamic loading, effect kinds, async callables, public API presence, and recognized dependency families.

Tags describe available capability evidence. They do not decide what the user should build.

## Bundled bootstrap

The bundled bootstrap now covers the major reusable capability lanes Receipt needs for practical program assembly while keeping every lane pinned and provenance-preserving:

- `pallets/click` — CLI, command dispatch, configuration, terminal I/O;
- `psf/requests` — synchronous HTTP/network client infrastructure;
- `python-attrs/attrs` — data modeling, validation, typing, compatibility;
- `fastapi/fastapi` — web APIs, routing, dependency injection, request validation, OpenAPI;
- `encode/httpx` — synchronous/async HTTP, streaming, networking and authentication;
- `sqlalchemy/sqlalchemy` — SQL, persistence, ORM and transaction infrastructure;
- `pydantic/pydantic` — typed data models, validation, serialization and schema surfaces;
- `agronholm/apscheduler` — scheduling, jobs, async runtime and coordination;
- `hynek/structlog` — structured logging, context and observability;
- `openai/openai-python` — AI client, tool-interface, structured-output and streaming surfaces.

The manifest pins exact commits. Receipt does not vendor those repositories into its own Git history. Running the bootstrap reconstructs the catalogs from the pinned sources and lets internal G.R.A.F.T.+ fingerprint each independent catalog.

```text
receipt stock manifest
receipt stock bootstrap -o ~/receipt-stock
receipt stock status ~/receipt-stock
```

Materialized layout:

```text
receipt-stock/
├── bootstrap-manifest.v1.json
├── stock-index.v1.json
└── catalogs/
    ├── click-core/
    ├── requests-core/
    ├── attrs-modern/
    ├── attrs-compat/
    ├── fastapi-web/
    ├── httpx-async-client/
    ├── sqlalchemy-core/
    ├── pydantic-models/
    ├── apscheduler-runtime/
    ├── structlog-observability/
    └── openai-sdk/
```

Each catalog retains normal Receipt raw/normalized/contracts/dependencies/topology evidence plus `admission.v1.json`; each receipt in `receipts.json` gains a `stock` envelope containing bootstrap provenance, license metadata, source capabilities, and its admission decision.
