"""Verify explicitly built Windows packages. Never compile or publish on startup.

A manifest binds source/version/binary hashes; it is not a digital signature.
The package directory must be populated through a trusted release process.
"""
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Optional


class AgentPackageError(ValueError):
    pass


class AgentBuilder:
    def __init__(self, base_dir: Optional[str] = None, package_dir: Optional[str] = None):
        self.base_dir = Path(base_dir or Path(__file__).resolve().parents[1])
        self.agent_cs_path = self.base_dir / "agent" / "UltronAgent.cs"
        self.package_dir = Path(package_dir or os.environ.get(
            "ULTRON_AGENT_PACKAGE_DIR", self.base_dir / "agent" / "dist"))

    @staticmethod
    def _sha256(path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def _source_sha256(self):
        # Git checkout uses CRLF on Windows and LF on Linux.
        text = self.agent_cs_path.read_text(encoding="utf-8")
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def get_source_version(self):
        source = self.agent_cs_path.read_text(encoding="utf-8")
        match = re.search(r'public\s+const\s+string\s+CurrentVersion\s*=\s*"([0-9]+\.[0-9]+\.[0-9]+)"', source)
        if not match:
            raise AgentPackageError("Versao do fonte ausente ou invalida.")
        return match.group(1)

    def get_latest_agent_binary(self):
        try:
            manifest = json.loads((self.package_dir / "manifest.json").read_text(encoding="utf-8-sig"))
            binary = self.package_dir / "UltronAgent.exe"
            if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
                raise ValueError("Manifesto invalido")
            if manifest.get("version") != self.get_source_version():
                raise ValueError("Versao divergente")
            for key in ("source_sha256", "binary_sha256"):
                if not re.fullmatch(r"[a-fA-F0-9]{64}", str(manifest.get(key, ""))):
                    raise ValueError("Hash invalido")
            if manifest["source_sha256"].lower() != self._source_sha256():
                raise ValueError("Fonte divergente")
            if manifest["binary_sha256"].lower() != self._sha256(binary):
                raise ValueError("Binario divergente")
            if not re.fullmatch(r"[a-fA-F0-9]{40}", str(manifest.get("commit", ""))):
                raise ValueError("Commit ausente")
            if binary.stat().st_size == 0:
                raise ValueError("Binario vazio")
            return dict(version=manifest["version"], file_path=str(binary),
                        filename="UltronAgent_v" + manifest["version"] + ".exe",
                        size_bytes=binary.stat().st_size,
                        sha256=manifest["binary_sha256"].lower(), commit=manifest["commit"])
        except (OSError, ValueError, TypeError, KeyError):
            raise AgentPackageError("Pacote ausente ou divergente; gere e homologue um pacote revisado.") from None

    def get_distributable_agent_binary(self):
        if os.environ.get("ULTRON_AGENT_DOWNLOAD_ENABLED") != "true":
            raise AgentPackageError("Distribuicao suspensa ate homologacao do pacote Windows.")
        return self.get_latest_agent_binary()

    def needs_compilation(self):
        # Compatibility with callers; no timestamps or fallback to legacy executables.
        try:
            self.get_latest_agent_binary()
            return False
        except AgentPackageError:
            return True

    def compile(self, force=False):
        # Compatibility shim: explicit build_agent.ps1 is the only build entry point.
        try:
            info = self.get_latest_agent_binary()
            return dict(success=True, recompiled=False, **info)
        except AgentPackageError:
            return dict(success=False, recompiled=False,
                        error="Compilacao automatica removida; use agent/build_agent.ps1.")


agent_builder = AgentBuilder()
