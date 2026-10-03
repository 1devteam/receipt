from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from collector.collect import collect_to
from common.io import write_json
from receipt_graft.evidence import canonical_fingerprint
from receipt_graft.graph import build_stock_graph
from receipt_stock.admission import evaluate_catalog
from receipt_stock.coverage import write_stock_coverage
from receipt_stock.manifest import github_spec, load_bootstrap_manifest
from receipt_stock.mount import mount_catalog_payload
from receipt_stock.query import write_unit_index

STOCK_INDEX_SCHEMA = "receipt.stock.index.v1"

Collector = Callable[..., dict[str, Any]]


def _annotate_payload(
    payload: dict[str, Any],
    admission_report: dict[str, Any],
    source: dict[str, Any],
) -> dict[str, Any]:
    by_sha = {
        row.get("source_sha256"): row.get("admission")
        for row in admission_report.get("files") or []
        if isinstance(row, dict) and row.get("source_sha256")
    }
    enriched: list[dict[str, Any]] = []
    for rec in payload.get("files") or []:
        item = dict(rec)
        admission = by_sha.get(rec.get("source_sha256") or rec.get("sha256"))
        item["stock"] = {
            "bootstrap_source_id": source["id"],
            "repository": source["repository"],
            "commit": source["commit"],
            "subpath": source["subpath"],
            "mount": source["mount"],
            "license": source["license"],
            "source_capabilities": list(source["capabilities"]),
            "admission": admission,
        }
        enriched.append(item)
    return {**payload, "files": enriched}


def bootstrap_stock(
    out: Path | str,
    *,
    manifest_path: Path | str | None = None,
    collector: Collector = collect_to,
    force: bool = False,
) -> dict[str, Any]:
    """Materialize curated pinned stock into independent Receipt catalogs."""
    manifest = load_bootstrap_manifest(manifest_path)
    out = Path(out).expanduser().resolve()
    catalogs_root = out / "catalogs"
    catalogs_root.mkdir(parents=True, exist_ok=True)

    source_rows: list[dict[str, Any]] = []
    totals = {"files": 0, "accepted": 0, "constrained": 0, "rejected": 0}
    all_tags: set[str] = set()

    for source in manifest["sources"]:
        catalog = catalogs_root / source["id"]
        payload = collector(
            github_spec(source),
            catalog,
            force=force or not (catalog / "receipts.json").exists(),
            update=(catalog / "receipts.json").exists() and not force,
        )
        payload = mount_catalog_payload(payload, catalog, source)
        admission = evaluate_catalog(payload, source_tags=source["capabilities"])
        enriched = _annotate_payload(payload, admission, source)
        write_json(catalog / "receipts.json", enriched)
        write_json(catalog / "admission.v1.json", admission)

        graph = build_stock_graph(enriched)
        graph_fingerprint = canonical_fingerprint(graph)
        admitted_tags = sorted(
            {
                tag
                for row in admission.get("files") or []
                if isinstance(row, dict)
                for tag in ((row.get("admission") or {}).get("capability_tags") or [])
            }
        )
        all_tags.update(admitted_tags)
        counts = admission["counts"]
        file_count = len(enriched.get("files") or [])
        totals["files"] += file_count
        for key in ("accepted", "constrained", "rejected"):
            totals[key] += int(counts.get(key) or 0)

        source_rows.append(
            {
                "id": source["id"],
                "repository": source["repository"],
                "commit": source["commit"],
                "subpath": source["subpath"],
                "mount": source["mount"],
                "license": source["license"],
                "declared_capabilities": list(source["capabilities"]),
                "observed_capabilities": admitted_tags,
                "catalog": str(catalog),
                "files": file_count,
                "admission": counts,
                "stock_graph_fingerprint": graph_fingerprint,
            }
        )

    unit_index = write_unit_index(out, source_rows)
    coverage = write_stock_coverage(out)
    index: dict[str, Any] = {
        "schema": STOCK_INDEX_SCHEMA,
        "manifest_schema": manifest["schema"],
        "manifest_fingerprint": canonical_fingerprint(manifest),
        "purpose": (
            "Reproducible Receipt stock inventory assembled from pinned, provenance-bound "
            "Python sources and evaluated through deterministic admission gates."
        ),
        "sources": source_rows,
        "totals": totals,
        "capability_tags": sorted(all_tags),
        "unit_index": {
            "schema": unit_index["schema"],
            "path": "stock-units.v1.json",
            "units": unit_index.get("counts", {}).get("units", 0),
            "fingerprint": unit_index.get("fingerprint"),
        },
        "coverage": {
            "schema": coverage.get("schema"),
            "path": "stock-coverage.v1.json",
            "fingerprint": coverage.get("fingerprint"),
            "latent_stock_joins": (coverage.get("totals") or {}).get("latent_stock_joins", 0),
            "uncovered_external_packages": (coverage.get("totals") or {}).get(
                "uncovered_external_packages", 0
            ),
        },
        "grants_execution_authority": False,
    }
    index["fingerprint"] = canonical_fingerprint(index)
    write_json(out / "stock-index.v1.json", index)
    write_json(out / "bootstrap-manifest.v1.json", manifest)
    return index
