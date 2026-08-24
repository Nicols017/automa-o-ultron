"""
Módulo de Varredura e Descoberta de Rede da Bancada - Ultron Lab Automation
Varre a subrede do laboratório para identificar máquinas ativas e prontas para automação (Porta 5985 WinRM).
"""

import socket
import ipaddress
import yaml
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Optional
from core.switch_identifier import SwitchIdentifier

class NetworkScanner:
    def __init__(self, subnet: Optional[str] = None, config_path: Optional[str] = None):
        self.switch_id = SwitchIdentifier(config_path)
        if not subnet:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            settings_file = config_path or os.path.join(base_dir, "config", "settings.yaml")
            self.subnet = self._load_subnet_from_config(settings_file)
        else:
            self.subnet = subnet

    def _load_subnet_from_config(self, settings_file: str) -> str:
        try:
            if os.path.exists(settings_file):
                with open(settings_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                    return data.get("network", {}).get("lab_subnet", "192.168.57.0/24")
        except Exception as e:
            print(f"⚠️ Erro ao ler subrede de {settings_file}: {e}")
        return "192.168.57.0/24"

    def _check_host(self, ip_str: str, timeout: float = 0.5) -> Optional[Dict[str, Any]]:
        """
        Verifica portas essenciais (5985 WinRM, 445 SMB, 22 SSH, 80 HTTP) em uma máquina alvo.
        """
        ports_to_check = {
            5985: "WinRM",
            445: "SMB",
            22: "SSH",
            80: "HTTP"
        }
        open_ports = []
        winrm_ready = False

        for port, service in ports_to_check.items():
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.settimeout(timeout)
                    if sock.connect_ex((ip_str, port)) == 0:
                        open_ports.append(port)
                        if port == 5985:
                            winrm_ready = True
            except Exception:
                pass

        if not open_ports:
            return None

        # Tenta resolver o hostname
        hostname = ip_str
        try:
            resolved_host, _, _ = socket.gethostbyaddr(ip_str)
            hostname = resolved_host
        except Exception:
            pass

        # Identifica bancada / porta física e MAC
        bench_info = self.switch_id.identify_bench(ip=ip_str)
        detected_mac = bench_info.get("mac", "")
        if detected_mac == "Desconhecido":
            detected_mac = ""

        # Resolve fabricante OEM a partir do MAC (Dell, HP, Lenovo, etc.)
        vendor_name = "Desconhecido"
        if detected_mac:
            from core.public_tools import MacVendorResolver
            vendor_data = MacVendorResolver.resolve(detected_mac)
            vendor_name = vendor_data.get("vendor", "Genérico")

        return {
            "ip": ip_str,
            "hostname": hostname,
            "mac": detected_mac,
            "vendor": vendor_name,
            "bench_name": bench_info.get("bench_name", f"Bancada ({ip_str})"),
            "switch_port": bench_info.get("port", "N/A"),
            "winrm_ready": winrm_ready,
            "open_ports": open_ports,
            "status": "ready" if winrm_ready else "discovered"
        }

    def scan_network(self, max_threads: int = 50, timeout: float = 0.4) -> List[Dict[str, Any]]:
        """
        Varre todos os IPs da subrede configurada e retorna a lista de máquinas ativas.
        """
        try:
            net = ipaddress.ip_network(self.subnet, strict=False)
        except ValueError:
            print(f"❌ Subrede inválida: {self.subnet}")
            return []

        hosts = [str(ip) for ip in net.hosts()]
        active_devices = []

        with ThreadPoolExecutor(max_workers=max_threads) as executor:
            futures = {executor.submit(self._check_host, ip, timeout): ip for ip in hosts}
            for future in as_completed(futures):
                result = future.result()
                if result:
                    active_devices.append(result)

        # Ordena pelo IP
        active_devices.sort(key=lambda x: [int(part) for part in x["ip"].split(".") if part.isdigit()])
        return active_devices
