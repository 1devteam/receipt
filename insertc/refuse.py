"""Names that try to own the machine stay out of the house."""

from pathlib import PurePosixPath

REFUSE_FILES = {
    "fleetlauncher.py",
    "forkfleetcontroller.py",
    "payload_modules.py",
    "live_command_handler.py",
    "resurrect.py",
}

REFUSE_PATH_PARTS = {
    "warpackage",
    "venv",
    ".venv",
    "node_modules",
    "__pycache__",
    "site-packages",
    ".git",
}

REFUSE_NAME_BITS = (
    "beacon",
    "exploit",
)


def refused(path: str) -> str | None:
    posix = PurePosixPath(path.replace("\\", "/"))
    parts = {p.lower() for p in posix.parts}
    if parts & REFUSE_PATH_PARTS:
        return "vendor-or-refuse-path"
    name = posix.name.lower()
    if name in REFUSE_FILES:
        return "refused-filename"
    for bit in REFUSE_NAME_BITS:
        if bit in name:
            return f"refused-name:{bit}"
    return None
