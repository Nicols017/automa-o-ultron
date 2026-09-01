"""
Ultron Automation Server - Pense Rede Lab
Ponto de entrada principal da aplicação FastAPI, Web Dashboard e orquestração de bancada.
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

import asyncio
from fastapi import FastAPI, BackgroundTasks, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import uvicorn

from core.profile_manager import ProfileManager
from core.network_scanner import NetworkScanner
from core.orchestrator import LabOrchestrator
from core.package_manager import UnifiedPackageManager
from chatops.bot import TrueConfBot
from core.public_tools import (
    MacVendorResolver,
    NetworkDiagnosticsService,
    LabWeatherService,
    DnsDiagnosticsService,
    CveSecurityService,
    WindowsErrorLookupService,
    QrCodeService,
    CisaKevService,
    NtpTimeService,
    GitHubToolsVersionService,
    TechWisdomService
)
from core.agent_builder import agent_builder

app = FastAPI(
    title="Ultron Lab Automation Server",
    description="Servidor de Automação de Bancada e Laboratório - Pense Rede",
    version="1.4.0"
)

# Diretórios base
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

# Monta arquivos estáticos
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Gerenciador de conexões WebSocket para Log Streaming
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop

    async def connect(self, session_id: str, websocket: WebSocket):
        await websocket.accept()
        if session_id not in self.active_connections:
            self.active_connections[session_id] = []
        self.active_connections[session_id].append(websocket)

    def disconnect(self, session_id: str, websocket: WebSocket):
        if session_id in self.active_connections:
            if websocket in self.active_connections[session_id]:
                self.active_connections[session_id].remove(websocket)
            if not self.active_connections[session_id]:
                del self.active_connections[session_id]

    async def send_event_async(self, session_id: str, event: dict):
        if session_id in self.active_connections:
            for connection in list(self.active_connections[session_id]):
                try:
                    await connection.send_json(event)
                except Exception:
                    pass

    def send_event(self, session_id: str, event: dict):
        """Dispara eventos em tempo real a partir de threads síncronas do pipeline"""
        if session_id in self.active_connections and self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.send_event_async(session_id, event), self.loop)

manager = ConnectionManager()

# Instancia componentes principais
profile_mgr = ProfileManager()
network_scanner = NetworkScanner()
orchestrator = LabOrchestrator()
package_mgr = UnifiedPackageManager(winrm_executor=orchestrator.winrm)
settings = profile_mgr.get_settings()

# Inicializa Gerenciador de Tarefas Reversas do UltronAgent
class AgentTaskManager:
    def __init__(self):
        self._queues: Dict[str, List[Dict[str, Any]]] = {}
        self._results: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def enqueue_task(self, target_identifier: str, command: str, task_type: str = "powershell", task_id: Optional[str] = None) -> str:
        if not task_id:
            task_id = f"task_{uuid.uuid4().hex[:8]}"
        task = {
            "task_id": task_id,
            "command": command,
            "type": task_type,
            "created_at": time.time(),
            "target": target_identifier
        }
        with self._lock:
            key = target_identifier.strip().lower()
            if key not in self._queues:
                self._queues[key] = []
            self._queues[key].append(task)
        return task_id

    def get_pending_task(self, target_identifier: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            for k in [target_identifier.strip().lower(), target_identifier.strip()]:
                if k in self._queues and self._queues[k]:
                    return self._queues[k].pop(0)
        return None

    def store_result(self, task_id: str, result: Dict[str, Any]):
        with self._lock:
            self._results[task_id] = {
                **result,
                "completed_at": time.time()
            }

    def get_result(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._results.get(task_id)

agent_task_mgr = AgentTaskManager()

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
    # Garante que o UltronAgent.exe esteja sempre sincronizado com o código C#
    try:
        agent_builder.compile()
    except Exception as e:
        print(f"⚠️ Aviso na compilação do UltronAgent: {e}")

    manager.set_loop(asyncio.get_running_loop())
    if bot.bot_password or bot.api_token:
        bot.start_polling(interval_sec=3)

@app.on_event("shutdown")
async def shutdown_event():
    bot.stop_polling()

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
    session_id: Optional[str] = Field(None, description="ID da sessão do WebSocket para streaming em tempo real")
    domain_config: Optional[DomainJoinRequest] = Field(None, description="Configurações dinâmicas de domínio e rede")

class DiagnosticRequest(BaseModel):
    ip: str = Field(..., description="Endereço IP da máquina alvo na bancada")

class BackupRequest(BaseModel):
    ip: str = Field(..., description="Endereço IP da máquina alvo")
    client_name: str = Field("CLIENTE", description="Nome do cliente para a pasta de backup")
    ticket_number: Optional[str] = Field("", description="Número do chamado / ticket no Milvus")
    source_drive: Optional[str] = Field("C:", description="Unidade de origem para cópia de dados")

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
    auth_user: Optional[str] = Field("UltronAdmin", description="Usuário de automação local provisionado")
    auth_pass: Optional[str] = Field("Ultron@AutoBench2026!", description="Senha da conta de automação local")

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

# --- Gerenciador de Fila de Tarefas Reversas (Reverse Task Queue) ---
class AgentTaskManager:
    def __init__(self):
        self._queues: Dict[str, List[Dict[str, Any]]] = {}
        self._results: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def enqueue_task(self, target_identifier: str, command: str, task_type: str = "powershell", task_id: Optional[str] = None) -> str:
        if not task_id:
            task_id = f"task_{uuid.uuid4().hex[:8]}"
        task = {
            "task_id": task_id,
            "command": command,
            "type": task_type,
            "created_at": time.time(),
            "target": target_identifier
        }
        with self._lock:
            key = target_identifier.strip().lower()
            if key not in self._queues:
                self._queues[key] = []
            self._queues[key].append(task)
        return task_id

    def get_pending_task(self, target_identifier: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            for k in [target_identifier.strip().lower(), target_identifier.strip()]:
                if k in self._queues and self._queues[k]:
                    return self._queues[k].pop(0)
        return None

    def store_result(self, task_id: str, result: Dict[str, Any]):
        with self._lock:
            self._results[task_id] = {
                **result,
                "completed_at": time.time()
            }

    def get_result(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._results.get(task_id)

agent_task_mgr = AgentTaskManager()

# --- Rotas da Interface Web & Downloads ---

@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
def get_dashboard():
    """Entrega a interface web visual do Ultron Lab Dashboard com proteção anti-cache"""
    template_path = os.path.join(TEMPLATES_DIR, "index.html")
    if os.path.exists(template_path):
        with open(template_path, "r", encoding="utf-8") as f:
            content = f.read()
        resp = HTMLResponse(content=content)
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        return resp
    return HTMLResponse(content="<h2>Ultron Lab Automation Server Online</h2>")

@app.get("/download/UltronAgent.exe")
@app.get("/download/UltronAgent.exe.")
@app.get("/downloads/UltronAgent.exe")
@app.get("/downloads/UltronAgent.exe.")
@app.get("/download/UltronUnlocker.exe")
@app.get("/UltronAgent.exe")
@app.get("/UltronUnlocker.exe")
def download_ultron_agent():
    """Entrega o executável nativo do Agente Ultron garantindo que esteja sempre na compilação mais recente"""
    bin_info = agent_builder.get_latest_agent_binary()
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
        "release_notes": f"UltronAgent {ver}: Auto-Updater OTA silencioso, Reconhecimento de Usuário Logado, Detecção de AnyDesk ID, Auto-Instalação como Serviço Windows e Suporte a Bundles UniGetUI."
    }

@app.get("/api/v1/agent/tasks/{target_id}")
def get_agent_pending_tasks(target_id: str):
    """Permite ao UltronAgent consultar tarefas pendentes via canal reverso HTTP"""
    task = agent_task_mgr.get_pending_task(target_id)
    if task:
        return task
    return {"status": "no_tasks"}

@app.post("/api/v1/agent/tasks/{task_id}/result")
def submit_agent_task_result(task_id: str, result: AgentTaskResult):
    """Recebe o resultado da execução da tarefa enviada pelo UltronAgent"""
    agent_task_mgr.store_result(task_id, result.model_dump())
    return {"success": True, "message": f"Resultado da tarefa {task_id} armazenado com sucesso"}

@app.post("/api/v1/agent/alert")
def receive_agent_alert(alert: AgentAlert):
    """Recebe alertas críticos de hardware (BSOD, S.M.A.R.T, Superaquecimento) e notifica o TrueConf"""
    tc_user = settings.get("trueconf", {}).get("default_tech_user_id", "nicolas.silva")
    
    icon = "🚨" if alert.type == "BSOD" else "🔥"
    msg = (
        f"{icon} **ALERTA PROATIVO DE HARDWARE — ULTRON AGENT**\n\n"
        f"📍 **Máquina:** {alert.hostname} ({alert.ip})\n"
        f"🏷️ **Serial:** {alert.serial}\n"
        f"⚠️ **Tipo de Ocorrência:** {alert.type}\n"
        f"📋 **Detalhes:** {alert.details}\n\n"
        f"💡 Sugestão: Inspecione os discos e a memória RAM com *'diagnóstico no {alert.ip}'*."
    )
    bot.send_direct_message(tc_user, msg)
    return {"success": True, "message": "Alerta processado e notificado com sucesso"}

@app.post("/api/v1/agent/cleanup/{target_id}")
def enqueue_agent_cleanup(target_id: str):
    """Enfileira comando de auto-limpeza e desinstalação para uma máquina entregue"""
    task_id = agent_task_mgr.enqueue_task(target_id, "CLEANUP_SYSTEM", task_type="cleanup")
    return {
        "success": True,
        "task_id": task_id,
        "message": f"Ordem de auto-limpeza e desinstalação enfileirada para {target_id}."
    }

@app.post("/api/v1/agent/register")
def agent_register(data: AgentRegistration, background_tasks: BackgroundTasks):
    """Webhook chamado pelo UltronAgent.exe após liberar a máquina e coletar hardware"""
    print(f"🤖 [ULTRON AGENT] Máquina registrada: {data.computer_name} ({data.ip}) - Serial: {data.serial} - RAM: {data.ram_gb} GB")
    
    # Salva credenciais de automação zero-prompt no WinRMExecutor e no ChatOps
    auth_user = data.auth_user or "UltronAdmin"
    auth_pass = data.auth_pass or "Ultron@AutoBench2026!"
    orchestrator.winrm.set_host_credentials(data.ip, auth_user, auth_pass)
    if bot and bot.chatops:
        bot.chatops.winrm.set_host_credentials(data.ip, auth_user, auth_pass)
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
    anydesk_str = f"🔑 AnyDesk ID: **{data.anydesk_id}** ([Abrir AnyDesk](anydesk:{data.anydesk_id}))\n" if data.anydesk_id else ""

    # Notifica o técnico no TrueConf com formatação limpa
    user_header = f" — MÁQUINA DE {data.logged_in_user.upper()}" if data.logged_in_user else ""
    msg = (
        f"💻 **ULTRON AGENT CONECTADO{user_header}**\n\n"
        f"📍 IP: **{data.ip}**\n"
        f"{user_str}"
        f"🏷️ Serial: `{data.serial}`\n"
        f"💻 Host: **{data.computer_name}** ({data.manufacturer} {data.model})\n"
        f"🧠 CPU: {data.cpu}\n"
        f"💾 RAM: {data.ram_gb} GB\n"
        f"{anydesk_str}"
        f"🛡️ Serviço: **UltronService (SYSTEM)** Ativo & Autônomo\n\n"
        f"💡 Ações Rápidas:\n"
        f"• *\"diagnóstico no {data.ip}\"*\n"
        f"• *\"preparar {data.ip} para <cliente>\"*\n"
        f"• *\"ativar {data.ip}\"*"
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
def agent_heartbeat(data: AgentHeartbeat):
    """Heartbeat periódico do UltronAgent.exe em segundo plano"""
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


# --- WebSocket Log Stream ---

@app.websocket("/ws/pipeline/{session_id}")
async def websocket_pipeline_endpoint(websocket: WebSocket, session_id: str):
    """Endpoint WebSocket para recepção de logs e status da esteira em tempo real"""
    await manager.connect(session_id, websocket)
    try:
        await websocket.send_json({
            "type": "connected",
            "session_id": session_id,
            "message": "🔌 Conectado ao Ultron Realtime Log Streamer"
        })
        while True:
            # Mantém conexão aberta e escuta possíveis comandos
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(session_id, websocket)
    except Exception:
        manager.disconnect(session_id, websocket)

# --- Rotas da API ---

@app.get("/api/v1/info")
def read_root():
    return {
        "agent": "Ultron",
        "status": "online",
        "company": "Pense Rede",
        "lab": "Hardware & Bench Automation",
        "endpoints": {
            "dashboard": "/dashboard",
            "clients": "/api/v1/clients",
            "scan": "/api/v1/bench/scan",
            "run": "/api/v1/bench/run",
            "diagnose": "/api/v1/bench/diagnose",
            "mdt_webhook": "/api/v1/mdt/completed",
            "reports": "/api/v1/reports/list",
            "infra_status": "/api/v1/infra/status",
            "ws_pipeline": "/ws/pipeline/{session_id}"
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
def get_infra_status():
    """Retorna o status de conectividade com os servidores da infraestrutura do laboratório (Paralelizado)"""
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
def test_trueconf_notification(req: Optional[TrueConfTestRequest] = None):
    """Envia uma notificação privada de teste no TrueConf para o técnico"""
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
def trueconf_webhook(payload: Optional[TrueConfWebhookPayload] = None):
    """
    Recebe mensagens enviadas ao Bot Ultron no TrueConf Server e processa via ChatOps
    """
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
        "received": message_text,
        "reply": reply
    }

@app.get("/api/v1/clients")
def list_clients(force_refresh: bool = False):
    """Retorna todos os clientes e perfis disponíveis no Ultron sincronizados com o Milvus"""
    clients = profile_mgr.list_clients(force_refresh_milvus=force_refresh)
    return {
        "total": len(clients),
        "clients": clients
    }

@app.get("/api/v1/clients/{client_id}")
def get_client_profile(client_id: str):
    """Retorna as configurações e pacotes do perfil de um cliente específico"""
    profile = profile_mgr.get_client_profile(client_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Perfil de cliente não encontrado")
    return profile

# --- Rotas de Integração Milvus ---

@app.get("/api/v1/milvus/config")
def get_milvus_config():
    """Retorna as configurações atuais e status da conexão com a Dashboard Milvus (192.168.57.7)"""
    return profile_mgr.get_milvus_config()

@app.post("/api/v1/milvus/config")
def update_milvus_config(req: MilvusConfigRequest):
    """Atualiza e salva as credenciais e parâmetros da Dashboard Milvus em config/settings.yaml"""
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
def test_milvus_connection(req: Optional[MilvusTestRequest] = None):
    """Testa a conectividade, latência e endpoints da Dashboard Milvus em tempo real"""
    custom_url = req.custom_url if req else None
    custom_token = req.custom_token if req else None
    result = profile_mgr.milvus.test_connection(custom_url=custom_url, custom_token=custom_token)
    return result

@app.get("/api/v1/milvus/client-tokens")
def get_milvus_client_tokens():
    """Retorna a lista de todos os clientes e seus tokens de instalação do agente Milvus (clients.yaml)"""
    tokens = profile_mgr.get_client_tokens()
    return {
        "total": len(tokens),
        "clients": tokens
    }

@app.post("/api/v1/milvus/client-tokens")
def update_milvus_client_token(req: ClientTokenUpdateRequest):
    """Atualiza o token de instalação do agente Milvus para um cliente específico em clients.yaml"""
    ok = profile_mgr.update_client_token(req.client_id, req.milvus_token)
    if not ok:
        raise HTTPException(status_code=500, detail="Falha ao atualizar token do cliente")
    return {
        "success": True,
        "client_id": req.client_id,
        "message": f"Token Milvus do cliente '{req.client_id}' atualizado com sucesso!"
    }

@app.get("/api/v1/milvus/tickets")
def get_milvus_tickets(force_refresh: bool = False):
    """Retorna a lista de chamados em aberto e pendentes na Dashboard Milvus (192.168.57.7)"""
    tickets = profile_mgr.milvus.get_open_tickets(force_refresh=force_refresh)
    return {
        "total": len(tickets),
        "milvus_online": profile_mgr.milvus.is_online(timeout=0.8),
        "tickets": tickets
    }

@app.post("/api/v1/milvus/sync")
def sync_milvus_data():
    """Força a sincronização imediata de clientes e chamados da Dashboard Milvus"""
    companies = profile_mgr.milvus.get_companies(force_refresh=True)
    tickets = profile_mgr.milvus.get_open_tickets(force_refresh=True)
    return {
        "success": True,
        "companies_synced": len(companies),
        "tickets_synced": len(tickets),
        "message": f"Sincronização concluída: {len(companies)} clientes e {len(tickets)} chamados obtidos da Dashboard Milvus"
    }

@app.get("/api/v1/milvus/agent/download/{client_id}")
def download_client_milvus_agent(client_id: str, force_download: bool = False):
    """
    Baixa ou entrega o instalador .MSI oficial do Agente Milvus já configurado com o token do cliente.
    Permite que qualquer máquina na rede ou técnico baixe o instalador pronto via API.
    """
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
def sync_all_milvus_agents(background_tasks: BackgroundTasks):
    """
    Baixa em lote e armazena em cache local os instaladores MSI de todos os clientes que possuem token configurado.
    """
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
def list_cached_agents():
    """Lista todos os instaladores MSI em cache local no servidor Ultron"""
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

@app.get("/api/v1/telemetry/wan")
def get_wan_telemetry():
    """Retorna telemetria de WAN, provedor ISP, ASN, geolocalização e latência do laboratório"""
    return NetworkDiagnosticsService.get_wan_diagnostics()

@app.get("/api/v1/telemetry/thermal")
def get_thermal_telemetry(lat: float = Query(-20.3155, description="Latitude do laboratório"), lon: float = Query(-40.3128, description="Longitude do laboratório")):
    """Retorna clima ambiente e análise de headroom térmico para testes de estresse (Burn-in)"""
    return LabWeatherService.get_ambient_conditions(lat=lat, lon=lon)

@app.get("/api/v1/tools/cve/search")
def search_cve_vulnerabilities(package: str = Query(..., description="Nome do pacote/software"), version: Optional[str] = Query(None, description="Versão específica")):
    """Consulta banco público de vulnerabilidades de segurança (OSV.dev & CIRCL CVE)"""
    return CveSecurityService.search_vulnerabilities(package, version)

@app.get("/api/v1/tools/cve/kev")
def get_cisa_kev_feed(limit: int = Query(6, description="Quantidade máxima de CVEs recentes")):
    """Retorna o catálogo CISA de vulnerabilidades exploradas ativamente na internet"""
    return CisaKevService.get_latest_exploited_vulns(limit=limit)

@app.get("/api/v1/tools/windows-error/lookup")
def lookup_windows_error(code: str = Query(..., description="Código de erro hexadecimal (ex: 0x80070005)")):
    """Decodifica códigos de erro hexadecimais do Windows/BSOD com causas e scripts de correção"""
    return WindowsErrorLookupService.lookup(code)

@app.get("/api/v1/tools/dns/inspect")
def inspect_domain_dns(domain: str = Query(..., description="Nome do domínio (ex: penserede.local)"), dns_server: Optional[str] = Query(None, description="Servidor DNS")):
    """Inspeciona resolução DNS e controladores de domínio AD (registros SRV) antes do Domain Join"""
    return DnsDiagnosticsService.inspect_domain(domain, dns_server)

@app.get("/api/v1/tools/ntp/check")
def check_ntp_drift():
    """Verifica sincronismo atômico do relógio local contra servidores NTP para autenticação Kerberos"""
    return NtpTimeService.check_clock_drift()

@app.get("/api/v1/tools/versions/check")
def check_bench_tools_versions():
    """Consulta as versões mais recentes das ferramentas de automação no GitHub Releases"""
    return {
        "tools": GitHubToolsVersionService.get_tools_versions()
    }

@app.get("/api/v1/tools/quote")
def get_tech_quote():
    """Retorna citação inspiracional de tecnologia para o console"""
    return TechWisdomService.get_quote()

@app.get("/api/v1/tools/mac/resolve")
def resolve_mac_vendor(mac: str = Query(..., description="Endereço MAC (ex: 00:14:22:01:23:45)")):
    """Identifica o fabricante de hardware OEM a partir do endereço MAC"""
    return MacVendorResolver.resolve(mac)

@app.get("/api/v1/tools/qr")
def get_qr_code_url(data: str = Query(..., description="Conteúdo textual ou URL para o QR Code"), size: int = Query(250, description="Tamanho em pixels")):
    """Gera URL de QR Code para visualização ou handoff mobile"""
    qr_url = QrCodeService.generate_qr_url(data, size)
    return {
        "data": data,
        "size": size,
        "qr_url": qr_url
    }

# --- Rotas de Bancada & Pipeline ---

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
def diagnose_machine(req: DiagnosticRequest):
    """Executa varredura de hardware e análise de IA na máquina alvo sem alterar configurações"""
    result = orchestrator.run_diagnostics_only(req.ip)
    return result

# --- Rotas de Ações Rápidas de Bancada ---

@app.post("/api/v1/bench/action/backup")
def execute_backup_action(req: BackupRequest):
    """Executa o script de backup de perfil de usuário da máquina alvo para o Storage Macrium"""
    backup_server = settings.get("network", {}).get("backup_server_ip", "192.168.57.112")
    params = {
        "TargetServer": backup_server,
        "ClientName": req.client_name,
        "TicketNumber": req.ticket_number or "",
        "SourceDrive": req.source_drive or "C:"
    }
    result = orchestrator.winrm.run_script_file(req.ip, "Backup-UserData.ps1", params=params)
    return {
        "success": result["success"],
        "ip": req.ip,
        "backup_server": backup_server,
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", "")
    }

@app.post("/api/v1/bench/action/power")
def execute_power_action(req: PowerActionRequest):
    """Executa reinicialização ou desligamento remoto da máquina de bancada"""
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
def execute_rename_action(req: RenameComputerRequest):
    """Altera o nome do computador (hostname) e reinicia opcionalmente"""
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
def execute_activation_action(req: ActivationRequest):
    """Executa a ativação automática do Windows e Office via Massgrave (MAS)"""
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
def install_packages_api(req: PackageInstallRequest):
    """Instala uma lista de pacotes via instalador unificado UniGetUI/Winget"""
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
def upgrade_all_packages_api(req: PackageUpgradeRequest):
    """Atualiza em massa todos os programas instalados na máquina alvo via Winget"""
    res = package_mgr.upgrade_all_packages(req.ip)
    return res

@app.post("/api/v1/packages/backup")
def backup_packages_api(req: PackageBackupRequest):
    """Varre e exporta todos os programas instalados em um bundle UniGetUI (.json)"""
    res = package_mgr.export_machine_packages(req.ip, identifier=req.identifier)
    return res

@app.post("/api/v1/packages/restore")
def restore_packages_api(req: PackageRestoreRequest):
    """Restaura um bundle UniGetUI (.json) previamente salvo na máquina alvo"""
    res = package_mgr.restore_machine_packages(req.ip, bundle_name_or_id=req.bundle_name)
    return res

@app.post("/api/v1/bench/action/install-software")
def execute_install_software_action(req: InstallSoftwareRequest):
    """Instala uma lista de pacotes via instalador unificado na máquina alvo"""
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
def execute_domain_join_action(req: DomainJoinRequest):
    """Executa a configuração de rede e o ingresso da máquina no domínio com credenciais dinâmicas"""
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
    session_id: Optional[str],
    domain_config: Optional[dict] = None
):
    callback = (lambda evt: manager.send_event(session_id, evt)) if session_id else None
    return orchestrator.run_pipeline(
        ip=ip,
        client_id=client_id,
        tech_user_id=tech_user_id,
        technician_name=technician_name,
        skip_burnin=skip_burnin,
        custom_packages=custom_packages,
        domain_config=domain_config,
        log_callback=callback
    )

@app.post("/api/v1/bench/run")
def run_bench_pipeline(req: RunPipelineRequest, background_tasks: BackgroundTasks, async_mode: bool = True):
    """Dispara a esteira completa de preparação da máquina (softwares, domínio, burn-in e laudo)"""
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
            session_id=req.session_id,
            domain_config=dom_dict
        )
        return {
            "status": "queued",
            "message": f"Esteira de automação iniciada em segundo plano para {req.ip}",
            "client_id": req.client_id,
            "ip": req.ip,
            "session_id": req.session_id
        }
    else:
        result = _execute_pipeline_task(
            ip=req.ip,
            client_id=req.client_id,
            tech_user_id=req.tech_user_id,
            technician_name=req.technician_name,
            skip_burnin=req.skip_burnin,
            custom_packages=req.custom_packages or [],
            session_id=req.session_id,
            domain_config=dom_dict
        )
        return result

@app.post("/api/v1/mdt/completed")
def mdt_completed(data: MDTNotification, background_tasks: BackgroundTasks):
    """
    Webhook chamado pelo script Notify-Ultron.ps1 ao final da Task Sequence do MDT
    """
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
def list_reports():
    """Lista todos os laudos técnicos em PDF gerados pelo Ultron"""
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
def download_report(filename: str):
    """Permite o download de um laudo técnico gerado"""
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
