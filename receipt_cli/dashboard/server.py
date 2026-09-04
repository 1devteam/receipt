from __future__ import annotations

import json
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from collector.collect import CollectError, collect_to
from receipt_cli.shelf import (
    DEFAULT_CATALOGS,
    ShelfError,
    catalog_summary,
    default_catalog,
    list_catalogs,
    list_receipts,
    read_copy,
    search_symbols,
    show_receipt,
)
from receipt_cli.stack import StackError, plan as stack_plan, stack as stack_build

STATIC_DIR = Path(__file__).resolve().parent / "static"


def _json_bytes(data: Any, status: int = 200) -> tuple[int, bytes, str]:
    body = json.dumps(data, indent=2).encode("utf-8")
    return status, body, "application/json; charset=utf-8"


def _read_json(handler: BaseHTTPRequestHandler) -> Any:
    length = int(handler.headers.get("Content-Length") or 0)
    raw = handler.rfile.read(length) if length else b"{}"
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def _qs(path: str) -> dict[str, str]:
    q = parse_qs(urlparse(path).query)
    return {k: v[0] for k, v in q.items() if v}


def _catalog_from_params(params: dict[str, str]) -> Path:
    return default_catalog(params.get("catalog") or None)


class DashboardHandler(BaseHTTPRequestHandler):
    catalogs_root: Path = DEFAULT_CATALOGS
    default_catalog_path: Path | None = None

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _resolve_catalog(self, params: dict[str, str]) -> Path:
        if params.get("catalog"):
            return Path(params["catalog"]).expanduser().resolve()
        if self.default_catalog_path is not None:
            return self.default_catalog_path
        return _catalog_from_params(params)

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        params = _qs(self.path)
        path = urlparse(self.path).path

        try:
            if path in {"/", "/index.html"}:
                html = (STATIC_DIR / "index.html").read_bytes()
                self._send(200, html, "text/html; charset=utf-8")
                return

            if path == "/health":
                status, body, ctype = _json_bytes({"ok": True, "service": "receipt-dashboard"})
                self._send(status, body, ctype)
                return

            if path == "/api/meta":
                cat = None
                try:
                    cat = str(self.default_catalog_path or default_catalog(None))
                except ShelfError:
                    cat = None
                status, body, ctype = _json_bytes(
                    {
                        "catalogs_root": str(self.catalogs_root),
                        "default_catalog": cat,
                    }
                )
                self._send(status, body, ctype)
                return

            if path == "/api/catalogs":
                root = Path(params["root"]).expanduser() if params.get("root") else self.catalogs_root
                rows = list_catalogs(root)
                status, body, ctype = _json_bytes(
                    {"root": str(root.expanduser().resolve()), "catalogs": rows}
                )
                self._send(status, body, ctype)
                return

            if path == "/api/status":
                catalog = self._resolve_catalog(params)
                status, body, ctype = _json_bytes(catalog_summary(catalog))
                self._send(status, body, ctype)
                return

            if path == "/api/list":
                catalog = self._resolve_catalog(params)
                limit = int(params["limit"]) if params.get("limit") else None
                rows = list_receipts(catalog, query=params.get("query"), limit=limit)
                status, body, ctype = _json_bytes(
                    {
                        "catalog": str(catalog.resolve()),
                        "count": len(rows),
                        "limit": limit,
                        "receipts": rows,
                    }
                )
                self._send(status, body, ctype)
                return

            if path == "/api/find":
                catalog = self._resolve_catalog(params)
                q = params.get("q") or params.get("query") or ""
                hits = search_symbols(catalog, q)
                status, body, ctype = _json_bytes(
                    {"catalog": str(catalog.resolve()), "query": q, "hits": hits}
                )
                self._send(status, body, ctype)
                return

            if path == "/api/show":
                catalog = self._resolve_catalog(params)
                key = params.get("key") or ""
                status, body, ctype = _json_bytes(show_receipt(catalog, key))
                self._send(status, body, ctype)
                return

            if path == "/api/copy":
                catalog = self._resolve_catalog(params)
                key = params.get("key") or ""
                status, body, ctype = _json_bytes(read_copy(catalog, key))
                self._send(status, body, ctype)
                return

            self._send(404, b'{"error":"not found"}', "application/json; charset=utf-8")
        except (ShelfError, StackError, CollectError, FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
            status, body, ctype = _json_bytes({"error": str(exc)}, status=400)
            self._send(status, body, ctype)
        except Exception as exc:  # pragma: no cover
            status, body, ctype = _json_bytes({"error": f"server error: {exc}"}, status=500)
            self._send(status, body, ctype)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            payload = _read_json(self)
            if path == "/api/plan":
                catalog = Path(
                    payload.get("catalog") or self.default_catalog_path or default_catalog(None)
                )
                seeds = payload.get("seeds") or []
                if not seeds:
                    raise StackError("seeds required")
                result = stack_plan(catalog, list(seeds))
                status, body, ctype = _json_bytes(result)
                self._send(status, body, ctype)
                return

            if path == "/api/stack":
                catalog = Path(
                    payload.get("catalog") or self.default_catalog_path or default_catalog(None)
                )
                seeds = payload.get("seeds") or []
                name = payload.get("name")
                out = payload.get("out")
                if not seeds:
                    raise StackError("seeds required")
                if not name:
                    raise StackError("name required")
                if not out:
                    raise StackError("out required")
                result = stack_build(
                    catalog,
                    list(seeds),
                    name=str(name),
                    out=Path(out).expanduser(),
                    check=bool(payload.get("check", True)),
                    force=bool(payload.get("force", False)),
                )
                status, body, ctype = _json_bytes(result)
                self._send(status, body, ctype)
                return

            if path == "/api/collect":
                tree = payload.get("tree")
                out = payload.get("out")
                if not tree or not out:
                    raise CollectError("tree and out required")
                tree_spec = str(tree).strip()
                out_path = Path(str(out)).expanduser().resolve()
                ref = str(payload["ref"]).strip() if payload.get("ref") else None
                data = collect_to(tree_spec, out_path, ref=ref or None)
                # Refresh default catalog pointer if we wrote into catalogs root.
                if out_path.is_dir() and out_path.parent == self.catalogs_root:
                    self.default_catalog_path = out_path
                status, body, ctype = _json_bytes(
                    {
                        "catalog": data.get("catalog") or str(out_path),
                        "files": len(data.get("files") or []),
                        "skipped": len(data.get("skipped") or []),
                        "onboard": data.get("onboard"),
                        "source": data.get("source"),
                        "root": data.get("root"),
                    }
                )
                self._send(status, body, ctype)
                return

            self._send(404, b'{"error":"not found"}', "application/json; charset=utf-8")
        except (ShelfError, StackError, CollectError, FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
            status, body, ctype = _json_bytes({"error": str(exc)}, status=400)
            self._send(status, body, ctype)
        except Exception as exc:  # pragma: no cover
            status, body, ctype = _json_bytes({"error": f"server error: {exc}"}, status=500)
            self._send(status, body, ctype)


def serve(
    *,
    host: str = "127.0.0.1",
    port: int = 8787,
    catalogs_root: Path | None = None,
    catalog: Path | None = None,
    open_browser: bool = True,
) -> int:
    if not (STATIC_DIR / "index.html").is_file():
        raise FileNotFoundError(f"dashboard UI missing: {STATIC_DIR / 'index.html'}")

    DashboardHandler.catalogs_root = (catalogs_root or DEFAULT_CATALOGS).expanduser().resolve()
    if catalog is not None:
        DashboardHandler.default_catalog_path = Path(catalog).expanduser().resolve()
    else:
        try:
            DashboardHandler.default_catalog_path = default_catalog(None)
        except ShelfError:
            DashboardHandler.default_catalog_path = None

    server = ThreadingHTTPServer((host, port), DashboardHandler)
    url = f"http://{host}:{port}/"
    print(
        json.dumps(
            {
                "dashboard": url,
                "catalogs_root": str(DashboardHandler.catalogs_root),
                "catalog": (
                    str(DashboardHandler.default_catalog_path)
                    if DashboardHandler.default_catalog_path
                    else None
                ),
            },
            indent=2,
        )
    )
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nreceipt dashboard stopped", file=sys.stderr)
    finally:
        server.server_close()
    return 0
