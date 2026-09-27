import tempfile
import unittest
from pathlib import Path

from collector.collect import collect_to
from common.source_identity import (
    GRAFT_REF_SCHEMA,
    SOURCE_IDENTITY_SCHEMA,
    SourceIdentityError,
    bridge_payload,
    build_source_identity,
    graft_ref,
)


class SourceIdentityTests(unittest.TestCase):
    def test_local_collect_attaches_non_authoritative_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            tree = tmp_path / "tree"
            tree.mkdir()
            (tree / "unit.py").write_text("def run():\n    return 1\n", encoding="utf-8")
            catalog = tmp_path / "catalog"

            data = collect_to(tree, catalog)
            unit = data["files"][0]
            identity = unit["source_identity"]
            self.assertEqual(identity["schema"], SOURCE_IDENTITY_SCHEMA)
            self.assertEqual(identity["kind"], "local")
            self.assertEqual(identity["path"], "unit.py")
            self.assertEqual(identity["source_sha256"], unit["source_sha256"])
            self.assertIsNone(identity["repository"])
            self.assertIsNone(identity["commit"])
            self.assertEqual(unit["graft_refs"], [])
            self.assertFalse(unit["evidence_bridge"]["grants_execution_authority"])

    def test_github_identity_requires_commit_pinning(self):
        source = {
            "kind": "github",
            "owner": "1devteam",
            "repo": "receipt",
            "sha": "abc123",
        }
        identity = build_source_identity(
            rel="collector/collect.py",
            source_sha256="deadbeef",
            source=source,
            origin="https://github.com/1devteam/receipt/blob/abc123/collector/collect.py",
        )
        self.assertEqual(identity["kind"], "github")
        self.assertEqual(identity["repository"], "1devteam/receipt")
        self.assertEqual(identity["commit"], "abc123")
        self.assertEqual(identity["path"], "collector/collect.py")

        with self.assertRaises(SourceIdentityError):
            build_source_identity(
                rel="collector/collect.py",
                source_sha256="deadbeef",
                source={"kind": "github", "owner": "1devteam", "repo": "receipt"},
            )

    def test_graft_reference_is_evidence_only(self):
        identity = build_source_identity(rel="unit.py", source_sha256="abc")
        ref = graft_ref(
            artifact="graft-pack/graph.json",
            subject="file:unit.py",
            evidence={"line": 12},
        )
        self.assertEqual(ref["schema"], GRAFT_REF_SCHEMA)
        self.assertFalse(ref["grants_execution_authority"])
        bridge = bridge_payload(identity, [ref])
        self.assertEqual(bridge["source_identity"], identity)
        self.assertEqual(bridge["graft_refs"], [ref])
        self.assertFalse(bridge["grants_execution_authority"])

    def test_bridge_rejects_untyped_or_authority_granting_refs(self):
        identity = build_source_identity(rel="unit.py", source_sha256="abc")
        with self.assertRaises(SourceIdentityError):
            bridge_payload(identity, [{"artifact": "graph.json", "subject": "file:unit.py"}])
        with self.assertRaises(SourceIdentityError):
            bridge_payload(
                identity,
                [
                    {
                        "schema": GRAFT_REF_SCHEMA,
                        "artifact": "graph.json",
                        "subject": "file:unit.py",
                        "evidence": {},
                        "grants_execution_authority": True,
                    }
                ],
            )


if __name__ == "__main__":
    unittest.main()
