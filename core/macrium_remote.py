"""Ultron Macrium verification bridge (Windows WinRM only; no formatting).

The Jarvis server coordinates a previously approved Windows workstation which
has MRVerify.exe installed. The backup image is checked in place; logs are
written to the Windows workstation, not the backup share or Jarvis.

The integration is intentionally disabled unless explicitly configured.
It NEVER calls Macrium restore, MDT, repartitioning or cleanup.
"""

import ipaddress
import json
import ntpath
import os
import re
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, Optional, Sequence

SENTINEL = "ULTRON_MACRIUM_JSON:"
BLOCKED_PS_CHARS = re.compile(r"""[\x00-\x1f"$\x60';&|*?<>]""")
ACTIVE = {"QUEUED", "RUNNING"}
MAX_RECORDS = 100


class MacriumBridgeError(Exception):
    pass


def _normalized_windows_path(path: str) -> str:
    if not isinstance(path, str) or not (3 <= len(path) <= 1024):
        raise MacriumBridgeError("Caminho Windows inválido.")
    if BLOCKED_PS_CHARS.search(path) or "/" in path:
        raise MacriumBridgeError("O caminho contém caracteres não permitidos.")
    if any(part in {".", ".."} for part in path.replace("/", "\\").split("\\")):
        raise MacriumBridgeError("Caminhos relativos não são aceitos.")
    normalized = ntpath.normpath(path)
    if path.rstrip("\\") != normalized:
        raise MacriumBridgeError("O caminho deve ser absoluto e canônico.")
    if not (path.startswith("\\\\") or re.match(r"^[A-Za-z]:\\", path)):
        raise MacriumBridgeError("Utilize um caminho absoluto do Windows ou UNC.")
    if ":" in path[2:]:
        raise MacriumBridgeError("Fluxos alternativos de arquivo não são aceitos.")
    return normalized


def validate_image_path(image_path: str, allowed_roots: Sequence[str]) -> str:
    image = _normalized_windows_path(image_path)
    if not image.lower().endswith(".mrimg"):
        raise MacriumBridgeError("Somente arquivos .mrimg podem ser verificados.")
    if not allowed_roots:
        raise MacriumBridgeError("Nenhuma pasta de backup foi autorizada.")
    for root_raw in allowed_roots:
        root = _normalized_windows_path(root_raw.rstrip("\\"))
        if image.casefold().startswith(root.casefold() + "\\"):
            return root
    raise MacriumBridgeError("Imagem fora das pastas autorizadas.")


def read_configuration() -> Dict[str, Any]:
    if os.environ.get("ULTRON_MACRIUM_VERIFY_ENABLED", "").strip().lower() not in ("true", "1", "yes"):
        raise MacriumBridgeError("Verificação Macrium pelo Ultron está desabilitada.")
    host = os.environ.get("ULTRON_MACRIUM_VERIFIER_HOST", "").strip()
    try:
        parsed = ipaddress.ip_address(host)
        if parsed.version != 4 or parsed.is_multicast or parsed.is_unspecified or parsed.is_loopback:
            raise ValueError("host")
    except ValueError:
        raise MacriumBridgeError("IP da estação Windows verificadora não configurado.")
    raw = os.environ.get("ULTRON_MACRIUM_ALLOWED_ROOTS", "")
    roots = [root.strip() for root in raw.split(";") if root.strip()]
    if not roots:
        raise MacriumBridgeError("Nenhum diretório de backup permitido foi configurado.")
    return {"host": host, "roots": roots}


def verify_on_windows(
    image_path: str,
    *,
    host: str,
    roots: Sequence[str],
    executor: Any
) -> Dict[str, Any]:
    """One read-only verification via configured host; never queue to agent."""
    allowed_root = validate_image_path(image_path, roots)
    try:
        res = executor.run_script_file(
            host,
            "Verify-MacriumImage.ps1",
            params={"ImagePath": image_path, "AllowedRoot": allowed_root},
        )
    except Exception as exc:
        raise MacriumBridgeError("Não foi possível obter confirmação do verificador Windows.") from exc

    if not isinstance(res, dict):
        raise MacriumBridgeError("Resposta WinRM inválida.")
    output = str(res.get("stdout") or "")
    payloads = [line[len(SENTINEL):] for line in output.splitlines()
                if line.strip().startswith(SENTINEL)]
    if len(payloads) != 1:
        raise MacriumBridgeError("O verificador não retornou evidência estruturada única.")

    try:
        report = json.loads(payloads[0])
    except (TypeError, ValueError) as exc:
        raise MacriumBridgeError("Resultado Macrium corrompido ou malformado.") from exc
    if not isinstance(report, dict):
        raise MacriumBridgeError("Resultado Macrium inválido.")
    if ntpath.normcase(str(report.get("image_path") or "")) != ntpath.normcase(image_path):
        raise MacriumBridgeError("O verificador retornou uma imagem diferente da solicitada.")
    if not res.get("success") or res.get("status_code") != 0:
        raise MacriumBridgeError(str(report.get("reason") or "O WinRM não confirmou sucesso."))
    if report.get("verified") is not True or report.get("exit_code") != 0:
        raise MacriumBridgeError("A imagem não passou na verificação Macrium.")
    if not isinstance(report.get("size_bytes"), int) or report["size_bytes"] <= 0:
        raise MacriumBridgeError("Tamanho da imagem não confirmado.")
    if not isinstance(report.get("log_path"), str) or not report["log_path"]:
        raise MacriumBridgeError("Log de verificação ausente.")
    try:
        checked = datetime.fromisoformat(report["verified_at"].replace("Z", "+00:00"))
        if checked.tzinfo is None:
            raise ValueError("timezone")
    except (TypeError, ValueError, KeyError, AttributeError) as exc:
        raise MacriumBridgeError("Horário de verificação inválido.") from exc

    return {
        "verified": True,
        "image_path": image_path,
        "verified_by": host,
        "size_bytes": report["size_bytes"],
        "verified_at": report["verified_at"],
        "log_path": report["log_path"],
        "restored": False,
        "mdt_authorized": False,
    }


class MacriumVerificationJobs:
    """One verification job at a time; results are in-memory only.

    Restarting the Ultron service loses job statuses. Never automatically
    redispatch after a restart; operator reconciles any unknown state.
    """

    def __init__(
        self, executor_factory: Optional[Callable] = None,
        thread_factory: Optional[Callable] = None,
    ):
        self.executor_factory = executor_factory or self._default_executor
        self.thread_factory = thread_factory or threading.Thread
        self._lock = threading.Lock()
        self._jobs: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def _default_executor():
        from core.winrm_executor import WinRMExecutor
        return WinRMExecutor()

    def start(self, image_path: str, on_done: Optional[Callable] = None) -> Dict[str, Any]:
        config = read_configuration()
        validate_image_path(image_path, config["roots"])
        with self._lock:
            if any(job["status"] in ACTIVE for job in self._jobs.values()):
                raise MacriumBridgeError("Já existe uma verificação em andamento.")
            if len(self._jobs) >= MAX_RECORDS:
                for old_id, old in list(self._jobs.items()):
                    if old["status"] not in ACTIVE:
                        del self._jobs[old_id]
                        break
            job_id = "verify_" + uuid.uuid4().hex
            self._jobs[job_id] = {
                "job_id": job_id,
                "status": "QUEUED",
                "image_path": image_path,
                "host": config["host"],
                "created_at": time.time(),
            }
        def worker():
            with self._lock:
                self._jobs[job_id]["status"] = "RUNNING"
            try:
                result = verify_on_windows(
                    image_path, host=config["host"], roots=config["roots"],
                    executor=self.executor_factory(),
                )
            except Exception as exc:
                result = {"verified": False, "reason": str(exc),
                          "restored": False, "mdt_authorized": False}
                status = "ERROR"
            else:
                status = "SUCCESS"

            with self._lock:
                self._jobs[job_id].update({
                    "status": status,
                    "finished_at": time.time(),
                    "result": result,
                })
                snapshot = dict(self._jobs[job_id])
            if on_done:
                try:
                    on_done(snapshot)
                except Exception:
                    pass

        thread = self.thread_factory(target=worker, daemon=True)
        try:
            thread.start()
        except Exception:
            with self._lock:
                self._jobs.pop(job_id, None)
            raise MacriumBridgeError("Não foi possível iniciar a verificação.")
        return self.get(job_id)

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None


macrium_jobs = MacriumVerificationJobs()
