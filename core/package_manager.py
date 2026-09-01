"""
Módulo de Gerenciamento Unificado de Pacotes - Ultron Lab Automation
Compatível com bundles e catálogos do UniGetUI (Winget, Chocolatey, Scoop).
Permite backup de softwares antes da formatação, restauração automática e atualização em massa.
"""

import os
import json
import time
import logging
from typing import Dict, Any, List, Optional
from core.winrm_executor import WinRMExecutor

logger = logging.getLogger("ultron_package_manager")

class UnifiedPackageManager:
    def __init__(self, winrm_executor: Optional[WinRMExecutor] = None):
        self.winrm = winrm_executor or WinRMExecutor()
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.backups_dir = os.path.join(self.base_dir, "backups", "softwares")
        os.makedirs(self.backups_dir, exist_ok=True)

    def export_machine_packages(self, ip: str, identifier: Optional[str] = None) -> Dict[str, Any]:
        """
        Varre todos os programas instalados na máquina de bancada e salva um bundle UniGetUI (.json).
        """
        target_id = (identifier or ip).replace(":", "-").replace(".", "_")
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"bundle_{target_id}_{timestamp}.json"
        bundle_file_path = os.path.join(self.backups_dir, filename)

        res = self.winrm.run_script_file(ip, "Export-InstalledPackages.ps1")
        if not res["success"] or not res["stdout"]:
            return {
                "success": False,
                "ip": ip,
                "error": res.get("stderr") or "Falha ao consultar softwares instalados na máquina."
            }

        stdout_txt = res["stdout"].strip()
        json_start = stdout_txt.find("{")
        json_end = stdout_txt.rfind("}") + 1

        bundle_data = {}
        if json_start != -1 and json_end != -1:
            try:
                bundle_data = json.loads(stdout_txt[json_start:json_end])
            except Exception as e:
                logger.warning(f"Erro ao parsear JSON de bundle do UniGetUI: {e}")

        if not bundle_data:
            return {
                "success": False,
                "ip": ip,
                "error": "Não foi possível extrair a lista de softwares em formato UniGetUI válido."
            }

        # Salva o arquivo de bundle localmente
        try:
            with open(bundle_file_path, "w", encoding="utf-8") as f:
                json.dump(bundle_data, f, indent=2, ensure_ascii=False)
            
            # Cria ou atualiza link 'latest' para este alvo
            latest_file = os.path.join(self.backups_dir, f"latest_{target_id}.json")
            with open(latest_file, "w", encoding="utf-8") as f:
                json.dump(bundle_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Erro ao salvar arquivo de bundle: {e}")

        pkgs = bundle_data.get("packages", [])
        return {
            "success": True,
            "ip": ip,
            "filename": filename,
            "file_path": bundle_file_path,
            "packages_count": len(pkgs),
            "hostname": bundle_data.get("hostname", "PC"),
            "packages": pkgs
        }

    def restore_machine_packages(self, ip: str, bundle_name_or_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Reinstala na máquina de bancada os softwares contidos em um bundle do UniGetUI salvo anteriormente.
        """
        # Procura o arquivo correspondente
        bundle_file = None
        if bundle_name_or_id:
            # Tenta caminho direto
            if os.path.exists(bundle_name_or_id):
                bundle_file = bundle_name_or_id
            elif os.path.exists(os.path.join(self.backups_dir, bundle_name_or_id)):
                bundle_file = os.path.join(self.backups_dir, bundle_name_or_id)
            else:
                # Tenta por prefixo latest
                clean_id = bundle_name_or_id.replace(":", "-").replace(".", "_")
                candidate = os.path.join(self.backups_dir, f"latest_{clean_id}.json")
                if os.path.exists(candidate):
                    bundle_file = candidate

        # Se não especificou, tenta o latest do próprio IP
        if not bundle_file:
            ip_clean = ip.replace(".", "_")
            candidate = os.path.join(self.backups_dir, f"latest_{ip_clean}.json")
            if os.path.exists(candidate):
                bundle_file = candidate

        if not bundle_file or not os.path.exists(bundle_file):
            return {
                "success": False,
                "ip": ip,
                "error": f"Nenhum backup de softwares UniGetUI encontrado para '{bundle_name_or_id or ip}'."
            }

        try:
            with open(bundle_file, "r", encoding="utf-8") as f:
                bundle_data = json.load(f)
        except Exception as e:
            return {"success": False, "ip": ip, "error": f"Erro ao ler arquivo de bundle: {e}"}

        pkgs = bundle_data.get("packages", [])
        pkg_ids = [p.get("Id") for p in pkgs if p.get("Id")]

        if not pkg_ids:
            return {"success": False, "ip": ip, "error": "O arquivo de backup não contém nenhum ID de pacote válido."}

        # Executa a instalação multi-gerenciador
        res = self.winrm.run_script_file(
            ip,
            "Install-UnifiedPackages.ps1",
            params={"Packages": pkg_ids}
        )

        return {
            "success": res["success"],
            "ip": ip,
            "bundle_file": os.path.basename(bundle_file),
            "packages_sent": len(pkg_ids),
            "output": res.get("stdout", ""),
            "error": res.get("stderr", "")
        }

    def upgrade_all_packages(self, ip: str) -> Dict[str, Any]:
        """
        Dispara a atualização em massa de todos os programas instalados na máquina via Winget/UniGetUI.
        """
        res = self.winrm.run_script_file(ip, "Upgrade-AllPackages.ps1")
        return {
            "success": res["success"],
            "ip": ip,
            "output": res.get("stdout", ""),
            "error": res.get("stderr", "")
        }

    def list_saved_bundles(self) -> List[Dict[str, Any]]:
        """
        Retorna a lista de todos os backups de softwares UniGetUI salvos no laboratório.
        """
        bundles = []
        if not os.path.exists(self.backups_dir):
            return bundles

        for f in sorted(os.listdir(self.backups_dir), reverse=True):
            if f.endswith(".json") and not f.startswith("latest_"):
                fpath = os.path.join(self.backups_dir, f)
                try:
                    with open(fpath, "r", encoding="utf-8") as bf:
                        data = json.load(bf)
                        bundles.append({
                            "filename": f,
                            "hostname": data.get("hostname", "PC"),
                            "packages_count": len(data.get("packages", [])),
                            "created_at": data.get("created_at", "N/A"),
                            "file_path": fpath
                        })
                except Exception:
                    pass
        return bundles
