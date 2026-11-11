"""
Módulo de Execução Remota WinRM - Ultron Lab Automation
Gerencia conexões remotas via WinRM com as máquinas de bancada para execução de scripts PowerShell.
"""

import os
import socket
import winrm
import yaml
import asyncio
import traceback
from typing import Dict, Any, Optional, List, Tuple
from core.reliability import ResilientWinRM, new_trace_id, log

class WinRMExecutor:
    def __init__(self, config_path: str = None):
        self.config = self._load_config(config_path)
        self.default_user = self.config.get("winrm", {}).get("default_user", "Administrator")
        self.default_pass = self.config.get("winrm", {}).get("default_pass", "")
        self.port = self.config.get("winrm", {}).get("port", 5986)
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.scripts_dir = os.path.join(self.base_dir, "scripts", "powershell")
        # Cache dinâmico de credenciais fornecidas pelos técnicos por IP
        self.cached_credentials: Dict[str, Tuple[str, str]] = {}

    def set_host_credentials(self, ip: str, username: str, password: str):
        """Armazena credenciais válidas fornecidas pelo técnico para um IP de máquina"""
        if ip and username:
            self.cached_credentials[ip.strip()] = (username.strip(), password or "")

    def get_host_credentials(self, ip: str) -> Optional[Tuple[str, str]]:
        """Recupera credenciais em cache para uma máquina"""
        return self.cached_credentials.get(ip.strip()) if ip else None

    def _load_config(self, config_path: Optional[str]) -> Dict[str, Any]:
        if not config_path:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            config_path = os.path.join(base_dir, "config", "settings.yaml")
        try:
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
        except Exception as e:
            print(f"⚠️ Erro ao carregar {config_path}: {e}")
        return {}

    def test_connection(self, ip: str, timeout: float = 3.0) -> bool:
        """
        Verifica rapidamente se a porta WinRM (5985) está aberta na máquina alvo.
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((ip, self.port))
            sock.close()
            return result == 0
        except Exception:
            return False

    def is_smb_rpc_reachable(self, ip: str, timeout: float = 2.0) -> bool:
        """
        Verifica se as portas administrativas SMB (445) ou RPC (135) estão acessíveis.
        """
        for port in [445, 135]:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(timeout)
                res = sock.connect_ex((ip, port))
                sock.close()
                if res == 0:
                    return True
            except Exception:
                pass
        return False

    def get_session(self, ip: str, username: Optional[str] = None, password: Optional[str] = None) -> winrm.Session:
        """
        Cria uma sessão WinRM autenticada com a máquina alvo.
        Executa 100% silencioso em Session 0 (invisível ao usuário).
        """
        user = username or self.default_user
        pwd = password if password is not None else self.default_pass
        scheme = self.config.get("winrm", {}).get("scheme", "https")
        if scheme not in ("http", "https"):
            raise ValueError("WinRM scheme deve ser http ou https")
        if scheme == "http" and not self.config.get("winrm", {}).get("allow_http_ntlm", False):
            raise ValueError("HTTP/NTLM exige allow_http_ntlm explicito")
        endpoint = f"{scheme}://{ip}:{self.port}/wsman"
        return winrm.Session(
            endpoint,
            auth=(user, pwd),
            transport="ntlm",
            server_cert_validation="validate",
            message_encryption="always",
            read_timeout_sec=1810,
            operation_timeout_sec=1800
        )

    def _get_credential_candidates(self, ip: str, username: Optional[str] = None, password: Optional[str] = None) -> List[Tuple[str, str]]:
        # One identity per request: never guess passwords or spray accounts.
        if username:
            return [(username, password if password is not None else "")]
        cached = self.get_host_credentials(ip)
        if cached:
            return [cached]
        if self.default_user and self.default_pass:
            return [(self.default_user, self.default_pass)]
        return []

    def run_powershell_code(self, ip, script_code, username=None, password=None):
        """Execute once; transport failure can mean UNKNOWN remote outcome."""
        from core.winrm_diagnostics import classify_winrm_error
        candidates = self._get_credential_candidates(ip, username, password)
        result = dict(success=False, auth_failed=False, status_code=-1,
                      stdout="", stderr="", ip=ip)
        if not candidates:
            result.update(error_code="CREDENTIALS_MISSING",
                          stderr="Informe credencial WinRM; token do agente nao e senha Windows.")
            return result
        user, pwd = candidates[0]
        try:
            response = self.get_session(ip, user, pwd).run_ps(script_code)
            result.update(success=response.status_code == 0,
                          status_code=response.status_code,
                          stdout=response.std_out.decode("utf-8", errors="replace").strip(),
                          stderr=response.std_err.decode("utf-8", errors="replace").strip(),
                          user_used=user)
            self.set_host_credentials(ip, user, pwd)
        except Exception as exc:
            diagnostic = classify_winrm_error(exc)
            result.update(diagnostic)
            result["auth_failed"] = diagnostic["error_code"] == "AUTHENTICATION"
        return result

    def run_script_file(
        self,
        ip: str,
        script_name: str,
        params: Optional[Dict[str, Any]] = None,
        username: Optional[str] = None,
        password: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Carrega um script da pasta scripts/powershell/ e o executa com os parâmetros fornecidos.
        """
        script_path = os.path.join(self.scripts_dir, script_name)
        if not os.path.exists(script_path):
            if not os.path.isabs(script_name):
                script_path = os.path.abspath(script_name)
            if not os.path.exists(script_path):
                return {
                    "success": False,
                    "status_code": -1,
                    "stdout": "",
                    "stderr": f"Script não encontrado: {script_name}",
                    "ip": ip
                }

        try:
            with open(script_path, "r", encoding="utf-8") as f:
                script_content = f.read()
        except UnicodeDecodeError:
            with open(script_path, "r", encoding="latin-1") as f:
                script_content = f.read()

        param_str = ""
        if params:
            parts = []
            for k, v in params.items():
                if not __import__("re").fullmatch(r"[A-Za-z][A-Za-z0-9_]*", k):
                    raise ValueError("Nome de parametro PowerShell invalido")
                def literal(value):
                    return "'" + str(value).replace("'", "''") + "'"
                if isinstance(v, bool):
                    val = "$true" if v else "$false"
                elif isinstance(v, (int, float)):
                    import math
                    if not math.isfinite(v):
                        raise ValueError("Numero nao finito")
                    val = str(v)
                elif isinstance(v, str):
                    val = literal(v)
                elif isinstance(v, (list, tuple)):
                    val = "@(" + ",".join(literal(item) for item in v) + ")"
                else:
                    raise ValueError("Tipo de parametro nao suportado")
                parts.append(f"-{k} {val}")
            param_str = " ".join(parts)

        invoker = f"""
& {{
{script_content}
}} {param_str}
"""
        return self.run_powershell_code(ip, invoker, username, password)
