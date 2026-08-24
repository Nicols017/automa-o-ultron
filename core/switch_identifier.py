"""
Módulo de Identificação de Porta do Switch e Posição Física na Bancada - Ultron Lab Automation
Mapeia endereços MAC/IP para portas do switch e bancadas físicas do laboratório (Mikrotik, SNMP ou ARP).
"""

import os
import re
import subprocess
import yaml
from typing import Dict, Any, Optional

class SwitchIdentifier:
    def __init__(self, config_path: Optional[str] = None):
        self.config = self._load_config(config_path)
        self.switch_cfg = self.config.get("switch", {})
        self.enabled = self.switch_cfg.get("enabled", False)
        self.host = self.switch_cfg.get("host", "192.168.57.1")
        self.switch_type = self.switch_cfg.get("type", "mikrotik_ssh").lower()
        self.user = self.switch_cfg.get("user", "admin")
        self.password = self.switch_cfg.get("password", "")
        self.ports_mapping = self.switch_cfg.get("ports_mapping", {})

    def _load_config(self, config_path: Optional[str]) -> Dict[str, Any]:
        if not config_path:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            config_path = os.path.join(base_dir, "config", "settings.yaml")
        try:
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
        except Exception as e:
            print(f"⚠️ Erro ao carregar configurações de switch em {config_path}: {e}")
        return {}

    def normalize_mac(self, mac: str) -> str:
        """Normaliza qualquer formato de MAC para XX:XX:XX:XX:XX:XX em maiúsculo"""
        if not mac:
            return ""
        clean = re.sub(r'[^a-fA-F0-9]', '', mac).upper()
        if len(clean) == 12:
            return ":".join(clean[i:i+2] for i in range(0, 12, 2))
        return mac.upper()

    def get_mac_from_arp(self, ip: str) -> Optional[str]:
        """Tenta descobrir o MAC de um IP a partir da tabela ARP do sistema operacional"""
        try:
            # No Windows: arp -a <ip> | No Linux: arp -n <ip> ou ip neigh show <ip>
            cmd = ["arp", "-a", ip] if os.name == "nt" else ["ip", "neigh", "show", ip]
            output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=2).decode("utf-8", errors="ignore")
            
            # Procura padrão de MAC
            mac_match = re.search(r'([0-9a-fA-F]{2}[:-]){5}([0-9a-fA-F]{2})', output)
            if mac_match:
                return self.normalize_mac(mac_match.group(0))
        except Exception:
            pass
        return None

    def query_mikrotik_ssh(self, mac: str) -> Optional[str]:
        """Consulta a porta do switch via SSH no Mikrotik RouterOS (/interface bridge host print)"""
        try:
            import paramiko
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                self.host,
                username=self.user,
                password=self.password,
                timeout=3,
                allow_agent=False,
                look_for_keys=False
            )
            
            # Formato de MAC no Mikrotik é XX:XX:XX:XX:XX:XX
            formatted_mac = self.normalize_mac(mac)
            cmd = f':put [/interface bridge host get [find mac-address="{formatted_mac}"] on-interface]'
            stdin, stdout, stderr = client.exec_command(cmd, timeout=3)
            port_name = stdout.read().decode("utf-8").strip()
            client.close()
            
            if port_name and not "no such" in port_name.lower():
                return port_name
        except Exception as e:
            # Falha silenciosa ou log de debug
            pass
        return None

    def identify_bench(self, mac: Optional[str] = None, ip: Optional[str] = None) -> Dict[str, Any]:
        """
        Retorna a localização física da máquina na bancada e a porta correspondente.
        """
        target_mac = self.normalize_mac(mac) if mac else None
        if not target_mac and ip:
            target_mac = self.get_mac_from_arp(ip)

        port = "N/A"
        bench_name = "Bancada de Laboratório"

        if self.enabled and target_mac:
            if "mikrotik" in self.switch_type:
                found_port = self.query_mikrotik_ssh(target_mac)
                if found_port:
                    port = found_port
                    # Mapeia para o nome amigável da bancada
                    bench_name = self.ports_mapping.get(port, self.ports_mapping.get(str(port), f"Bancada (Porta {port})"))

        # Se não tiver porta detectada mas tiver mapeamento por IP
        if port == "N/A" and ip:
            bench_name = f"Bancada (IP {ip})"

        return {
            "mac": target_mac or "Desconhecido",
            "ip": ip or "Desconhecido",
            "port": port,
            "bench_name": bench_name,
            "identified": (port != "N/A")
        }
