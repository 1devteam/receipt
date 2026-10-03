from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from common.io import write_json
from receipt_graft.evidence import canonical_fingerprint
from receipt_stock.query import load_unit_index

STOCK_COVERAGE_SCHEMA = "receipt.stock.coverage.v1"


class StockCoverageError(ValueError):
    """Invalid federated stock coverage evidence."""


def _root(module: str) -> str:
    return str(module or "").strip().lstrip(".").split(".", 1)[0]


def build_stock_coverage(stock_root: Path | str) -> dict[str, Any]:
    """Reveal which observed external requirements can already be supplied by stock.

    This is architectural evidence only. A matching package mount means Receipt has
    source for that import root; it does not assert version/API/license compatibility
    and does not select or compile anything.
    """
    root = Path(stock_root).expanduser().resolve()
    unit_index = load_unit_index(root)
    units = [row for row in unit_index.get("units") or [] if isinstance(row, dict)]

    mount_sources: dict[str, set[str]] = defaultdict(set)
    source_mounts: dict[str, set[str]] = defaultdict(set)
    for unit in units:
        source_id = str(unit.get("source_id") or "")
        mount = str(unit.get("mount") or "").strip().replace("/", ".")
        mount_root = _root(mount)
        if source_id and mount_root:
            mount_sources[mount_root].add(source_id)
            source_mounts[source_id].add(mount_root)

    join_counts: Counter[tuple[str, str, str]] = Counter()
    join_units: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    uncovered_counts: Counter[str] = Counter()
    uncovered_sources: dict[str, set[str]] = defaultdict(set)
    source_totals: Counter[str] = Counter()
    source_covered: Counter[str] = Counter()
    source_uncovered: Counter[str] = Counter()

    for unit in units:
        consumer = str(unit.get("source_id") or "")
        unit_id = str(unit.get("id") or "")
        externals = sorted({_root(dep) for dep in unit.get("external_dependencies") or [] if _root(dep)})
        for package in externals:
            source_totals[consumer] += 1
            providers = sorted(mount_sources.get(package) or [])
            other_providers = [provider for provider in providers if provider != consumer]
            if other_providers:
                source_covered[consumer] += 1
                for provider in other_providers:
                    key = (consumer, provider, package)
                    join_counts[key] += 1
                    if unit_id:
                        join_units[key].add(unit_id)
            elif providers and consumer in providers:
                # The dependency names the source's own mounted package but remained
                # external after source-local analysis. Surface it as an unresolved
                # self-boundary rather than pretending another pack is required.
                source_uncovered[consumer] += 1
                uncovered_counts[package] += 1
                uncovered_sources[package].add(consumer)
            else:
                source_uncovered[consumer] += 1
                uncovered_counts[package] += 1
                if consumer:
                    uncovered_sources[package].add(consumer)

    joins = [
        {
            "consumer_source": consumer,
            "provider_source": provider,
            "package": package,
            "reference_count": count,
            "consumer_units": sorted(join_units[(consumer, provider, package)]),
            "compatibility": "not-determined",
            "license_compatibility": "not-determined",
        }
        for (consumer, provider, package), count in sorted(
            join_counts.items(), key=lambda item: (-item[1], item[0])
        )
    ]
    uncovered = [
        {
            "package": package,
            "reference_count": count,
            "consumer_sources": sorted(uncovered_sources[package]),
            "stock_provider": False,
        }
        for package, count in sorted(
            uncovered_counts.items(), key=lambda item: (-item[1], item[0])
        )
    ]
    source_rows = []
    all_sources = sorted({str(unit.get("source_id") or "") for unit in units if unit.get("source_id")})
    for source_id in all_sources:
        total = int(source_totals[source_id])
        covered = int(source_covered[source_id])
        missing = int(source_uncovered[source_id])
        source_rows.append(
            {
                "source_id": source_id,
                "mounts": sorted(source_mounts.get(source_id) or []),
                "external_references": total,
                "references_satisfiable_by_other_stock": covered,
                "references_without_stock_provider": missing,
                "stock_coverage_ratio": round(covered / total, 6) if total else 1.0,
            }
        )

    report: dict[str, Any] = {
        "schema": STOCK_COVERAGE_SCHEMA,
        "purpose": (
            "Reveal dependency roots already represented by other permanent Receipt stock "
            "packs and expose remaining inventory gaps without asserting compatibility."
        ),
        "stock_unit_index_fingerprint": unit_index.get("fingerprint"),
        "mounts": {
            package: sorted(sources) for package, sources in sorted(mount_sources.items())
        },
        "latent_stock_joins": joins,
        "uncovered_external_packages": uncovered,
        "sources": source_rows,
        "totals": {
            "sources": len(all_sources),
            "units": len(units),
            "mounted_package_roots": len(mount_sources),
            "latent_stock_joins": len(joins),
            "covered_external_references": sum(source_covered.values()),
            "uncovered_external_references": sum(source_uncovered.values()),
            "uncovered_external_packages": len(uncovered),
        },
        "authority": {
            "selects_units": False,
            "asserts_api_compatibility": False,
            "asserts_version_compatibility": False,
            "asserts_license_compatibility": False,
            "grants_execution_authority": False,
        },
        "grants_execution_authority": False,
    }
    report["fingerprint"] = canonical_fingerprint(report)
    return report


def write_stock_coverage(stock_root: Path | str) -> dict[str, Any]:
    root = Path(stock_root).expanduser().resolve()
    report = build_stock_coverage(root)
    write_json(root / "stock-coverage.v1.json", report)
    return report
