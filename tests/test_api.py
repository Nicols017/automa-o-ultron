"""
Testes de Integração da API FastAPI e Dashboard - Ultron Lab Automation
"""

import os
import sys

# Forçar UTF-8
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Adiciona raiz do projeto ao sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_dashboard_endpoint():
    print("\n--- [1/6] Testando GET / e GET /dashboard (HTML) ---")
    res = client.get("/")
    assert res.status_code == 200
    assert "ULTRON" in res.text
    assert "Dispositivos em Bancada" in res.text
    print("✅ Dashboard HTML servido com sucesso!")

    res_dash = client.get("/dashboard")
    assert res_dash.status_code == 200
    print("✅ Dashboard HTML servido com sucesso!")

def test_info_and_infra_endpoints():
    print("\n--- [2/6] Testando GET /api/v1/info e GET /api/v1/infra/status ---")
    res_info = client.get("/api/v1/info")
    assert res_info.status_code == 200
    data_info = res_info.json()
    assert data_info["agent"] == "Ultron"

    res_infra = client.get("/api/v1/infra/status")
    assert res_infra.status_code == 200
    data_infra = res_infra.json()
    assert "ultron" in data_infra
    assert "mdt_server" in data_infra
    assert "backup_storage" in data_infra
    print(f"✅ Status de Infraestrutura OK: {data_infra}")

def test_clients_endpoints():
    print("\n--- [3/6] Testando GET /api/v1/clients e /api/v1/clients/{id} ---")
    res = client.get("/api/v1/clients")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] > 0
    print(f"✅ Total de clientes retornados: {data['total']}")

    res_wg = client.get("/api/v1/clients/white_group")
    assert res_wg.status_code == 200
    wg = res_wg.json()
    assert wg["cliente_id"] == "white_group"
    print(f"✅ Perfil white_group obtido com sucesso: {wg.get('nome_exibicao')}")

def test_reports_endpoints():
    print("\n--- [4/6] Testando GET /api/v1/reports/list ---")
    res = client.get("/api/v1/reports/list")
    assert res.status_code == 200
    data = res.json()
    print(f"✅ Laudos encontrados: {data['total']}")
    if data["total"] > 0:
        first_report = data["reports"][0]["filename"]
        dl_res = client.get(f"/api/v1/reports/download/{first_report}")
        assert dl_res.status_code == 200
        assert dl_res.headers["content-type"] == "application/pdf"
        print(f"✅ Download de laudo verificado: {first_report} ({len(dl_res.content)} bytes)")

def test_mdt_webhook():
    print("\n--- [5/6] Testando POST /api/v1/mdt/completed ---")
    payload = {
        "serial": "TEST-SRV-999",
        "ip": "192.168.57.199",
        "mac": "00:11:22:33:44:55",
        "computer_name": "BENCH-PC-99",
        "status": "SUCCESS",
        "client_id": "cliente_padrao",
        "auto_run": False
    }
    res = client.post("/api/v1/mdt/completed", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["serial"] == "TEST-SRV-999"
    print(f"✅ Webhook MDT OK: {data}")

def test_bench_endpoints():
    print("\n--- [6/6] Testando POST /api/v1/bench/run (Async Queued) ---")
    payload = {
        "ip": "192.168.57.250",
        "client_id": "cliente_padrao",
        "tech_user_id": "nicolas",
        "skip_burnin": True
    }
    res = client.post("/api/v1/bench/run?async_mode=true", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "queued"
    print(f"✅ Disparo de pipeline assíncrono OK: {data}")

def test_bootstrap_endpoint():
    print("\n--- Testando GET /bootstrap.ps1 ---")
    res = client.get("/bootstrap.ps1")
    assert res.status_code == 200
    assert "Bootstrap Universal" in res.text
    print(f"✅ Script /bootstrap.ps1 servido com sucesso ({len(res.text)} caracteres)")

def test_websocket_stream_endpoint():
    print("\n--- Testando WebSocket /ws/pipeline/{session_id} ---")
    with client.websocket_connect("/ws/pipeline/test_session_123") as ws:
        data = ws.receive_json()
        assert data["type"] == "connected"
        assert data["session_id"] == "test_session_123"
        print(f"✅ WebSocket conectado e handshake recebido: {data}")

def test_quick_actions():
    print("\n--- Testando Endpoints de Ações Rápidas de Bancada ---")
    
    # 1. Backup
    res_b = client.post("/api/v1/bench/action/backup", json={
        "ip": "192.168.254.254",
        "client_name": "TEST_CLIENT",
        "ticket_number": "99999",
        "source_drive": "C:"
    })
    assert res_b.status_code == 200
    assert "backup_server" in res_b.json()
    print("✅ Endpoint /action/backup OK")

    # 2. Power (Restart/Shutdown)
    res_p = client.post("/api/v1/bench/action/power", json={
        "ip": "192.168.254.254",
        "action": "restart"
    })
    assert res_p.status_code == 200
    assert res_p.json()["action"] == "restart"
    print("✅ Endpoint /action/power OK")

    # 3. Rename
    res_r = client.post("/api/v1/bench/action/rename", json={
        "ip": "192.168.254.254",
        "new_name": "TEST-PC-01",
        "restart": False
    })
    assert res_r.status_code == 200
    assert res_r.json()["new_name"] == "TEST-PC-01"
    print("✅ Endpoint /action/rename OK")

    # 4. Activate
    res_a = client.post("/api/v1/bench/action/activate", json={
        "ip": "192.168.254.254"
    })
    assert res_a.status_code == 200
    print("✅ Endpoint /action/activate OK")

    # 5. Install Software
    res_i = client.post("/api/v1/bench/action/install-software", json={
        "ip": "192.168.254.254",
        "packages": ["7zip.7zip"]
    })
    assert res_i.status_code == 200
    print("✅ Endpoint /action/install-software OK")

    # 6. Domain Join (com credenciais e rede dinâmicas)
    res_d = client.post("/api/v1/bench/action/domain-join", json={
        "ip": "192.168.254.254",
        "domain_name": "penserede.local",
        "dns_server": "192.168.1.10",
        "domain_user": "admin.suporte",
        "domain_password": "TempPassword123!"
    })
    assert res_d.status_code == 200
    assert res_d.json()["domain"] == "penserede.local"
    print("✅ Endpoint /action/domain-join OK")

def test_trueconf_endpoint():
    print("\n--- Testando Endpoint TrueConf Bot & ChatOps Bi-Direcional ---")
    
    # 1. Teste de envio de notificação direta
    res_test = client.post("/api/v1/trueconf/test", json={
        "user_id": "nicolas",
        "message": "Teste automatizado da suíte de testes"
    })
    assert res_test.status_code == 200
    data_t = res_test.json()
    assert "server_url" in data_t
    print(f"✅ TrueConf Test Notification OK: Destinatário @{data_t['user_id']}")

    # 2. ChatOps: Comando /ajuda
    res_help = client.post("/api/v1/trueconf/webhook", json={
        "user_id": "nicolas",
        "body": "/ajuda"
    })
    assert res_help.status_code == 200
    reply_help = res_help.json()["reply"]
    assert "Ultron ChatOps" in reply_help
    print("✅ ChatOps /ajuda OK: Menu de comandos retornado com sucesso")

    # 3. ChatOps: Comando /bancada
    res_bench = client.post("/api/v1/trueconf/webhook", json={
        "user_id": "nicolas",
        "body": "/bancada"
    })
    assert res_bench.status_code == 200
    assert "Bancada Ultron" in res_bench.json()["reply"] or "Status da Bancada" in res_bench.json()["reply"]
    print("✅ ChatOps /bancada OK: Varredura de bancada retornada")

    # 4. ChatOps: Comando /clientes
    res_cli = client.post("/api/v1/trueconf/webhook", json={
        "user_id": "nicolas",
        "body": "/clientes"
    })
    assert res_cli.status_code == 200
    assert "Perfis de Clientes" in res_cli.json()["reply"]
    print("✅ ChatOps /clientes OK: Lista de clientes formatada")

    # 5. ChatOps: Comando /chamados
    res_cham = client.post("/api/v1/trueconf/webhook", json={
        "user_id": "nicolas",
        "body": "/chamados"
    })
    assert res_cham.status_code == 200
    assert "Chamados" in res_cham.json()["reply"]
    print("✅ ChatOps /chamados OK: Chamados Milvus formatados")

    # 6. ChatOps: Comando /erro 0x80070005
    res_err = client.post("/api/v1/trueconf/webhook", json={
        "user_id": "nicolas",
        "body": "/erro 0x80070005"
    })
    assert res_err.status_code == 200
    assert "0X80070005" in res_err.json()["reply"]
    print("✅ ChatOps /erro OK: Decodificador de erro com script PowerShell")

    # 7. ChatOps: Comando /cve winrar
    res_cve = client.post("/api/v1/trueconf/webhook", json={
        "user_id": "nicolas",
        "body": "/cve winrar"
    })
    assert res_cve.status_code == 200
    assert "winrar" in res_cve.json()["reply"].lower()
    print("✅ ChatOps /cve OK: Vulnerabilidades consultadas")

    # 8. ChatOps: Comando /clima
    res_clim = client.post("/api/v1/trueconf/webhook", json={
        "user_id": "nicolas",
        "body": "/clima"
    })
    assert res_clim.status_code == 200
    assert "Telemetria Térmica" in res_clim.json()["reply"]
    print("✅ ChatOps /clima OK: Temperatura e headroom térmico")

    # 9. ChatOps: Disparar esteira com /preparar
    res_prep = client.post("/api/v1/trueconf/webhook", json={
        "user_id": "nicolas",
        "body": "/preparar 192.168.57.25 nova_via"
    })
    assert res_prep.status_code == 200
    assert "Esteira Iniciada" in res_prep.json()["reply"]
    print("✅ ChatOps /preparar OK: Disparo assíncrono iniciado")

    # 10. ChatOps: Diálogo Interativo (MDT Hook + Resposta numérica "1")
    from trueconf.bot import TrueConfBot
    tc_bot = TrueConfBot(server_url="http://trueconf.penserede.local", api_token="")
    prompt_mdt = tc_bot.chatops.register_mdt_arrival(user_id="nicolas", ip="192.168.57.99", serial="BRG999TEST")
    assert "Nova Máquina Pronta no MDT" in prompt_mdt
    print("✅ ChatOps MDT Hook OK: Menu interativo gerado")

    # Técnico responde apenas "1" no chat
    res_choice = client.post("/api/v1/trueconf/webhook", json={
        "user_id": "nicolas",
        "body": "1"
    })
    assert res_choice.status_code == 200
    assert "Esteira Iniciada" in res_choice.json()["reply"]
    print("✅ ChatOps Diálogo Numérico OK: Resposta '1' iniciou esteira para a máquina do MDT")

def test_milvus_endpoints():
    print("\n--- Testando Integração e Central de Tokens Milvus ---")
    
    # 1. Configuração do Milvus
    res_cfg = client.get("/api/v1/milvus/config")
    assert res_cfg.status_code == 200
    cfg = res_cfg.json()
    assert "dashboard_url" in cfg
    print(f"✅ Configuração Milvus OK: Host {cfg['dashboard_url']} (Tem Token: {cfg['has_token']})")

    # 2. Salvar configuração Milvus
    res_save = client.post("/api/v1/milvus/config", json={
        "dashboard_url": "http://192.168.57.7",
        "api_token": "TEST_TOKEN_MASTER_123",
        "demo_mode": True
    })
    assert res_save.status_code == 200
    assert res_save.json()["success"] is True
    print("✅ POST /api/v1/milvus/config OK")

    # 3. Teste de conexão Milvus
    res_test = client.post("/api/v1/milvus/test", json={
        "custom_url": "http://192.168.57.7",
        "custom_token": "TEST_TOKEN_MASTER_123"
    })
    assert res_test.status_code == 200
    test_data = res_test.json()
    assert "endpoints" in test_data
    print(f"✅ POST /api/v1/milvus/test OK: Latência {test_data['latency_ms']}ms")

    # 4. Listar e atualizar tokens de clientes (clients.yaml)
    res_ct = client.get("/api/v1/milvus/client-tokens")
    assert res_ct.status_code == 200
    ct_data = res_ct.json()
    assert ct_data["total"] > 0
    print(f"✅ GET /api/v1/milvus/client-tokens OK: {ct_data['total']} clientes mapeados")

    res_up = client.post("/api/v1/milvus/client-tokens", json={
        "client_id": "nova_via",
        "milvus_token": "TOKEN_TEST_NOVA_VIA_UPDATED"
    })
    assert res_up.status_code == 200
    assert res_up.json()["success"] is True
    print("✅ POST /api/v1/milvus/client-tokens OK")

    # 5. Chamados em aberto
    res_t = client.get("/api/v1/milvus/tickets")
    assert res_t.status_code == 200
    data_t = res_t.json()
    assert "tickets" in data_t
    print(f"✅ Chamados retornados do Milvus: {data_t['total']} (Milvus Online: {data_t['milvus_online']})")

    # 6. Sincronização forçada
    res_s = client.post("/api/v1/milvus/sync")
    assert res_s.status_code == 200
    data_s = res_s.json()
    assert data_s["success"] is True
    print(f"✅ Sincronização Milvus OK: {data_s['message']}")

    # 7. Sincronização e Listagem de MSI em Cache
    res_sync_msi = client.post("/api/v1/milvus/agent/sync-all")
    assert res_sync_msi.status_code == 200
    assert "total_clients_queued" in res_sync_msi.json()
    print(f"✅ POST /api/v1/milvus/agent/sync-all OK: {res_sync_msi.json()['total_clients_queued']} clientes enfileirados")

    res_cached = client.get("/api/v1/milvus/agent/cached")
    assert res_cached.status_code == 200
    assert "agents" in res_cached.json()
    print(f"✅ GET /api/v1/milvus/agent/cached OK: {res_cached.json()['total']} MSIs em cache")

def test_public_tools_suite():

    print("\n--- Testando Suíte de APIs Públicas Gratuitas (public-apis) ---")

    # 1. Telemetria WAN
    res_wan = client.get("/api/v1/telemetry/wan")
    assert res_wan.status_code == 200
    wan = res_wan.json()
    assert "wan_ip" in wan
    print(f"✅ WAN Telemetry OK: IP {wan['wan_ip']} - Provedor: {wan.get('isp')}")

    # 2. Clima e Térmica
    res_therm = client.get("/api/v1/telemetry/thermal")
    assert res_therm.status_code == 200
    therm = res_therm.json()
    assert "temperature_c" in therm
    assert "thermal_headroom_rating" in therm
    print(f"✅ Thermal Telemetry OK: {therm['temperature_c']}°C - {therm['thermal_headroom_rating']}")

    # 3. Scanner de CVEs
    res_cve = client.get("/api/v1/tools/cve/search?package=winrar")
    assert res_cve.status_code == 200
    cve = res_cve.json()
    assert cve["package"] == "winrar"
    print(f"✅ CVE Security Search OK: {cve['total_found']} vulnerabilidades encontradas")

    # 4. Catálogo CISA KEV
    res_kev = client.get("/api/v1/tools/cve/kev?limit=4")
    assert res_kev.status_code == 200
    kev = res_kev.json()
    assert "recent_vulnerabilities" in kev
    print(f"✅ CISA KEV Threat Feed OK: {len(kev['recent_vulnerabilities'])} CVEs ativamente explorados")

    # 5. Decodificador de Erros do Windows
    res_err = client.get("/api/v1/tools/windows-error/lookup?code=0x80070005")
    assert res_err.status_code == 200
    err = res_err.json()
    assert err["code"] == "0X80070005"
    assert "ERROR_ACCESS_DENIED" in err["name"]
    print(f"✅ Windows Error Lookup OK: {err['code']} -> {err['name']}")

    # 6. Inspetor de DNS e AD
    res_dns = client.get("/api/v1/tools/dns/inspect?domain=penserede.local")
    assert res_dns.status_code == 200
    dns = res_dns.json()
    assert dns["domain"] == "penserede.local"
    print(f"✅ DNS / AD Domain Inspector OK: {dns['domain']} -> {dns['status']}")

    # 7. Sincronismo NTP
    res_ntp = client.get("/api/v1/tools/ntp/check")
    assert res_ntp.status_code == 200
    ntp = res_ntp.json()
    assert "drift_seconds" in ntp
    print(f"✅ NTP Clock Drift OK: {ntp['drift_seconds']}s ({ntp['status']})")

    # 8. Versões das Ferramentas no GitHub
    res_ver = client.get("/api/v1/tools/versions/check")
    assert res_ver.status_code == 200
    assert "tools" in res_ver.json()
    print(f"✅ GitHub Tools Version Watcher OK: {len(res_ver.json()['tools'])} ferramentas")

    # 9. Tech Quote
    res_q = client.get("/api/v1/tools/quote")
    assert res_q.status_code == 200
    assert "quote" in res_q.json()
    print(f"✅ Tech Quote OK: \"{res_q.json()['quote'][:45]}...\"")

    # 10. Resolução de Fabricante OEM por MAC
    res_mac = client.get("/api/v1/tools/mac/resolve?mac=00:14:22:12:34:56")
    assert res_mac.status_code == 200
    assert res_mac.json()["vendor"] == "Dell Inc."
    print("✅ MAC OEM Vendor Resolver OK: Dell Inc.")

    # 11. Gerador de QR Code
    res_qr = client.get("/api/v1/tools/qr?data=http://192.168.57.43:8000/dashboard&size=200")
    assert res_qr.status_code == 200
    assert "qr_url" in res_qr.json()
    print("✅ QR Code Mobile Generator OK")

if __name__ == "__main__":
    print("🚀 INICIANDO TESTES DE API, MILVUS & PUBLIC TOOLS DO ULTRON...\n")
    test_dashboard_endpoint()
    test_bootstrap_endpoint()
    test_info_and_infra_endpoints()
    test_clients_endpoints()
    test_reports_endpoints()
    test_mdt_webhook()
    test_bench_endpoints()
    test_websocket_stream_endpoint()
    test_trueconf_endpoint()
    test_milvus_endpoints()
    test_public_tools_suite()
    print("\n🎉 TODOS OS TESTES DA API, TRUECONF, MILVUS & PUBLIC TOOLS PASSARAM COM SUCESSO!")
