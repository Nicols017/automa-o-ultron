"""
Script de Validação e Testes Automatizados dos Módulos do Ultron
"""

import os
import sys
import json

# Forçar UTF-8
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Adiciona raiz do projeto ao sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.profile_manager import ProfileManager
from core.network_scanner import NetworkScanner
from core.winrm_executor import WinRMExecutor
from reports.report_generator import ReportGenerator

def test_profile_manager():
    print("--- [1/4] Testando ProfileManager ---")
    pm = ProfileManager()
    clients = pm.list_clients()
    print(f"✅ Total de clientes carregados: {len(clients)}")
    assert len(clients) > 0, "Nenhum cliente carregado"

    # Testa perfil específico (white_group)
    wg_profile = pm.get_client_profile("white_group")
    print(f"✅ Perfil white_group: {wg_profile.get('nome_exibicao')} - Softwares Winget: {len(wg_profile.get('softwares', {}).get('winget', []))}")
    assert "Microsoft.VisualStudioCode" in wg_profile.get("softwares", {}).get("winget", [])

    # Testa fallback para cliente padrão
    std_profile = pm.get_client_profile("agilis")
    print(f"✅ Perfil agilis (com herança padrão): {std_profile.get('nome_exibicao')}")
    assert std_profile.get("cliente_id") == "agilis"
    print("✨ ProfileManager OK!\n")

def test_report_generator():
    print("--- [2/4] Testando ReportGenerator (PDF) ---")
    rg = ReportGenerator()
    dummy_telemetry = {
        "computer_name": "LAB-TEST-PC01",
        "serial_number": "BRG8472910X",
        "cpu": "Intel Core i7-12700 @ 2.10GHz (12 Cores)",
        "ram_gb": 32.0,
        "disks": [
            {
                "model": "Samsung SSD 980 PRO 1TB",
                "type": "NVMe SSD",
                "size_gb": 1000.0,
                "health": "Healthy",
                "operational": "OK"
            },
            {
                "model": "Kingston A400 480GB",
                "type": "SATA SSD",
                "size_gb": 480.0,
                "health": "Healthy",
                "operational": "OK"
            }
        ],
        "bsod_dumps": [],
        "device_errors": []
    }
    
    ai_diagnosis = (
        "1. 🚨 Problemas Identificados: Nenhum erro de hardware ou driver detectado.\n\n"
        "2. 🔬 Causa Raiz: Sistema operando em temperatura ideal e integridade SMART 100%.\n\n"
        "3. 🛠️ Ações de Reparo: Nenhuma ação necessária, pronto para uso.\n\n"
        "4. 🩺 Veredito da Máquina: APROVADA para entrega ao cliente."
    )

    pdf_path = rg.generate_report(
        telemetry_data=dummy_telemetry,
        client_name="NOVA VIA PEÇAS E ACESSORIOS",
        ai_diagnosis=ai_diagnosis,
        burnin_status="Aprovado (0 erros de estresse)"
    )
    print(f"✅ PDF de teste gerado com sucesso em: {pdf_path}")
    assert os.path.exists(pdf_path), "PDF não foi gerado no disco"
    assert os.path.getsize(pdf_path) > 1000, "Arquivo PDF gerado está vazio ou corrompido"
    print("✨ ReportGenerator OK!\n")

def test_network_scanner():
    print("--- [3/4] Testando NetworkScanner ---")
    scanner = NetworkScanner()
    print(f"✅ Subrede configurada: {scanner.subnet}")
    # Testa checagem pontual (localhost)
    local_check = scanner._check_host("127.0.0.1", timeout=0.1)
    print(f"✅ Checagem de host local executada com sucesso (Resultado: {local_check is not None})")
    print("✨ NetworkScanner OK!\n")

def test_winrm_executor():
    print("--- [4/4] Testando WinRMExecutor ---")
    executor = WinRMExecutor()
    print(f"✅ Usuário padrão: {executor.default_user} - Porta: {executor.port}")
    # Testa host inexistente (deve retornar success: False sem crashar)
    offline_res = executor.run_powershell_code("192.168.254.254", "Write-Host 'Test'")
    print(f"✅ Tratamento de host offline verificado: success={offline_res['success']} ({offline_res['stderr']})")
    assert not offline_res["success"], "Host offline deveria retornar success=False"
    print("✨ WinRMExecutor OK!\n")

if __name__ == "__main__":
    print("🚀 INICIANDO TESTES DO ULTRON LAB AUTOMATION...\n")
    test_profile_manager()
    test_report_generator()
    test_network_scanner()
    test_winrm_executor()
    print("🎉 TODOS OS TESTES PASSARAM COM SUCESSO!")
