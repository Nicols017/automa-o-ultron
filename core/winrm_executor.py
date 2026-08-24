"""
Módulo de Execução Remota WinRM - Ultron Lab Automation
Gerencia conexões remotas via WinRM com as máquinas de bancada para execução de scripts PowerShell.
"""

import os
import socket
import winrm
import yaml
from typing import Dict, Any, Optional, List, Tuple

class WinRMExecutor:
    def __init__(self, config_path: str = None):
        self.config = self._load_config(config_path)
        self.default_user = self.config.get("winrm", {}).get("default_user", "Administrator")
        self.default_pass = self.config.get("winrm", {}).get("default_pass", "SenhaTemporariaLab123!")
        self.port = self.config.get("winrm", {}).get("port", 5985)
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.scripts_dir = os.path.join(self.base_dir, "scripts", "powershell")

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
        pwd = password or self.default_pass
        endpoint = f"http://{ip}:{self.port}/wsman"
        return winrm.Session(
            endpoint,
            auth=(user, pwd),
            transport="ntlm",
            server_cert_validation="ignore"
        )

    def _get_credential_candidates(self, username: Optional[str] = None, password: Optional[str] = None) -> List[Tuple[str, str]]:
        primary_user = username or self.default_user
        primary_pass = password or self.default_pass
        
        candidates = [(primary_user, primary_pass)]
        
        # Alterna entre Administrator e Administrador (padrão EN/PT-BR do Windows)
        if primary_user.lower() == "administrator":
            candidates.append(("Administrador", primary_pass))
        elif primary_user.lower() == "administrador":
            candidates.append(("Administrator", primary_pass))

        return candidates

    def run_powershell_code(
        self,
        ip: str,
        script_code: str,
        username: Optional[str] = None,
        password: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Executa um código arbitrário em PowerShell na máquina remota com fallback de credenciais.
        """
        if not self.test_connection(ip):
            return {
                "success": False,
                "status_code": -1,
                "stdout": "",
                "stderr": f"Host {ip}:{self.port} inacessível ou porta WinRM fechada.",
                "ip": ip
            }

        last_error = ""
        for user, pwd in self._get_credential_candidates(username, password):
            try:
                session = self.get_session(ip, user, pwd)
                response = session.run_ps(script_code)
                
                stdout_str = response.std_out.decode("utf-8", errors="replace").strip() if response.std_out else ""
                stderr_str = response.std_err.decode("utf-8", errors="replace").strip() if response.std_err else ""
                
                # Se autenticou com sucesso (mesmo que o script retorne erro de execução)
                if response.status_code == 0 or "credentials were rejected" not in stderr_str:
                    return {
                        "success": response.status_code == 0,
                        "status_code": response.status_code,
                        "stdout": stdout_str,
                        "stderr": stderr_str,
                        "ip": ip,
                        "user_used": user
                    }
                last_error = stderr_str
            except Exception as e:
                last_error = str(e)
                if "credentials were rejected" not in str(e).lower() and "401" not in str(e):
                    break

        return {
            "success": False,
            "status_code": -1,
            "stdout": "",
            "stderr": f"Erro durante a execução WinRM: {last_error}",
            "ip": ip
        }

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
                if isinstance(v, bool):
                    val = "$true" if v else "$false"
                    parts.append(f"-{k} {val}")
                elif isinstance(v, (int, float)):
                    parts.append(f"-{k} {v}")
                elif isinstance(v, str):
                    clean_v = v.replace('"', '`"')
                    parts.append(f"-{k} \"{clean_v}\"")
            param_str = " ".join(parts)

        invoker = f"""
& {{
{script_content}
}} {param_str}
"""
        return self.run_powershell_code(ip, invoker, username, password)
