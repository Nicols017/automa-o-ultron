"""Independent, read-only Macrium Reflect 8 verification and signed evidence.

Run ONLY on a designated Windows verification workstation with Macrium
Reflect 8 MRVerify.exe installed and read-only access to the image share.
This utility never formats a target, alters an image, invokes --fix, or
contacts the Jarvis server. It does not authorize MDT formatting.
"""

import argparse
import hashlib
import hmac
import ipaddress
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path, PureWindowsPath
from typing import Any, Callable, Dict, Optional

MRVERIFY_EXE = r"C:\Program Files\Macrium\Reflect\MRVerify.exe"
FAILURE_MARKERS = (
    "verify failure",
    "backup set is not complete",
    "password error",
    "repaired",
    "verify warning",
)
MAX_VERIFICATION_SECONDS = 4 * 60 * 60
HASH_CHUNK_SIZE = 4 * 1024 * 1024


class VerificationError(Exception):
    """The verifier was unable to establish trustworthy backup evidence."""


def canonical_bytes(payload: Dict[str, Any]) -> bytes:
    """Exact serialization expected by core.backup_gate.MacriumBackupGate."""
    return json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")


def hash_file(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(HASH_CHUNK_SIZE)
            if not chunk:
                break
            sha.update(chunk)
    return sha.hexdigest()


def secure_windows_share_path(image_path: str, share: str) -> None:
    """Deny traversals, non-UNC paths, alternate streams, and other shares."""
    if not isinstance(image_path, str) or not isinstance(share, str):
        raise VerificationError("Caminho ou compartilhamento inválido.")
    path = image_path.replace("/", "\\")
    root = share.replace("/", "\\").rstrip("\\")
    if (not path.startswith("\\\\") or not root.startswith("\\\\") or
            not path.lower().startswith(root.lower() + "\\") or
            not path.lower().endswith(".mrimg")):
        raise VerificationError("Imagem fora do compartilhamento Macrium autorizado.")
    parts = PureWindowsPath(path).parts
    if any(part in (".", "..") or ":" in part for part in parts[1:]):
        raise VerificationError("Caminho com traversal ou alternate data stream.")
    if (path.endswith("\\") or any(part == "" for part in path[2:].split("\\"))):
        raise VerificationError("Caminho de imagem não canônico.")
    # We do not accept folder paths, wildcard expressions, or repair options.
    if "*" in path or "?" in path:
        raise VerificationError("O caminho da imagem deve ser exato.")


def _trusted_manifest_entry(manifest: Path, serial: str, allowed_share: str) -> Dict[str, str]:
    """Inventory is maintained by an authorized operator, never by the client."""
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        devices = data["devices"]
        entry = devices[serial]
        ip = str(ipaddress.ip_address(entry["source_ip"]))
        image = entry["image_path"]
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise VerificationError("Inventário independente do equipamento inválido.")
    secure_windows_share_path(image, allowed_share)
    if not isinstance(entry, dict):
        raise VerificationError("Inventário inconsistente.")
    return {"serial": serial, "source_ip": ip, "storage_path": image}


def verify_and_attest(
    *, serial: str, inventory_file: Path, allowed_share: str,
    signing_key_file: Path, output_directory: Path, verifier_id: str,
    mrverify_executable: Path = Path(MRVERIFY_EXE),
    runner: Callable[..., Any] = subprocess.run,
    now: Callable[[], float] = time.time,
    image_resolver: Callable[[str], Path] = Path,
) -> Path:
    """Verify using real MRVerify.exe and sign only after success.

    The optional runner and clock injections are exclusively for local unit
    tests with a fake executable. The CLI never exposes these injections.
    """
    if not serial or not re.fullmatch(r"[A-Za-z0-9_-]{3,128}", serial):
        raise VerificationError("Serial não reconhecido.")
    if not verifier_id or not re.fullmatch(r"[A-Za-z0-9_.-]{3,128}", verifier_id):
        raise VerificationError("Identificador do verificador inválido.")
    entry = _trusted_manifest_entry(inventory_file, serial, allowed_share)
    image = image_resolver(entry["storage_path"])

    # The CLI additionally mandates the Windows platform, where UNC paths
    # behave as real network files. Tests use a fake runner and fake filesystem.
    if not mrverify_executable.is_file():
        raise VerificationError("MRVerify.exe não encontrado no verificador.")
    if not image.is_file():
        raise VerificationError("Imagem não localizada no storage autorizado.")
    if not signing_key_file.is_file():
        raise VerificationError("Chave de assinatura do verificador ausente.")
    signing_key = signing_key_file.read_bytes().strip()
    if len(signing_key) < 32:
        raise VerificationError("Chave de assinatura insuficiente.")

    original_stat = image.stat()
    if original_stat.st_size <= 0:
        raise VerificationError("Imagem Macrium vazia.")
    output_directory.mkdir(parents=True, exist_ok=True)
    execution_id = uuid.uuid4().hex
    log_file = output_directory / ("mrverify-" + execution_id + ".log")

    # Do NOT pass --fix; --set checks every required file in the backup set.
    # Keep the log separate from the source image share.
    command = [
        str(mrverify_executable),
        str(image),
        "--set",
        "--logfile",
        str(log_file),
    ]
    try:
        completed = runner(
            command, capture_output=True, text=True, errors="replace",
            timeout=MAX_VERIFICATION_SECONDS, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise VerificationError("MRVerify falhou ou excedeu o tempo máximo.") from error

    if completed.returncode != 0:
        raise VerificationError("MRVerify retornou falha na validação.")
    if not log_file.is_file():
        raise VerificationError("MRVerify não gerou log auditável.")
    # Macrium docs state logs include "Verify Success" or "Verify Failure".
    # An exit code of 0 alone is insufficient for this gate.
    log_content = log_file.read_text(encoding="utf-8-sig", errors="replace")
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    combined = (log_content + "\n" + stdout + "\n" + stderr).lower()
    if any(marker in combined for marker in FAILURE_MARKERS):
        raise VerificationError("MRVerify relatou falha, warning ou reparo.")
    if "verify success" not in combined:
        raise VerificationError("MRVerify não confirmou sucesso no log.")
    # The verification log should explicitly refer to the requested image.
    if image.name.lower() not in combined:
        raise VerificationError("Log não referencia a imagem verificada.")

    checksum = hash_file(image)
    current_stat = image.stat()
    if (current_stat.st_size != original_stat.st_size or
            current_stat.st_mtime_ns != original_stat.st_mtime_ns):
        raise VerificationError("A imagem foi alterada durante a verificação.")

    verified_at = int(now())
    evidence = {
        "kind": "macrium_reflect_8_image",
        "verify_method": "macrium_reflect_8_verify",
        "verification_status": "SUCCESS",
        "verifier_id": verifier_id,
        "serial": entry["serial"],
        "source_ip": entry["source_ip"],
        "storage_path": entry["storage_path"],
        "sha256": checksum,
        "size_bytes": current_stat.st_size,
        "verified_at": verified_at,
        "issued_at": verified_at,
        "expires_at": verified_at + 3600,
        "mrverify_exit_code": completed.returncode,
        "mrverify_log_sha256": hash_file(log_file),
        "verification_id": execution_id,
    }
    signature = hmac.new(signing_key, canonical_bytes(evidence), hashlib.sha256).hexdigest()
    attestation = {"evidence": evidence, "signature": signature}

    output = output_directory / ("macrium-evidence-" + execution_id + ".json")
    # Exclusive create; never overwrite an existing attestation.
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(attestation, stream, sort_keys=True, ensure_ascii=False, indent=2)
        stream.write("\n")
    return output


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verificação read-only MRVerify.exe (Windows). NÃO formata equipamentos."
    )
    parser.add_argument("--serial", required=True)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--share", required=True)
    parser.add_argument("--signing-key", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--verifier-id", required=True)
    args = parser.parse_args(argv)

    if os.name != "nt":
        print("ERRO: execução real permitida apenas em Windows com Macrium Reflect 8.", file=sys.stderr)
        return 2
    try:
        evidence_file = verify_and_attest(
            serial=args.serial, inventory_file=args.inventory,
            allowed_share=args.share, signing_key_file=args.signing_key,
            output_directory=args.output, verifier_id=args.verifier_id,
        )
    except VerificationError as exc:
        print("ERRO: " + str(exc), file=sys.stderr)
        return 1
    print("Verificação Macrium aprovada; comprovante gerado: " + str(evidence_file))
    print("ATENÇÃO: resultado NÃO autoriza formatação ou substitui teste de restauração.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
