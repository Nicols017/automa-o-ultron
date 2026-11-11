"""Offline integrity checks against disposable package fixtures, never real executables."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from core.agent_builder import AgentBuilder, AgentPackageError


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "agent").mkdir()
        (self.root / "agent/UltronAgent.cs").write_text(
            'public const string CurrentVersion = "2.3.0";', encoding="utf-8")
        self.package = self.root / "package"
        self.package.mkdir()
        self.binary = self.package / "UltronAgent.exe"
        self.binary.write_bytes(b"not-an-executable-fixture")
        self.builder = AgentBuilder(str(self.root), str(self.package))
        self.manifest = dict(schema_version=1, version="2.3.0", commit="a" * 40,
                             source_sha256=hashlib.sha256((self.root / "agent/UltronAgent.cs").read_bytes()).hexdigest(),
                             binary_sha256=hashlib.sha256(self.binary.read_bytes()).hexdigest())
        self.write_manifest()

    def write_manifest(self):
        (self.package / "manifest.json").write_text(json.dumps(self.manifest), encoding="utf-8")

    def test_valid_manifest(self):
        result = self.builder.get_latest_agent_binary()
        self.assertEqual(result["version"], "2.3.0")
        self.assertEqual(result["file_path"], str(self.binary))
        self.assertFalse(self.builder.needs_compilation())

    def test_changed_binary_rejected_even_with_same_size(self):
        self.binary.write_bytes(b"x" * len(self.binary.read_bytes()))
        with self.assertRaises(AgentPackageError):
            self.builder.get_latest_agent_binary()

    def test_source_hash_is_portable_between_windows_and_linux(self):
        source = self.root / "agent/UltronAgent.cs"
        source.write_bytes(b'public const string CurrentVersion = "2.3.0";\r\n')
        self.manifest["source_sha256"] = hashlib.sha256(source.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
        self.write_manifest()
        self.builder.get_latest_agent_binary()
        source.write_bytes(source.read_bytes().replace(b"\r\n", b"\n"))
        self.builder.get_latest_agent_binary()

    def test_changed_source_rejected(self):
        with (self.root / "agent/UltronAgent.cs").open("a") as file:
            file.write(" // modified")
        with self.assertRaises(AgentPackageError):
            self.builder.get_latest_agent_binary()

    def test_bad_version_hash_or_commit_rejected(self):
        for key, value in (("version", "99.0.0"), ("commit", ""), ("source_sha256", "z" * 64),
                           ("binary_sha256", "a" * 64), ("schema_version", 9)):
            original = self.manifest[key]
            self.manifest[key] = value
            self.write_manifest()
            with self.subTest(key=key), self.assertRaises(AgentPackageError):
                self.builder.get_latest_agent_binary()
            self.manifest[key] = original

    def test_legacy_binary_does_not_bypass_missing_manifest(self):
        (self.package / "manifest.json").unlink()
        (self.root / "agent/UltronAgent.exe").write_bytes(b"old")
        self.assertFalse(self.builder.compile()["success"])
        with self.assertRaises(AgentPackageError):
            self.builder.get_latest_agent_binary()
        self.assertFalse((self.root / "static").exists())

    def test_manifest_filename_cannot_select_arbitrary_file(self):
        self.manifest["filename"] = "../../secret"
        self.write_manifest()
        self.assertEqual(self.builder.get_latest_agent_binary()["file_path"], str(self.binary))

    def test_malformed_manifest_fails_closed(self):
        for contents in ("not-json", "null", "[]"):
            (self.package / "manifest.json").write_text(contents)
            with self.subTest(contents=contents), self.assertRaises(AgentPackageError):
                self.builder.get_latest_agent_binary()


if __name__ == "__main__":
    unittest.main()
