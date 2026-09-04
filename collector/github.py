"""Fetch a GitHub tree or file into a local snapshot for collect."""

from __future__ import annotations

import os
import re
import shutil
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

USER_AGENT = "receipt-cli"
API_VERSION = "2022-11-28"
TIMEOUT_S = 120

_HOSTS = {"github.com", "www.github.com"}
_SLUG = re.compile(
    r"^(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)(?:@(?P<ref>[^:]+))?(?::(?P<subpath>.+))?$"
)


class GitHubError(ValueError):
    """GitHub spec parse or fetch failure."""


@dataclass(frozen=True)
class GitHubSpec:
    owner: str
    repo: str
    ref: str | None = None
    subpath: str | None = None
    kind: str = "tree"  # tree | blob

    def repo_url(self) -> str:
        return f"https://github.com/{self.owner}/{self.repo}"

    def page_url(self) -> str:
        base = self.repo_url()
        if self.ref and self.subpath:
            verb = "blob" if self.kind == "blob" else "tree"
            return f"{base}/{verb}/{self.ref}/{self.subpath}"
        if self.ref:
            return f"{base}/tree/{self.ref}"
        if self.subpath:
            return f"{base}/tree/HEAD/{self.subpath}"
        return base

    def blob_url(self, rel: str) -> str:
        ref = self.ref or "HEAD"
        if self.kind == "blob" and self.subpath:
            full = self.subpath
        elif self.subpath:
            full = str(PurePosixPath(self.subpath) / rel).lstrip("/")
        else:
            full = rel
        return f"https://github.com/{self.owner}/{self.repo}/blob/{ref}/{full}"

    def as_meta(self) -> dict:
        return {
            "kind": "github",
            "owner": self.owner,
            "repo": self.repo,
            "ref": self.ref or "HEAD",
            "subpath": self.subpath,
            "url": self.page_url(),
        }


def _token() -> str | None:
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or None


def is_github_spec(spec: str | os.PathLike[str]) -> bool:
    """True when spec names GitHub rather than a local tree."""
    s = str(spec).strip()
    if not s:
        return False
    local = Path(s).expanduser()
    try:
        if local.exists():
            return False
    except OSError:
        pass
    if s.startswith(("github:", "git@github.com:")):
        return True
    parsed = urlparse(s)
    if parsed.scheme in {"http", "https"} and parsed.netloc.lower() in _HOSTS:
        return True
    if s.startswith((".", "/", "~", "\\")) or "\\" in s:
        return False
    return bool(_SLUG.fullmatch(s.removesuffix(".git")))


def parse_github(spec: str, *, ref: str | None = None) -> GitHubSpec:
    s = spec.strip()
    if not s:
        raise GitHubError("empty github spec")
    if s.startswith("github:"):
        parsed = _parse_slug(s[7:], override_ref=ref)
    elif s.startswith("git@github.com:"):
        parsed = _parse_slug(s[len("git@github.com:") :], override_ref=ref)
    else:
        parsed = urlparse(s)
        if parsed.scheme in {"http", "https"} and parsed.netloc.lower() in _HOSTS:
            parsed = _parse_url_path(parsed.path, override_ref=ref)
        else:
            parsed = _parse_slug(s, override_ref=ref)
    if ref:
        parsed = GitHubSpec(
            owner=parsed.owner,
            repo=parsed.repo,
            ref=ref,
            subpath=parsed.subpath,
            kind=parsed.kind,
        )
    return parsed


def _clean_repo(name: str) -> str:
    name = name.strip()
    if name.endswith(".git"):
        name = name[: -len(".git")]
    return name.strip("/")


def _parse_slug(raw: str, *, override_ref: str | None) -> GitHubSpec:
    s = raw.strip().strip("/")
    subpath = None
    if ":" in s:
        s, subpath = s.split(":", 1)
        subpath = subpath.strip().lstrip("/") or None
    found_ref = None
    if "@" in s:
        s, found_ref = s.split("@", 1)
        found_ref = found_ref.strip() or None
    parts = [p for p in s.split("/") if p]
    if len(parts) < 2:
        raise GitHubError(f"not a github spec: {raw}")
    owner, repo, *rest = parts
    repo = _clean_repo(repo)
    extra = "/".join(rest) or None
    return GitHubSpec(
        owner=owner,
        repo=repo,
        ref=override_ref or found_ref,
        subpath=subpath or extra,
    )


def _parse_url_path(path: str, *, override_ref: str | None) -> GitHubSpec:
    parts = [p for p in path.split("/") if p]
    if len(parts) < 2:
        raise GitHubError(f"github url missing owner/repo: {path}")
    owner = parts[0]
    repo = _clean_repo(parts[1])
    extra = parts[2:]
    kind = "tree"
    found_ref = None
    subpath = None
    if extra:
        head = extra[0]
        if head in {"tree", "blob", "raw", "commit"}:
            kind = "blob" if head in {"blob", "raw"} else "tree"
            if len(extra) >= 2:
                found_ref = extra[1]
                if len(extra) > 2:
                    subpath = "/".join(extra[2:])
        elif head not in {"archive", "releases", "issues", "pull", "actions", "wiki"}:
            subpath = "/".join(extra)
    return GitHubSpec(
        owner=owner,
        repo=repo,
        ref=override_ref or found_ref,
        subpath=subpath,
        kind=kind,
    )


def _headers(token: str | None) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT,
        "X-GitHub-Api-Version": API_VERSION,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _download(url: str, dest: Path, *, token: str | None) -> None:
    req = Request(url, headers=_headers(token))
    try:
        with urlopen(req, timeout=TIMEOUT_S) as resp:
            with dest.open("wb") as fh:
                _copy_stream(resp, fh)
    except HTTPError as exc:
        slug = url
        if exc.code in {401, 403}:
            raise GitHubError(
                "github refused (auth or rate limit). "
                "set GITHUB_TOKEN or GH_TOKEN for private repos / higher limits"
            ) from exc
        if exc.code == 404:
            raise GitHubError(f"github repo or ref not found: {url}") from exc
        raise GitHubError(f"github http {exc.code}: {slug}") from exc
    except URLError as exc:
        raise GitHubError(f"github network error: {exc.reason}") from exc


def _copy_stream(src: BinaryIO, dest: BinaryIO) -> None:
    while True:
        chunk = src.read(1024 * 1024)
        if not chunk:
            break
        dest.write(chunk)


def _safe_extract(archive: Path, dest: Path) -> None:
    dest = dest.resolve()
    dest_s = str(dest)
    with tarfile.open(archive, "r:*") as tar:
        for member in tar.getmembers():
            name = member.name.replace("\\", "/")
            if name.startswith("/") or any(p == ".." for p in PurePosixPath(name).parts):
                raise GitHubError(f"unsafe tar member: {member.name}")
            target = (dest / name).resolve()
            if not (str(target) == dest_s or str(target).startswith(dest_s + os.sep)):
                raise GitHubError(f"unsafe tar member: {member.name}")
        if hasattr(tarfile, "data_filter"):
            tar.extractall(dest, filter="data")
        else:
            tar.extractall(dest)


def _unpacked_root(extract_dir: Path) -> Path:
    kids = [p for p in extract_dir.iterdir() if p.name not in {".", ".."}]
    dirs = [p for p in kids if p.is_dir()]
    if len(dirs) == 1 and len(kids) == 1:
        return dirs[0]
    if not kids:
        raise GitHubError("github tarball was empty")
    return extract_dir


def fetch_github(spec: GitHubSpec, dest: Path, *, token: str | None = None) -> Path:
    """Download a repo snapshot and return the path collect should scan."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    token = token if token is not None else _token()
    ref_part = f"/{spec.ref}" if spec.ref else ""
    url = f"https://api.github.com/repos/{spec.owner}/{spec.repo}/tarball{ref_part}"
    archive = dest / "repo.tar.gz"
    _download(url, archive, token=token)
    extract_dir = dest / "unpacked"
    extract_dir.mkdir(parents=True, exist_ok=True)
    try:
        _safe_extract(archive, extract_dir)
    except tarfile.TarError as exc:
        raise GitHubError(f"github tarball corrupt: {exc}") from exc
    root = _unpacked_root(extract_dir)
    if not spec.subpath:
        return root
    target = root.joinpath(*PurePosixPath(spec.subpath).parts)
    if not target.exists():
        raise GitHubError(
            f"github path not in {spec.owner}/{spec.repo}"
            f"@{spec.ref or 'HEAD'}: {spec.subpath}"
        )
    return target


def snapshot_github(spec: str | GitHubSpec, *, ref: str | None = None) -> tuple[Path, GitHubSpec, Path]:
    """Parse + fetch into a temp dir. Returns (scan_root, spec, cleanup_dir)."""
    parsed = spec if isinstance(spec, GitHubSpec) else parse_github(str(spec), ref=ref)
    cleanup = Path(tempfile.mkdtemp(prefix="receipt-gh-"))
    try:
        root = fetch_github(parsed, cleanup)
    except Exception:
        shutil.rmtree(cleanup, ignore_errors=True)
        raise
    return root, parsed, cleanup
