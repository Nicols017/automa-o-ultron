"""Offline integrity checks against disposable package fixtures, never real executables."""
import ast
import types
import hashlib
import json
from pathlib import Path
import tempfile
from unittest.mock import Mock, patch
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

    def test_distribution_disabled_even_with_valid_package(self):
        with patch.dict("os.environ", {}, clear=True), self.assertRaises(AgentPackageError):
            self.builder.get_distributable_agent_binary()

    def test_distribution_enabled_still_requires_integrity(self):
        self.binary.write_bytes(b"tampered")
        with patch.dict("os.environ", {"ULTRON_AGENT_DOWNLOAD_ENABLED": "true"}):
            with self.assertRaises(AgentPackageError):
                self.builder.get_distributable_agent_binary()

    def test_chatops_missing_package_never_sends_file(self):
        source = Path(__file__).resolve().parents[1] / "chatops/chatops.py"
        method = next(node for node in ast.walk(ast.parse(source.read_text(encoding="utf-8")))
                      if isinstance(node, ast.FunctionDef) and node.name == "_cmd_download_agent")
        namespace = {"logger": Mock()}
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), namespace)
        caller = types.SimpleNamespace(bot=Mock(), _get_server_url=lambda: "https://example.invalid")
        with patch("core.agent_builder.agent_builder.get_distributable_agent_binary",
                   side_effect=AgentPackageError("private-path-secret")):
            result = namespace["_cmd_download_agent"](caller, "fixture-user")
        caller.bot.send_direct_file.assert_not_called()
        self.assertIn("suspensa", result)
        self.assertNotIn("private-path-secret", result)

    def test_chatops_does_not_claim_unsent_attachment(self):
        source = Path(__file__).resolve().parents[1] / "chatops/chatops.py"
        method = next(node for node in ast.walk(ast.parse(source.read_text(encoding="utf-8")))
                      if isinstance(node, ast.FunctionDef) and node.name == "_cmd_download_agent")
        namespace = {"logger": Mock()}
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), namespace)
        bot = Mock()
        bot.send_direct_file.return_value = False
        caller = types.SimpleNamespace(bot=bot, _get_server_url=lambda: "https://example.invalid")
        with patch("core.agent_builder.agent_builder.get_distributable_agent_binary",
                   return_value={"version": "2.3.0", "file_path": "fixture", "filename": "fixture.exe"}):
            result = namespace["_cmd_download_agent"](caller, "fixture-user")
        self.assertIn("Anexo nao enviado", result)
        self.assertNotIn("OTA", result)

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
