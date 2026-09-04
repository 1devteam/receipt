from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VAULT = ROOT / "vault"
MANIFESTS = VAULT / "manifests"
# Compiled projects live outside insertc/insert — sibling of this repo.
COMPILED_ROOT = ROOT.parent / "compiled"


def ensure_vault() -> None:
    VAULT.mkdir(parents=True, exist_ok=True)
    MANIFESTS.mkdir(parents=True, exist_ok=True)
    init = VAULT / "__init__.py"
    if not init.exists():
        init.write_text("# insert vault\n", encoding="utf-8")
