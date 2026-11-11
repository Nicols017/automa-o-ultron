"""Conservative Macrium Reflect 8 pre-format evidence verification.

This module validates the *attestation* from an independently trusted verifier;
it DOES NOT open .mrimg files or run Macrium Verify itself. A signed statement
is only acceptable after an independent verifier has actually checked the
backup and recorded its result. Formatting remains disabled until integration
and end-to-end validation are complete.
"""

import hashlib
import hmac
import json
import os
import re
import stat
import time
from pathlib import Path
from typing import Mapping, Optional


class BackupNotVerified(Exception):
    pass


class MacriumBackupGate:
    MAX_AGE_SECONDS = 24 * 60 * 60

    def __init__(self, key_file: Optional[str] = None, backup_share: Optional[str] = None):
        self.key_file = key_file or os.environ.get("ULTRON_MACRIUM_VERIFIER_KEY_FILE", "")
        self.backup_share = backup_share or os.environ.get("ULTRON_MACRIUM_BACKUP_SHARE", "")

    def _key(self) -> bytes:
        if not self.key_file:
            raise BackupNotVerified("Verificador Macrium não configurado.")
        file = Path(self.key_file)
        try:
            if os.name == "posix" and stat.S_IMODE(file.stat().st_mode) & 0o077:
                raise BackupNotVerified("Chave de verificação com permissões inseguras.")
            key = file.read_bytes().strip()
            if len(key) < 32:
                raise BackupNotVerified("Chave do verificador inválida.")
            return key
        except OSError:
            raise BackupNotVerified("Chave do verificador indisponível.")

    @staticmethod
    def _canonical(payload: Mapping) -> bytes:
        return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    @staticmethod
    def _unc_normalized(path: str) -> str:
        return path.replace("/", "\\").rstrip("\\").lower()

    def validate(self, attestation: Mapping, expected_serial: str, expected_ip: str,
                 now: Optional[float] = None) -> Mapping:
        if not isinstance(attestation, dict):
            raise BackupNotVerified("Comprovante de backup ausente.")
        document = attestation.get("evidence")
        signature = attestation.get("signature")
        if not isinstance(document, dict) or not isinstance(signature, str):
            raise BackupNotVerified("Comprovante não assinado.")
        mac = hmac.new(self._key(), self._canonical(document), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(mac, signature):
            raise BackupNotVerified("Assinatura do comprovante inválida.")

        # All claims below are checked only AFTER signature verification.
        if (document.get("kind") != "macrium_reflect_8_image" or
                document.get("verify_method") != "macrium_reflect_8_verify" or
                document.get("verification_status") != "SUCCESS" or
                not document.get("verifier_id")):
            raise BackupNotVerified("Verificação Macrium não comprovada.")
        serial = str(document.get("serial", "")).strip().lower()
        ip = str(document.get("source_ip", "")).strip()
        if not serial or serial != str(expected_serial).strip().lower() or ip != expected_ip:
            raise BackupNotVerified("Backup não corresponde ao equipamento solicitado.")

        timestamp = now if now is not None else time.time()
        try:
            verified_at = float(document["verified_at"])
            issued_at = float(document["issued_at"])
            expires_at = float(document["expires_at"])
        except (KeyError, TypeError, ValueError):
            raise BackupNotVerified("Horários de verificação inválidos.")
        if not (timestamp - self.MAX_AGE_SECONDS <= verified_at <= issued_at <= timestamp + 60 and
                timestamp <= expires_at <= issued_at + self.MAX_AGE_SECONDS):
            raise BackupNotVerified("Comprovante expirado, futuro ou fora do prazo.")

        path = document.get("storage_path")
        share = self.backup_share
        if not isinstance(path, str) or not isinstance(share, str) or not share:
            raise BackupNotVerified("Destino Macrium não autorizado.")
        normalized = self._unc_normalized(path)
        root = self._unc_normalized(share)
        if (not root.startswith("\\\\") or not normalized.startswith(root + "\\") or
                ".." in normalized.split("\\") or not normalized.endswith(".mrimg")):
            raise BackupNotVerified("Imagem Macrium fora do storage permitido.")
        checksum = document.get("sha256")
        if not isinstance(checksum, str) or not re.fullmatch(r"[a-f0-9]{64}", checksum):
            raise BackupNotVerified("Checksum SHA-256 da imagem ausente.")
        size = document.get("size_bytes")
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            raise BackupNotVerified("Tamanho da imagem inválido.")
        # The signature covers a claim of Macrium Verify success. It does not
        # itself prove that the image is still present or restore-capable.
        return document
