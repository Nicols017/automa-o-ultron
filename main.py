"""
Ultron Automation Server - Pense Rede Lab
Ponto de entrada da API FastAPI do Ultron, com automações e integração TrueConf.
"""

import os
import sys
import time
import glob
import socket
import threading
import uuid
import requests
from typing import Optional, Dict, Any, List

# Ensure UTF-8 output encoding on Windows
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from fastapi import FastAPI, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field
import uvicorn

from core.profile_manager import ProfileManager
from core.network_scanner import NetworkScanner
from core.orchestrator import LabOrchestrator
from core.package_manager import UnifiedPackageManager
from chatops.bot import TrueConfBot
from core.agent_builder import agent_builder, AgentPackageError
from core.agent_runtime import agent_task_mgr
from core.agent_auth import AgentAuthenticator, require_operator
from core.trueconf_webhook_auth import require_trueconf_webhook
from core.macrium_remote import macrium_jobs, MacriumBridgeError
from core.preformat_files_backup import file_backup_jobs, FileBackupError

app = FastAPI(
    title="Ultron Lab Automation Server",
    description="Servidor de Automação de Bancada e Laboratório - Pense Rede",
    version="1.4.0"
)

# Diretorio base para scripts, laudos e binarios utilizados pelas automacoes.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Instancia componentes principais
profile_mgr = ProfileManager()
network_scanner = NetworkScanner()
orchestrator = LabOrchestrator()
package_mgr = UnifiedPackageManager(winrm_executor=orchestrator.winrm)
settings = profile_mgr.get_settings()

tc_cfg = settings.get("trueconf", {})
bot = TrueConfBot(
    server_url=tc_cfg.get("server_url", "https://trueconf.penserede.com.br"),
    bot_username=tc_cfg.get("bot_username", "ultron"),
    bot_password=tc_cfg.get("bot_password", ""),
    api_token=tc_cfg.get("api_token", tc_cfg.get("bot_token", "")),
    default_tech_user_id=tc_cfg.get("default_tech_user_id", "nicolas.silva")
)

@app.on_event("startup")
async def startup_event():
    from core.task_registry import task_registry
    if task_registry.acquire_runtime():
        task_registry.recover_after_restart()
    # Windows packages are built explicitly in CI, never on server startup.

    if bot.bot_password or bot.api_token:
        bot.start_polling(interval_sec=3)

@app.on_event("shutdown")
async def shutdown_event():
    bot.stop_polling()
    # Keep the runtime lease until process exit: daemon workers may still be active.

# --- Schemas ---

class MDTNotification(BaseModel):
    serial: str = Field(..., description="Número de série ou Service Tag")
    ip: str = Field(..., description="Endereço IP atribuído à máquina")
    mac: Optional[str] = Field("", description="Endereço MAC da placa de rede")
    computer_name: Optional[str] = Field("DESKTOP", description="Nome do computador")
    status: Optional[str] = Field("SUCCESS", description="Status da Task Sequence do MDT")
    client_id: Optional[str] = Field(None, description="ID do cliente se pré-definido")
    auto_run: Optional[bool] = Field(False, description="Se True, inicia esteira imediatamente")
    tech_user_id: Optional[str] = Field(None, description="ID do técnico no TrueConf a ser notificado")

class DomainJoinRequest(BaseModel):
    ip: str = Field(..., description="Endereço IP da máquina alvo")
    domain_name: str = Field(..., description="Nome do domínio (ex: cliente.local)")
    dns_server: Optional[str] = Field("", description="IP do servidor DNS / Controlador de Domínio")
    static_ip: Optional[str] = Field("", description="IP Estático na placa de rede da empresa (opcional)")
    subnet_mask: Optional[str] = Field("255.255.255.0", description="Máscara de subrede (opcional)")
    gateway: Optional[str] = Field("", description="Gateway padrão da empresa (opcional)")
    domain_user: str = Field(..., description="Usuário administrador do AD")
    domain_password: str = Field(..., description="Senha do usuário do AD")
    ou_path: Optional[str] = Field("", description="Unidade Organizacional (OU) opcional")

class RunPipelineRequest(BaseModel):
    ip: str = Field(..., description="Endereço IP da máquina na bancada")
    client_id: str = Field("cliente_padrao", description="ID do perfil de cliente a aplicar")
    tech_user_id: Optional[str] = Field("nicolas.silva", description="Usuário do TrueConf para notificações privadas")
    technician_name: Optional[str] = Field("Nicolas Silva", description="Nome do técnico responsável")
    skip_burnin: Optional[bool] = Field(False, description="Se True, pula o teste de estresse térmico")
    custom_packages: Optional[List[str]] = Field(default_factory=list, description="Softwares adicionais selecionados via Winget")
    domain_config: Optional[DomainJoinRequest] = Field(None, description="Configurações dinâmicas de domínio e rede")

class DiagnosticRequest(BaseModel):
    ip: str = Field(..., description="Endereço IP da máquina alvo na bancada")

class BackupRequest(BaseModel):
    ip: str = Field(..., description="Endereço IP da máquina alvo")
    client_name: str = Field("CLIENTE", description="Nome do cliente para a pasta de backup")
    ticket_number: Optional[str] = Field("", description="Número do chamado / ticket no Milvus")
    source_drive: Optional[str] = Field("C:", description="Unidade de origem para cópia de dados")

class MacriumVerifyRequest(BaseModel):
    image_path: str = Field(..., min_length=5, max_length=1024, description="Caminho completo da imagem .mrimg na estação verificadora autorizada")

class PowerActionRequest(BaseModel):
    ip: str = Field(..., description="Endereço IP da máquina alvo")
    action: str = Field("restart", description="'restart' para reiniciar ou 'shutdown' para desligar")

class RenameComputerRequest(BaseModel):
    ip: str = Field(..., description="Endereço IP da máquina alvo")
    new_name: str = Field(..., description="Novo nome (hostname) do computador")
    restart: Optional[bool] = Field(True, description="Se True, reinicia imediatamente para aplicar o novo nome")

class ActivationRequest(BaseModel):
    ip: str = Field(..., description="Endereço IP da máquina alvo")

class PackageInstallRequest(BaseModel):
    ip: str = Field(..., description="IP da máquina alvo")
    packages: List[str] = Field(..., description="Lista de IDs ou nomes de softwares a instalar")
    interactive: bool = Field(True, description="Se True, exibe aviso e tenta modo visível com termos aceitos")

class PackageUpgradeRequest(BaseModel):
    ip: str = Field(..., description="IP da máquina alvo")

class PackageBackupRequest(BaseModel):
    ip: str = Field(..., description="IP da máquina alvo")
    identifier: Optional[str] = Field(None, description="Identificador amigável ou serial")

class PackageRestoreRequest(BaseModel):
    ip: str = Field(..., description="IP da máquina alvo")
    bundle_name: Optional[str] = Field(None, description="Nome do arquivo .json do bundle ou latest")

class InstallSoftwareRequest(BaseModel):
    ip: str = Field(..., description="Endereço IP da máquina alvo")
    packages: List[str] = Field(..., description="Lista de IDs de pacotes do Winget a instalar")

class MilvusConfigRequest(BaseModel):
    dashboard_url: str = Field(..., description="URL base da Dashboard Milvus (ex: http://192.168.57.7)")
    api_token: Optional[str] = Field("", description="Token master de autenticação na API do Milvus")
    demo_mode: Optional[bool] = Field(False, description="Ativa modo demonstração/simulação para bancada offline")

class MilvusTestRequest(BaseModel):
    custom_url: Optional[str] = Field(None, description="URL customizada para teste temporário")
    custom_token: Optional[str] = Field(None, description="Token customizado para teste temporário")

class ClientTokenUpdateRequest(BaseModel):
    client_id: str = Field(..., description="Identificador do cliente (ex: nova_via, superior_transportes)")
    milvus_token: str = Field(..., description="Token de instalação do agente Milvus para este cliente")

class TrueConfTestRequest(BaseModel):
    user_id: Optional[str] = Field("nicolas", description="ID do usuário técnico no TrueConf para envio da DM")
    message: Optional[str] = Field("🔔 Teste de Notificação Direta do Ultron Server", description="Mensagem de teste a ser enviada no privado")

class TrueConfWebhookPayload(BaseModel):
    user_id: Optional[str] = None
    sender: Optional[str] = None
    author: Optional[str] = None
    body: Optional[str] = None
    text: Optional[str] = None
    message: Optional[str] = None
    event: Optional[Dict[str, Any]] = None

class AgentRegistration(BaseModel):
    serial: str = Field(..., description="Número de série ou Service Tag")
    ip: str = Field(..., description="Endereço IP da máquina")
    computer_name: Optional[str] = Field("HOST", description="Nome do computador")
    manufacturer: Optional[str] = Field("Generic", description="Fabricante")
    model: Optional[str] = Field("Generic", description="Modelo")
    cpu: Optional[str] = Field("", description="Processador")
    ram_gb: Optional[float] = Field(0.0, description="Memória RAM em GB")
    mac: Optional[str] = Field("", description="MAC Address")
    client_id: Optional[str] = Field("cliente_padrao", description="ID do cliente")
    disks: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="Lista de discos físicos")
    anydesk_id: Optional[str] = Field("", description="AnyDesk ID detectado")
    logged_in_user: Optional[str] = Field("", description="Usuário logado/ativo na máquina no momento")
    status: Optional[str] = Field("READY_FOR_PIPELINE", description="Status do Agente")
    winrm_ready: Optional[bool] = Field(True, description="Se WinRM foi desbloqueado")
    agent_version: Optional[str] = Field("2.0.0", description="Versão do UltronAgent.exe")
    # Credenciais WinRM não devem ser enviadas ou provisionadas neste webhook.
    auth_user: Optional[str] = Field(None, description="Legado: ignorado pelo servidor")
    auth_pass: Optional[str] = Field(None, description="Legado: ignorado pelo servidor")

class AgentHeartbeat(BaseModel):
    ip: str = Field(..., description="Endereço IP da máquina")
    hostname: Optional[str] = Field("", description="Nome da máquina")
    serial: Optional[str] = Field("", description="Serial da máquina")
    anydesk_id: Optional[str] = Field("", description="AnyDesk ID")
    logged_in_user: Optional[str] = Field("", description="Usuário logado na máquina")
    agent_version: Optional[str] = Field("2.0.0", description="Versão do agente")
    status: Optional[str] = Field("IDLE", description="Status atual")

class AgentTaskResult(BaseModel):
    task_id: str = Field(..., description="ID da tarefa executada")
    exit_code: int = Field(0, description="Código de saída do processo")
    stdout: Optional[str] = Field("", description="Saída padrão")
    stderr: Optional[str] = Field("", description="Saída de erro")
    status: Optional[str] = Field("SUCCESS", description="Status da execução")

class AgentAlert(BaseModel):
    type: str = Field(..., description="Tipo de alerta: BSOD, DISK_ALERT, TEMPERATURE")
    ip: str = Field(..., description="Endereço IP")
    serial: Optional[str] = Field("", description="Serial number")
    hostname: Optional[str] = Field("", description="Hostname")
    details: str = Field(..., description="Detalhes técnicos do alerta")

# O painel web foi removido: a interface do tecnico e o TrueConf.
@app.get("/")
def service_status():
    """Resposta minima de saude da API, sem frontend ou dashboard."""
    return {"service": "ultron", "status": "online", "interface": "trueconf"}

@app.get("/download/UltronAgent.exe")
@app.get("/download/UltronAgent.exe.")
@app.get("/downloads/UltronAgent.exe")
@app.get("/downloads/UltronAgent.exe.")
@app.get("/download/UltronUnlocker.exe")
@app.get("/UltronAgent.exe")
@app.get("/UltronUnlocker.exe")
def download_ultron_agent():
    """Entrega o executável nativo do Agente Ultron garantindo que esteja sempre na compilação mais recente"""
    if os.environ.get("ULTRON_AGENT_DOWNLOAD_ENABLED") != "true":
        raise HTTPException(status_code=503, detail="Distribuicao suspensa ate homologacao do pacote Windows revisado.")
    try:
        bin_info = agent_builder.get_distributable_agent_binary()
    except AgentPackageError:
        raise HTTPException(status_code=503, detail="Pacote Windows ausente ou nao validado.")

    exe_path = bin_info["file_path"]
    filename = bin_info["filename"]
    if os.path.exists(exe_path):
        resp = FileResponse(
            exe_path,
            media_type="application/octet-stream",
            filename=filename
        )
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        return resp
    raise HTTPException(status_code=404, detail="Executável UltronAgent.exe não encontrado")

@app.get("/bootstrap.ps1", response_class=PlainTextResponse)
def get_bootstrap_script():
    """Entrega o script de bootstrap universal para execução via One-Liner PowerShell em qualquer máquina"""
    script_path = os.path.join(BASE_DIR, "scripts", "powershell", "Bootstrap-Ultron.ps1")
    if os.path.exists(script_path):
        with open(script_path, "r", encoding="utf-8") as f:
            return PlainTextResponse(content=f.read(), media_type="text/plain; charset=utf-8")
    raise HTTPException(status_code=404, detail="Script Bootstrap-Ultron.ps1 não encontrado")

@app.get("/api/v1/agent/version")
def get_agent_version():
    """Informa a versão atual do UltronAgent para o auto-updater OTA"""
    ver = agent_builder.get_source_version()
    return {
        "version": ver,
        "download_url": "/download/UltronAgent.exe",
        "release_notes": f"UltronAgent {ver}: instalacao explicita; WinRM nativo separado; sem OTA automatico."
    }

@app.get("/api/v1/agent/tasks/{target_id}")
def get_agent_pending_tasks(target_id: str, request: Request):
    """Entrega tarefas somente ao agente autenticado para este serial."""
    AgentAuthenticator().authenticate(request, expected_agent=target_id)
    task = agent_task_mgr.get_pending_task(target_id)
    if task:
        return task
    return {"status": "no_tasks"}

@app.post("/api/v1/agent/tasks/{task_id}/result")
def submit_agent_task_result(task_id: str, result: AgentTaskResult, request: Request):
    """Aceita resultados apenas do agente dono da tarefa."""
    agent_id = AgentAuthenticator().authenticate(request)
    if not agent_task_mgr.agent_can_access_task(agent_id, task_id):
        raise HTTPException(status_code=403, detail="Agente não autorizado para esta tarefa.")
    try:
        agent_task_mgr.store_result(task_id, result.model_dump())
    except KeyError:
        raise HTTPException(status_code=404, detail="Tarefa desconhecida.")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"success": True, "message": f"Resultado da tarefa {task_id} armazenado com sucesso"}

@app.post("/api/v1/agent/alert")
def receive_agent_alert(alert: AgentAlert, request: Request):
    """Recebe alertas autenticados e encaminha ao TrueConf."""
    AgentAuthenticator().authenticate(request, expected_agent=alert.serial)
    tc_user = settings.get("trueconf", {}).get("default_tech_user_id", "nicolas.silva")
    
    icon = "🚨" if alert.type == "BSOD" else "🔥"
    msg = (
        f"{icon} ALERTA PROATIVO DE HARDWARE — ULTRON AGENT\n\n"
        f"📍 Máquina: {alert.hostname} ({alert.ip})\n"
        f"🏷️ Serial: {alert.serial}\n"
        f"⚠️ Tipo de Ocorrência: {alert.type}\n"
        f"📋 Detalhes: {alert.details}\n\n"
        f"💡 Sugestão: Inspecione os discos e a memória RAM com 'diagnóstico no {alert.ip}'."
    )
    bot.send_direct_message(tc_user, msg)
    return {"success": True, "message": "Alerta processado e notificado com sucesso"}

@app.post("/api/v1/agent/cleanup/{target_id}")
def enqueue_agent_cleanup(target_id: str, request: Request):
    """Bloqueado até existir autorização de operador e fluxo auditável."""
    require_operator(request)
    raise HTTPException(status_code=423, detail="Limpeza remota desabilitada até homologação.")

@app.post("/api/v1/agent/register")
def agent_register(data: AgentRegistration, background_tasks: BackgroundTasks, request: Request):
    """Registro somente de dispositivo pré-provisionado, sobre HTTPS."""
    AgentAuthenticator().authenticate(request, expected_agent=data.serial)
    print(f"🤖 [ULTRON AGENT] Máquina registrada: {data.computer_name} ({data.ip}) - Serial: {data.serial} - RAM: {data.ram_gb} GB")
    agent_task_mgr.bind_identity(data.serial, data.ip)
    
    # O registro não aceita senhas WinRM transmitidas pelo agente.
    # Credenciais devem ser provisionadas por canal administrativo independente.
    if bot and bot.chatops:
        # Atualiza o cache local de dispositivos no ChatOps imediatamente
        new_dev = {
            "ip": data.ip,
            "hostname": data.computer_name,
            "mac": data.mac,
            "serial": data.serial,
            "vendor": f"{data.manufacturer} {data.model}".strip(),
            "anydesk_id": data.anydesk_id or "",
            "logged_in_user": data.logged_in_user or "",
            "winrm_ready": True,
            "bench_name": "Bancada Ultron",
            "last_seen": time.time()
        }
        # Substitui ou adiciona ao cache
        updated_cache = [d for d in bot.chatops._cached_devices if d.get("ip") != data.ip]
        updated_cache.insert(0, new_dev)
        bot.chatops._cached_devices = updated_cache
        bot.chatops._last_scan_time = time.time()

    # Formata Usuário Logado se presente
    user_badge = ""
    if bot and bot.chatops and data.logged_in_user:
        user_badge = bot.chatops._format_user_badge(data.logged_in_user)
    user_str = f"{user_badge}\n" if user_badge else (f"👤 Usuário: `{data.logged_in_user}`\n" if data.logged_in_user else "")

    # Formata AnyDesk se presente
    anydesk_str = f"🔑 AnyDesk ID: {data.anydesk_id} ([Abrir AnyDesk](anydesk:{data.anydesk_id}))\n" if data.anydesk_id else ""

    # Notifica o técnico no TrueConf com formatação limpa
    user_header = f" — MÁQUINA DE {data.logged_in_user.upper()}" if data.logged_in_user else ""
    msg = (
        f"💻 ULTRON AGENT CONECTADO{user_header}\n\n"
        f"📍 IP: {data.ip}\n"
        f"{user_str}"
        f"🏷️ Serial: `{data.serial}`\n"
        f"💻 Host: {data.computer_name} ({data.manufacturer} {data.model})\n"
        f"🧠 CPU: {data.cpu}\n"
        f"💾 RAM: {data.ram_gb} GB\n"
        f"{anydesk_str}"
        f"🛡️ Serviço: UltronService (SYSTEM) Ativo & Autônomo\n\n"
        f"💡 Ações Rápidas:\n"
        f"• \"diagnóstico no {data.ip}\"\n"
        f"• \"preparar {data.ip} para <cliente>\"\n"
        f"• \"ativar {data.ip}\""
    )
    tc_user = settings.get("trueconf", {}).get("default_tech_user_id", "nicolas.silva")
    bot.send_direct_message(tc_user, msg)
    
    return {
        "success": True,
        "message": "Máquina registrada e liberada com sucesso no Ultron Server (Zero-Prompt Ativo)",
        "ip": data.ip,
        "serial": data.serial
    }

@app.post("/api/v1/agent/heartbeat")
def agent_heartbeat(data: AgentHeartbeat, request: Request):
    """Heartbeat somente de agente autenticado."""
    AgentAuthenticator().authenticate(request, expected_agent=data.serial)
    if data.serial and data.ip:
        agent_task_mgr.bind_identity(data.serial, data.ip)
    # Atualiza cache do ChatOps se serial ou IP vier no heartbeat
    if bot and bot.chatops and data.ip:
        for dev in bot.chatops._cached_devices:
            if dev.get("ip") == data.ip:
                dev["last_seen"] = time.time()
                if data.anydesk_id:
                    dev["anydesk_id"] = data.anydesk_id
                if data.logged_in_user:
                    dev["logged_in_user"] = data.logged_in_user
                break

    return {"status": "ok", "server_time": time.time(), "ip": data.ip}


# --- Rotas da API ---

@app.get("/api/v1/info")
def read_root():
    return {
        "agent": "Ultron",
        "status": "online",
        "company": "Pense Rede",
        "lab": "Hardware & Bench Automation",
        "endpoints": {
            "clients": "/api/v1/clients",
            "scan": "/api/v1/bench/scan",
            "run": "/api/v1/bench/run",
            "diagnose": "/api/v1/bench/diagnose",
            "mdt_webhook": "/api/v1/mdt/completed",
            "reports": "/api/v1/reports/list",
            "infra_status": "/api/v1/infra/status"
        }
    }

def check_tcp_port(ip: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            return sock.connect_ex((ip, port)) == 0
    except Exception:
        return False

@app.get("/api/v1/infra/status")
def get_infra_status(request: Request):
    """Retorna o status de conectividade com os servidores da infraestrutura do laboratório (Paralelizado)"""
    require_operator(request)
    current_settings = profile_mgr.get_settings()
    net_cfg = current_settings.get("network", {})
    mdt_ip = net_cfg.get("mdt_server_ip", "192.168.57.87")
    backup_ip = net_cfg.get("backup_server_ip", "192.168.57.112")
    milvus_ip = net_cfg.get("milvus_dashboard_ip", "192.168.57.7")
    llm_cfg = current_settings.get("llm", {})
    llm_url = llm_cfg.get("base_url", "http://192.168.57.31:8080/v1")
    tc_server = current_settings.get("trueconf", {}).get("server_url", "https://trueconf.penserede.com.br")

    def _check_llm() -> bool:
        base_clean = llm_url.replace("/v1", "").rstrip("/")
        for probe in ["/health", "/v1/models", "/api/tags"]:
            try:
                r = requests.get(f"{base_clean}{probe}", timeout=0.6)
                if r.status_code == 200:
                    return True
            except Exception:
                continue
        return False

    def _check_mdt() -> bool:
        return check_tcp_port(mdt_ip, 445, timeout=0.35) or check_tcp_port(mdt_ip, 80, timeout=0.35)

    def _check_backup() -> bool:
        return check_tcp_port(backup_ip, 445, timeout=0.35) or check_tcp_port(backup_ip, 139, timeout=0.35)

    def _check_milvus() -> bool:
        return profile_mgr.milvus.is_online(timeout=0.5)

    def _check_trueconf() -> bool:
        try:
            r_tc = requests.get(f"{tc_server.rstrip('/')}", timeout=0.5)
            return r_tc.status_code < 500
        except Exception:
            return False

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=5) as executor:
        f_llm = executor.submit(_check_llm)
        f_mdt = executor.submit(_check_mdt)
        f_backup = executor.submit(_check_backup)
        f_milvus = executor.submit(_check_milvus)
        f_tc = executor.submit(_check_trueconf)

        llm_online = f_llm.result()
        mdt_online = f_mdt.result()
        backup_online = f_backup.result()
        milvus_online = f_milvus.result()
        trueconf_online = f_tc.result()

    return {
        "ultron": True,
        "llm": llm_online,
        "ollama": llm_online,
        "mdt_server": mdt_online,
        "backup_storage": backup_online,
        "milvus_dashboard": milvus_online,
        "trueconf": trueconf_online,
        "ips": {
            "mdt_ip": mdt_ip,
            "backup_ip": backup_ip,
            "milvus_ip": milvus_ip,
            "llm_ip": "192.168.57.31"
        }
    }

@app.post("/api/v1/trueconf/test")
def test_trueconf_notification(request: Request, req: Optional[TrueConfTestRequest] = None):
    """Envia uma notificação privada de teste no TrueConf para o técnico"""
    require_operator(request)
    user_id = req.user_id if req else "nicolas"
    msg = req.message if req else "🔔 Teste de Notificação Direta do Ultron Server"
    sent = bot.send_direct_message(user_id=user_id, message=msg)
    return {
        "success": sent,
        "user_id": user_id,
        "server_url": bot.server_url,
        "message": f"Mensagem enviada com sucesso para @{user_id}" if sent else f"Falha ao enviar mensagem para @{user_id}. Servidor TrueConf ({bot.server_url}) inacessível ou token inválido."
    }

@app.post("/api/v1/trueconf/webhook")
@app.post("/webhook/trueconf")
def trueconf_webhook(request: Request, payload: Optional[TrueConfWebhookPayload] = None):
    """
    Recebe mensagens enviadas ao Bot Ultron no TrueConf Server e processa via ChatOps
    """
    require_trueconf_webhook(request)
    p = payload or TrueConfWebhookPayload()
    user_id = p.user_id or p.sender or p.author or "nicolas"
    message_text = p.body or p.text or p.message or ""

    if not message_text and p.event:
        if isinstance(p.event, dict):
            user_id = p.event.get("user_id") or user_id
            message_text = p.event.get("body") or p.event.get("text") or ""

    # Processa o comando e responde ao usuário
    reply = bot.process_incoming_message(user_id=user_id, message_text=message_text, reply_directly=True)
    
    return {
        "success": True,
        "user_id": user_id,
        "accepted": True,
        "reply": reply
    }

@app.get("/api/v1/clients")
def list_clients(request: Request, force_refresh: bool = False):
    """Retorna todos os clientes e perfis disponíveis no Ultron sincronizados com o Milvus"""
    require_operator(request)
    clients = profile_mgr.list_clients(force_refresh_milvus=force_refresh)
    return {
        "total": len(clients),
        "clients": clients
    }

@app.get("/api/v1/clients/{client_id}")
def get_client_profile(request: Request, client_id: str):
    """Retorna as configurações e pacotes do perfil de um cliente específico"""
    require_operator(request)
    profile = profile_mgr.get_client_profile(client_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Perfil de cliente não encontrado")
    return profile

# --- Rotas de Integração Milvus ---

@app.get("/api/v1/milvus/config")
def get_milvus_config(request: Request):
    """Retorna as configurações atuais e status da conexão com a Dashboard Milvus (192.168.57.7)"""
    require_operator(request)
    return profile_mgr.get_milvus_config()

@app.post("/api/v1/milvus/config")
def update_milvus_config(request: Request, req: MilvusConfigRequest):
    """Atualiza e salva as credenciais e parâmetros da Dashboard Milvus em config/settings.yaml"""
    require_operator(request)
    ok = profile_mgr.save_milvus_config(
        milvus_url=req.dashboard_url,
        milvus_token=req.api_token or "",
        demo_mode=req.demo_mode or False
    )
    if not ok:
        raise HTTPException(status_code=500, detail="Falha ao salvar configurações do Milvus")
    return {
        "success": True,
        "message": "Configurações do Milvus salvas com sucesso!",
        "config": profile_mgr.get_milvus_config()
    }

@app.post("/api/v1/milvus/test")
def test_milvus_connection(request: Request, req: Optional[MilvusTestRequest] = None):
    """Testa a conectividade, latência e endpoints da Dashboard Milvus em tempo real"""
    require_operator(request)
    custom_url = req.custom_url if req else None
    custom_token = req.custom_token if req else None
    result = profile_mgr.milvus.test_connection(custom_url=custom_url, custom_token=custom_token)
    return result

@app.get("/api/v1/milvus/client-tokens")
def get_milvus_client_tokens(request: Request):
    """Retorna a lista de todos os clientes e seus tokens de instalação do agente Milvus (clients.yaml)"""
    require_operator(request)
    tokens = profile_mgr.get_client_tokens()
    return {
        "total": len(tokens),
        "clients": tokens
    }

@app.post("/api/v1/milvus/client-tokens")
def update_milvus_client_token(request: Request, req: ClientTokenUpdateRequest):
    """Atualiza o token de instalação do agente Milvus para um cliente específico em clients.yaml"""
    require_operator(request)
    ok = profile_mgr.update_client_token(req.client_id, req.milvus_token)
    if not ok:
        raise HTTPException(status_code=500, detail="Falha ao atualizar token do cliente")
    return {
        "success": True,
        "client_id": req.client_id,
        "message": f"Token Milvus do cliente '{req.client_id}' atualizado com sucesso!"
    }

@app.get("/api/v1/milvus/tickets")
def get_milvus_tickets(request: Request, force_refresh: bool = False):
    """Retorna a lista de chamados em aberto e pendentes na Dashboard Milvus (192.168.57.7)"""
    require_operator(request)
    tickets = profile_mgr.milvus.get_open_tickets(force_refresh=force_refresh)
    return {
        "total": len(tickets),
        "milvus_online": profile_mgr.milvus.is_online(timeout=0.8),
        "tickets": tickets
    }

@app.post("/api/v1/milvus/sync")
def sync_milvus_data(request: Request):
    """Força a sincronização imediata de clientes e chamados da Dashboard Milvus"""
    require_operator(request)
    companies = profile_mgr.milvus.get_companies(force_refresh=True)
    tickets = profile_mgr.milvus.get_open_tickets(force_refresh=True)
    return {
        "success": True,
        "companies_synced": len(companies),
        "tickets_synced": len(tickets),
        "message": f"Sincronização concluída: {len(companies)} clientes e {len(tickets)} chamados obtidos da Dashboard Milvus"
    }

@app.get("/api/v1/milvus/agent/download/{client_id}")
def download_client_milvus_agent(request: Request, client_id: str, force_download: bool = False):
    """
    Baixa ou entrega o instalador .MSI oficial do Agente Milvus já configurado com o token do cliente.
    Permite que qualquer máquina na rede ou técnico baixe o instalador pronto via API.
    """
    require_operator(request)
    profile = profile_mgr.get_client_profile(client_id)
    if not profile:
        raise HTTPException(status_code=404, detail=f"Cliente '{client_id}' não encontrado")

    client_name = profile.get("nome_exibicao", client_id)
    token = profile.get("milvus_token", "")

    if not token or "TOKEN_MILVUS" in token:
        raise HTTPException(
            status_code=400,
            detail=f"Cliente '{client_name}' não possui um Token Milvus válido cadastrado no clients.yaml"
        )

    agents_dir = os.path.join(BASE_DIR, "reports", "cache", "milvus_agents")
    os.makedirs(agents_dir, exist_ok=True)
    import re
    clean_name = re.sub(r'[^a-zA-Z0-9_]', '', client_name.replace(" ", "_"))
    cached_file = os.path.join(agents_dir, f"Milvus_{clean_name}.msi")

    if not force_download and os.path.exists(cached_file) and os.path.getsize(cached_file) > 1024:
        return FileResponse(
            cached_file,
            media_type="application/octet-stream",
            filename=f"Milvus_{clean_name}.msi"
        )

    # Executa o download oficial
    res = profile_mgr.milvus.download_client_agent(
        client_id=client_id,
        client_name=client_name,
        token=token,
        output_dir=agents_dir
    )

    if res["success"] and os.path.exists(res["file_path"]):
        return FileResponse(
            res["file_path"],
            media_type="application/octet-stream",
            filename=res["filename"]
        )
    else:
        raise HTTPException(status_code=502, detail=res.get("error", "Falha ao baixar instalador do Milvus"))

@app.post("/api/v1/milvus/agent/sync-all")
def sync_all_milvus_agents(request: Request, background_tasks: BackgroundTasks):
    """
    Baixa em lote e armazena em cache local os instaladores MSI de todos os clientes que possuem token configurado.
    """
    require_operator(request)
    clients_tokens = profile_mgr.get_client_tokens()
    valid_clients = [c for c in clients_tokens if c.get("has_token")]
    agents_dir = os.path.join(BASE_DIR, "reports", "cache", "milvus_agents")
    os.makedirs(agents_dir, exist_ok=True)

    def _sync_task():
        for c in valid_clients:
            try:
                profile_mgr.milvus.download_client_agent(
                    client_id=c["client_id"],
                    client_name=c["nome"],
                    token=c["milvus_token"],
                    output_dir=agents_dir
                )
            except Exception as e:
                print(f"⚠️ Erro ao sincronizar MSI de {c['nome']}: {e}")

    background_tasks.add_task(_sync_task)
    return {
        "success": True,
        "total_clients_queued": len(valid_clients),
        "message": f"Sincronização de instaladores MSI iniciada em segundo plano para {len(valid_clients)} clientes."
    }

@app.get("/api/v1/milvus/agent/cached")
def list_cached_agents(request: Request):
    """Lista todos os instaladores MSI em cache local no servidor Ultron"""
    require_operator(request)
    agents_dir = os.path.join(BASE_DIR, "reports", "cache", "milvus_agents")
    if not os.path.exists(agents_dir):
        return {"total": 0, "agents": []}

    msi_files = glob.glob(os.path.join(agents_dir, "*.msi"))
    agents = []
    for f in msi_files:
        agents.append({
            "filename": os.path.basename(f),
            "size_kb": round(os.path.getsize(f) / 1024, 1),
            "path": f
        })
    return {"total": len(agents), "agents": agents}


# --- Rotas de Telemetria e Ferramentas Públicas (Public APIs) ---

# Endpoints auxiliares exclusivos do painel foram retirados.
# Serviços equivalentes permanecem acessíveis ao TrueConf pelos módulos internos.

@app.get("/api/v1/bench/scan")
def scan_bench_network(timeout: float = Query(0.3, description="Timeout de conexão por porta em segundos")):
    """Varre a subrede do laboratório em busca de máquinas ativas com WinRM (5985)"""
    devices = network_scanner.scan_network(timeout=timeout)
    return {
        "subnet": network_scanner.subnet,
        "total_active": len(devices),
        "devices": devices
    }

@app.post("/api/v1/bench/diagnose")
def diagnose_machine(req: DiagnosticRequest, request: Request):
    """Executa varredura de hardware e análise de IA na máquina alvo sem alterar configurações"""
    require_operator(request)
    from core.task_registry import task_registry, TaskRegistryError
    try:
        job = task_registry.create("api_operator", req.ip, "diagnose")
    except TaskRegistryError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    try:
        result = task_registry.execute("api_operator", job["job_id"],
            lambda: orchestrator.run_diagnostics_only(req.ip))
    except Exception:
        return {"success": False, "job_id": job["job_id"], "outcome": "UNKNOWN"}
    return dict(result, job_id=job["job_id"])

# --- Rotas de Ações Rápidas de Bancada ---

@app.post("/api/v1/bench/action/backup")
def execute_backup_action(req: BackupRequest, request: Request):
    """Inicia cópia de arquivos do usuário via WinRM, não uma imagem Macrium."""
    require_operator(request)
    if req.source_drive not in ("C:", None, ""):
        raise HTTPException(status_code=400, detail="Apenas C: é suportado nesta fase.")
    try:
        job = file_backup_jobs.start(
            req.ip, req.client_name,
            (req.ticket_number or "").strip(), owner="api_operator",
        )
    except FileBackupError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return job


@app.get("/api/v1/bench/action/backup/{job_id}")
def get_backup_action(job_id: str, request: Request):
    """Status da cópia: sucesso NÃO libera operação destrutiva no MDT."""
    require_operator(request)
    job = file_backup_jobs.get(job_id)
    if job is None:
        from core.task_registry import task_registry
        job = task_registry.get("api_operator", job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Tarefa nao encontrada.")
    return job


@app.get("/api/v1/tasks")
def list_operator_tasks(request: Request):
    require_operator(request)
    from core.task_registry import task_registry
    return {"tasks": task_registry.recent("api_operator")}


@app.get("/api/v1/tasks/{job_id}")
def get_operator_task(job_id: str, request: Request):
    require_operator(request)
    from core.task_registry import task_registry
    job = task_registry.get("api_operator", job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Tarefa nao encontrada.")
    return job


@app.post("/api/v1/bench/action/verify-macrium")
def start_macrium_verification(req: MacriumVerifyRequest, request: Request):
    """Verificação assíncrona e somente leitura via MRVerify num host Windows fixo."""
    require_operator(request)
    try:
        job = macrium_jobs.start(req.image_path)
    except MacriumBridgeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return job


@app.get("/api/v1/bench/action/verify-macrium/{job_id}")
def get_macrium_verification(job_id: str, request: Request):
    """Consulta a execução; reinícios do serviço não retomam tarefas desconhecidas."""
    require_operator(request)
    job = macrium_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Verificação não encontrada neste processo.")
    return job


@app.post("/api/v1/bench/action/power")
def execute_power_action(req: PowerActionRequest, request: Request):
    """Executa reinicialização ou desligamento remoto da máquina de bancada"""
    require_operator(request)
    if req.action == "shutdown":
        cmd = "Stop-Computer -Force"
        action_name = "Desligamento"
    else:
        cmd = "Restart-Computer -Force"
        action_name = "Reinicialização"

    result = orchestrator.winrm.run_powershell_code(req.ip, cmd)
    return {
        "success": result["success"],
        "action": req.action,
        "message": f"Comando de {action_name} enviado para {req.ip}",
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", "")
    }

@app.post("/api/v1/bench/action/rename")
def execute_rename_action(req: RenameComputerRequest, request: Request):
    """Altera o nome do computador (hostname) e reinicia opcionalmente"""
    require_operator(request)
    clean_name = req.new_name.strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail="Novo nome inválido")

    cmd = f"Rename-Computer -NewName '{clean_name}' -Force"
    if req.restart:
        cmd += "; Restart-Computer -Force"

    result = orchestrator.winrm.run_powershell_code(req.ip, cmd)
    return {
        "success": result["success"],
        "new_name": clean_name,
        "restarted": req.restart,
        "message": f"Hostname alterado para {clean_name}" if result["success"] else "Falha ao renomear computador",
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", "")
    }

@app.post("/api/v1/bench/action/activate")
def execute_activation_action(req: ActivationRequest, request: Request):
    """Executa a ativação automática do Windows e Office via Massgrave (MAS)"""
    require_operator(request)
    mas_cmd = "irm https://get.activated.win | iex"
    result = orchestrator.winrm.run_powershell_code(req.ip, mas_cmd)
    return {
        "success": result["success"],
        "ip": req.ip,
        "message": "Script de ativação Massgrave MAS executado",
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", "")
    }

CURATED_SOFTWARE_CATALOG = [
    {
        "category": "Navegadores & Web",
        "icon": "globe",
        "packages": [
            {"id": "Google.Chrome", "name": "Google Chrome", "desc": "Navegador padrão corporativo rápido e seguro", "tag": "Popular"},
            {"id": "Mozilla.Firefox", "name": "Mozilla Firefox", "desc": "Navegador livre com foco em privacidade e extensões", "tag": "Essencial"},
            {"id": "Brave.Brave", "name": "Brave Browser", "desc": "Navegador com bloqueio nativo de rastreadores e anúncios", "tag": "Privacidade"},
            {"id": "Microsoft.Edge", "name": "Microsoft Edge", "desc": "Navegador nativo otimizado para o ecossistema Windows", "tag": "Nativo"}
        ]
    },
    {
        "category": "Produtividade & Escritório",
        "icon": "briefcase",
        "packages": [
            {"id": "Adobe.Acrobat.Reader.64-bit", "name": "Adobe Acrobat Reader", "desc": "Leitor padrão oficial de documentos PDF", "tag": "Padrão"},
            {"id": "Microsoft.Office", "name": "Microsoft 365 (Office)", "desc": "Word, Excel, PowerPoint, Outlook e Teams", "tag": "Enterprise"},
            {"id": "Notepad++.Notepad++", "name": "Notepad++", "desc": "Editor de texto e scripts leve e potente", "tag": "Leve"},
            {"id": "Obsidian.Obsidian", "name": "Obsidian", "desc": "Base de conhecimento e anotações em Markdown", "tag": "Produtividade"}
        ]
    },
    {
        "category": "Comunicação & Reuniões",
        "icon": "message-square",
        "packages": [
            {"id": "Microsoft.Teams", "name": "Microsoft Teams", "desc": "Chat corporativo e chamadas de vídeo", "tag": "Trabalho"},
            {"id": "Zoom.Zoom", "name": "Zoom Meetings", "desc": "Plataforma de videoconferências e reuniões", "tag": "Vídeo"},
            {"id": "Discord.Discord", "name": "Discord", "desc": "Comunicação por voz, vídeo e canais de texto", "tag": "Comunidade"},
            {"id": "SlackTechnologies.Slack", "name": "Slack", "desc": "Comunicação e colaboração para equipes de TI", "tag": "Equipe"}
        ]
    },
    {
        "category": "Suporte & Acesso Remoto",
        "icon": "shield-check",
        "packages": [
            {"id": "AnyDeskSoftwareGmbH.AnyDesk", "name": "AnyDesk", "desc": "Software de acesso remoto de alta velocidade", "tag": "TI Lab"},
            {"id": "PuTTY.PuTTY", "name": "PuTTY SSH Client", "desc": "Terminal SSH e Telnet para servidores e switches", "tag": "Redes"},
            {"id": "TimKosse.FileZilla.Client", "name": "FileZilla FTP", "desc": "Cliente FTP e SFTP para envio de arquivos", "tag": "Redes"},
            {"id": "WiresharkFoundation.Wireshark", "name": "Wireshark", "desc": "Analisador profissional de pacotes e tráfego de rede", "tag": "Segurança"}
        ]
    },
    {
        "category": "Desenvolvimento & TI",
        "icon": "code-2",
        "packages": [
            {"id": "Microsoft.VisualStudioCode", "name": "Visual Studio Code", "desc": "Editor de código fonte e IDE moderna", "tag": "Top Dev"},
            {"id": "Git.Git", "name": "Git SCM", "desc": "Sistema de controle de versão distribuído", "tag": "Dev"},
            {"id": "Python.Python.3.11", "name": "Python 3.11", "desc": "Linguagem de automação e scripts de backend", "tag": "Dev"},
            {"id": "OpenJS.NodeJS", "name": "Node.js (LTS)", "desc": "Ambiente de execução JavaScript no servidor", "tag": "Web"},
            {"id": "dbeaver.dbeaver", "name": "DBeaver Community", "desc": "Gerenciador universal de Bancos de Dados SQL", "tag": "DB"}
        ]
    },
    {
        "category": "Utilitários & Mídia",
        "icon": "wrench",
        "packages": [
            {"id": "7zip.7zip", "name": "7-Zip (64-bit)", "desc": "Descompactador e compactador ultra veloz", "tag": "Essencial"},
            {"id": "RARLab.WinRAR", "name": "WinRAR", "desc": "Utilitário clássico de descompactação RAR/ZIP", "tag": "Popular"},
            {"id": "VideoLAN.VLC", "name": "VLC Media Player", "desc": "Reprodutor de vídeo com suporte a todos os formatos", "tag": "Mídia"},
            {"id": "Spotify.Spotify", "name": "Spotify", "desc": "Streaming de música e podcasts", "tag": "Áudio"},
            {"id": "OBSProject.OBSStudio", "name": "OBS Studio", "desc": "Gravação de tela e transmissão ao vivo", "tag": "Vídeo"},
            {"id": "Rufus.Rufus", "name": "Rufus", "desc": "Criação de pendrives inicializáveis para formatação", "tag": "TI Lab"}
        ]
    },
    {
        "category": "Jogos & Criação 3D",
        "icon": "gamepad-2",
        "packages": [
            {"id": "Valve.Steam", "name": "Steam", "desc": "Plataforma de jogos e distribuição digital", "tag": "Games"},
            {"id": "BlenderFoundation.Blender", "name": "Blender 3D", "desc": "Criação, modelagem e renderização 3D", "tag": "Design"},
            {"id": "GIMP.GIMP", "name": "GIMP", "desc": "Manipulação e edição de imagens profissional", "tag": "Design"}
        ]
    }
]

@app.get("/api/v1/packages/catalog")
def get_packages_catalog():
    """Retorna o catálogo curado de softwares para exibição no painel visual"""
    return {
        "success": True,
        "categories": CURATED_SOFTWARE_CATALOG
    }

@app.get("/api/v1/packages/bundles")
def list_package_bundles():
    """Retorna os backups e bundles UniGetUI salvos no laboratório"""
    bundles = package_mgr.list_saved_bundles()
    return {
        "success": True,
        "bundles": bundles
    }

@app.post("/api/v1/packages/install")
def install_packages_api(request: Request, req: PackageInstallRequest):
    """Instala uma lista de pacotes via instalador unificado UniGetUI/Winget"""
    require_operator(request)
    if not req.packages:
        raise HTTPException(status_code=400, detail="Nenhum pacote selecionado para instalação.")
    res = orchestrator.winrm.run_script_file(
        req.ip,
        "Install-UnifiedPackages.ps1",
        params={
            "Packages": req.packages,
            "Interactive": req.interactive
        }
    )
    return {
        "success": res.get("success", False),
        "ip": req.ip,
        "packages": req.packages,
        "stdout": res.get("stdout", ""),
        "stderr": res.get("stderr", "")
    }

@app.post("/api/v1/packages/upgrade_all")
def upgrade_all_packages_api(request: Request, req: PackageUpgradeRequest):
    """Atualiza em massa todos os programas instalados na máquina alvo via Winget"""
    require_operator(request)
    res = package_mgr.upgrade_all_packages(req.ip)
    return res

@app.post("/api/v1/packages/backup")
def backup_packages_api(request: Request, req: PackageBackupRequest):
    """Varre e exporta todos os programas instalados em um bundle UniGetUI (.json)"""
    require_operator(request)
    res = package_mgr.export_machine_packages(req.ip, identifier=req.identifier)
    return res

@app.post("/api/v1/packages/restore")
def restore_packages_api(request: Request, req: PackageRestoreRequest):
    """Restaura um bundle UniGetUI (.json) previamente salvo na máquina alvo"""
    require_operator(request)
    res = package_mgr.restore_machine_packages(req.ip, bundle_name_or_id=req.bundle_name)
    return res

@app.post("/api/v1/bench/action/install-software")
def execute_install_software_action(request: Request, req: InstallSoftwareRequest):
    """Instala uma lista de pacotes via instalador unificado na máquina alvo"""
    require_operator(request)
    if not req.packages:
        raise HTTPException(status_code=400, detail="Nenhum pacote selecionado")
    res = orchestrator.winrm.run_script_file(
        req.ip,
        "Install-UnifiedPackages.ps1",
        params={"Packages": req.packages, "Interactive": True}
    )
    return {
        "success": res.get("success", False),
        "ip": req.ip,
        "installed": req.packages if res.get("success") else [],
        "stdout": res.get("stdout", ""),
        "stderr": res.get("stderr", "")
    }

@app.post("/api/v1/bench/action/domain-join")
def execute_domain_join_action(request: Request, req: DomainJoinRequest):
    """Executa a configuração de rede e o ingresso da máquina no domínio com credenciais dinâmicas"""
    require_operator(request)
    params = {
        "DomainName": req.domain_name,
        "DomainUser": req.domain_user,
        "DomainPassword": req.domain_password,
        "DnsServer": req.dns_server or "",
        "StaticIp": req.static_ip or "",
        "SubnetMask": req.subnet_mask or "255.255.255.0",
        "Gateway": req.gateway or "",
        "OUPath": req.ou_path or ""
    }
    result = orchestrator.winrm.run_script_file(req.ip, "Join-CustomerDomain.ps1", params=params)
    return {
        "success": result["success"],
        "ip": req.ip,
        "domain": req.domain_name,
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", "")
    }

def _execute_pipeline_task(
    ip: str,
    client_id: str,
    tech_user_id: Optional[str],
    technician_name: Optional[str],
    skip_burnin: bool,
    custom_packages: Optional[List[str]],
    domain_config: Optional[dict] = None
):
    return orchestrator.run_pipeline(
        ip=ip,
        client_id=client_id,
        tech_user_id=tech_user_id,
        technician_name=technician_name,
        skip_burnin=skip_burnin,
        custom_packages=custom_packages,
        domain_config=domain_config,
        log_callback=None
    )

@app.post("/api/v1/bench/run")
def run_bench_pipeline(req: RunPipelineRequest, background_tasks: BackgroundTasks, request: Request, async_mode: bool = True):
    """Dispara a esteira completa de preparação da máquina (softwares, domínio, burn-in e laudo)"""
    require_operator(request)
    dom_dict = req.domain_config.model_dump() if req.domain_config else None
    if async_mode:
        background_tasks.add_task(
            _execute_pipeline_task,
            ip=req.ip,
            client_id=req.client_id,
            tech_user_id=req.tech_user_id,
            technician_name=req.technician_name,
            skip_burnin=req.skip_burnin,
            custom_packages=req.custom_packages or [],
            domain_config=dom_dict
        )
        return {
            "status": "queued",
            "message": f"Esteira de automação iniciada em segundo plano para {req.ip}",
            "client_id": req.client_id,
            "ip": req.ip
        }
    else:
        result = _execute_pipeline_task(
            ip=req.ip,
            client_id=req.client_id,
            tech_user_id=req.tech_user_id,
            technician_name=req.technician_name,
            skip_burnin=req.skip_burnin,
            custom_packages=req.custom_packages or [],
            domain_config=dom_dict
        )
        return result

@app.post("/api/v1/mdt/completed")
def mdt_completed(data: MDTNotification, background_tasks: BackgroundTasks, request: Request):
    """
    Webhook chamado pelo script Notify-Ultron.ps1 ao final da Task Sequence do MDT.
    Exige a mesma credencial do agente associado ao serial.
    """
    AgentAuthenticator().authenticate(request, expected_agent=data.serial)
    print(f"🤖 [ULTRON] Webhook MDT recebido para o PC: {data.computer_name} ({data.ip}) - Serial: {data.serial}")
    
    # 1. Notifica o técnico no privado (ou técnico responsável) via TrueConf
    bot.notify_mdt_finished(bench_ip=data.ip, serial=data.serial, user_id=data.tech_user_id)

    # 2. Se auto_run estiver ativo ou cliente informado, inicia automação em segundo plano
    if data.auto_run and data.client_id:
        background_tasks.add_task(
            orchestrator.run_pipeline,
            ip=data.ip,
            client_id=data.client_id,
            tech_user_id=data.tech_user_id or "nicolas.silva"
        )

    return {
        "message": "Notificação recebida com sucesso pelo Ultron",
        "ip": data.ip,
        "serial": data.serial,
        "auto_started": bool(data.auto_run and data.client_id)
    }

@app.get("/api/v1/reports/list")
def list_reports(request: Request):
    """Lista todos os laudos técnicos em PDF gerados pelo Ultron"""
    require_operator(request)
    output_dir = os.path.join(BASE_DIR, "reports", "output")
    if not os.path.exists(output_dir):
        return {"total": 0, "reports": []}

    pdf_files = glob.glob(os.path.join(output_dir, "*.pdf"))
    reports = []
    for f in pdf_files:
        reports.append({
            "filename": os.path.basename(f),
            "size_kb": round(os.path.getsize(f) / 1024, 1),
            "created_at": os.path.getctime(f)
        })
    reports.sort(key=lambda x: x["created_at"], reverse=True)
    return {"total": len(reports), "reports": reports}

@app.get("/api/v1/reports/download/{filename}")
def download_report(request: Request, filename: str):
    """Permite o download de um laudo técnico gerado"""
    require_operator(request)
    # Prevent path traversal and exposing arbitrary files.
    if filename != os.path.basename(filename) or not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Nome de relatório inválido.")
    file_path = os.path.join(BASE_DIR, "reports", "output", filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Laudo técnico não encontrado")
    return FileResponse(file_path, media_type="application/pdf", filename=filename)

if __name__ == "__main__":
    srv_cfg = settings.get("server", {})
    host = srv_cfg.get("host", "0.0.0.0")
    port = srv_cfg.get("port", 7000)
    is_dev = srv_cfg.get("env", "production") == "development"
    print(f"🚀 Iniciando Servidor Ultron na RTX 5060Ti em {host}:{port}...")
    uvicorn.run("main:app", host=host, port=port, reload=is_dev)
