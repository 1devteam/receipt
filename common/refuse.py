from pathlib import PurePosixPath

# Vendor, cache, and build artifacts only. Source from the tree (including launchers) is collected.
VENDOR_PARTS = {
    "venv",
    ".venv",
    "env",
    ".env",
    "node_modules",
    "__pycache__",
    "site-packages",
    "dist-packages",
    ".git",
    ".hg",
    ".svn",
    ".tox",
    ".nox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".pyre",
    ".pytype",
    ".hypothesis",
    ".uv",
    ".eggs",
    "build",
    "dist",
    "htmlcov",
    "coverage",
}

VENDOR_SUFFIXES = (
    ".egg-info",
    ".dist-info",
    ".egg",
)


def refused(path: str) -> str | None:
    posix = PurePosixPath(path.replace("\\", "/"))
    parts = [p.lower() for p in posix.parts]
    part_set = set(parts)
    if part_set & VENDOR_PARTS:
        return "vendor-or-cache"
    for part in parts:
        if part.endswith(VENDOR_SUFFIXES):
            return "vendor-or-cache"
    return None
