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
        self.default_pass = self.config.get("winrm", {}).get("default_pass", "")
        self.port = self.config.get("winrm", {}).get("port", 5985)
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
        endpoint = f"http://{ip}:{self.port}/wsman"
        return winrm.Session(
            endpoint,
            auth=(user, pwd),
            transport="ntlm",
            server_cert_validation="ignore"
        )

    def _get_credential_candidates(self, ip: str, username: Optional[str] = None, password: Optional[str] = None) -> List[Tuple[str, str]]:
        candidates = []
        
        # 1. Credencial fornecida explicitamente na chamada
        if username:
            candidates.append((username, password or ""))

        # 2. Credencial em cache obtida do registro do agente ou técnico para este IP
        cached = self.get_host_credentials(ip)
        if cached and cached not in candidates:
            candidates.append(cached)

        # 3. Credencial padrão de automação do UltronAgent (Zero-Prompt)
        agent_cred = ("UltronAdmin", "Ultron@AutoBench2026!")
        if agent_cred not in candidates:
            candidates.append(agent_cred)

        # 4. Usuário padrão configurado se houver
        if self.default_user and (self.default_user, self.default_pass) not in candidates:
            candidates.append((self.default_user, self.default_pass))

        # 5. Fallback credentials configuradas no settings.yaml
        fb_list = self.config.get("winrm", {}).get("fallback_credentials", [])
        for fb in fb_list:
            u = fb.get("user")
            p = fb.get("pass", "")
            if u and (u, p) not in candidates:
                candidates.append((u, p))

        # 6. Contas padrão adicionais de bancada e suporte
        extra_fallbacks = [
            ("Administrator", ""),
            ("Administrador", ""),
            ("penserede", ""),
            ("suporte", ""),
            ("admin", ""),
            ("nicolas.silva", ""),
            ("nicolas", ""),
            ("penserede\\Administrator", ""),
            ("penserede\\Administrador", ""),
        ]
        for u, p in extra_fallbacks:
            if (u, p) not in candidates:
                candidates.append((u, p))

        # Alterna entre Administrator e Administrador (padrão EN/PT-BR do Windows)
        for u, p in list(candidates):
            if u.lower() == "administrator" and ("Administrador", p) not in candidates:
                candidates.append(("Administrador", p))
            elif u.lower() == "administrador" and ("Administrator", p) not in candidates:
                candidates.append(("Administrator", p))

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
                "auth_failed": False,
                "status_code": -1,
                "stdout": "",
                "stderr": f"Host {ip}:{self.port} inacessível ou porta WinRM fechada.",
                "ip": ip
            }

        last_error = ""
        is_auth_error = False
        candidates = self._get_credential_candidates(ip, username, password)

        for user, pwd in candidates:
            try:
                session = self.get_session(ip, user, pwd)
                response = session.run_ps(script_code)
                
                stdout_str = response.std_out.decode("utf-8", errors="replace").strip() if response.std_out else ""
                stderr_str = response.std_err.decode("utf-8", errors="replace").strip() if response.std_err else ""
                
                # Se autenticou com sucesso (mesmo que o script retorne erro de execução)
                if response.status_code == 0 or ("credentials were rejected" not in stderr_str.lower() and "401" not in stderr_str and "access is denied" not in stderr_str.lower()):
                    # Salva no cache como credencial funcional
                    self.set_host_credentials(ip, user, pwd)
                    return {
                        "success": response.status_code == 0,
                        "auth_failed": False,
                        "status_code": response.status_code,
                        "stdout": stdout_str,
                        "stderr": stderr_str,
                        "ip": ip,
                        "user_used": user
                    }
                last_error = stderr_str
                is_auth_error = True
            except Exception as e:
                last_error = str(e)
                err_lower = str(e).lower()
                if "credentials were rejected" in err_lower or "401" in err_lower or "unauthorized" in err_lower or "access is denied" in err_lower:
                    is_auth_error = True
                else:
                    break

        return {
            "success": False,
            "auth_failed": is_auth_error,
            "status_code": -1,
            "stdout": "",
            "stderr": f"Erro de autenticação ou execução WinRM: {last_error}",
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
