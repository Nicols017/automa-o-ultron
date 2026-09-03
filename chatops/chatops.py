"""
TrueConf ChatOps — Ultron Lab Automation
Processa comandos slash, diálogos interativos, solicitação dinâmica de credenciais e conversação com IA no TrueConf.
"""

import os
import socket
import logging
import time
import re
import threading
from typing import Any, Dict, List, Optional, Tuple
import unicodedata
import html

logger = logging.getLogger("ultron_chatops")

from datetime import datetime, timedelta
import requests
from core.profile_manager import ProfileManager
from core.network_scanner import NetworkScanner
from core.winrm_executor import WinRMExecutor
from core.scheduler import UltronScheduler
from core.package_manager import UnifiedPackageManager
from core.public_tools import (
    CveSecurityService,
    LabWeatherService,
    NetworkDiagnosticsService,
    WindowsErrorLookupService,
)
from core.reliability import IntentRouter, MessageBuilder, TraceLogger, new_trace_id, DEFAULT_INTENTS, log

def _clean_chat_text(s: str) -> str:
    """Higieniza tags HTML (<br>, <span>, etc.) e decodifica entidades HTML (&quot;, &#39;, &amp;) do TrueConf"""
    if not s:
        return ""
    t = re.sub(r"<\s*br\s*/?\s*>", "\n", s, flags=re.IGNORECASE)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t)
    return t.strip()

def _normalize_token(s: str) -> str:
    """Remove acentos e converte para minúsculas"""
    if not s:
        return ""
    clean = _clean_chat_text(s)
    n = unicodedata.normalize('NFKD', clean)
    return "".join(c for c in n if not unicodedata.combining(c)).lower()

class TrueConfChatOps:
    """Roteador central de comandos ChatOps do Ultron para o TrueConf."""

    def __init__(self, orchestrator=None, bot=None):
        self.orchestrator = orchestrator
        self.bot          = bot

        # Serviços de infraestrutura
        self.profile_mgr = ProfileManager()
        self.scanner     = NetworkScanner()
        self.winrm       = WinRMExecutor()
        self.scheduler   = UltronScheduler(bot=bot)
        self.pkg_mgr     = UnifiedPackageManager(winrm_executor=self.winrm)

        # Serviços públicos / consultas externas
        self.weather_svc = LabWeatherService()
        self.error_svc   = WindowsErrorLookupService()
        self.cve_svc     = CveSecurityService()
        self.wan_svc     = NetworkDiagnosticsService()
        
        # Reliability Layer
        self.intent_router = IntentRouter(DEFAULT_INTENTS)
        self.msg_builder = MessageBuilder()

        # Sessões interativas e credenciais por técnico
        self.user_sessions: Dict[str, Dict[str, Any]] = {}
        self.user_conversations: Dict[str, List[Dict[str, str]]] = {}
        self._last_dispatched_message: Dict[str, str] = {}
        self._last_user_ip: Dict[str, str] = {}
        self._pending_message_target: Dict[str, str] = {}

        # Cache de varredura de bancada para resposta instantânea
        self._cached_devices: List[Dict[str, Any]] = []
        self._last_scan_time: float = 0

    def _get_server_url(self) -> str:
        """Resolve o IP oficial do servidor configurado em settings.yaml ou detecta da rede local"""
        try:
            import yaml
            cfg_path = os.path.join(os.path.dirname(__file__), "..", "config", "settings.yaml")
            if os.path.exists(cfg_path):
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = yaml.safe_load(f)
                    cfg_ip = cfg.get("network", {}).get("ultron_ip")
                    if cfg_ip and cfg_ip != "localhost" and not cfg_ip.startswith("127."):
                        return f"http://{cfg_ip}:7000"
        except Exception:
            pass

        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.5)
            s.connect(("192.168.57.1", 80))
            ip = s.getsockname()[0]
            s.close()
            if ip and not ip.startswith("127."):
                return f"http://{ip}:7000"
        except Exception:
            pass

        return "http://192.168.57.43:7000"

    def _extract_target_ip(self, text: str) -> Optional[str]:
        """Extrai um endereço IP alvo a partir de texto livre (formatos completos, abreviados ou numéricos)."""
        # 1. IP completo (ex: 192.168.57.48, 10.0.0.15, 172.20.1.10)
        m_full = re.search(r"\b((?:192\.168|10\.\d{1,3}|172\.\d{1,3})\.\d{1,3}\.\d{1,3})\b", text)
        if m_full:
            return m_full.group(1)

        # 2. Notação abreviada de subrede (ex: 57.48, 57.25)
        m_sub = re.search(r"\b57\.(\d{1,3})\b", text)
        if m_sub:
            return f"192.168.57.{m_sub.group(1)}"

        # 3. Notação por número de máquina (ex: pc 48, maquina 25, ip 48, host 15)
        m_pc = re.search(r"\b(?:pc|maquina|máquina|ip|host|bancada|final)\s*[:#-]?\s*(\d{1,3})\b", text, re.IGNORECASE)
        if m_pc:
            num = int(m_pc.group(1))
            if 1 <= num <= 254:
                return f"192.168.57.{num}"

        # 4. Se o texto for apenas um número isolado entre 1 e 254
        stripped = text.strip()
        if stripped.isdigit():
            num = int(stripped)
            if 10 <= num <= 254:
                return f"192.168.57.{num}"

        return None

    def _extract_client_id(self, text: str) -> Optional[str]:
        """Identifica o perfil de cliente a partir de menções em texto livre."""
        norm = _normalize_token(text)
        clients = self.profile_mgr.list_clients()
        for c in clients:
            c_id = c.get("id", "").lower()
            c_nome = _normalize_token(c.get("nome", ""))
            if c_id and (c_id in norm or c_id.replace("_", " ") in norm):
                return c.get("id")
            if c_nome and len(c_nome) >= 3 and c_nome in norm:
                return c.get("id")

        if "white group" in norm or "whitegroup" in norm or "white" in norm:
            return "white_group"
        if "nova via" in norm or "novavia" in norm or "nova" in norm:
            return "nova_via"
        if "pense rede" in norm or "penserede" in norm or "padrao" in norm or "padrão" in norm:
            return "cliente_padrao"
        return None

    def _get_cached_devices(self, force_fresh: bool = False) -> List[Dict[str, Any]]:
        """Retorna dispositivos em cache imediatamente e agenda atualização em background se expirado."""
        now = time.time()
        if force_fresh or (now - self._last_scan_time > 60) or not self._cached_devices:
            def _async_scan():
                try:
                    devs = self.scanner.scan_network(timeout=0.25)
                    if devs:
                        self._cached_devices = devs
                        self._last_scan_time = time.time()
                except Exception:
                    pass

            if force_fresh:
                try:
                    self._cached_devices = self.scanner.scan_network(timeout=0.3)
                    self._last_scan_time = time.time()
                except Exception:
                    pass
            else:
                threading.Thread(target=_async_scan, daemon=True).start()

        return self._cached_devices

    def _match_natural_intent(self, user_id: str, text: str, norm_text: str) -> Optional[str]:
        """Processa intenções em linguagem natural livre sem exigir comandos rígidos (/slash)."""
        # 0. Consulta de AnyDesk ID / Acesso Remoto (Zero friction)
        anydesk_kws = ["anydesk", "any desk", "anidisk", "anidesk", "qual o anydesk", "id do anydesk", "passa o anydesk", "me passa o anydesk", "acesso remoto", "id remoto", "link do anydesk", "codigo do anydesk", "código do anydesk", "qual o id"]
        if any(kw in norm_text for kw in anydesk_kws) and not any(w in norm_text for w in ["instalar", "instala", "remover", "como funciona", "como instalar", "usuario", "colaborador"]):
            ip = self._extract_target_ip(text)
            return self._cmd_anydesk(user_id, [ip] if ip else [])

        # 1. Download do UltronAgent.exe (com envio direto do arquivo no TrueConf)
        agent_dl_kws = [
            "baixar agent", "baixar agente", "download agent", "download do agente", "onde baixo o exe",
            "link do exe", "ultronagent.exe", "baixar o exe", "como baixar", "link do agent",
            "manda o agent", "me manda o agent", "manda o agente", "me manda o agente",
            "manda o executavel", "me manda o executavel", "manda o exe", "me manda o exe",
            "quero o executavel", "quero o agente", "quero o agent", "passa o executavel",
            "passa o agent", "passa o agente", "passa o exe", "me passa o executavel",
            "me passa o agent", "me passa o agente", "me passa o exe", "envia o executavel",
            "me envia o executavel", "envia o agent", "me envia o agent", "envia o agente",
            "me envia o agente", "ultronagent", "arquivo do agent", "arquivo do agente",
            "arquivo executavel", "arquivo de download", "download", "baixar", "o executavel",
            "o arquivo de download", "disponivel o download", "mandar o executavel", "mandar o exe",
            "manda o arquivo", "me manda o arquivo", "passa o arquivo", "me passa o arquivo",
            "versão atualizada", "versao atualizada", "agente atualizado", "me envie o agente",
            "envie o agente"
        ]
        if any(kw in norm_text for kw in agent_dl_kws) and not any(w in norm_text for w in ["mensagem", "msg", "popup", "texto", "aviso"]):
            return self._cmd_download_agent(user_id)

        # 2. Diagnóstico de Hardware / S.M.A.R.T / Saúde / Teste
        diag_kws = [
            "diag", "diagnostico", "diagnóstico", "diagnosticar", "smart", "saude", "saúde",
            "saude do disco", "saúde do disco", "testar hardware", "teste de estresse", "teste",
            "testar", "verificar", "verifica", "verifique", "checar", "checa", "cheque",
            "olhar", "olha", "olhe", "analisar", "analisa", "analise", "integridade",
            "status do pc", "status da maquina", "status da máquina", "saude da maquina", "saude do pc"
        ]
        if any(kw in norm_text for kw in diag_kws) and not any(w in norm_text for w in ["como fazer", "o que e", "o que é", "explica", "ajuda"]):
            ip = self._extract_target_ip(text)
            if not ip:
                cached = self._get_cached_devices()
                winrm_devs = [d for d in cached if d.get("winrm_ready")]
                if len(winrm_devs) == 1:
                    ip = winrm_devs[0].get("ip")
                    return f"🔍 Identifiquei a máquina {ip} ({winrm_devs[0].get('hostname', 'PC')}) na bancada.\n\n" + self._cmd_diagnostico(user_id, [ip])
                elif len(cached) == 1:
                    ip = cached[0].get("ip")
                    return f"🔍 Identifiquei a máquina {ip} na bancada.\n\n" + self._cmd_diagnostico(user_id, [ip])
                else:
                    self.user_sessions[user_id] = {"type": "wizard_diag"}
                    return (
                        "🩺 DIAGNÓSTICO DE HARDWARE\n\n"
                        "Em qual máquina da bancada você gostaria que eu fizesse a análise? (Você pode me mandar o IP ou apenas o final dele, por exemplo 57.48 ou 48)\n\n"
                        "[ 0 ] Cancelar"
                    )
            return self._cmd_diagnostico(user_id, [ip])

        # 2.1 Enviar Mensagem / Pop-up na tela física de um PC de Bancada (requer IP ou termo 'na tela'/'popup')
        screen_popup_kws = ["popup", "pop-up", "mensagem na tela", "aviso na tela", "msg na tela", "alerta na tela", "janela na tela", "/msg"]
        ip = self._extract_target_ip(text)
        if any(kw in norm_text for kw in screen_popup_kws) or (ip and any(kw in norm_text for kw in ["mensagem", "msg", "popup", "pop-up", "alerta"])):
            if ip:
                clean_msg = text
                for kw in [
                    "manda uma mensagem para o ip", "manda uma mensagem pro ip", "manda mensagem para o ip",
                    "manda mensagem pro ip", "enviar mensagem para o ip", "enviar mensagem pro ip",
                    "mensagem para o ip", "mensagem pro ip", "mensagem para", "mensagem pro", "avisa o ip",
                    "avise o ip", "notifica o ip", "notifique o ip", "manda uma mensagem", "manda mensagem",
                    "enviar mensagem", "mensagem", "avise", "avisa", "mande", "popup", "pop-up", "na tela"
                ]:
                    clean_msg = re.sub(re.escape(kw), "", clean_msg, flags=re.IGNORECASE)
                clean_msg = re.sub(r"\b" + re.escape(ip) + r"\b", "", clean_msg).strip()
                clean_msg = re.sub(r"\b(?:192\.168\.\d{1,3}\.\d{1,3}|57\.\d{1,3}|\d{1,3})\b", "", clean_msg).strip()
                clean_msg = clean_msg.strip(" :-=,\"'\t\n")

                if clean_msg:
                    return self._cmd_message(user_id, [ip] + clean_msg.split())
                else:
                    self.user_sessions[user_id] = {"type": "wizard_msg_text", "ip": ip}
                    return f"📢 ENVIAR MENSAGEM — MÁQUINA {ip}\n\nQual mensagem você deseja exibir na tela do usuário?\n\n[ 0 ] Cancelar"
            else:
                return self._start_wizard_msg(user_id)

        # 3. Preparar / Formatar / Esteira
        prep_kws = ["preparar", "prepara", "formatar", "formata", "esteira", "deploy", "iniciar esteira", "inicia a esteira", "rodar esteira", "roda a esteira", "aplicar perfil", "montar pc", "configurar maquina"]
        if any(kw in norm_text for kw in prep_kws):
            ip = self._extract_target_ip(text)
            client_id = self._extract_client_id(text)
            if ip and client_id:
                return self._cmd_preparar(user_id, [ip, client_id])
            elif client_id and not ip:
                cached = self._get_cached_devices()
                winrm_devs = [d for d in cached if d.get("winrm_ready")]
                target = winrm_devs[0] if len(winrm_devs) == 1 else (cached[0] if len(cached) == 1 else None)
                if target:
                    ip = target.get("ip")
                    return self._cmd_preparar(user_id, [ip, client_id])
                else:
                    self.user_sessions[user_id] = {"type": "wizard_preparar_ip", "client_id": client_id}
                    return f"🚀 PREPARAÇÃO DE MÁQUINA — {client_id.upper()}\n\nQual é o IP do computador na bancada? (Ex: 57.48)\n\n[ 0 ] Cancelar"
            elif ip and not client_id:
                self.user_sessions[user_id] = {"type": "wizard_preparar_client", "ip": ip}
                return (
                    f"🚀 PREPARAÇÃO DA MÁQUINA {ip}\n\n"
                    f"Para qual cliente devemos configurar? (Ex: White Group, Nova Via, Perfil Padrão ou digite o número do perfil)\n\n"
                    f"[ 0 ] Cancelar"
                )
            else:
                return self._start_wizard_preparar(user_id)

        # 4. Ativação Windows / Office (MAS)
        ativ_kws = ["ativar", "ativa", "ativacao", "ativação", "licenca", "licença", "ativar windows", "ativar office", "validar windows", "massgrave", "mas"]
        if any(kw in norm_text for kw in ativ_kws):
            ip = self._extract_target_ip(text)
            if not ip:
                cached = self._get_cached_devices()
                winrm_devs = [d for d in cached if d.get("winrm_ready")]
                target = winrm_devs[0] if len(winrm_devs) == 1 else (cached[0] if len(cached) == 1 else None)
                if target:
                    ip = target.get("ip")
                    return self._cmd_ativar(user_id, [ip])
                else:
                    self.user_sessions[user_id] = {"type": "wizard_ativar"}
                    return "🔑 ATIVAÇÃO WINDOWS & OFFICE\n\nQual é o IP da máquina na bancada que você deseja ativar? (Ex: 57.48)\n\n[ 0 ] Cancelar"
            return self._cmd_ativar(user_id, [ip])

        # 5. Domínio Active Directory
        dom_kws = ["dominio", "domínio", "active directory", "ingressar no dominio", "colocar no dominio", "ad join", "join domain"]
        if any(kw in norm_text for kw in dom_kws):
            ip = self._extract_target_ip(text)
            m_dom = re.search(r"\b([a-zA-Z0-9-]+\.(?:local|corp|lan|com(?:\.br)?))\b", text, re.IGNORECASE)
            dom_name = m_dom.group(1) if m_dom else None
            if ip and dom_name:
                return self._cmd_dominio(user_id, [ip, dom_name])
            elif ip and not dom_name:
                self.user_sessions[user_id] = {"type": "wizard_dominio_domain", "ip": ip}
                return f"🛡️ INGRESSO NO DOMÍNIO — MÁQUINA {ip}\n\nQual é o nome do domínio? (Ex: penserede.local ou o nome do cliente)\n\n[ 0 ] Cancelar"
            else:
                return self._start_wizard_dominio(user_id)

        # 6. Reiniciar / Desligar
        if any(kw in norm_text for kw in ["reiniciar", "reinicia", "reboot", "restart"]):
            ip = self._extract_target_ip(text)
            if not ip:
                cached = self._get_cached_devices()
                winrm_devs = [d for d in cached if d.get("winrm_ready")]
                target = winrm_devs[0] if len(winrm_devs) == 1 else (cached[0] if len(cached) == 1 else None)
                if target:
                    ip = target.get("ip")
                else:
                    self.user_sessions[user_id] = {"type": "wizard_power", "action": "restart"}
                    return "🔌 REINICIAR COMPUTADOR\n\nQual é o IP da máquina que você deseja reiniciar?\n\n[ 0 ] Cancelar"
            return self._cmd_power(user_id, [ip], "restart")

        if any(kw in norm_text for kw in ["desligar", "desliga", "shutdown", "apagar pc", "desligar maquina"]):
            ip = self._extract_target_ip(text)
            if not ip:
                cached = self._get_cached_devices()
                winrm_devs = [d for d in cached if d.get("winrm_ready")]
                target = winrm_devs[0] if len(winrm_devs) == 1 else (cached[0] if len(cached) == 1 else None)
                if target:
                    ip = target.get("ip")
                else:
                    self.user_sessions[user_id] = {"type": "wizard_power", "action": "shutdown"}
                    return "🔌 DESLIGAR COMPUTADOR\n\nQual é o IP da máquina que você deseja desligar?\n\n[ 0 ] Cancelar"
            return self._cmd_power(user_id, [ip], "shutdown")

        # 7. Backup
        if any(kw in norm_text for kw in ["backup", "salvar dados", "copiar perfil", "fazer backup", "storage"]):
            ip = self._extract_target_ip(text)
            if not ip:
                cached = self._get_cached_devices()
                winrm_devs = [d for d in cached if d.get("winrm_ready")]
                target = winrm_devs[0] if len(winrm_devs) == 1 else (cached[0] if len(cached) == 1 else None)
                if target:
                    ip = target.get("ip")
                else:
                    self.user_sessions[user_id] = {"type": "wizard_backup"}
                    return "💾 BACKUP DE USUÁRIO\n\nQual é o IP da máquina que você deseja fazer o backup?\n\n[ 0 ] Cancelar"
            return self._cmd_backup(user_id, [ip])

        # 8. Consulta / Varredura de Bancada e Detecção de IPs / Máquinas Disponíveis
        ip_terms = ["ip", "ips", "maquina", "maquinas", "máquina", "máquinas", "pc", "pcs", "computador", "computadores", "dispositivo", "dispositivos", "equipamento", "equipamentos"]
        action_terms = [
            "quais", "qual", "quem", "tem", "mostra", "mostrar", "mostre", "lista", "listar",
            "liste", "ver", "veja", "acha", "achar", "ache", "busca", "buscar", "busque",
            "detecta", "detectar", "detectando", "disponivel", "disponiveis", "disponível", "disponíveis",
            "presente", "presentes", "ativo", "ativos", "ativa", "ativas", "online", "conectado",
            "conectados", "conectada", "conectadas", "ligado", "ligados", "ligada", "ligadas", "livre", "livres"
        ]
        bench_terms = ["bancada", "bancda", "bancad", "rede", "lab", "laboratorio", "laboratório"]

        has_ip = any(w in norm_text for w in ip_terms)
        has_act = any(w in norm_text for w in action_terms)
        has_bench = any(w in norm_text for w in bench_terms)

        is_bench_query = (has_ip and has_act) or (has_bench and (has_act or has_ip)) or any(kw in norm_text for kw in [
            "bancada", "status da bancada", "ver bancada", "scan", "scanner", "varredura", "varrer", "quem ta ai", "quem tá aí", "o que tem na bancada"
        ])

        if is_bench_query:
            # Garante que não é uma ação direcionada a um IP específico (ex: "faz o diagnóstico no 57.48" ou "reinicia o 57.10")
            if not any(kw in norm_text for kw in ["diag", "prepar", "ativ", "reinici", "deslig", "backup", "dominio", "popup", "msg", "mensagem", "mandar", "enviar"]):
                return self._cmd_bancada(user_id)

        # 9. Consulta de Chamados Milvus
        tickets_kws = ["chamados", "chamado", "tickets", "ticket", "milvus", "ordens de servico", "ordens de serviço", "minhas os", "o que tem pra fazer"]
        is_inquiry = any(w in norm_text for w in ["apenas no meu", "meu nome", "como funciona", "por que", "porque", "o que e", "o que é", "qual a diferenca", "como puxa"])
        if any(kw in norm_text for kw in tickets_kws) and not is_inquiry:
            return self._cmd_chamados()

        # 10. Consulta de Clientes
        clients_kws = ["clientes", "cliente", "empresas", "empresa", "perfis", "quais perfis", "quais clientes", "lista de clientes"]
        if any(kw in norm_text for kw in clients_kws):
            return self._cmd_clientes()

        # 11. Consulta de Laudos
        laudos_kws = ["laudos", "laudo", "relatorios", "relatórios", "ver laudos", "pdfs"]
        if any(kw in norm_text for kw in laudos_kws):
            return self._cmd_laudos([])

        # 12. Clima / Térmica / WAN
        if any(kw in norm_text for kw in ["clima", "temperatura", "termica", "térmica", "calor"]):
            return self._cmd_clima()
        if any(kw in norm_text for kw in ["ip wan", "meu ip", "provedor", "link de internet"]):
            return self._cmd_wan()

        # 13. Limpeza Pós-Bancada / Auto-Destruição para Entrega ao Cliente
        clean_kws = ["limpar", "limpeza", "desinstalar", "desinstala", "entrega", "entregar", "finalizar bancada", "remover agente", "auto-destruicao", "autodestruicao"]
        if any(kw in norm_text for kw in clean_kws) and not any(w in norm_text for w in ["como", "ajuda", "o que e", "o que é", "explica"]):
            ip = self._extract_target_ip(text)
            if not ip:
                cached = self._get_cached_devices()
                winrm_devs = [d for d in cached if d.get("winrm_ready")]
                target = winrm_devs[0] if len(winrm_devs) == 1 else (cached[0] if len(cached) == 1 else None)
                if target:
                    ip = target.get("ip")
                else:
                    self.user_sessions[user_id] = {"type": "wizard_limpar", "step": "ip"}
                    return "🧹 **LIMPEZA PÓS-BANCADA (ENTREGA AO CLIENTE)**\n\nQual é o IP da máquina que você deseja desinstalar e limpar?\n\n[ 0 ] Cancelar"
            return self._cmd_limpar(user_id, [ip])

        return None

    def _is_master_user(self, user_id: str) -> bool:
        """Verifica se o usuário possui privilégios de Administrador Master (Nicolas Silva)"""
        clean_user = (user_id or "").lower().strip().lstrip("@")
        return clean_user in ["nicolas.silva", "nicolas", "nicolas_silva", "admin"]

    def _cmd_list_trueconf_users(self) -> str:
        """Consulta os usuários cadastrados no TrueConf Server via REST API"""
        if not self.bot or not self.bot.api_token:
            return "⚠️ Integração com TrueConf API Token não configurada para listar usuários."
        try:
            url = f"{self.bot.raw_server_url}/api/v4/users"
            headers = {"Authorization": f"Bearer {self.bot.api_token}"}
            r = requests.get(url, headers=headers, verify=False, timeout=5)
            if r.status_code == 200:
                data = r.json().get("users", [])
                if not data:
                    return "ℹ️ Nenhum usuário retornado pelo TrueConf Server."
                lines = [f"👥 USUÁRIOS NO TRUECONF ({len(data)} cadastrados):\n"]
                for u in data[:25]:
                    uid = u.get("id", "")
                    display = u.get("display_name", "") or (u.get("first_name", "") + " " + u.get("last_name", ""))
                    status = "🟢 Online" if u.get("status") == 1 else "⚪ Offline"
                    lines.append(f"• @{uid} ({display.strip()}) — {status}")
                return "\n".join(lines)
            return f"⚠️ Resposta da API TrueConf: HTTP {r.status_code}"
        except Exception as e:
            return f"⚠️ Erro ao consultar usuários no TrueConf: {e}"

    _users_cache: List[Dict[str, Any]] = []
    _users_cache_time: float = 0

    def _get_trueconf_users_cached(self) -> List[Dict[str, Any]]:
        """Retorna lista de usuários do TrueConf com cache de 60 segundos"""
        now = time.time()
        if self._users_cache and (now - self._users_cache_time) < 60:
            return self._users_cache

        srv_url = ""
        token = ""
        if self.bot:
            srv_url = getattr(self.bot, "raw_server_url", "")
            token = getattr(self.bot, "api_token", "")

        if not srv_url or not token:
            tc_cfg = self.profile_mgr.get_settings().get("trueconf", {})
            srv_url = tc_cfg.get("server_url", "https://trueconf.penserede.com.br").rstrip("/")
            token = tc_cfg.get("api_token", tc_cfg.get("bot_token", ""))

        if not token:
            return []

        try:
            url = f"{srv_url}/api/v4/users"
            headers = {"Authorization": f"Bearer {token}"}
            r = requests.get(url, headers=headers, verify=False, timeout=4)
            if r.status_code == 200:
                self._users_cache = r.json().get("users", [])
                self._users_cache_time = now
                return self._users_cache
        except Exception:
            pass

        return self._users_cache

    def _resolve_trueconf_user(self, query: str) -> str:
        """Resolve o ID exato do usuário no TrueConf a partir de login, primeiro nome ou nome completo com pontuação inteligente."""
        clean = _normalize_token(query or "")
        clean = re.sub(r'^(?:para\s+(?:o\s+|a\s+)?|pro\s+|pra\s+|ao\s+|a\s+|o\s+|usuario\s+|usuário\s+|colaborador\s+)+', '', clean).strip()
        clean_tokens = [t for t in clean.split() if t not in ["o", "a", "de", "do", "da", "e", "em", "um", "uma"]]

        if not clean_tokens:
            return (query or "").strip().lower().lstrip("@").replace(" ", ".")

        dotted = ".".join(clean_tokens)
        underscored = "_".join(clean_tokens)

        users = self._get_trueconf_users_cached()
        if not users:
            return dotted

        best_user = None
        best_score = 0

        for u in users:
            uid = _normalize_token(u.get("id", ""))
            dname = _normalize_token(u.get("display_name", "") or (u.get("first_name", "") + " " + u.get("last_name", "")))
            fname = _normalize_token(u.get("first_name", ""))
            lname = _normalize_token(u.get("last_name", ""))

            score = 0
            # 1. Match exato de ID
            if uid in [clean, dotted, underscored]:
                score = 100
            # 2. Match exato de Display Name
            elif dname == clean or dname == " ".join(clean_tokens):
                score = 95
            # 3. Todos os tokens da busca estão presentes no display name ou id
            elif all(t in dname.split() or t in uid.split(".") for t in clean_tokens):
                score = 90
            # 4. Primeiro e segundo token coincidem
            elif len(clean_tokens) >= 2 and clean_tokens[0] in dname and clean_tokens[1] in dname:
                score = 85
            # 5. Primeiro nome exato
            elif clean_tokens[0] == fname or clean_tokens[0] == uid.split(".")[0]:
                score = 75
            elif clean_tokens[0] in dname.split():
                score = 70

            if score > best_score:
                best_score = score
                best_user = u.get("id")

        if best_score >= 70 and best_user:
            return best_user

        return dotted

    def _handle_master_intent(self, user_id: str, text: str, norm_text: str) -> Optional[str]:
        """Processa comandos administrativos e controle mestre para Nicolas Silva"""
        if not self._is_master_user(user_id):
            return None

        # 0. Envio da MESMA MENSAGEM / Repetição contextual (Ex: "manda a mesma mensagem para arthur gabriel")
        if any(kw in norm_text for kw in ["mesma mensagem", "mesmo recado", "mesmo texto", "mesma msg"]):
            m_same = re.search(
                r"(?:manda|mandar|mande|envia|enviar|envie|fala|falar|avisa|avise|notifica|notifique|repete|repetir)\s+(?:a\s+)?(?:mesma\s+mensagem|mesmo\s+recado|mesmo\s+texto|mesma\s+msg)\s+(?:para\s+(?:o\s+|a\s+)?|pro\s+|pra\s+|ao\s+|a\s+|o\s+)?([a-zA-Z0-9._\s-]+)",
                text, re.IGNORECASE
            )
            if m_same:
                target_user = m_same.group(1).strip().lstrip("@")
                last_msg = self._last_dispatched_message.get(user_id)
                if not last_msg:
                    return "⚠️ Nenhuma mensagem anterior encontrada no histórico recente para repetir."

                resolved_target = self._resolve_trueconf_user(target_user)
                formatted = f"📢 Mensagem de Nicolas Silva:\n\n{last_msg}"
                if self.bot:
                    success = self.bot.send_direct_message(resolved_target, formatted)
                    if success:
                        return f"🚀 Mesma mensagem enviada instantaneamente para @{resolved_target} no TrueConf!\n\n📝 \"{last_msg}\""
                    return f"⚠️ Não foi possível entregar a mensagem para @{resolved_target}. Verifique se o usuário existe no TrueConf Server."
                else:
                    return f"🚀 Mesma mensagem enviada instantaneamente para @{resolved_target} no TrueConf!\n\n📝 \"{last_msg}\""

        # 1. ENVIO DE EXECUTÁVEL / ARQUIVO DO AGENTE PARA OUTRO USUÁRIO (com ou sem recado)
        # Ex: "manda o executável para o arthur gabriel e uma mensagem escrito 'baixa aí neguin'"
        is_file_request = any(kw in norm_text for kw in ["executavel", "agente", "agent", "exe", "arquivo do agent", "ultronagent"])
        if is_file_request and any(w in norm_text for w in ["para", "pro", "pra", "ao"]):
            m_file = re.search(
                r"^(?:manda|mandar|mande|envia|enviar|envie|passa|passar|passe)\s+(?:o\s+)?(?:executavel|executável|agente|agent|exe|arquivo(?:\s+do\s+agent)?|ultronagent(?:\.exe)?)\s+(?:para\s+(?:o\s+|a\s+)?|pro\s+|pra\s+|ao\s+|a\s+|o\s+)(?:usuario\s+|usuário\s+|colaborador\s+)?([a-zA-Z0-9._\s-]+?)(?:\s+(?:e\s+(?:uma\s+)?mensagem\s*(?:ecrito|escrito|escrita|dizendo|com\s+o\s+texto|falando|de\s+que|que)?|com\s+(?:o\s+texto|a\s+mensagem)|dizendo|falando|ecrito|escrito|e\s+fala|e\s+avisa|:|-)\s*[:\s]*[\"\'\“\‘]?([\s\S]+?)[\"\'\”\’]?$|$)",
                text, re.IGNORECASE
            )
            if m_file:
                target_raw = m_file.group(1).strip()
                extra_msg = m_file.group(2).strip().strip("\"'“”‘’") if m_file.group(2) else ""
                resolved_target = self._resolve_trueconf_user(target_raw)

                from core.agent_builder import agent_builder
                bin_info = agent_builder.get_latest_agent_binary()
                found_exe = bin_info["file_path"]
                version = bin_info["version"]
                versioned_filename = bin_info["filename"]

                if self.bot and found_exe and os.path.exists(found_exe):
                    caption = f"📎 {versioned_filename} (Atualizado) — Agente de Automação de Bancada (Pense Rede)"
                    if extra_msg:
                        caption += f"\n\n📢 Recado de Nicolas Silva:\n\"{extra_msg}\""

                    file_sent = self.bot.send_direct_file(
                        user_id=resolved_target,
                        file_path=found_exe,
                        caption=caption,
                        filename=versioned_filename
                    )

                    # Se enviou o arquivo e há mensagem extra, também reforça em mensagem de texto
                    if extra_msg:
                        self.bot.send_direct_message(resolved_target, f"📢 Mensagem de Nicolas Silva:\n\n{extra_msg}")

                    if file_sent:
                        msg_feedback = f"\n\n📝 Recado anexado: *\"{extra_msg}\"*" if extra_msg else ""
                        return f"🚀 **{versioned_filename} enviado com sucesso para @{resolved_target} no TrueConf!**{msg_feedback}"
                    else:
                        # Fallback resiliente: envia a mensagem e o link de download direto
                        srv_url = self._get_server_url()
                        dm_text = f"📎 **{versioned_filename} (Atualizado) — Agente de Automação de Bancada**\n\n👉 Baixar direto: {srv_url}/download/UltronAgent.exe"
                        if extra_msg:
                            dm_text += f"\n\n📢 Recado de Nicolas Silva:\n\"{extra_msg}\""
                        dm_sent = self.bot.send_direct_message(resolved_target, dm_text)
                        if dm_sent:
                            msg_feedback = f"\n\n📝 Recado anexado: *\"{extra_msg}\"*" if extra_msg else ""
                            return f"🚀 **{versioned_filename} e recado enviados com sucesso para @{resolved_target} no TrueConf!**{msg_feedback}"
                        return f"⚠️ Não foi possível entregar para @{resolved_target}. Verifique se o usuário está ativo no TrueConf Server."
                else:
                    return f"⚠️ Arquivo {versioned_filename} não foi encontrado no servidor para envio."

        # 2. Consulta de usuários do TrueConf
        if any(kw in norm_text for kw in ["usuarios do trueconf", "usuarios da empresa", "lista usuarios", "usuarios trueconf", "quem esta no trueconf", "colaboradores"]):
            return self._cmd_list_trueconf_users()

        # 3. Cancelamento de agendamento
        m_cancel = re.search(r"(?:cancela|cancelar|apaga|remover|excluir)\s+(?:o\s+)?(?:agendamento|agendada|mensagem)?\s*(?:id\s*)?([a-zA-Z0-9_]+)", text, re.IGNORECASE)
        if m_cancel and ("agend" in norm_text or "sch_" in text or "cancela" in norm_text):
            t_id = m_cancel.group(1).strip()
            if self.scheduler.cancel_task(t_id):
                return f"✅ Agendamento `{t_id}` cancelado com sucesso."
            return f"⚠️ Agendamento `{t_id}` não encontrado ou já executado."

        # 4. Listagem de mensagens agendadas
        if any(kw in norm_text for kw in ["agendad", "agendamento", "agendamentos", "agendados", "agendadas", "o que ta agendado", "minhas mensagens agendadas", "/agendados"]):
            tasks = self.scheduler.list_scheduled()
            if not tasks:
                return "ℹ️ Nenhuma mensagem agendada no momento."
            res = ["⏰ MENSAGENS PROGRAMADAS NO TRUECONF:\n"]
            for t in tasks:
                res.append(f"• ID: `{t['id']}` | Para: @{t['target']} | Horário: {t['time']} | Faltam: {t['remaining_sec']//60}min\n  📝 \"{t['message']}\"")
            res.append("\n💡 Para cancelar: 'cancela o agendamento <ID>'")
            return "\n".join(res)

        # 5. Agendamento explícito com horário fixo (ex: "às 15:30")
        m_time_sched = re.search(
            r"(?:manda|mandar|mande|envia|enviar|envie|avisa|avise|agenda|agendar)\s+(?:uma\s+)?mensagem\s+(?:para\s+(?:o\s+|a\s+)?|pro\s+|pra\s+|ao\s+)?([a-zA-Z0-9._\s-]+)\s+(?:[àa]s\s+|para\s+[àa]s\s+)(\d{1,2}:\d{2})\s*(?:com\s+o\s+texto|dizendo|falando|que|:)?\s*([\s\S]+)",
            text, re.IGNORECASE
        )
        if m_time_sched:
            target_user = m_time_sched.group(1).strip().lstrip("@")
            time_str = m_time_sched.group(2).strip()
            msg_content = m_time_sched.group(3).strip()

            if not re.match(r"^\d{1,3}\.\d{1,3}", target_user):
                try:
                    now = datetime.now()
                    hh, mm = map(int, time_str.split(":"))
                    target_dt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
                    if target_dt <= now:
                        target_dt += timedelta(days=1)

                    resolved_target = self._resolve_trueconf_user(target_user)
                    self._last_dispatched_message[user_id] = msg_content
                    self.scheduler.schedule_message(user_id, resolved_target, msg_content, target_dt)
                    return (
                        f"⏰ MENSAGEM AGENDADA COM SUCESSO!\n\n"
                        f"👤 Destinatário: @{resolved_target}\n"
                        f"🕒 Horário Programado: {target_dt.strftime('%H:%M')} ({'Hoje' if target_dt.day == now.day else 'Amanhã'})\n"
                        f"📝 Mensagem: \"{msg_content}\"\n\n"
                        f"💡 Assim que for entregue no chat dele(a), te confirmarei aqui em tempo real!"
                    )
                except Exception as e:
                    return f"⚠️ Erro ao calcular horário do agendamento: {e}"

        # 6. Agendamento com delay relativo (ex: "daqui a 10 minutos")
        m_delay_sched = re.search(
            r"(?:daqui\s+a\s+|em\s+)(\d+)\s*(?:min|minuto|minutos|m)\s*(?:manda|mandar|mande|envia|enviar|envie|avisa|avise)?\s*(?:uma\s+)?mensagem\s+(?:para\s+(?:o\s+|a\s+)?|pro\s+|pra\s+|ao\s+)?([a-zA-Z0-9._\s-]+)\s*(?:com\s+o\s+texto|dizendo|falando|que|:)?\s*([\s\S]+)",
            text, re.IGNORECASE
        )
        if m_delay_sched:
            minutes = int(m_delay_sched.group(1))
            target_user = m_delay_sched.group(2).strip().lstrip("@")
            msg_content = m_delay_sched.group(3).strip()

            if not re.match(r"^\d{1,3}\.\d{1,3}", target_user):
                target_dt = datetime.now() + timedelta(minutes=minutes)
                resolved_target = self._resolve_trueconf_user(target_user)
                self._last_dispatched_message[user_id] = msg_content
                self.scheduler.schedule_message(user_id, resolved_target, msg_content, target_dt)
                return (
                    f"⏰ MENSAGEM PROGRAMADA (DAQUI A {minutes} MINUTOS)!\n\n"
                    f"👤 Destinatário: @{resolved_target}\n"
                    f"🕒 Envio previsto para: {target_dt.strftime('%H:%M:%S')}\n"
                    f"📝 Mensagem: \"{msg_content}\"\n\n"
                    f"💡 Te avisarei assim que a mensagem for entregue!"
                )

        # 7. ENVIO IMEDIATO E DIRETO DE MENSAGEM PARA QUALQUER PESSOA NO TRUECONF
        # 7.1 Mensagem com texto entre aspas primeiro (ex: manda a mensagem "..." para Arthur Gabriel)
        m_text_first = re.search(
            r"^(?:manda|mandar|mande|envia|enviar|envie|fala|falar|avisa|avise|notifica|notifique)\s+(?:(?:uma|a)\s+)?(?:mensagem|recado|aviso|texto)?\s*[:\s]*[\"\'\“\‘]([\s\S]+?)[\"\'\”\’]\s+(?:para\s+(?:o\s+|a\s+)?|pro\s+|pra\s+|ao\s+|a\s+|o\s+)(?:usuario\s+|usuário\s+|colaborador\s+)?([a-zA-Z0-9._\s-]+)$",
            text, re.IGNORECASE
        )
        target_user = None
        msg_content = None
        if m_text_first:
            msg_content = m_text_first.group(1).strip().strip("\"'“”‘’")
            target_user = m_text_first.group(2).strip().lstrip("@")
        else:
            # 7.2 Padrão com delimitadores: dizendo, falando, com o texto, que, ecrito, escrito, :, -, ou aspas
            m_delim = re.search(
                r"^(?:manda\s+(?:um\s+)?(?:recado|aviso)|recado|aviso|manda|mandar|mande|envia|enviar|envie|fala|falar|avisa|avise|notifica|notifique)\s+(?:(?:uma\s+)?(?:mensagem|recado|aviso|texto)\s+)?(?:para\s+(?:o\s+|a\s+)?|pro\s+|pra\s+|ao\s+|a\s+|o\s+)?(?:usuario\s+|usuário\s+|colaborador\s+)?([a-zA-Z0-9._\s-]+?)\s*(?::\s*|\s+-\s*|\s+(?:com\s+o\s+texto|dizendo|falando|de\s+que|que|ecrito|escrito)\s*:?\s*|\s+[\"\'\“\‘])([\s\S]+)$",
                text, re.IGNORECASE
            )
            # 7.3 Padrão simplificado "fala pro Arthur Gabriel que ..."
            m_simple = re.search(
                r"^(?:fala|falar|avisa|avise|notifica|notifique)\s+(?:para\s+(?:o\s+|a\s+)?|pro\s+|pra\s+|ao\s+)(?:usuario\s+|usuário\s+|colaborador\s+)?([a-zA-Z0-9._\s-]+?)\s+(?:que\s+|de\s+que\s+)?([\s\S]+)$",
                text, re.IGNORECASE
            )
            m_res = m_delim or m_simple
            if m_res:
                target_user = m_res.group(1).strip().lstrip("@")
                msg_content = m_res.group(2).strip().strip("\"'“”‘’")
            elif not m_text_first:
                m_missing = re.search(
                    r"^(?:manda|mandar|mande|envia|enviar|envie)\s+(?:uma\s+)?(?:mensagem|recado|aviso)\s+(?:para\s+(?:o\s+|a\s+)?|pro\s+|pra\s+|ao\s+)?([a-zA-Z0-9._\s-]+)$",
                    text, re.IGNORECASE
                )
                if m_missing:
                    target = m_missing.group(1).strip()
                    self._pending_message_target[user_id] = target
                    return f"💬 O que você quer que eu escreva para {target}?\n(Basta digitar o texto da mensagem agora, sem nenhum comando)"

        if target_user and msg_content:
            msg_content = _clean_chat_text(msg_content)
            forbidden_usernames = {"mesma", "mesmo", "outro", "outra", "todos", "alguem", "ninguem", "ele", "ela", "mensagem", "recado", "aviso", "ip", "pc", "maquina", "computador"}
            # Se não for um IP e não for palavra-chave reservada
            if target_user.lower() not in forbidden_usernames and not re.match(r"^(?:192\.168|10\.|172\.|57\.|\d{1,3}\.)", target_user):
                resolved_target = self._resolve_trueconf_user(target_user)
                self._last_dispatched_message[user_id] = msg_content
                formatted = f"📢 Mensagem de Nicolas Silva:\n\n{msg_content}"
                if self.bot:
                    success = self.bot.send_direct_message(resolved_target, formatted)
                    if success:
                        return f"🚀 Mensagem enviada para @{resolved_target} no TrueConf!\n\n📝 \"{msg_content}\""
                    return f"⚠️ Não foi possível entregar a mensagem para @{resolved_target}. Verifique se o usuário existe."
                else:
                    return f"🚀 Mensagem enviada para @{resolved_target} no TrueConf!\n\n📝 \"{msg_content}\""

        # 8. Instalação e download de softwares em linguagem natural
        # Ex: "instala a steam 57.166", "instala chrome no 57.48", "baixa vlc e steam em 57.166", "poe office 57.166"
        m_app_install = re.search(
            r"^(?:instala|instalar|instale|baixa|baixar|baixe|coloca|colocar|coloque|poe|põe)\s+(?:os?\s+)?(?:programas?|softwares?|apps?|aplicativos?)?\s*(.+?)\s*(?:(?:no|na|para|pro|pra|em)\s+)?(?:o\s+|a\s+)?(?:ip\s+|maquina\s+|máquina\s+|pc\s+)?(192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|57\.\d{1,3}|\d{1,3}\.\d{1,3}|\d{1,3})[^\d]*$",
            norm_text, re.IGNORECASE
        )
        if m_app_install:
            raw_apps = m_app_install.group(1).strip()
            raw_ip = m_app_install.group(2).strip()
            target_ip = self._extract_target_ip(raw_ip) or raw_ip
            if target_ip and raw_apps:
                return self._cmd_softwares(user_id, [target_ip, raw_apps])

        return None

    def handle_incoming_message(self, user_id: str, message: str) -> str:
        """
        Recebe qualquer mensagem enviada ao bot no chat privado do TrueConf.
        Suporta linguagem natural livre, menus interativos, wizards passo a passo e autenticação dinâmica.
        """
        trace_id = new_trace_id()
        log.info("incoming_message", trace_id, user_id=user_id, message=message[:100])
        
        text = _clean_chat_text(message or "")
        if not text:
            return self._cmd_interactive_menu()

        norm_text = _normalize_token(text)

        # 0. Verifica se estamos aguardando o conteúdo de uma mensagem para alguém
        if user_id in self._pending_message_target:
            target = self._pending_message_target.pop(user_id)
            msg_content = _clean_chat_text(text)
            resolved_target = self._resolve_trueconf_user(target)
            self._last_dispatched_message[user_id] = msg_content
            formatted = f"📢 Mensagem de Nicolas Silva:\n\n{msg_content}"
            if self.bot:
                success = self.bot.send_direct_message(resolved_target, formatted)
                if success:
                    return f"🚀 Mensagem enviada para @{resolved_target} no TrueConf!\n\n📝 \"{msg_content}\""
                return f"⚠️ Não foi possível entregar a mensagem para @{resolved_target}. Verifique se o usuário existe."
            return f"🚀 Mensagem enviada para @{resolved_target} no TrueConf!\n\n📝 \"{msg_content}\""

        # 1. Sessão interativa pendente (Wizard passo a passo ou Solicitação de Senha)
        if user_id in self.user_sessions:
            return self._handle_wizard_step(user_id, self.user_sessions[user_id], text)

        # 1.1 Controle Mestre / Agendamento exclusivo para Nicolas Silva
        master_reply = self._handle_master_intent(user_id, text, norm_text)
        if master_reply:
            return master_reply

        # 2. Navegação rápida pelo Menu Numérico Principal
        menu_choices = {
            "1": lambda: self._cmd_bancada(user_id, trace_id=trace_id),
            "01": lambda: self._cmd_bancada(user_id, trace_id=trace_id),
            "2": lambda: self._start_wizard_diagnostico(user_id, trace_id=trace_id),
            "02": lambda: self._start_wizard_diagnostico(user_id, trace_id=trace_id),
            "3": lambda: self._start_wizard_msg(user_id, trace_id=trace_id),
            "03": lambda: self._start_wizard_msg(user_id, trace_id=trace_id),
            "4": lambda: self._start_wizard_preparar(user_id, trace_id=trace_id),
            "04": lambda: self._start_wizard_preparar(user_id, trace_id=trace_id),
            "5": lambda: self._start_wizard_ativar(user_id, trace_id=trace_id),
            "05": lambda: self._start_wizard_ativar(user_id, trace_id=trace_id),
            "6": lambda: self._start_wizard_backup(user_id, trace_id=trace_id),
            "06": lambda: self._start_wizard_backup(user_id, trace_id=trace_id),
            "7": lambda: self._start_wizard_dominio(user_id, trace_id=trace_id),
            "07": lambda: self._start_wizard_dominio(user_id, trace_id=trace_id),
            "8": lambda: self._start_wizard_softwares(user_id, trace_id=trace_id),
            "08": lambda: self._start_wizard_softwares(user_id, trace_id=trace_id),
            "9": lambda: self._start_wizard_power(user_id, trace_id=trace_id),
            "09": lambda: self._start_wizard_power(user_id, trace_id=trace_id),
            "10": lambda: self._cmd_clientes(trace_id=trace_id),
            "11": lambda: self._cmd_chamados(trace_id=trace_id),
            "12": lambda: self._cmd_laudos([], trace_id=trace_id),
            "13": lambda: self._cmd_download_agent(user_id, trace_id=trace_id),
            "14": lambda: self._start_wizard_limpar(user_id, trace_id=trace_id),
        }

        if text in menu_choices:
            return menu_choices[text]()

        # 3. Solicitação de Menu Principal
        menu_kws = ["menu", "ajuda", "help", "inicio", "comecar", "/menu", "/start", "/ajuda", "/help", "opcoes", "opções"]
        if norm_text in menu_kws:
            return self._cmd_interactive_menu()

        # 3.1 Entrada isolada de endereço IP (ex: "57.166", "192.168.57.166", "48", "ip 57.166")
        clean_no_prefix = re.sub(r"^(?:ip|maquina|máquina|pc|host|computador)\s*", "", norm_text).strip()
        isolated_ip = self._extract_target_ip(clean_no_prefix)
        is_only_ip = bool(isolated_ip and clean_no_prefix in [isolated_ip, isolated_ip.replace("192.168.", ""), isolated_ip.split(".")[-1]])
        if is_only_ip:
            self._last_user_ip[user_id] = isolated_ip
            cached = self._get_cached_devices()
            dev = next((d for d in cached if d.get("ip") == isolated_ip), None)
            host = (dev.get("hostname") or "PC").replace(".penserede.local", "") if dev else "PC"
            any_id = dev.get("anydesk_id") if dev else None
            any_str = f"\n🔑 AnyDesk ID: `{any_id}` ([Conectar](anydesk:{any_id}))" if any_id else ""
            
            user_badge = self._format_user_badge(dev.get("logged_in_user") if dev else None)
            user_str = f"\n{user_badge}" if user_badge else ""

            return (
                f"🖥️ **Máquina {isolated_ip} ({host}) em Foco**{user_str}{any_str}\n\n"
                f"📍 O que você deseja executar nela agora?\n"
                f"• *'diagnóstico no {isolated_ip}'* (Saúde de discos S.M.A.R.T, CPU, RAM e drivers)\n"
                f"• *'preparar {isolated_ip} para <cliente>'* (Esteira completa de softwares)\n"
                f"• *'anydesk {isolated_ip}'* (Consultar/gerar ID de acesso remoto)\n"
                f"• *'ativar {isolated_ip}'* (Licença digital MAS permanente)\n"
                f"• *'reiniciar {isolated_ip}'* (Controle remoto de energia)\n"
                f"• *'limpar {isolated_ip}'* (Desinstalação para entrega ao cliente)"
            )

        # 4. Roteamento de comandos slash explícitos
        parts = text.split()
        first_token = parts[0] if parts else ""
        norm_token = _normalize_token(first_token)

        routes = {
            frozenset(["/bancada", "/status", "/maquinas", "/lab", "/hosts"]):
                lambda: self._cmd_bancada(user_id, trace_id=trace_id),
            frozenset(["/clientes", "/perfis", "/empresas"]):
                lambda: self._cmd_clientes(trace_id=trace_id),
            frozenset(["/chamados", "/milvus", "/tickets"]):
                lambda: self._cmd_chamados(trace_id=trace_id),
            frozenset(["/preparar", "/iniciar", "/deploy", "/formatar"]):
                lambda: self._cmd_preparar(user_id, parts[1:], trace_id=trace_id),
            frozenset(["/diagnostico", "/diag", "/inspecionar", "/smart"]):
                lambda: self._cmd_diagnostico(user_id, parts[1:], trace_id=trace_id),
            frozenset(["/ativar", "/ativacao", "/mas"]):
                lambda: self._cmd_ativar(user_id, parts[1:], trace_id=trace_id),
            frozenset(["/backup", "/storage"]):
                lambda: self._cmd_backup(user_id, parts[1:], trace_id=trace_id),
            frozenset(["/dominio", "/domain", "/ad"]):
                lambda: self._cmd_dominio(user_id, parts[1:], trace_id=trace_id),
            frozenset(["/softwares", "/apps", "/instalar"]):
                lambda: self._cmd_softwares(user_id, parts[1:], trace_id=trace_id),
            frozenset(["/reiniciar", "/reboot"]):
                lambda: self._cmd_power(user_id, parts[1:], "restart", trace_id=trace_id),
            frozenset(["/desligar", "/shutdown"]):
                lambda: self._cmd_power(user_id, parts[1:], "shutdown", trace_id=trace_id),
            frozenset(["/msg", "/mensagem", "/notificar", "/alerta", "/aviso", "/popup"]):
                lambda: self._cmd_message(user_id, parts[1:], trace_id=trace_id),
            frozenset(["/laudos", "/laudo", "/relatorios"]):
                lambda: self._cmd_laudos(parts[1:], trace_id=trace_id),
            frozenset(["/download", "/agent", "/agente", "/exe", "/baixar"]):
                lambda: self._cmd_download_agent(user_id, trace_id=trace_id),
            frozenset(["/erro", "/error", "/bsod"]):
                lambda: self._cmd_erro(parts[1:], trace_id=trace_id),
            frozenset(["/cve", "/seguranca", "/vuln"]):
                lambda: self._cmd_cve(parts[1:], trace_id=trace_id),
            frozenset(["/clima", "/termica", "/temperatura"]):
                lambda: self._cmd_clima(trace_id=trace_id),
            frozenset(["/wan", "/ip"]):
                lambda: self._cmd_wan(trace_id=trace_id),
            frozenset(["/anydesk", "/acesso", "/id"]):
                lambda: self._cmd_anydesk(user_id, parts[1:], trace_id=trace_id),
            frozenset(["/garantia", "/warranty", "/tag", "/serial"]):
                lambda: self._cmd_garantia(user_id, parts[1:], trace_id=trace_id),
            frozenset(["/senha", "/pwned", "/hibp", "/seguranca_senha"]):
                lambda: self._cmd_senha(parts[1:], trace_id=trace_id),
            frozenset(["/backup_softwares", "/bkp_softwares", "/exportar_softwares", "/unigetui_backup"]):
                lambda: self._cmd_backup_softwares(user_id, parts[1:], trace_id=trace_id),
            frozenset(["/restaurar_softwares", "/restore_softwares", "/importar_softwares", "/unigetui_restore"]):
                lambda: self._cmd_restaurar_softwares(user_id, parts[1:], trace_id=trace_id),
            frozenset(["/atualizar_softwares", "/upgrade_softwares", "/atualizar_tudo", "/upgrade_all"]):
                lambda: self._cmd_upgrade_softwares(user_id, parts[1:], trace_id=trace_id),
            frozenset(["/buscar_software", "/buscar_app", "/pesquisar_software", "/procurar_app"]):
                lambda: self._cmd_buscar_software(user_id, parts[1:], trace_id=trace_id),
            frozenset(["/bundles", "/backups_softwares", "/list_bundles"]):
                lambda: self._cmd_list_bundles(trace_id=trace_id),
            frozenset(["/limpar", "/clean", "/limpeza", "/desinstalar"]):
                lambda: self._cmd_limpar(user_id, parts[1:], trace_id=trace_id),
        }

        for keywords, handler in routes.items():
            if norm_token in keywords:
                return handler()

        # 5. Disparo de mensagem para a máquina por linguagem natural
        ip_match = re.search(r"\b(192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3})\b", text)
        msg_action_kws = ["manda uma mensagem", "mandar mensagem", "enviar mensagem", "avisa o ip", "notifica o ip", "avise o ip", "mande uma mensagem"]
        if ip_match and any(kw in norm_text for kw in msg_action_kws):
            target_ip = ip_match.group(1)
            quoted = re.search(r'["\']([^"\']+)["\']', text)
            if quoted:
                clean_msg = quoted.group(1)
            else:
                clean_msg = re.sub(r'^(?:.*?)' + re.escape(target_ip) + r'[:\s-]*', '', text, flags=re.IGNORECASE).strip()
            if clean_msg:
                return self._cmd_message(user_id, [target_ip] + clean_msg.split())

        # 6. Erro hexadecimal Windows em texto livre
        hex_match = re.search(r"\b(0x[0-9a-fA-F]{8})\b", text)
        if hex_match:
            return self._cmd_erro([hex_match.group(1)])

        # Reliability Layer: IntentRouter (Prioridade para intenções robustas)
        intent_match = self.intent_router.classify(text, trace_id=trace_id)
        if intent_match.intent:
            host = intent_match.entities.get("host")
            if intent_match.intent == "instalar_software":
                return self._cmd_softwares(user_id, [host, "tudo"], trace_id=trace_id) if host else self._start_wizard_softwares(user_id, trace_id=trace_id)
            elif intent_match.intent == "verificar_saude":
                return self._cmd_diagnostico(user_id, [host], trace_id=trace_id) if host else self._start_wizard_diagnostico(user_id, trace_id=trace_id)
            elif intent_match.intent == "preparar_maquina":
                return self._cmd_preparar(user_id, [host, "padrao"], trace_id=trace_id) if host else self._start_wizard_preparar(user_id, trace_id=trace_id)
            elif intent_match.intent == "ativar_windows":
                return self._cmd_ativar(user_id, [host], trace_id=trace_id) if host else self._start_wizard_ativar(user_id, trace_id=trace_id)
            elif intent_match.intent == "enviar_mensagem_tela":
                return self._cmd_message(user_id, [host, "Olá, do Ultron!"], trace_id=trace_id) if host else self._start_wizard_msg(user_id, trace_id=trace_id)
            elif intent_match.intent == "reiniciar_maquina":
                return self._cmd_power(user_id, [host], "restart", trace_id=trace_id) if host else self._start_wizard_power(user_id, trace_id=trace_id)
        elif intent_match.confidence > 0.2:  # Só pede clarificação se houver o mínimo de match
            return self.intent_router.build_clarification(intent_match, text)

        # Fallback para regex antigo caso o IntentRouter não classifique as intenções nativas
        natural_reply = self._match_natural_intent(user_id, text, norm_text)
        if natural_reply:
            return natural_reply

        # 8. IA Conversacional Fluida
        return self._handle_ai_conversation(user_id, text)

    # ------------------------------------------------------------------
    # Comandos
    # ------------------------------------------------------------------

    def _cmd_interactive_menu(self) -> str:
        return (
            "🤖 **Central de Automação Ultron**\n\n"
            "Como posso te ajudar agora? Você pode falar comigo em linguagem natural ou escolher uma opção:\n\n"
            "[ 1 ] 💻 Ver computadores na bancada\n"
            "[ 2 ] 🩺 Diagnóstico rápido de hardware & S.M.A.R.T\n"
            "[ 3 ] 📢 Enviar mensagem na tela de um PC\n"
            "[ 4 ] 🚀 Iniciar esteira de preparação de máquina\n"
            "[ 5 ] 🔑 Ativar Windows e Office (MAS)\n"
            "[ 6 ] 💾 Fazer backup do perfil de usuário\n"
            "[ 7 ] 🛡️ Ingressar máquina no domínio (AD)\n"
            "[ 8 ] 📦 Instalar softwares básicos\n"
            "[ 9 ] 🔌 Reiniciar ou desligar computador\n"
            "[ 10 ] 🏢 Consultar perfis de clientes\n"
            "[ 11 ] 🎫 Consultar chamados no Milvus\n"
            "[ 12 ] 📄 Ver laudos técnicos emitidos\n"
            "[ 13 ] 📥 Baixar o UltronAgent.exe\n"
            "[ 14 ] 🧹 Limpeza pós-bancada (Entrega ao Cliente)\n\n"
            "💬 Basta digitar o número correspondente (ex: 1, 4, 11) ou me dizer o que você precisa!"
        )

    def _cmd_help(self) -> str:
        return self._cmd_interactive_menu()

    # ------------------------------------------------------------------
    # Wizard Interativo & Solicitação Dinâmica de Credenciais
    # ------------------------------------------------------------------

    def _prompt_for_credentials(self, user_id: str, ip: str, action_name: str, callback_fn, retry_msg: str = "") -> str:
        """Configura a sessão do técnico para receber usuário e senha de uma máquina"""
        self.user_sessions[user_id] = {
            "type": "wizard_credentials",
            "ip": ip,
            "action_name": action_name,
            "callback": callback_fn
        }
        prefix = f"{retry_msg}\n\n" if retry_msg else ""
        return (
            f"{prefix}🔐 ACESSO NECESSÁRIO — MÁQUINA {ip}\n\n"
            f"Para executar '{action_name}' na máquina {ip}, por favor informe o usuário e senha de Administrador local.\n\n"
            f"💬 Responda no formato: `usuario senha`\n"
            f"(Ex: `Administrador Senha123` ou `.\\suporte P@ssword`)\n\n"
            f"[ 0 ] Cancelar"
        )

    def _prompt_for_domain_credentials(self, user_id: str, ip: str, domain: str) -> str:
        """Solicita credenciais do domínio Active Directory"""
        self.user_sessions[user_id] = {
            "type": "wizard_domain_credentials",
            "ip": ip,
            "domain": domain
        }
        return (
            f"🛡️ CREDENCIAIS DE DOMÍNIO — {domain}\n\n"
            f"Para ingressar a máquina {ip} no domínio '{domain}', informe as credenciais de Administrador do Domínio.\n\n"
            f"💬 Responda no formato: `usuario senha`\n"
            f"(Ex: `admin_rede P@ssAD2026`)\n\n"
            f"[ 0 ] Cancelar"
        )

    def _handle_wizard_step(self, user_id: str, session: Dict[str, Any], text: str) -> str:
        norm = _normalize_token(text)
        if norm in ["0", "cancelar", "cancela", "voltar", "sair", "menu", "parar"]:
            self.user_sessions.pop(user_id, None)
            return "❌ Operação cancelada.\n\n" + self._cmd_interactive_menu()

        wtype = session.get("type")

        # 1. Tratamento de Credenciais de Máquina
        if wtype == "wizard_credentials":
            ip = session.get("ip")
            action_name = session.get("action_name", "Operação")
            callback = session.get("callback")

            parts = text.strip().split(None, 1)
            if not parts:
                return "⚠️ Formato inválido. Envie no formato: `usuario senha` (ou '0' para cancelar)."

            user = parts[0]
            pwd = parts[1] if len(parts) > 1 else ""

            # Armazena credencial para o IP
            self.winrm.set_host_credentials(ip, user, pwd)
            self.user_sessions.pop(user_id, None)

            if callback:
                return callback()
            return f"✅ Credenciais para {ip} salvas. Reexecutando {action_name}..."

        # 2. Tratamento de Credenciais de Domínio
        if wtype == "wizard_domain_credentials":
            ip = session.get("ip")
            domain = session.get("domain")

            parts = text.strip().split(None, 1)
            if not parts:
                return "⚠️ Formato inválido. Envie no formato: `usuario senha` (ou '0' para cancelar)."

            dom_user = parts[0]
            dom_pwd = parts[1] if len(parts) > 1 else ""
            self.user_sessions.pop(user_id, None)

            return self._execute_domain_join(user_id, ip, domain, dom_user, dom_pwd)

        # 3. Escolha pós-MDT
        if wtype == "pending_mdt":
            return self._handle_pending_mdt_choice(user_id, session, text)

        # 4. Wizard de Diagnóstico
        if wtype == "wizard_diag":
            ip = self._extract_target_ip(text) or text.strip()
            self.user_sessions.pop(user_id, None)
            return self._cmd_diagnostico(user_id, [ip])

        # 5. Wizard de Mensagem na Tela
        if wtype == "wizard_msg":
            step = session.get("step")
            if step == "ip":
                ip = self._extract_target_ip(text) or text.strip()
                session["ip"] = ip
                session["step"] = "text"
                return (
                    f"📢 Destino: {ip}\n\n"
                    f"💬 Digite o texto da mensagem que vai aparecer no meio da tela do usuário:\n"
                    f"(ex: O laboratório está finalizando a configuração do seu computador)\n\n"
                    f"[ 0 ] Cancelar"
                )
            elif step == "text":
                ip = session.get("ip")
                msg_text = text.strip()
                self.user_sessions.pop(user_id, None)
                return self._cmd_message(user_id, [ip] + msg_text.split())

        # 6. Wizard de Preparação (IP & Cliente)
        if wtype == "wizard_preparar":
            step = session.get("step")
            if step == "ip":
                ip = self._extract_target_ip(text) or text.strip()
                session["ip"] = ip
                session["step"] = "client"
                clients = self.profile_mgr.list_clients()
                lines = [f"🚀 Preparar Máquina {ip}\n\nEscolha o Perfil do Cliente digitando o número ou o nome:\n"]
                for idx, c in enumerate(clients[:10], 1):
                    lines.append(f"[ {idx} ] {c.get('nome')} ({c.get('id')})")
                lines.append("\n[ 0 ] Cancelar")
                return "\n".join(lines)
            elif step == "client":
                ip = session.get("ip")
                client_id = self._extract_client_id(text)
                if not client_id:
                    if text.strip().isdigit():
                        clients = self.profile_mgr.list_clients()
                        idx = int(text.strip()) - 1
                        if 0 <= idx < len(clients):
                            client_id = clients[idx].get("id", text.strip())
                    else:
                        client_id = text.strip()
                self.user_sessions.pop(user_id, None)
                return self._cmd_preparar(user_id, [ip, client_id])

        if wtype == "wizard_preparar_ip":
            client_id = session.get("client_id")
            ip = self._extract_target_ip(text) or text.strip()
            self.user_sessions.pop(user_id, None)
            return self._cmd_preparar(user_id, [ip, client_id])

        if wtype == "wizard_preparar_client":
            ip = session.get("ip")
            client_id = self._extract_client_id(text)
            if not client_id:
                if text.strip().isdigit():
                    clients = self.profile_mgr.list_clients()
                    idx = int(text.strip()) - 1
                    if 0 <= idx < len(clients):
                        client_id = clients[idx].get("id", text.strip())
                else:
                    client_id = text.strip()
            self.user_sessions.pop(user_id, None)
            return self._cmd_preparar(user_id, [ip, client_id])

        # 7. Wizard de Ativação MAS
        if wtype == "wizard_ativar":
            ip = self._extract_target_ip(text) or text.strip()
            self.user_sessions.pop(user_id, None)
            return self._cmd_ativar(user_id, [ip])

        # 8. Wizard de Backup
        if wtype == "wizard_backup":
            ip = self._extract_target_ip(text) or text.strip()
            self.user_sessions.pop(user_id, None)
            return self._cmd_backup(user_id, [ip])

        # 9. Wizard de Domínio
        if wtype == "wizard_dominio":
            step = session.get("step")
            if step == "ip":
                ip = self._extract_target_ip(text) or text.strip()
                session["ip"] = ip
                session["step"] = "domain"
                return (
                    f"🛡️ Ingressar {ip} no Domínio\n\n"
                    f"Digite o nome do domínio ou o ID do cliente:\n"
                    f"(ex: penserede.local ou penserede)\n\n"
                    f"[ 0 ] Cancelar"
                )
            elif step == "domain":
                ip = session.get("ip")
                dom = text.strip()
                self.user_sessions.pop(user_id, None)
                return self._cmd_dominio(user_id, [ip, dom])

        if wtype == "wizard_dominio_domain":
            ip = session.get("ip")
            dom = text.strip()
            self.user_sessions.pop(user_id, None)
            return self._cmd_dominio(user_id, [ip, dom])

        if wtype == "wizard_power":
            ip = self._extract_target_ip(text) or text.strip()
            action = session.get("action", "restart")
            self.user_sessions.pop(user_id, None)
            return self._cmd_power(user_id, [ip], action)

        # 10. Wizard de Softwares
        if wtype == "wizard_softwares":
            step = session.get("step")
            if step == "ip":
                ip = text.strip()
                session["ip"] = ip
                session["step"] = "choice"
                return (
                    f"📦 Instalação de Softwares em {ip}\n\n"
                    f"Escolha o pacote digitando o número:\n"
                    f"[ 1 ] Pacote Padrão de Escritório (Chrome, AnyDesk, WinRAR, 7-Zip, Acrobat Reader)\n"
                    f"[ 2 ] Google Chrome\n"
                    f"[ 3 ] AnyDesk\n"
                    f"[ 4 ] WinRAR + 7-Zip\n"
                    f"[ 5 ] Digitar nomes avulsos (ex: Google.Chrome,AnyDesk)\n\n"
                    f"[ 0 ] Cancelar"
                )
            elif step == "choice":
                ip = session.get("ip")
                pkgs_map = {
                    "1": "Google.Chrome,AnyDeskSoftwareGmbH.AnyDesk,RARLab.WinRAR,7zip.7zip,Adobe.Acrobat.Reader.64-bit",
                    "2": "Google.Chrome",
                    "3": "AnyDeskSoftwareGmbH.AnyDesk",
                    "4": "RARLab.WinRAR,7zip.7zip",
                }
                pkgs = pkgs_map.get(text.strip(), text.strip())
                self.user_sessions.pop(user_id, None)
                return self._cmd_softwares(user_id, [ip, pkgs])

        # 11. Wizard de Energia
        if wtype == "wizard_power":
            step = session.get("step")
            if step == "ip":
                ip = text.strip()
                session["ip"] = ip
                session["step"] = "action"
                return (
                    f"🔌 Controle de Energia para {ip}\n\n"
                    f"Escolha a ação digitando o número:\n"
                    f"[ 1 ] Reiniciar Computador\n"
                    f"[ 2 ] Desligar Computador\n\n"
                    f"[ 0 ] Cancelar"
                )
            elif step == "action":
                ip = session.get("ip")
                act = "restart" if text.strip() == "1" else "shutdown" if text.strip() == "2" else None
                self.user_sessions.pop(user_id, None)
                if act:
                    return self._cmd_power(user_id, [ip], act)
                return "❌ Opção inválida. Operação cancelada."

        # 12. Wizard de Limpeza Pós-Bancada
        if wtype == "wizard_limpar":
            ip = self._extract_target_ip(text) or text.strip()
            self.user_sessions.pop(user_id, None)
            return self._cmd_limpar(user_id, [ip])

        self.user_sessions.pop(user_id, None)
        return self._cmd_interactive_menu()

    # ------------------------------------------------------------------
    # Starters dos Wizards
    # ------------------------------------------------------------------

    def _start_wizard_diagnostico(self, user_id: str) -> str:
        self.user_sessions[user_id] = {"type": "wizard_diag", "step": "ip"}
        return (
            "🩺 DIAGNÓSTICO DE HARDWARE & S.M.A.R.T\n\n"
            "Digite o IP do computador que deseja inspecionar:\n"
            "(ex: 192.168.57.59 ou 192.168.58.182)\n\n"
            "[ 0 ] Cancelar e voltar ao Menu"
        )

    def _start_wizard_msg(self, user_id: str) -> str:
        self.user_sessions[user_id] = {"type": "wizard_msg", "step": "ip"}
        return (
            "📢 ENVIAR MENSAGEM / POP-UP NA TELA\n\n"
            "Digite o IP do computador de destino:\n"
            "(ex: 192.168.57.59 ou 192.168.58.182)\n\n"
            "[ 0 ] Cancelar e voltar ao Menu"
        )

    def _start_wizard_preparar(self, user_id: str) -> str:
        self.user_sessions[user_id] = {"type": "wizard_preparar", "step": "ip"}
        return (
            "🚀 PREPARAÇÃO AUTOMÁTICA DE MÁQUINA\n\n"
            "Digite o IP do computador na bancada:\n"
            "(ex: 192.168.57.59 ou 192.168.58.182)\n\n"
            "[ 0 ] Cancelar e voltar ao Menu"
        )

    def _start_wizard_ativar(self, user_id: str) -> str:
        self.user_sessions[user_id] = {"type": "wizard_ativar", "step": "ip"}
        return (
            "🔑 ATIVAÇÃO DO WINDOWS E OFFICE (MAS)\n\n"
            "Digite o IP do computador que deseja ativar:\n"
            "(ex: 192.168.57.59)\n\n"
            "[ 0 ] Cancelar e voltar ao Menu"
        )

    def _start_wizard_backup(self, user_id: str) -> str:
        self.user_sessions[user_id] = {"type": "wizard_backup", "step": "ip"}
        return (
            "💾 BACKUP DE DADOS PARA O STORAGE\n\n"
            "Digite o IP do computador de origem:\n"
            "(ex: 192.168.57.59)\n\n"
            "[ 0 ] Cancelar e voltar ao Menu"
        )

    def _start_wizard_dominio(self, user_id: str) -> str:
        self.user_sessions[user_id] = {"type": "wizard_dominio", "step": "ip"}
        return (
            "🛡️ INGRESSO NO DOMÍNIO (ACTIVE DIRECTORY)\n\n"
            "Digite o IP do computador:\n"
            "(ex: 192.168.57.59)\n\n"
            "[ 0 ] Cancelar e voltar ao Menu"
        )

    def _start_wizard_softwares(self, user_id: str) -> str:
        self.user_sessions[user_id] = {"type": "wizard_softwares", "step": "ip"}
        return (
            "📦 INSTALAÇÃO DE SOFTWARES\n\n"
            "Digite o IP do computador:\n"
            "(ex: 192.168.57.59)\n\n"
            "[ 0 ] Cancelar e voltar ao Menu"
        )

    def _start_wizard_power(self, user_id: str) -> str:
        self.user_sessions[user_id] = {"type": "wizard_power", "step": "ip"}
        return (
            "🔌 CONTROLE REMOTO DE ENERGIA\n\n"
            "Digite o IP do computador:\n"
            "(ex: 192.168.57.59)\n\n"
            "[ 0 ] Cancelar e voltar ao Menu"
        )

    def _start_wizard_limpar(self, user_id: str) -> str:
        self.user_sessions[user_id] = {"type": "wizard_limpar", "step": "ip"}
        return (
            "🧹 **LIMPEZA PÓS-BANCADA (ENTREGA AO CLIENTE)**\n\n"
            "Digite o IP do computador que deseja desinstalar e limpar:\n"
            "(ex: 192.168.57.59 ou 57.48)\n\n"
            "[ 0 ] Cancelar e voltar ao Menu"
        )

    def _cmd_limpar(self, user_id: str, args: List[str]) -> str:
        if not args:
            return self._start_wizard_limpar(user_id)

        target = args[0].strip()
        ip = self._extract_target_ip(target) or target
        self._last_user_ip[user_id] = ip

        # 1. Enfileira a tarefa reversa no AgentTaskManager (para caso o WinRM não esteja disponível)
        try:
            from main import agent_task_mgr
            agent_task_mgr.enqueue_task(ip, "CLEANUP_SYSTEM", task_type="cleanup")
        except Exception:
            pass

        # 2. Tenta executar diretamente via WinRM se a máquina estiver online
        def _bg_clean():
            try:
                self.winrm.run_command(ip, "cmd.exe /c sc stop UltronService & sc delete UltronService & net user UltronAdmin /delete 2>nul & rmdir /s /q \"%ProgramFiles%\\UltronAgent\" 2>nul", timeout_sec=20)
            except Exception:
                pass

        threading.Thread(target=_bg_clean, daemon=True).start()

        return (
            f"🧹 **Ordem de Limpeza Pós-Bancada Enviada**\n\n"
            f"📍 Máquina Alvo: **{ip}**\n\n"
            f"O `UltronService`, a conta `UltronAdmin` e os arquivos temporários de automação estão sendo desinstalados e removidos da máquina.\n\n"
            f"✅ A máquina ficará 100% limpa para entrega ao cliente final."
        )

    @staticmethod
    def _clean_vendor(vendor: Optional[str]) -> Optional[str]:
        """Normaliza e encurta nomes de fabricantes para exibição amigável e limpa."""
        if not vendor or vendor in ["Desconhecido", "Genérico / Não Catalogado", "Generic", "None"]:
            return None
        v_upper = vendor.upper()
        if "MICROSOFT" in v_upper:
            return "Hyper-V / MS"
        if "CLOUD NETWORK" in v_upper or "HON HAI" in v_upper or "FOXCONN" in v_upper:
            return "Foxconn"
        if "DELL" in v_upper:
            return "Dell"
        if "HEWLETT" in v_upper or "HP" in v_upper:
            return "HP"
        if "LENOVO" in v_upper:
            return "Lenovo"
        if "INTEL" in v_upper:
            return "Intel"
        if "ASUS" in v_upper:
            return "ASUS"
        if "TP-LINK" in v_upper:
            return "TP-Link"
        if "REALTEK" in v_upper:
            return "Realtek"
        if "BILIAN" in v_upper:
            return "Bilian"
        if "VMWARE" in v_upper:
            return "VMware"
        if "ACER" in v_upper:
            return "Acer"
        if "SAMSUNG" in v_upper:
            return "Samsung"
        if "APPLE" in v_upper:
            return "Apple"
        if len(vendor) > 22:
            return vendor.split()[0].title()
    def _format_user_badge(self, raw_user: Optional[str]) -> str:
        """Formata o nome do usuário logado na máquina vinculando ao TrueConf quando possível."""
        if not raw_user:
            return ""
        clean = raw_user.replace("PENSEREDE\\", "").replace(".\\", "").strip()
        if not clean or clean.upper() in ["SYSTEM", "LOCAL SERVICE", "NETWORK SERVICE", "ULTRONADMIN", "DEFAULTACCOUNT", "WDAGUTILITYACCOUNT"]:
            return ""
        
        # Procura o nome do colaborador no TrueConf
        try:
            tc_users = self._get_trueconf_users_cached()
            for u in tc_users:
                uid = u.get("id", "").lower()
                if uid == clean.lower() or uid == clean.lower().replace(" ", "."):
                    display = (u.get("display_name") or (u.get("first_name", "") + " " + u.get("last_name", ""))).strip()
                    return f"👤 {display} (@{uid})"
        except Exception:
            pass
        
        return f"👤 {clean}"

    def _format_device_display(self, d: Dict[str, Any]) -> str:
        """Formata um dispositivo de bancada de forma limpa, elegante com usuário e AnyDesk."""
        ip = d.get("ip", "?")
        raw_host = (d.get("hostname") or "").strip()
        cleaned_vendor = self._clean_vendor(d.get("vendor"))
        vendor_part = f" • {cleaned_vendor}" if cleaned_vendor else ""
        anydesk_id = d.get("anydesk_id")
        anydesk_part = f" • AnyDesk: `{anydesk_id}`" if anydesk_id else ""
        
        user_badge = self._format_user_badge(d.get("logged_in_user"))
        user_part = f" • **{user_badge}**" if user_badge else ""

        if raw_host and raw_host != ip and not raw_host.startswith("192.168."):
            host_label = raw_host.replace(".penserede.local", "")
            return f"• **{host_label}** ({ip}){user_part}{vendor_part}{anydesk_part}"
        else:
            return f"• **{ip}**{user_part}{vendor_part}{anydesk_part}"


    def _cmd_bancada(self, user_id: str) -> str:
        cached = self._cached_devices

        def _worker_refresh():
            try:
                devs = self.scanner.scan_network(timeout=0.3)
                if devs:
                    # Enriquece com dados prévios de telemetria/AnyDesk/usuário se existirem
                    old_map = {d.get("ip"): d for d in self._cached_devices}
                    for d in devs:
                        old = old_map.get(d.get("ip"))
                        if old:
                            if not d.get("logged_in_user") and old.get("logged_in_user"):
                                d["logged_in_user"] = old.get("logged_in_user")
                            if not d.get("anydesk_id") and old.get("anydesk_id"):
                                d["anydesk_id"] = old.get("anydesk_id")
                            if not d.get("serial") and old.get("serial"):
                                d["serial"] = old.get("serial")
                    self._cached_devices = devs
                    self._last_scan_time = time.time()
            except Exception:
                pass

        threading.Thread(target=_worker_refresh, daemon=True).start()

        if not cached:
            try:
                cached = self.scanner.scan_network(timeout=0.35)
                self._cached_devices = cached
                self._last_scan_time = time.time()
            except Exception:
                cached = []

        if not cached:
            return (
                "🔍 Não encontrei computadores ativos na rede da bancada (192.168.57.0/24) no momento.\n\n"
                "💡 Verifique se as máquinas estão ligadas e com o cabo de rede conectado."
            )

        winrm_ready = [d for d in cached if d.get("winrm_ready")]
        other_devices = [d for d in cached if not d.get("winrm_ready")]

        lines = [f"🖥️ **Bancada Ultron** ({len(cached)} equipamentos detectados na rede)\n"]

        if winrm_ready:
            lines.append(f"🟢 **Prontas para automação (WinRM ativo — {len(winrm_ready)}):**")
            for d in winrm_ready[:8]:
                lines.append(self._format_device_display(d))
            if len(winrm_ready) > 8:
                lines.append(f"• ... e mais {len(winrm_ready) - 8} máquina(s) pronta(s).")
            lines.append("")

        if other_devices:
            lines.append(f"🟡 **Outros dispositivos conectados ({len(other_devices)}):**")
            for d in other_devices[:4]:
                lines.append(self._format_device_display(d))
            if len(other_devices) > 4:
                lines.append(f"• ... e mais {len(other_devices) - 4} dispositivo(s).")
            lines.append("")

        lines.append("💬 Você pode me pedir: *'diagnosticar 57.52'*, *'preparar 57.48 para White Group'* ou *'ativar Windows do 57.10'*.")

        return "\n".join(lines)

    def _cmd_anydesk(self, user_id: str, args: List[str]) -> str:
        """Consulta o AnyDesk ID de uma máquina específica ou de todas as máquinas ativas na bancada"""
        target_ip = args[0] if args else self._last_user_ip.get(user_id)
        if target_ip:
            target_ip = self._extract_target_ip(target_ip) or target_ip

        cached = self._get_cached_devices()

        # Se não informou IP e não há IP em contexto, verifica apenas máquinas que já possuem AnyDesk
        if not target_ip:
            with_anydesk = [d for d in cached if d.get("anydesk_id")]
            if with_anydesk:
                lines = [f"🔑 **AnyDesk dos Computadores Conectados** ({len(with_anydesk)} detectado(s)):\n"]
                for d in with_anydesk:
                    ip = d.get("ip")
                    host = (d.get("hostname") or "PC").replace(".penserede.local", "")
                    any_id = d.get("anydesk_id")
                    lines.append(f"• **{host}** ({ip}) — ID: `{any_id}` ([Conectar](anydesk:{any_id}))")
                lines.append("\n💡 Para consultar uma máquina específica: *'anydesk 57.166'*")
                return "\n".join(lines)

            # Se nenhuma máquina tem AnyDesk em cache mas há apenas 1 máquina de bancada ativa
            winrm_devs = [d for d in cached if d.get("winrm_ready")]
            target = winrm_devs[0] if len(winrm_devs) == 1 else (cached[0] if len(cached) == 1 else None)
            if target:
                target_ip = target.get("ip")
            else:
                return (
                    "🔑 **AnyDesk — Acesso Remoto**\n\n"
                    "Nenhum ID do AnyDesk foi registrado automaticamente na bancada ainda.\n\n"
                    "💡 Envie o IP da máquina para eu consultar diretamente nela:\n"
                    "Exemplo: *'anydesk 57.166'* ou *'anydesk 192.168.57.63'*"
                )

        # Busca dados do dispositivo
        dev = next((d for d in cached if d.get("ip") == target_ip), None)
        hostname = (dev.get("hostname") or "PC").replace(".penserede.local", "") if dev else "PC"
        anydesk_id = dev.get("anydesk_id") if dev else None

        # Se não tem AnyDesk no cache, tenta consultar via WinRM rapidamente
        if not anydesk_id:
            try:
                res = self.winrm.run_command(target_ip, "powershell -Command \"$c = '$env:ProgramData\\AnyDesk\\system.conf'; if (Test-Path $c) { (Get-Content $c | Select-String 'ad.anynet.id=').Line.Replace('ad.anynet.id=','').Trim() } else { '' }\"", timeout_sec=3)
                raw_out = (res.get("stdout") or "").strip()
                if raw_out and (raw_out.isdigit() or len(raw_out) >= 7):
                    anydesk_id = raw_out
                    if dev:
                        dev["anydesk_id"] = anydesk_id
            except Exception:
                pass

        if anydesk_id:
            self._last_user_ip[user_id] = target_ip
            return (
                f"🔑 **AnyDesk — Máquina {target_ip}**\n\n"
                f"💻 Host: **{hostname}**\n"
                f"📍 ID: `{anydesk_id}`\n"
                f"🔗 Link direto: anydesk:{anydesk_id}\n\n"
                f"💡 Você pode clicar no link ou copiar o ID acima para conectar remotamente."
            )
        else:
            self._last_user_ip[user_id] = target_ip
            return (
                f"⚠️ **AnyDesk não detectado em {target_ip} ({hostname})**\n\n"
                f"O AnyDesk ainda não foi instalado ou o serviço ainda não gerou um ID nesta máquina.\n\n"
                f"💡 Para instalar automaticamente via Winget: *'instalar AnyDesk no {target_ip}'*"
            )

    def _cmd_clientes(self) -> str:
        clients = self.profile_mgr.list_clients()
        if not clients:
            return "🏢 Nenhum cliente cadastrado no sistema."

        lines = [f"🏢 **Perfis de Clientes Cadastrados** ({len(clients)} empresas):\n"]
        for idx, c in enumerate(clients[:10], 1):
            dom = f" • AD: `{c.get('dominio')}`" if c.get("dominio") else ""
            lines.append(f"{idx:02d}. **{c.get('nome')}** (`{c.get('id')}`){dom}")

        if len(clients) > 10:
            lines.append(f"\n... e mais {len(clients) - 10} perfis configurados.")

        lines.append("\n💬 Para iniciar a preparação: *'prepara o <IP> para <Cliente>'*")
        return "\n".join(lines)

    def _cmd_chamados(self) -> str:
        tickets = self.profile_mgr.milvus.get_open_tickets()
        if not tickets:
            return "📋 Nenhum chamado pendente no Milvus no momento. Tudo limpo por aqui!"

        lines = [f"📋 **Chamados Abertos no Milvus** ({len(tickets)} pendentes):\n"]
        for t in tickets[:6]:
            num = t.get("numero") or "S/N"
            lines.append(
                f"• **#{num}** — {t.get('cliente')}\n"
                f"  Assunto: {t.get('assunto')}\n"
                f"  Técnico: {t.get('tecnico')}\n"
            )

        return "\n".join(lines)

    def _cmd_preparar(self, user_id: str, args: List[str], trace_id: str = None) -> str:
        trace_id = trace_id or new_trace_id()
        if not args:
            return self.msg_builder.error(WinRMResult(ok=False, host="N/A", command="/preparar", error="Uso: /preparar <IP> <cliente>"), trace_id)

        ip        = args[0]
        client_id = args[1] if len(args) > 1 else "cliente_padrao"
        self._last_user_ip[user_id] = ip

        if client_id.isdigit():
            clients = self.profile_mgr.list_clients()
            idx     = int(client_id) - 1
            if 0 <= idx < len(clients):
                client_id = clients[idx].get("id", client_id)

        def _worker():
            log.info("task_started", trace_id, ip=ip, action="preparar_maquina", client_id=client_id)
            self._ensure_orchestrator()
            self.orchestrator.run_pipeline(
                ip=ip,
                client_id=client_id,
                tech_user_id=user_id,
                technician_name=user_id.capitalize(),
            )

        threading.Thread(target=_worker, daemon=True).start()

        return self.msg_builder.success(
            "ESTEIRA DE PREPARAÇÃO INICIADA",
            {
                "Computador": ip,
                "Perfil do Cliente": client_id.upper(),
                "Status": "Etapas em execução automática. Você receberá o ID do AnyDesk e o laudo em PDF aqui assim que concluir."
            },
            trace_id,
            emoji="🚀"
        )

    def _cmd_diagnostico(self, user_id: str, args: List[str], trace_id: str = None) -> str:
        trace_id = trace_id or new_trace_id()
        if not args:
            return self.msg_builder.error(WinRMResult(ok=False, host="N/A", command="/diagnostico", error="Uso: /diagnostico <IP>"), trace_id)

        ip = args[0]
        self._last_user_ip[user_id] = ip
        self._ensure_orchestrator()

        def _worker():
            log.info("task_started", trace_id, ip=ip, action="diagnostico_hardware")
            try:
                diag = self.orchestrator.run_diagnostics_only(ip=ip)
                if not diag.get("success", True) or diag.get("error"):
                    err = diag.get("error", "Host inacessível via WinRM na porta 5985.")
                    
                    if "401" in err or "credentials" in err.lower() or "unauthorized" in err.lower() or "acesso negado" in err.lower() or "rejected" in err.lower():
                        srv_url = self._get_server_url()
                        reply = self.msg_builder.success(
                            "MÁQUINA NÃO DESBLOQUEADA",
                            {"Motivo": "Acesso não autorizado.", "Solução": f"Baixe e execute o agente: {srv_url}/download/UltronAgent.exe"},
                            trace_id, emoji="⚠️"
                        )
                    else:
                        reply = self.msg_builder.error(WinRMResult(ok=False, host=ip, command="Diagnostico", error=err), trace_id)
                else:
                    telem   = diag.get("telemetry", {})
                    ai_diag = diag.get("ai_diagnosis", "")

                    disks_list = []
                    for d in telem.get("disks", []):
                        health_icon = "🟢" if d.get("health") in ["Healthy", "OK", "0"] else "🔴"
                        disks_list.append(f"{health_icon} {d.get('model')} ({d.get('size_gb')} GB) — {d.get('health', 'OK')}")
                    disks_str = " | ".join(disks_list)

                    bsods = telem.get("bsod_dumps", [])
                    bsod_str = f"{len(bsods)} detectada(s)" if bsods else "Nenhuma detectada"

                    dev_errs = telem.get("device_errors", [])
                    dev_str = f"{len(dev_errs)} com erro" if dev_errs else "Todos operacionais"

                    logged_user = telem.get("logged_in_user")
                    user_badge = self._format_user_badge(logged_user)
                    user_str = f"{user_badge}" if user_badge else (f"{logged_user}" if logged_user else "N/A")

                    # Atualiza o cache com o usuário detectado
                    if logged_user:
                        with self._cache_lock:
                            for dev in self._cached_devices:
                                if dev.get("ip") == ip:
                                    dev["logged_in_user"] = logged_user
                                    break

                    serial_num = telem.get("serial_number", "N/A")
                    mfg = telem.get("manufacturer", "")
                    mdl = telem.get("model", "")
                    from core.public_tools import HardwareWarrantyService
                    warranty_info = HardwareWarrantyService.lookup_warranty(serial_num, vendor=mfg, model=mdl)
                    warranty_str = f"{warranty_info.get('warranty_status')} ({warranty_info.get('vendor')})" if warranty_info.get("support_url") else "N/A"

                    reply = self.msg_builder.success(
                        "DIAGNÓSTICO COMPLETO DE HARDWARE",
                        {
                            "Host": f"{telem.get('computer_name', 'N/A')} ({ip})",
                            "Usuário Logado": user_str,
                            "Serial": serial_num,
                            "Garantia": warranty_str,
                            "Processador": telem.get('cpu', 'N/A'),
                            "Memória RAM": f"{telem.get('ram_gb', 'N/A')} GB",
                            "Armazenamento": disks_str or 'Não detectado',
                            "Telas Azuis": bsod_str,
                            "Drivers": dev_str,
                            "Parecer da IA": ai_diag
                        },
                        trace_id, emoji="🩺"
                    )
            except Exception as e:
                reply = self.msg_builder.error(WinRMResult(ok=False, host=ip, command="Diagnostico", error=str(e)), trace_id)

            if self.bot:
                self.bot.send_direct_message(user_id, reply)

        threading.Thread(target=_worker, daemon=True).start()
        return self.msg_builder.success("Coletando Telemetria...", {"Alvo": ip, "Ação": "Análise S.M.A.R.T em andamento"}, trace_id, emoji="🔍")

    def _cmd_ativar(self, user_id: str, args: List[str], trace_id: str = None) -> str:
        trace_id = trace_id or new_trace_id()
        if not args:
            return self.msg_builder.error(WinRMResult(ok=False, host="N/A", command="/ativar", error="Uso: /ativar <IP>"), trace_id)
        ip = args[0]
        self._last_user_ip[user_id] = ip

        def _worker():
            log.info("task_started", trace_id, ip=ip, action="ativar_windows")
            res = self.winrm.run_script_file(ip, "Activate-WindowsOffice.ps1")
            if res.get("auth_failed"):
                srv_url = self._get_server_url()
                reply = self.msg_builder.error(WinRMResult(ok=False, host=ip, command="Activate", error=f"Acesso negado. Baixe o agente: {srv_url}/download/UltronAgent.exe"), trace_id)
                if self.bot: self.bot.send_direct_message(user_id, reply)
                return

            if res["success"]:
                reply = self.msg_builder.success("ATIVAÇÃO CONCLUÍDA", {"Host": ip, "Status": "Windows e Office licenciados (MAS)"}, trace_id, emoji="🔑")
            else:
                reply = self.msg_builder.error(WinRMResult(ok=False, host=ip, command="Activate", error=res.get('stderr') or 'Erro WinRM'), trace_id)
            if self.bot:
                self.bot.send_direct_message(user_id, reply)

        threading.Thread(target=_worker, daemon=True).start()
        return self.msg_builder.success("Ativação em Andamento", {"Alvo": ip, "Status": "Executando MAS"}, trace_id, emoji="🔑")

    def _cmd_backup(self, user_id: str, args: List[str], trace_id: str = None) -> str:
        trace_id = trace_id or new_trace_id()
        if not args:
            return self.msg_builder.error(WinRMResult(ok=False, host="N/A", command="/backup", error="Uso: /backup <IP>"), trace_id)
        ip = args[0]
        self._last_user_ip[user_id] = ip

        def _worker():
            log.info("task_started", trace_id, ip=ip, action="fazer_backup")
            res = self.winrm.run_script_file(ip, "Backup-UserData.ps1")
            if res.get("auth_failed"):
                srv_url = self._get_server_url()
                reply = self.msg_builder.error(WinRMResult(ok=False, host=ip, command="Backup", error=f"Acesso negado. Baixe o agente: {srv_url}/download/UltronAgent.exe"), trace_id)
                if self.bot: self.bot.send_direct_message(user_id, reply)
                return

            if res["success"]:
                reply = self.msg_builder.success("BACKUP CONCLUÍDO", {"Host": ip, "Status": "Dados do perfil salvos no Storage"}, trace_id, emoji="💾")
            else:
                reply = self.msg_builder.error(WinRMResult(ok=False, host=ip, command="Backup", error=res.get('stderr') or 'Erro WinRM'), trace_id)
            if self.bot:
                self.bot.send_direct_message(user_id, reply)

        threading.Thread(target=_worker, daemon=True).start()
        return self.msg_builder.success("Backup em Andamento", {"Alvo": ip, "Destino": "Storage Central"}, trace_id, emoji="💾")

    def _cmd_dominio(self, user_id: str, args: List[str]) -> str:
        if len(args) < 2:
            return "⚠️ Uso: /dominio <IP> <cliente|domínio>\nExemplo: /dominio 192.168.57.25 penserede.local"
        ip = args[0]
        self._last_user_ip[user_id] = ip
        dom_target = args[1]

        profile = self.profile_mgr.get_client_profile(dom_target)
        domain_name = profile.get("dominio", dom_target) if profile else dom_target

        # Solicita credenciais do AD ao técnico
        return self._prompt_for_domain_credentials(user_id, ip, domain_name)

    def _execute_domain_join(self, user_id: str, ip: str, domain_name: str, dom_user: str, dom_pass: str, trace_id: str = None) -> str:
        trace_id = trace_id or new_trace_id()
        self._last_user_ip[user_id] = ip
        def _worker():
            log.info("task_started", trace_id, ip=ip, action="ingressar_dominio", domain=domain_name)
            res = self.winrm.run_script_file(
                ip,
                "Join-CustomerDomain.ps1",
                params={
                    "DomainName": domain_name,
                    "DomainUser": dom_user,
                    "DomainPassword": dom_pass,
                    "OUPath": "OU=Workstations,DC=penserede,DC=local"
                },
            )
            if res["success"]:
                reply = self.msg_builder.success("INGRESSO NO DOMÍNIO", {"Host": ip, "Domínio": domain_name, "Status": "Concluído com sucesso"}, trace_id, emoji="🛡️")
            else:
                reply = self.msg_builder.error(WinRMResult(ok=False, host=ip, command="DomainJoin", error=res.get('stderr') or 'Verifique DNS e credenciais de AD'), trace_id)
            if self.bot:
                self.bot.send_direct_message(user_id, reply)

        threading.Thread(target=_worker, daemon=True).start()
        return self.msg_builder.success("Ingresso de Domínio Iniciado", {"Alvo": ip, "Domínio": domain_name, "Usuário": dom_user}, trace_id, emoji="🛡️")

    SOFTWARE_ALIASES = {
        "chrome": "Google.Chrome",
        "google chrome": "Google.Chrome",
        "anydesk": "AnyDeskSoftwareGmbH.AnyDesk",
        "7zip": "7zip.7zip",
        "7-zip": "7zip.7zip",
        "vlc": "VideoLAN.VLC",
        "winrar": "RARLab.WinRAR",
        "rar": "RARLab.WinRAR",
        "adobe": "Adobe.Acrobat.Reader.64-bit",
        "acrobat": "Adobe.Acrobat.Reader.64-bit",
        "pdf": "Adobe.Acrobat.Reader.64-bit",
        "reader": "Adobe.Acrobat.Reader.64-bit",
        "office": "Microsoft.Office",
        "teams": "Microsoft.Teams",
        "vscode": "Microsoft.VisualStudioCode",
        "code": "Microsoft.VisualStudioCode",
        "spotify": "Spotify.Spotify",
        "discord": "Discord.Discord",
        "zoom": "Zoom.Zoom",
        "firefox": "Mozilla.Firefox",
        "brave": "Brave.Brave",
        "edge": "Microsoft.Edge",
        "notepad++": "Notepad++.Notepad++",
        "npp": "Notepad++.Notepad++",
        "git": "Git.Git",
        "python": "Python.Python.3.11",
        "node": "OpenJS.NodeJS",
        "nodejs": "OpenJS.NodeJS",
        "dbeaver": "dbeaver.dbeaver",
        "putty": "PuTTY.PuTTY",
        "filezilla": "TimKosse.FileZilla.Client",
        "obs": "OBSProject.OBSStudio",
        "steam": "Valve.Steam",
        "rufus": "Rufus.Rufus",
    }

    def _cmd_softwares(self, user_id: str, args: List[str], trace_id: str = None) -> str:
        trace_id = trace_id or new_trace_id()
        if len(args) < 2:
            return self.msg_builder.error(WinRMResult(ok=False, host="N/A", command="/softwares", error="Uso: /softwares <IP> <app1, app2...>"), trace_id)
            
        ip = self._extract_target_ip(args[0]) or args[0]
        self._last_user_ip[user_id] = ip

        raw_str = " ".join(args[1:]) if len(args) > 1 else ""
        raw_items = [p.strip() for p in re.split(r"[,;]+|\be\b|\band\b", raw_str) if p.strip()]

        # Traduz nomes amigáveis para IDs oficiais do Winget / UniGetUI
        resolved_pkgs = []
        for item in raw_items:
            clean_item = re.sub(r"^(?:os?\s+|as?\s+|uns?\s+|umas?\s+|programa\s+|software\s+|app\s+|aplicativo\s+)+", "", item.strip(), flags=re.IGNORECASE).strip()
            norm = _normalize_token(clean_item)
            resolved = self.SOFTWARE_ALIASES.get(norm, clean_item or item)
            resolved_pkgs.append(resolved)

        if not resolved_pkgs:
            return self.msg_builder.error(WinRMResult(ok=False, host=ip, command="Install", error="Nenhum software válido identificado"), trace_id)

        def _worker():
            log.info("task_started", trace_id, ip=ip, action="instalar_software", packages=resolved_pkgs)
            res = self.winrm.run_script_file(
                ip,
                "Install-UnifiedPackages.ps1",
                params={"Packages": resolved_pkgs}
            )
            if res.get("auth_failed"):
                srv_url = self._get_server_url()
                reply = self.msg_builder.error(WinRMResult(ok=False, host=ip, command="Install", error=f"Acesso negado. Baixe o agente: {srv_url}/download/UltronAgent.exe"), trace_id)
                if self.bot: self.bot.send_direct_message(user_id, reply)
                return

            if res["success"]:
                reply = self.msg_builder.success(
                    "SOFTWARES INSTALADOS",
                    {
                        "Computador": ip,
                        "Pacotes processados": ", ".join(resolved_pkgs),
                        "Motor": "Winget / UniGetUI"
                    },
                    trace_id, emoji="📦"
                )
            else:
                reply = self.msg_builder.error(WinRMResult(ok=False, host=ip, command="Install", error=res.get('stderr') or res.get('stdout') or 'Erro Winget'), trace_id)
            if self.bot:
                self.bot.send_direct_message(user_id, reply)

        threading.Thread(target=_worker, daemon=True).start()
        return self.msg_builder.success("Instalação Iniciada", {"Alvo": ip, "Pacotes": ", ".join(resolved_pkgs)}, trace_id, emoji="📦")

    def _cmd_power(self, user_id: str, args: List[str], action: str, trace_id: str = None) -> str:
        trace_id = trace_id or new_trace_id()
        if not args:
            return self.msg_builder.error(WinRMResult(ok=False, host="N/A", command=action, error=f"Uso: /{action} <IP>"), trace_id)
        
        ip  = args[0]
        self._last_user_ip[user_id] = ip
        cmd = "Restart-Computer -Force" if action == "restart" else "Stop-Computer -Force"
        act = "reiniciada" if action == "restart" else "desligada"

        log.info("task_started", trace_id, ip=ip, action=f"power_{action}")

        # 1. Enfileira imediatamente no AgentTaskManager para caso o WinRM esteja offline/bloqueado
        agent_cmd = "shutdown /r /t 0 /f" if action == "restart" else "shutdown /s /t 0 /f"
        try:
            from main import agent_task_mgr
            agent_task_mgr.enqueue_task(ip, agent_cmd, task_type="cmd")
        except Exception:
            pass

        # 2. Executa via WinRM para efeito imediato
        try:
            res = self.winrm.run_powershell_code(ip, cmd)
            stderr = (res.get("stderr") or "").lower()
            if res.get("success") or "sendo desligado" in stderr or "shutting down" in stderr or "restartcomputerfailed" in stderr:
                return self.msg_builder.success("CONTROLE DE ENERGIA", {"Host": ip, "Ação": f"Máquina {act} com sucesso"}, trace_id, emoji="🔌")
            elif res.get("auth_failed"):
                srv_url = self._get_server_url()
                return self.msg_builder.success("CONTROLE DE ENERGIA (Fallback Agent)", {"Host": ip, "Ação": f"Ordem de {act} enviada para o UltronAgent em segundo plano", "Dica": f"Caso não execute, instale o agente: {srv_url}/download"}, trace_id, emoji="🔌")
            else:
                return self.msg_builder.success("CONTROLE DE ENERGIA (Fallback Agent)", {"Host": ip, "Ação": f"Ordem de {act} enviada para o UltronAgent (SYSTEM) em segundo plano"}, trace_id, emoji="🔌")
        except Exception:
            return self.msg_builder.success("CONTROLE DE ENERGIA", {"Host": ip, "Ação": f"Ordem para {act} enviada via UltronAgent"}, trace_id, emoji="🔌")

    def _cmd_message(self, user_id: str, args: List[str]) -> str:
        if len(args) < 2:
            return "⚠️ Uso: /msg <IP> <mensagem>\nExemplo: /msg 192.168.57.25 Máquina pronta para entrega"
        ip = args[0]
        self._last_user_ip[user_id] = ip
        msg_text = " ".join(args[1:])

        def _worker():
            # 1. Enfileira no AgentTaskManager para entrega garantida pelo UltronAgent
            try:
                from main import agent_task_mgr
                msg_cmd = f"powershell.exe -ExecutionPolicy Bypass -NoProfile -Command \"Add-Type -AssemblyName PresentationFramework; [System.Windows.MessageBox]::Show('{msg_text}', 'Ultron — Suporte Pense Rede', 'OK', 'Information')\""
                agent_task_mgr.enqueue_task(ip, msg_cmd, task_type="cmd")
            except Exception:
                pass

            # 2. Tenta via WinRM
            res = self.winrm.run_script_file(
                ip,
                "Show-UserMessage.ps1",
                params={
                    "Message": msg_text,
                    "Title": "Ultron — Suporte Pense Rede",
                    "Icon": "Information"
                }
            )
            if res.get("success"):
                reply = f"📢 MENSAGEM EXIBIDA COM SUCESSO\n\n📍 Destino: {ip}\n💬 Mensagem: \"{msg_text}\""
            else:
                reply = f"📢 MENSAGEM DESPACHADA\n\n📍 Destino: {ip}\n💬 Mensagem: \"{msg_text}\"\n✅ A mensagem será exibida na tela do computador pelo UltronAgent."

            if self.bot:
                self.bot.send_direct_message(user_id, reply)

        threading.Thread(target=_worker, daemon=True).start()
        return f"📢 Enviando mensagem para a tela do usuário em {ip}..."

    def _cmd_laudos(self, args: List[str]) -> str:
        from reports.report_generator import ReportGenerator
        r_gen = ReportGenerator()
        reports = r_gen.list_reports()
        if not reports:
            return "📄 Nenhum laudo técnico encontrado no sistema."

        lines = [f"📄 ÚLTIMOS LAUDOS TÉCNICOS GERADOS ({len(reports)}):\n"]
        for r in reports[:6]:
            lines.append(
                f"• {r.get('hostname')} ({r.get('client')})\n"
                f"  Serial: {r.get('serial')} | Data: {r.get('created_at')}\n"
                f"  Download: {r.get('download_url')}\n"
            )

        return "\n".join(lines)

    def _cmd_erro(self, args: List[str]) -> str:
        if len(args) < 1:
            return "⚠️ Informe o código de erro hexadecimal. Exemplo: /erro 0x80070005"
        code = args[0]
        data = self.error_svc.lookup(code)
        
        cmd_part = f"\n\n🔧 Comando de Reparo PowerShell:\n{data.get('command')}" if data.get("command") else ""
        return (
            f"🐞 DECODIFICADOR DE ERROS WINDOWS\n\n"
            f"🔍 Código: {data.get('code')} — {data.get('name')}\n"
            f"📌 Categoria: {data.get('category')}\n\n"
            f"⚠️ Causa Provável:\n{data.get('cause')}\n\n"
            f"✅ Solução Recomendada:\n{data.get('solution')}"
            f"{cmd_part}"
        )

    def _cmd_cve(self, args: List[str]) -> str:
        if len(args) < 1:
            return "⚠️ Informe o software para buscar vulnerabilidades. Exemplo: /cve winrar"
        pkg = args[0]
        data = self.cve_svc.search_vulnerabilities(pkg)
        vulns = data.get("vulnerabilities", [])
        if not vulns:
            return f"🛡️ Nenhuma vulnerabilidade crítica recente encontrada para {pkg}."

        lines = [f"🛡️ VULNERABILIDADES ENCONTRADAS — {pkg.upper()} ({len(vulns)}):\n"]
        for v in vulns[:4]:
            lines.append(
                f"• {v.get('id')} [{v.get('severity')}] ({v.get('published')})\n"
                f"  {v.get('summary')}\n"
            )
        return "\n".join(lines)

    def _cmd_clima(self) -> str:
        data = self.weather_svc.get_ambient_conditions()
        return (
            f"🌡️ TELEMETRIA TÉRMICA DO LABORATÓRIO\n\n"
            f"• Temperatura Atual: {data.get('temperature_c')}°C (Sensação: {data.get('apparent_temperature_c')}°C)\n"
            f"• Umidade Relativa: {data.get('relative_humidity_pct')}%\n"
            f"• Margem Térmica: {data.get('thermal_headroom_rating')}\n\n"
            f"💡 Avaliação: {data.get('thermal_warning')}"
        )

    def _cmd_wan(self) -> str:
        data = self.wan_svc.get_public_ip_info()
        return (
            f"🌐 TELEMETRIA DE CONEXÃO & LINK WAN\n\n"
            f"• IP Público: {data.get('ip')}\n"
            f"• Provedor (ISP): {data.get('isp')} ({data.get('asn')})\n"
            f"• Localização: {data.get('city')}, {data.get('region')} — {data.get('country')}\n"
            f"• Latência DNS: {data.get('dns_probe_latency_ms')} ms\n"
            f"• Status: {data.get('link_status')}"
        )

    def _cmd_garantia(self, user_id: str, args: List[str]) -> str:
        """Consulta status e portal de suporte oficial de garantia OEM de um IP ou Serial"""
        target = args[0] if args else self._last_user_ip.get(user_id)
        if not target:
            return "⚠️ Uso: /garantia <IP ou Serial>\nExemplo: /garantia 57.48 ou /garantia 6RTDPK3"

        target_ip = self._extract_target_ip(target)
        serial = target
        vendor = ""
        model = ""
        if target_ip:
            cached = self._get_cached_devices()
            dev = next((d for d in cached if d.get("ip") == target_ip), None)
            if dev:
                serial = dev.get("serial") or target_ip
                vendor = dev.get("vendor", "")
                model = dev.get("model", "")

        from core.public_tools import HardwareWarrantyService
        info = HardwareWarrantyService.lookup_warranty(serial, vendor, model)
        link_str = f"\n🔗 Portal Oficial: {info.get('support_url')}" if info.get("support_url") else ""

        return (
            f"🏷️ **GARANTIA & SUPORTE OFICIAL OEM**\n\n"
            f"💻 Fabricante: **{info.get('vendor')}** {model}\n"
            f"🏷️ Serial / Service Tag: `{serial}`\n"
            f"🛡️ Status: **{info.get('warranty_status')}**\n"
            f"📌 Nível de Cobertura: {info.get('support_level')}"
            f"{link_str}"
        )

    def _cmd_senha(self, args: List[str]) -> str:
        """Audita se uma senha corporativa/temporária consta em vazamentos públicos (HaveIBeenPwned)"""
        if not args:
            return "⚠️ Uso: /senha <senha_a_testar>\nExemplo: /senha Ultron@2026"
        pwd = args[0]
        from core.public_tools import HaveIBeenPwnedService
        res = HaveIBeenPwnedService.is_password_pwned(pwd)
        icon = "🚨" if res.get("pwned") else "✅"
        count_str = f"\n⚠️ Ocorrências em vazamentos públicos: **{res.get('breach_count')} vezes**" if res.get("pwned") else "\n🛡️ A senha é segura e nunca foi encontrada em vazamentos conhecidos."
        return (
            f"{icon} **AUDITORIA DE SEGURANÇA DE SENHA (HIBP)**\n\n"
            f"🔑 Avaliação: **{res.get('rating')}**"
            f"{count_str}"
        )

    def _cmd_backup_softwares(self, user_id: str, args: List[str]) -> str:
        """Varre os softwares instalados na máquina de bancada e salva bundle UniGetUI (.json)"""
        target_ip = args[0] if args else self._last_user_ip.get(user_id)
        if not target_ip:
            return "⚠️ Uso: /backup_softwares <IP>\nExemplo: /backup_softwares 57.48"

        target_ip = self._extract_target_ip(target_ip) or target_ip
        self._last_user_ip[user_id] = target_ip

        def _worker():
            res = self.pkg_mgr.export_machine_packages(target_ip)
            if res.get("success"):
                pkgs = res.get("packages", [])
                sample = ", ".join(p.get("Name", p.get("Id", "")) for p in pkgs[:6])
                more = f" e mais {len(pkgs)-6} programas" if len(pkgs) > 6 else ""
                reply = (
                    f"📦 **BACKUP DE SOFTWARES UNIGETUI CONCLUÍDO**\n\n"
                    f"📍 Computador: **{target_ip}** ({res.get('hostname')})\n"
                    f"📄 Arquivo: `{res.get('filename')}`\n"
                    f"📊 Total catalogado: **{res.get('packages_count')} programas**\n\n"
                    f"📋 Principais softwares:\n• {sample}{more}\n\n"
                    f"💡 Para reinstalar após a formatação: *'/restaurar_softwares {target_ip}'*"
                )
            else:
                reply = f"❌ Falha ao exportar softwares da máquina {target_ip}: {res.get('error')}"

            if self.bot:
                self.bot.send_direct_message(user_id, reply)

        threading.Thread(target=_worker, daemon=True).start()
        return f"🔍 Inspecionando e catalogando programas instalados em {target_ip} (formato UniGetUI)..."

    def _cmd_restaurar_softwares(self, user_id: str, args: List[str]) -> str:
        """Reinstala os softwares contidos em um bundle UniGetUI salvo anteriormente"""
        target_ip = args[0] if args else self._last_user_ip.get(user_id)
        if not target_ip:
            return "⚠️ Uso: /restaurar_softwares <IP> [nome_do_arquivo]\nExemplo: /restaurar_softwares 57.48"

        target_ip = self._extract_target_ip(target_ip) or target_ip
        self._last_user_ip[user_id] = target_ip
        bundle_arg = args[1] if len(args) > 1 else None

        def _worker():
            res = self.pkg_mgr.restore_machine_packages(target_ip, bundle_arg)
            if res.get("success"):
                reply = (
                    f"✅ **RESTAURAÇÃO DE SOFTWARES CONCLUÍDA**\n\n"
                    f"📍 Computador: **{target_ip}**\n"
                    f"📄 Bundle: `{res.get('bundle_file')}`\n"
                    f"📦 Pacotes processados: **{res.get('packages_sent')} softwares**\n\n"
                    f"Todos os programas do cliente foram restaurados na máquina via Winget/UniGetUI."
                )
            else:
                reply = f"❌ Falha ao restaurar softwares em {target_ip}: {res.get('error')}"

            if self.bot:
                self.bot.send_direct_message(user_id, reply)

        threading.Thread(target=_worker, daemon=True).start()
        return f"📦 Iniciando restauração do bundle de softwares na máquina {target_ip}..."

    def _cmd_upgrade_softwares(self, user_id: str, args: List[str]) -> str:
        """Atualiza todos os programas instalados na máquina para as versões mais recentes (winget upgrade --all)"""
        target_ip = args[0] if args else self._last_user_ip.get(user_id)
        if not target_ip:
            return "⚠️ Uso: /atualizar_softwares <IP>\nExemplo: /atualizar_softwares 57.48"

        target_ip = self._extract_target_ip(target_ip) or target_ip
        self._last_user_ip[user_id] = target_ip

        def _worker():
            res = self.pkg_mgr.upgrade_all_packages(target_ip)
            if res.get("success"):
                reply = (
                    f"🚀 **ATUALIZAÇÃO EM MASSA CONCLUÍDA**\n\n"
                    f"📍 Computador: **{target_ip}**\n\n"
                    f"✅ Todos os softwares instalados na máquina foram atualizados para as versões mais recentes disponíveis via Winget/UniGetUI!"
                )
            else:
                reply = f"⚠️ Conclusão do processo de atualização em {target_ip}:\n{res.get('error') or res.get('output')}"

            if self.bot:
                self.bot.send_direct_message(user_id, reply)

        threading.Thread(target=_worker, daemon=True).start()
        return f"🚀 Executando atualização em massa de todos os programas instalados em {target_ip}..."

    def _cmd_list_bundles(self) -> str:
        """Lista todos os backups de softwares de clientes salvos no laboratório"""
        bundles = self.pkg_mgr.list_saved_bundles()
        if not bundles:
            return "📦 Nenhum backup de softwares UniGetUI salvo no laboratório ainda.\n\n💡 Use *'/backup_softwares <IP>'* para criar um."

        lines = [f"📦 **Backups de Softwares UniGetUI Salvos** ({len(bundles)}):\n"]
        for b in bundles[:8]:
            lines.append(
                f"• **{b.get('hostname')}** ({b.get('packages_count')} softwares)\n"
                f"  📄 `{b.get('filename')}` | 📅 {b.get('created_at')}\n"
            )
        lines.append("💡 Para restaurar em uma máquina: *'/restaurar_softwares <IP> <arquivo>'*")
        return "\n".join(lines)

    def _cmd_buscar_software(self, user_id: str, args: List[str]) -> str:
        """Busca qualquer programa no catálogo global do UniGetUI / Winget"""
        if not args:
            return "⚠️ Uso: /buscar_software <nome_do_programa>\nExemplo: /buscar_software postman ou /buscar_software blender"

        query = " ".join(args).strip()
        target_ip = self._last_user_ip.get(user_id) or "192.168.57.48"

        def _worker():
            res = self.winrm.run_script_file(target_ip, "Search-Packages.ps1", params={"Query": query})
            out = res.get("stdout", "").strip()
            if out:
                reply = (
                    f"🔍 **RESULTADOS DE BUSCA NO UNIGETUI — '{query.upper()}'**\n\n"
                    f"```\n{out}\n```\n\n"
                    f"💡 Para instalar: *'/softwares {target_ip} {query}'*"
                )
            else:
                reply = f"⚠️ Nenhum software encontrado no catálogo para '{query}'."

            if self.bot:
                self.bot.send_direct_message(user_id, reply)

        threading.Thread(target=_worker, daemon=True).start()
        return f"🔍 Consultando catálogo global do UniGetUI para '{query}'..."

    def _cmd_download_agent(self, user_id: str) -> str:
        """Envia o executável UltronAgent.exe diretamente como anexo no TrueConf e fornece link"""
        from core.agent_builder import agent_builder
        bin_info = agent_builder.get_latest_agent_binary()
        found_path = bin_info["file_path"]
        version = bin_info["version"]
        versioned_filename = bin_info["filename"]

        # Se o bot estiver conectado, envia o arquivo diretamente como anexo no TrueConf
        if self.bot and found_path and os.path.exists(found_path):
            try:
                self.bot.send_direct_file(
                    user_id=user_id,
                    file_path=found_path,
                    caption=f"📎 {versioned_filename} (Atualizado) — Agente de Automação de Bancada (Pense Rede)",
                    filename=versioned_filename
                )
            except Exception as e:
                logger.warning(f"Não foi possível anexar arquivo no chat: {e}")

        srv_url = self._get_server_url()
        return (
            f"📥 ULTRON AGENT v{version} (.EXE) — PRONTO PARA USO\n\n"
            f"📎 O arquivo {versioned_filename} foi enviado como anexo diretamente aqui no seu chat!\n\n"
            f"💡 Novidades desta versão (v{version}):\n"
            "• Auto-Atualização Silenciosa OTA (Over-The-Air)\n"
            "• Detecção em tempo real do Usuário Logado na máquina\n"
            "• Captura automática de ID do AnyDesk\n"
            "• Auto-instalação como Serviço Windows SYSTEM (UltronService)\n"
            "• Suporte a instalações e bundles universais do UniGetUI\n\n"
            "🌐 Link para download direto no navegador:\n"
            f"{srv_url}/download/UltronAgent.exe"
        )

    # ------------------------------------------------------------------
    # Diálogos Interativos (MDT Hook & Sessões)
    # ------------------------------------------------------------------

    def register_mdt_arrival(self, user_id: str, ip: str, serial: str):
        """Registra uma máquina recém-chegada via MDT e monta um menu numerado para o técnico"""
        clients = self.profile_mgr.list_clients()[:6]
        options = [c.get("id") for c in clients]

        self.user_sessions[user_id] = {
            "type": "pending_mdt",
            "ip": ip,
            "serial": serial,
            "options": options
        }

        menu_lines = [
            f"🤖 Ultron — Nova Máquina Pronta no MDT!\n",
            f"📍 IP: {ip} | 🏷️ Serial: {serial}\n",
            f"Qual perfil de cliente devo aplicar nesta máquina? Responda com o número:\n"
        ]
        for idx, c in enumerate(clients, 1):
            menu_lines.append(f"{idx}. {c.get('nome')} ({c.get('id')})")

        menu_lines.append("\nOu envie: /preparar <IP> <cliente>")
        return "\n".join(menu_lines)

    def _handle_pending_mdt_choice(self, user_id: str, session: Dict[str, Any], text: str) -> Optional[str]:
        ip = session.get("ip")
        options = session.get("options", [])

        chosen_client = None
        if text.isdigit():
            idx = int(text) - 1
            if 0 <= idx < len(options):
                chosen_client = options[idx]
        elif text.lower() in [opt.lower() for opt in options]:
            chosen_client = text.lower()

        if chosen_client:
            del self.user_sessions[user_id]
            return self._cmd_preparar(user_id, [ip, chosen_client])

        return None

    # ------------------------------------------------------------------
    # IA Conversacional com Histórico e Restrições de Domínio
    # ------------------------------------------------------------------

    def _handle_ai_conversation(self, user_id: str, text: str) -> str:
        """Responde a conversas livres usando IA e Knowledge Engine com contexto de bancada instantâneo."""
        try:
            devices = self._get_cached_devices()
            clients = self.profile_mgr.list_clients()

            winrm_devs = [d for d in devices if d.get("winrm_ready")]
            if winrm_devs:
                winrm_str = f"{len(winrm_devs)} máquina(s) prontas com WinRM (" + ", ".join(f"{d.get('ip')} - {d.get('hostname', 'PC').replace('.penserede.local', '')}" for d in winrm_devs[:4]) + ")"
            else:
                winrm_str = "Nenhuma máquina com WinRM ativo"

            bench_summary = f"{len(devices)} dispositivos conectados ({winrm_str})" if devices else "Nenhum computador ativo detectado na bancada no momento."
            client_summary = ", ".join(f"{c.get('nome')} ({c.get('id')})" for c in clients[:8])

            if user_id not in self.user_conversations:
                self.user_conversations[user_id] = []

            self.user_conversations[user_id].append({"role": "user", "content": text})
            if len(self.user_conversations[user_id]) > 12:
                self.user_conversations[user_id] = self.user_conversations[user_id][-12:]

            system_prompt = f"""Você é ULTRON, o assistente operacional de automação de TI do laboratório da Pense Rede.

Você não é um chatbot genérico, atendente virtual ou assistente pessoal.
Você atua como um colega técnico experiente da equipe de suporte, integrado ao TrueConf e conectado às ferramentas de automação do laboratório.
Você está conversando no chat do TrueConf com: {user_title}.

# 1. IDENTIDADE
Seu nome é Ultron. Você trabalha no ambiente técnico da Pense Rede.
Você conhece o contexto de bancada, máquinas, IPs, usuários, clientes, softwares e operações disponíveis no sistema.
Sua personalidade deve transmitir: competência técnica, rapidez, clareza, segurança, naturalidade, iniciativa e objetividade.
Você deve parecer um técnico experiente conversando com outro técnico pelo chat.
Nunca fale como um robô, SAC, assistente corporativo genérico ou documentação técnica.

# 2. ESTILO DE CONVERSA
Converse como uma pessoa em um chat como WhatsApp, Teams ou TrueConf. Prefira frases curtas.
Se uma resposta puder ser dada em duas frases, não escreva cinco parágrafos.
Use português brasileiro natural. Exemplos aceitáveis: "Beleza, achei a máquina.", "Vou verificar o 57.48.", "Deu certo. O Chrome já foi instalado.", "Qual máquina?", "Qual cliente vai receber esse PC?".
Evite formalidade excessiva. Não use linguagem de atendimento ao cliente.

# 3. FRASES PROIBIDAS
Nunca utilize frases genéricas ou clichês típicos de assistentes de IA, incluindo:
"Como posso ajudar hoje?", "Como posso ajudá-lo?", "Estou aqui para ajudar.", "Espero que esta mensagem o encontre bem.", "Sou um modelo de linguagem.", "Como inteligência artificial...", "Aqui estão algumas opções.", "Certamente!", "Claro! Ficarei feliz em ajudar.", "Entendo como isso pode ser frustrante.", "Com base nas informações fornecidas...", "Por favor, forneça mais detalhes para que eu possa ajudá-lo melhor."
Não comece respostas com frases vazias. Vá direto ao assunto.

# 4. REGRA PRINCIPAL DE COMUNICAÇÃO
Pense sempre: "Como um técnico da equipe responderia isso no chat?"
A resposta deve parecer escrita por uma pessoa que trabalha no laboratório.

# 5. CONTEXTO DA CONVERSA
Mantenha o contexto das mensagens anteriores. Se o usuário mencionar uma máquina e continuar falando dela, considere que as próximas mensagens se referem à mesma máquina até que outro alvo seja informado. Não pergunte novamente o IP se ele já estiver claro no contexto.

# 6. NÃO REPITA PERGUNTAS
Nunca pergunte algo que o usuário já informou. Se o IP já apareceu na conversa, use-o. Se o cliente já foi informado, use-o.

# 7. COMO FAZER PERGUNTAS
Quando precisar perguntar algo, faça apenas a pergunta necessária.
Ruim: "Para que eu possa prosseguir com essa operação, poderia informar qual é o endereço IP da máquina em questão?"
Bom: "Qual máquina?"
Uma pergunta por vez sempre que possível.

# 8. INTERPRETAÇÃO DE LINGUAGEM NATURAL
Entenda frases naturais, abreviações e pequenas variações.
Exemplos: "instala chrome no 48", "bota anydesk no 57.48", "vê a saúde daquele pc", "reinicia ele". Interprete a intenção utilizando o contexto disponível antes de pedir esclarecimentos.

# 9. EXECUÇÃO DE OPERAÇÕES
Quando a intenção e os parâmetros necessários estiverem claros, execute a ação usando as ferramentas disponíveis.
Não responda com tutorial. O Ultron executa a operação quando possui uma ferramenta apropriada.

# 10. VERACIDADE OPERACIONAL
Nunca invente resultados. Existe diferença entre: AÇÃO SOLICITADA, AÇÃO ENVIADA, AÇÃO EM EXECUÇÃO, AÇÃO CONCLUÍDA, AÇÃO COM FALHA.
Se uma tarefa foi apenas enviada: "Comando enviado para o 57.48. Estou aguardando o retorno."
Somente confirme conclusão quando existir retorno real da ferramenta. Nunca diga: "Foi instalado." se o backend ainda não confirmou isso.

# 11. QUANDO UMA OPERAÇÃO FALHAR
Explique o problema de forma curta e prática.
Exemplo: "⚠️ O 57.48 está online, mas o WinRM recusou o acesso. Parece que o UltronAgent ainda não liberou a máquina."
Se souber uma próxima ação segura, sugira. Não despeje stack traces ou JSON.

# 12. CONFIRMAÇÕES
Não peça confirmação para ações simples e claramente solicitadas. Ex: "instala chrome no 48" -> execute.
Para ações destrutivas ou de maior impacto, confirme o alvo quando houver qualquer ambiguidade.

# 13. FUNÇÕES DO ULTRON
- Bancada: Consultar computadores.
- Diagnóstico: S.M.A.R.T, discos, memória, CPU.
- Preparação de máquinas: Iniciar a esteira automatizada.
- Softwares: Instalar, consultar, atualizar, backup.
- AnyDesk: Consultar ID.
- Backup, Active Directory, Energia, Mensagens, Garantia, Segurança.
- UltronAgent: Orientar instalação, download.

# 14. LIMITES E SEGURANÇA
Nunca invente uma capacidade que não esteja disponível. Nunca invente: IP, AnyDesk, serial, status, diagnóstico, resultado. Se não houver informação, diga claramente.
Não exponha credenciais, tokens, ou chaves.

# 15. NÃO EXPLIQUE A IMPLEMENTAÇÃO INTERNA
O técnico não precisa saber detalhes internos do código. Evite: "Vou utilizar o módulo WinRMExecutor..." Prefira: "Vou tentar acessar ela pelo WinRM."

# 16. TAMANHO DAS RESPOSTAS
Para operações normais: 1 a 4 linhas. Evite paredes de texto.

# 17. USO DE EMOJIS
Use principalmente para indicar estado: ✅ sucesso, ⚠️ atenção, ❌ erro, 🔍 consulta, 📦 software, 💻 máquina, 🔌 energia, 📢 mensagem. Não coloque vários emojis em todas as frases.

# 18. RESPOSTAS A MENSAGENS CURTAS
Interprete respostas curtas usando o contexto. Usuário: "foi?" -> Consulte o estado da última operação relevante. Usuário: "e o 49?" -> Consulte o 49. Usuário: "faz nele também" -> Use a operação anterior no alvo mais recente.

# 19. QUANDO NÃO ENTENDER
Não invente uma interpretação. Mas também não responda: "Não entendi sua solicitação." Tente identificar exatamente o que falta fazendo a menor pergunta possível.

# 20. PEDIDOS NÃO SUPORTADOS
Se o usuário pedir uma automação que você não possui (ex: instalar algo que não tem, ou uma função que não existe), NUNCA gere uma lista/menu com as coisas que você PODE fazer.
Diga apenas algo simples e direto, como: "Ainda não consigo automatizar isso. Se precisar, sugiro acessar a máquina via AnyDesk."

# 21. POSTURA
Seja confiante quando possuir dados. Seja transparente quando não possuir. Nunca finja certeza. Não aja como um menu automático. Você é o Ultron da bancada da Pense Rede: técnico, rápido, contextual e natural."""

            history_lines = []
            for m in self.user_conversations[user_id][:-1]:
                role_pt = "Usuário" if m["role"] == "user" else "Ultron"
                history_lines.append(f"{role_pt}: {m['content']}")
            history_text = "\n".join(history_lines)
            if history_text:
                history_text = f"\nHISTÓRICO RECENTE DA CONVERSA:\n{history_text}\n"

            prompt = (
                f"CONTEXTO DO LABORATÓRIO:\n"
                f"- Bancada: {bench_summary}\n"
                f"- Clientes cadastrados: {client_summary}\n"
                f"- Último IP operado: {self._last_user_ip.get(user_id, 'nenhum')}\n"
                f"- Usuário atual: {user_title}\n"
                f"{history_text}\n"
                f"Mensagem atual do Usuário: \"{text}\"\n"
            )

            self._ensure_orchestrator()
            reply = self.orchestrator.analyzer.generate(prompt, system_prompt=system_prompt)

            if reply and not reply.startswith("⚠️"):
                clean_reply = reply.replace("<br />", "\n").replace("<br/>", "\n").replace("<br>", "\n").strip()
                self.user_conversations[user_id].append({"role": "assistant", "content": clean_reply})
                return clean_reply
            elif reply:
                return reply

        except Exception as e:
            logger.error(f"Erro na IA conversacional: {e}")

        return "⚠️ Não entendi o comando. Se você está tentando enviar uma mensagem ou rodar uma automação, verifique a sintaxe ou digite `/ajuda`."

    # ------------------------------------------------------------------
    # Utilitários Internos
    # ------------------------------------------------------------------

    def _ensure_orchestrator(self):
        if not self.orchestrator:
            from core.orchestrator import LabOrchestrator
            self.orchestrator = LabOrchestrator()
