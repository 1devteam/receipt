from __future__ import annotations

from collector.github import parse_github


def test_github_slug_python_subpath_is_blob() -> None:
    parsed = parse_github(
        "github:python/typing_extensions@3ae9b7553a5c560dc09b484078d98ece2985eecd:src/typing_extensions.py"
    )
    assert parsed.kind == "blob"
    assert parsed.subpath == "src/typing_extensions.py"
    assert parsed.page_url().endswith(
        "/blob/3ae9b7553a5c560dc09b484078d98ece2985eecd/src/typing_extensions.py"
    )
    assert parsed.blob_url("typing_extensions.py") == parsed.page_url()
