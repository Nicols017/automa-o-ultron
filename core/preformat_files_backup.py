"""Conservative pre-format FILE backup orchestration for Ultron.

This workflow copies selected user folders via Robocopy from the source Windows
machine to the configured network share. It never creates a Macrium disk image,
never verifies disk restorable state, and never permits MDT formatting.

Disabled by default. Only one backup at a time to protect shared storage.
"""
import ipaddress
import json
import os
import re
import threading
import time
import uuid
from typing import Any, Callable, Dict, Optional

SENTINEL = "ULTRON_FILES_BACKUP_JSON:"
IN_PROGRESS = {"QUEUED", "RUNNING"}
CLIENT_RE = re.compile(r"^[^\W_][\w -]{1,59}$", re.UNICODE)
TICKET_RE = re.compile(r"^[0-9]{2,12}$")
MAX_JOBS = 100
PROTECTED_HOSTS = {
    "192.168.57.43",  # Jarvis
    "192.168.57.87",  # WDS/MDT
    "192.168.57.112", # backup storage
}


class FileBackupError(Exception):
    pass


def read_file_backup_configuration() -> Dict[str, Any]:
    if os.getenv("ULTRON_FILES_BACKUP_ENABLED", "").lower() not in ("yes", "true", "1"):
        raise FileBackupError("Backup remoto de arquivos está desabilitado no Ultron.")
    share = os.getenv("ULTRON_FILES_BACKUP_SHARE", "").strip()
    if not re.fullmatch(r"\\\\[A-Za-z0-9.-]+\\[A-Za-z0-9$._-]+", share):
        raise FileBackupError("Compartilhamento de destino não configurado ou inválido.")
    subnet = os.getenv("ULTRON_FILES_BACKUP_ALLOWED_SUBNET", "").strip()
    try:
        network = ipaddress.ip_network(subnet, strict=False)
        if network.version != 4 or not network.is_private:
            raise ValueError("network")
    except ValueError:
        raise FileBackupError("Sub-rede de máquinas autorizadas não configurada.")
    return {"share": share, "subnet": network}


def validate_file_backup_request(
    ip: str, client: str, ticket: str, config: Dict[str, Any],
) -> None:
    try:
        address = ipaddress.ip_address(ip)
        if address.version != 4 or address not in config["subnet"] or ip in PROTECTED_HOSTS:
            raise ValueError("forbidden")
    except ValueError:
        raise FileBackupError("IP de origem fora da rede de PCs autorizada.")
    if not isinstance(client, str) or not CLIENT_RE.fullmatch(client):
        raise FileBackupError("Nome do cliente inválido; use letras, números, espaço ou hífen.")
    if not isinstance(ticket, str) or not TICKET_RE.fullmatch(ticket):
        raise FileBackupError("Chamado inválido; informe de 2 a 12 dígitos.")


def _parse_result(res: Any, *, client: str, ticket: str) -> Dict[str, Any]:
    if not isinstance(res, dict):
        raise FileBackupError("WinRM retornou uma resposta inválida.")
    lines = [line.strip() for line in str(res.get("stdout") or "").splitlines()
             if line.strip().startswith(SENTINEL)]
    if len(lines) != 1:
        raise FileBackupError("WinRM não retornou confirmação única de backup.")
    try:
        report = json.loads(lines[0][len(SENTINEL):])
    except (TypeError, ValueError) as exc:
        raise FileBackupError("Relatório de backup inválido.") from exc
    if not isinstance(report, dict):
        raise FileBackupError("Relatório de backup incorreto.")
    if not res.get("success") or res.get("status_code") != 0:
        raise FileBackupError(str(report.get("reason") or "Falha WinRM ou Robocopy."))
    if (report.get("status") != "SUCCESS"
            or report.get("image_backup") is not False
            or report.get("mdt_authorized") is not False
            or report.get("type") != "selected_user_files"
            or report.get("client") != client
            or str(report.get("ticket")) != ticket):
        raise FileBackupError("Comprovante de backup inconsistente.")
    if (not isinstance(report.get("files_at_destination"), int)
            or report["files_at_destination"] <= 0
            or not isinstance(report.get("bytes_at_destination"), int)
            or report["bytes_at_destination"] < 0
            or not isinstance(report.get("folders_copied"), int)
            or report["folders_copied"] <= 0):
        raise FileBackupError("Nenhum dado copiado foi comprovado.")
    codes = report.get("robocopy_exit_codes")
    if not isinstance(codes, list) or not codes or any(
        not isinstance(code, int) or code < 0 or code >= 4 for code in codes
    ):
        raise FileBackupError("Status de cópia Robocopy não confirmado.")
    if not isinstance(report.get("destination"), str) or not report["destination"]:
        raise FileBackupError("Destino do backup ausente.")
    if not re.fullmatch(r"[a-f0-9]{32}", str(report.get("run_id", ""))):
        raise FileBackupError("Identificador da execução ausente.")
    return {
        "success": True,
        "type": "selected_user_files",
        "image_backup": False,
        "mdt_authorized": False,
        "destination": report["destination"],
        "client": client,
        "ticket": ticket,
        "files_at_destination": report["files_at_destination"],
        "bytes_at_destination": report["bytes_at_destination"],
        "profiles_found": report.get("profiles_found"),
        "folders_copied": report["folders_copied"],
        "run_id": report["run_id"],
        "reason": "Cópia das pastas selecionadas concluída; não é uma imagem completa.",
    }


class FileBackupJobs:
    def __init__(
        self, executor_factory: Optional[Callable] = None,
        thread_factory: Optional[Callable] = None, registry=None,
    ):
        self._registry = registry
        self._executor_factory = executor_factory or self._default_executor
        self._thread_factory = thread_factory or threading.Thread
        self._lock = threading.Lock()
        self._jobs: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def _default_executor():
        from core.winrm_executor import WinRMExecutor
        return WinRMExecutor()

    def start(
        self, ip: str, client: str, ticket: str,
        on_done: Optional[Callable] = None, owner: Optional[str] = None,
    ) -> Dict[str, Any]:
        tracked = owner is not None
        if tracked and self._registry is None:
            from core.task_registry import task_registry
            self._registry = task_registry
        config = read_file_backup_configuration()
        validate_file_backup_request(ip, client, ticket, config)
        with self._lock:
            if any(j["status"] in IN_PROGRESS for j in self._jobs.values()):
                raise FileBackupError("Outra cópia já está em andamento; aguarde a conclusão.")
            if len(self._jobs) >= MAX_JOBS:
                for key, job in list(self._jobs.items()):
                    if job["status"] not in IN_PROGRESS:
                        del self._jobs[key]
                        break
            job_id = "files_" + uuid.uuid4().hex
            if tracked:
                try:
                    self._registry.create(owner, ip, "file_backup", job_id=job_id)
                except Exception:
                    raise FileBackupError("Registro indisponivel ou equipamento ocupado; copia nao iniciada.") from None
            self._jobs[job_id] = {
                "job_id": job_id,
                "source_ip": ip,
                "client": client,
                "ticket": ticket,
                "status": "QUEUED",
                "created_at": time.time(),
            }

        def worker():
            with self._lock:
                self._jobs[job_id]["status"] = "RUNNING"
            result = None
            dispatched = False
            try:
                if tracked and not self._registry.begin(owner, job_id):
                    raise FileBackupError("Tarefa ja entregue ou encerrada; copia nao reenviada.")
                dispatched = True
                result = self._executor_factory().run_script_file(
                    ip, "Backup-UserData.ps1",
                    params={
                        "TargetShare": config["share"],
                        "ClientName": client,
                        "TicketNumber": ticket,
                        "SourceDrive": "C:",
                    },
                )
                details = _parse_result(result, client=client, ticket=ticket)
                status = "SUCCESS"
            except Exception as exc:
                details = {
                    "success": False,
                    "image_backup": False,
                    "mdt_authorized": False,
                    "reason": str(exc),
                }
                status = "UNKNOWN" if dispatched and (result is None or result.get("outcome") == "UNKNOWN") else "ERROR"
            if tracked:
                self._registry.finish(owner, job_id, status,
                    "BACKUP_REPORT_VALIDATED" if status == "SUCCESS" else "NONE")
            with self._lock:
                self._jobs[job_id].update({
                    "status": status,
                    "finished_at": time.time(),
                    "result": details,
                })
                snapshot = dict(self._jobs[job_id])
            if on_done:
                try:
                    on_done(snapshot)
                except Exception:
                    pass

        try:
            self._thread_factory(target=worker, daemon=True).start()
        except Exception as exc:
            if tracked:
                self._registry.finish(owner, job_id, "ERROR", "NOT_STARTED")
            with self._lock:
                del self._jobs[job_id]
            raise FileBackupError("Não foi possível iniciar a tarefa.") from exc
        return self.get(job_id)

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            value = self._jobs.get(job_id)
            return dict(value) if value else None


file_backup_jobs = FileBackupJobs()
