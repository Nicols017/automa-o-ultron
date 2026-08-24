"""
TrueConf ChatOps — Ultron Lab Automation
Processa comandos slash, diálogos interativos e conversação com IA local no chat privado do TrueConf.
"""

import re
import threading
from typing import Any, Dict, List, Optional

from core.profile_manager import ProfileManager
from core.network_scanner import NetworkScanner
from core.winrm_executor import WinRMExecutor
from core.public_tools import (
    CveSecurityService,
    LabWeatherService,
    NetworkDiagnosticsService,
    WindowsErrorLookupService,
)

class TrueConfChatOps:
    """Roteador central de comandos ChatOps do Ultron para o TrueConf."""

    def __init__(self, orchestrator=None, bot=None):
        self.orchestrator = orchestrator
        self.bot          = bot

        # Serviços de infraestrutura
        self.profile_mgr = ProfileManager()
        self.scanner     = NetworkScanner()
        self.winrm       = WinRMExecutor()

        # Serviços públicos / consultas externas
        self.weather_svc = LabWeatherService()
        self.error_svc   = WindowsErrorLookupService()
        self.cve_svc     = CveSecurityService()
        self.wan_svc     = NetworkDiagnosticsService()

        # Sessões interativas pendentes keyed por user_id
        # Ex: {"nicolas": {"type": "pending_mdt", "ip": "192.168.57.25", "options": ["nova_via", ...]}}
        self.user_sessions: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Ponto de entrada principal
    # ------------------------------------------------------------------

    def handle_incoming_message(self, user_id: str, message: str) -> str:
        """
        Recebe qualquer mensagem enviada ao bot no chat privado do TrueConf.
        Prioridade:
        1. Sessões interativas ativas (ex: escolha numerada pós-MDT)
        2. Roteamento de comandos slash explícitos (/bancada, /preparar, etc.)
        3. Detecção rápida de intenções em linguagem natural (códigos de erro, bancada, etc.)
        4. IA conversacional com contexto em tempo real do laboratório.
        """
        text = (message or "").strip()
        if not text:
            return "Olá! Envie `/ajuda` para ver os comandos de bancada disponíveis."

        # 1. Sessão interativa pendente (ex: escolha de cliente pós-MDT)
        if user_id in self.user_sessions:
            session = self.user_sessions[user_id]
            if session.get("type") == "pending_mdt":
                result = self._handle_pending_mdt_choice(user_id, session, text)
                if result:
                    return result

        # 2. Roteamento de comandos slash explícitos
        parts       = text.split()
        first_token = parts[0].lower() if parts else ""

        routes = {
            frozenset(["/ajuda", "/help", "/start", "ajuda", "help"]):
                lambda: self._cmd_help(),
            frozenset(["/bancada", "/status", "/maquinas", "/lab", "/hosts"]):
                lambda: self._cmd_bancada(user_id),
            frozenset(["/clientes", "/perfis", "/empresas"]):
                lambda: self._cmd_clientes(),
            frozenset(["/chamados", "/milvus", "/tickets"]):
                lambda: self._cmd_chamados(),
            frozenset(["/preparar", "/iniciar", "/deploy", "/formatar"]):
                lambda: self._cmd_preparar(user_id, parts[1:]),
            frozenset(["/diagnostico", "/diag", "/inspecionar", "/smart"]):
                lambda: self._cmd_diagnostico(user_id, parts[1:]),
            frozenset(["/ativar", "/ativacao", "/mas"]):
                lambda: self._cmd_ativar(parts[1:]),
            frozenset(["/backup", "/storage"]):
                lambda: self._cmd_backup(parts[1:]),
            frozenset(["/dominio", "/domain", "/ad"]):
                lambda: self._cmd_dominio(parts[1:]),
            frozenset(["/softwares", "/apps", "/instalar"]):
                lambda: self._cmd_softwares(parts[1:]),
            frozenset(["/reiniciar", "/reboot"]):
                lambda: self._cmd_power(parts[1:], "restart"),
            frozenset(["/desligar", "/shutdown"]):
                lambda: self._cmd_power(parts[1:], "shutdown"),
            frozenset(["/laudos", "/laudo", "/relatorios"]):
                lambda: self._cmd_laudos(parts[1:]),
            frozenset(["/erro", "/error", "/bsod"]):
                lambda: self._cmd_erro(parts[1:]),
            frozenset(["/cve", "/seguranca", "/vuln"]):
                lambda: self._cmd_cve(parts[1:]),
            frozenset(["/clima", "/termica", "/temperatura"]):
                lambda: self._cmd_clima(),
            frozenset(["/wan", "/ip"]):
                lambda: self._cmd_wan(),
        }

        for keywords, handler in routes.items():
            if first_token in keywords:
                return handler()

        # 3. Pré-roteamento por intenções claras em linguagem natural
        lower_text = text.lower()

        # Erro hexadecimal Windows (ex: "o que é 0x80070005", "erro 0x80240020")
        hex_match = re.search(r"\b(0x[0-9a-fA-F]{8})\b", text)
        if hex_match:
            return self._cmd_erro([hex_match.group(1)])

        # Consulta rápida de bancada/máquinas ativas
        if any(phrase in lower_text for phrase in ["quais maquinas", "quais máquinas", "computadores ligados", "ver bancada", "status do lab", "status bancada"]):
            return self._cmd_bancada(user_id)

        # Consulta rápida de clientes
        if any(phrase in lower_text for phrase in ["quais clientes", "lista de clientes", "empresas cadastradas", "ver clientes"]):
            return self._cmd_clientes()

        # Consulta rápida de clima ou temperatura
        if any(phrase in lower_text for phrase in ["temperatura do lab", "temperatura ambiente", "clima do lab", "como esta o calor"]):
            return self._cmd_clima()

        # Consulta rápida de WAN / IP público
        if any(phrase in lower_text for phrase in ["qual o ip externo", "qual o ip publico", "qual o ip do lab", "link de internet"]):
            return self._cmd_wan()

        # 4. Fallback: IA Conversacional Inteligente com Contexto Completo
        return self._handle_ai_conversation(user_id, text)

    # ------------------------------------------------------------------
    # Comandos
    # ------------------------------------------------------------------

    def _cmd_help(self) -> str:
        return (
            "🤖 **Ultron ChatOps - Central de Comando de Bancada**\n\n"
            "Comandos disponíveis para gerenciar o laboratório diretamente pelo TrueConf:\n\n"
            "💻 **Bancada & Máquinas:**\n"
            "• `/bancada` - Escaneia e lista computadores ativos na rede do lab\n"
            "• `/preparar <IP> <cliente>` - Inicia a esteira de automação completa (ex: `/preparar 192.168.57.25 nova_via`)\n"
            "• `/diagnostico <IP>` - Diagnóstico de hardware com S.M.A.R.T e laudo de IA\n"
            "• `/ativar <IP>` - Ativação permanente do Windows e Office via MAS\n"
            "• `/backup <IP>` - Backup de perfil do usuário para o servidor de Storage\n"
            "• `/dominio <IP> <cliente>` - Ingressa o computador no domínio Active Directory\n"
            "• `/softwares <IP> <app1,app2>` - Instala softwares avulsos (ex: `/softwares 192.168.57.25 chrome,anydesk`)\n"
            "• `/reiniciar <IP>` ou `/desligar <IP>` - Controle de energia remoto\n\n"
            "🏢 **Clientes & Chamados:**\n"
            "• `/clientes` - Lista empresas cadastradas no sistema e domínios\n"
            "• `/chamados` - Consulta chamados abertos e pendentes na Dashboard Milvus\n"
            "• `/laudos` - Lista os laudos técnicos em PDF gerados recentemente\n\n"
            "🛠️ **Diagnóstico & Segurança:**\n"
            "• `/erro <código>` - Decodifica erros do Windows (ex: `/erro 0x80070005`)\n"
            "• `/cve <programa>` - Consulta falhas de segurança conhecidas (ex: `/cve winrar`)\n"
            "• `/clima` - Telemetria térmica do laboratório e margem para testes de estresse\n"
            "• `/wan` - IP público e provedor de internet do lab\n\n"
            "💬 *Dica:* Você também pode me fazer perguntas técnicas diretas ou pedir diagnósticos em linguagem natural."
        )

    def _cmd_bancada(self, user_id: str) -> str:
        devices = self.scanner.scan_network()
        if not devices:
            return (
                "🔍 **Status da Bancada:**\n\n"
                "⚠️ Nenhum computador ativo detectado em `192.168.57.0/24`.\n"
                "Verifique se os equipamentos estão ligados e com o cabo de rede conectado."
            )

        lines = [f"💻 **Bancada Ultron — {len(devices)} Máquina(s) Detectada(s):**\n"]
        for d in devices:
            status   = "🟢" if d.get("winrm_ready") else "🟡"
            winrm    = "WinRM Pronto" if d.get("winrm_ready") else "Sem WinRM"
            vendor   = f" `[{d.get('vendor')}]`" if d.get("vendor") not in (None, "Desconhecido") else ""
            bench    = f" ({d.get('bench_name')})" if d.get("bench_name") else ""
            ip       = d.get("ip", "?")
            hostname = d.get("hostname") or "Host"
            lines.append(
                f"{status} **{hostname}**{vendor}{bench}\n"
                f"   📍 IP: `{ip}` | {winrm}\n"
                f"   ⚡ `/preparar {ip} <cliente>` | `/diagnostico {ip}`\n"
            )

        return "\n".join(lines)

    def _cmd_clientes(self) -> str:
        clients = self.profile_mgr.list_clients()
        if not clients:
            return "🏢 Nenhum cliente cadastrado no sistema."

        lines = ["🏢 **Perfis de Clientes Cadastrados:**\n"]
        for idx, c in enumerate(clients[:15], 1):
            dom = f" | AD: `{c.get('dominio')}`" if c.get("dominio") else ""
            token_icon = "🔑" if c.get("milvus_token") else "⚠️ Sem Token"
            lines.append(f"`{idx:02d}` **{c.get('nome')}** (`{c.get('id')}`){dom} | {token_icon}")

        lines.append("\n💡 *Para preparar um PC, use:* `/preparar <IP> <id_do_cliente>`")
        return "\n".join(lines)

    def _cmd_chamados(self) -> str:
        tickets = self.profile_mgr.milvus.get_open_tickets()
        if not tickets:
            return "📋 Nenhum chamado aberto ou pendente na Dashboard Milvus no momento."

        lines = [f"📋 **Chamados Abertos no Milvus ({len(tickets)}):**\n"]
        for t in tickets[:8]:
            status_badge = "🔴" if t.get("status") == "Aberto" else "🟡"
            lines.append(
                f"{status_badge} **#{t.get('numero')}** - {t.get('cliente')}\n"
                f"   📝 *{t.get('assunto')}* (Técnico: {t.get('tecnico')})\n"
            )

        return "\n".join(lines)

    def _cmd_preparar(self, user_id: str, args: List[str]) -> str:
        if not args:
            return "⚠️ **Uso:** `/preparar <IP> <cliente>`\nExemplo: `/preparar 192.168.57.25 nova_via`"

        ip        = args[0]
        client_id = args[1] if len(args) > 1 else "cliente_padrao"

        # Aceita número de índice no lugar do id textual
        if client_id.isdigit():
            clients = self.profile_mgr.list_clients()
            idx     = int(client_id) - 1
            if 0 <= idx < len(clients):
                client_id = clients[idx].get("id", client_id)

        def _worker():
            self._ensure_orchestrator()
            self.orchestrator.run_pipeline(
                ip=ip,
                client_id=client_id,
                tech_user_id=user_id,
                technician_name=user_id.capitalize(),
            )

        threading.Thread(target=_worker, daemon=True).start()

        return (
            f"🚀 **Esteira de Preparação Iniciada!**\n\n"
            f"📍 **IP:** `{ip}` | 🏢 **Cliente:** `{client_id}`\n\n"
            f"**Etapas do Fluxo:**\n"
            f"1. Conexão WinRM & Telemetria inicial\n"
            f"2. Instalação do Agente Milvus & Softwares Padrão\n"
            f"3. Softwares específicos do cliente (Winget)\n"
            f"4. Ingresso no Domínio AD (se configurado)\n"
            f"5. Ativação permanente Windows/Office (MAS)\n"
            f"6. Teste de Estresse Térmico & CPU\n"
            f"7. Emissão do Laudo Técnico em PDF\n\n"
            f"📱 O **AnyDesk ID** e o laudo em PDF serão enviados aqui no privado ao finalizar."
        )

    def _cmd_diagnostico(self, user_id: str, args: List[str]) -> str:
        if not args:
            return "⚠️ **Uso:** `/diagnostico <IP>`\nExemplo: `/diagnostico 192.168.57.25`"

        ip = args[0]
        self._ensure_orchestrator()

        if self.bot:
            self.bot.send_direct_message(user_id, f"🔍 Coletando telemetria S.M.A.R.T em `{ip}`...")

        try:
            diag    = self.orchestrator.run_diagnostics_only(ip=ip)
            telem   = diag.get("telemetry", {})
            ai_diag = diag.get("ai_diagnosis", "")

            disks_str = "".join(
                f"\n   • {d.get('model')} ({d.get('size_gb')} GB) — Saúde: **{d.get('health', 'OK')}**"
                for d in telem.get("disks", [])
            )

            return (
                f"🩺 **Diagnóstico Instantâneo de Hardware**\n\n"
                f"📍 **IP:** `{ip}` | Host: `{telem.get('computer_name', 'N/A')}`\n"
                f"🏷️ **Serial:** `{telem.get('serial_number', 'N/A')}`\n"
                f"🧠 **CPU:** {telem.get('cpu', 'N/A')}\n"
                f"💾 **RAM:** {telem.get('ram_gb', 'N/A')} GB\n"
                f"💽 **Armazenamento:**{disks_str or ' Não detectado'}\n\n"
                f"🤖 **Parecer Técnico da IA:**\n\n"
                f"{ai_diag}\n\n"
                f"💡 *Para aplicar um perfil:* `/preparar {ip} <cliente>`"
            )
        except Exception as e:
            return f"❌ Erro ao diagnosticar `{ip}`: {e}"

    def _cmd_ativar(self, args: List[str]) -> str:
        if not args:
            return "⚠️ **Uso:** `/ativar <IP>`\nExemplo: `/ativar 192.168.57.25`"
        ip  = args[0]
        res = self.winrm.run_script_file(ip, "Activate-WindowsOffice.ps1")
        if res["success"]:
            return f"🔑 **Ativação MAS Concluída em `{ip}`!**\nWindows e Office ativados permanentemente."
        return f"⚠️ Falha na ativação em `{ip}`: {res.get('stderr') or 'Erro de conexão WinRM'}"

    def _cmd_backup(self, args: List[str]) -> str:
        if not args:
            return "⚠️ **Uso:** `/backup <IP>`\nExemplo: `/backup 192.168.57.25`"
        ip  = args[0]
        res = self.winrm.run_script_file(ip, "Backup-UserProfile.ps1")
        if res["success"]:
            return (
                f"💾 **Backup Iniciado em `{ip}`!**\n"
                f"Dados do usuário sendo transferidos para o Storage (`192.168.57.112`)."
            )
        return f"⚠️ Falha ao iniciar backup em `{ip}`: {res.get('stderr') or 'Erro de conexão'}"

    def _cmd_dominio(self, args: List[str]) -> str:
        if len(args) < 2:
            return "⚠️ **Uso:** `/dominio <IP> <cliente|domínio>`\nExemplo: `/dominio 192.168.57.25 penserede.local`"
        ip         = args[0]
        dom_target = args[1]

        profile     = self.profile_mgr.get_client_profile(dom_target)
        domain_name = profile.get("dominio", dom_target) if profile else dom_target

        res = self.winrm.run_script_file(
            ip,
            "Join-ActiveDirectory.ps1",
            params={"DomainName": domain_name, "OUPath": "OU=Workstations,DC=penserede,DC=local"},
        )
        if res["success"]:
            return f"🛡️ **Ingresso no Domínio Concluído!**\n`{ip}` conectada ao domínio `{domain_name}`."
        return f"⚠️ Falha no ingresso ao domínio em `{ip}`: {res.get('stderr') or 'Verifique DNS/credenciais'}"

    def _cmd_softwares(self, args: List[str]) -> str:
        if len(args) < 2:
            return (
                "⚠️ **Uso:** `/softwares <IP> <app1,app2>`\n"
                "Exemplo: `/softwares 192.168.57.25 Google.Chrome,AnyDeskSoftwareGmbH.AnyDesk`"
            )
        ip   = args[0]
        pkgs = [p.strip() for p in args[1].split(",") if p.strip()]
        res  = self.winrm.run_script_file(ip, "Install-CustomPackages.ps1", params={"Packages": ",".join(pkgs)})
        if res["success"]:
            return f"📦 **Softwares Instalados em `{ip}`!**\nPacotes: {', '.join(pkgs)}"
        return f"⚠️ Falha na instalação em `{ip}`: {res.get('stderr') or 'Erro Winget'}"

    def _cmd_power(self, args: List[str], action: str) -> str:
        if not args:
            return f"⚠️ **Uso:** `/{action} <IP>`"
        ip  = args[0]
        cmd = "Restart-Computer -Force" if action == "restart" else "Stop-Computer -Force"
        res = self.winrm.execute_powershell(ip, cmd)
        act = "reiniciada" if action == "restart" else "desligada"
        if res["success"]:
            return f"🔌 Máquina `{ip}` está sendo {act}."
        return f"⚠️ Falha ao executar comando de energia em `{ip}`."

    def _cmd_laudos(self, args: List[str]) -> str:
        from reports.report_generator import ReportGenerator
        r_gen = ReportGenerator()
        reports = r_gen.list_reports()
        if not reports:
            return "📄 Nenhum laudo técnico encontrado no sistema."

        lines = [f"📄 **Últimos Laudos Técnicos Gerados ({len(reports)}):**\n"]
        for r in reports[:6]:
            lines.append(
                f"• **{r.get('hostname')}** ({r.get('client')})\n"
                f"  🏷️ Serial: `{r.get('serial')}` | Data: {r.get('created_at')}\n"
                f"  🔗 Download: `{r.get('download_url')}`\n"
            )

        return "\n".join(lines)

    def _cmd_erro(self, args: List[str]) -> str:
        if len(args) < 1:
            return "⚠️ Informe o código de erro hexadecimal. Exemplo: `/erro 0x80070005`"
        code = args[0]
        data = self.error_svc.lookup(code)
        
        cmd_part = f"\n\n🔧 **Comando de Reparo PowerShell:**\n```{data.get('command')}```" if data.get("command") else ""
        return (
            f"🐞 **Decodificador de Erro do Windows**\n\n"
            f"🔍 Código: `{data.get('code')}` - **{data.get('name')}**\n"
            f"📌 Categoria: {data.get('category')}\n\n"
            f"⚠️ **Causa Provável:**\n{data.get('cause')}\n\n"
            f"✅ **Solução Recomendada:**\n{data.get('solution')}"
            f"{cmd_part}"
        )

    def _cmd_cve(self, args: List[str]) -> str:
        if len(args) < 1:
            return "⚠️ Informe o software para buscar vulnerabilidades. Exemplo: `/cve winrar`"
        pkg = args[0]
        data = self.cve_svc.search_vulnerabilities(pkg)
        vulns = data.get("vulnerabilities", [])
        if not vulns:
            return f"🛡️ Nenhuma vulnerabilidade crítica recente encontrada para `{pkg}`."

        lines = [f"🛡️ **Vulnerabilidades Encontradas para `{pkg}` ({len(vulns)}):**\n"]
        for v in vulns[:4]:
            lines.append(
                f"• **{v.get('id')}** `[{v.get('severity')}]` ({v.get('published')})\n"
                f"  {v.get('summary')}\n"
            )
        return "\n".join(lines)

    def _cmd_clima(self) -> str:
        data = self.weather_svc.get_ambient_conditions()
        return (
            f"🌡️ **Telemetria Térmica do Laboratório**\n\n"
            f"• Temperatura Atual: **{data.get('temperature_c')}°C** (Sensação: {data.get('apparent_temperature_c')}°C)\n"
            f"• Umidade Relativa: **{data.get('relative_humidity_pct')}%**\n"
            f"• Margem Térmica: **{data.get('thermal_headroom_rating')}**\n\n"
            f"📝 *{data.get('thermal_delta_note')}*"
        )

    def _cmd_wan(self) -> str:
        data = self.wan_svc.get_wan_telemetry()
        return (
            f"🌐 **Telemetria de Conexão WAN do Lab**\n\n"
            f"• IP Público: `{data.get('wan_ip')}`\n"
            f"• Provedor (ISP): **{data.get('isp')}** (ASN: {data.get('asn')})\n"
            f"• Localização: {data.get('city')}, {data.get('region')} - {data.get('country')}\n"
            f"• Latência DNS DoH: **{data.get('ping_ms')} ms**"
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
            f"🤖 **Ultron - Nova Máquina Pronta no MDT!**\n",
            f"📍 **IP:** `{ip}` | 🏷️ **Serial:** `{serial}`\n",
            f"Qual perfil de cliente devo aplicar nesta máquina? **Responda com o número:**\n"
        ]
        for idx, c in enumerate(clients, 1):
            menu_lines.append(f"`{idx}` • **{c.get('nome')}** (`{c.get('id')}`)")

        menu_lines.append("\nOu digite `/preparar <IP> <cliente>` para personalizar.")
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
            # Remove a sessão pendente
            del self.user_sessions[user_id]
            # Dispara a esteira
            return self._cmd_preparar(user_id, [ip, chosen_client])

        return None

    # ------------------------------------------------------------------
    # IA Conversacional Local (Ollama / OpenAI-Compatible)
    # ------------------------------------------------------------------

    def _handle_ai_conversation(self, user_id: str, text: str) -> str:
        """Responde a perguntas livres usando o LLM local com contexto ao vivo do laboratório."""
        try:
            devices = self.scanner.scan_network()
            clients = self.profile_mgr.list_clients()
            weather = self.weather_svc.get_ambient_conditions()

            bench_summary = (
                f"{len(devices)} computadores ativos: "
                + ", ".join(f"{d.get('ip')} ({d.get('hostname')})" for d in devices)
                if devices else "Nenhum computador ativo no momento."
            )
            client_summary = ", ".join(f"{c.get('nome')} (`{c.get('id')}`)" for c in clients[:8])

            system_prompt = (
                "Você é o ULTRON, Inteligência Artificial de Automação de Bancada e Suporte Técnico da Pense Rede.\n"
                "Você conversa diretamente com os técnicos de TI do laboratório no chat do TrueConf.\n\n"
                "REGRAS OBRIGATÓRIAS DE COMUNICAÇÃO:\n"
                "1. Responda em Português do Brasil (pt-BR) com perfeição gramatical e precisão técnica.\n"
                "2. Seja DIRETO, CONCISO e OBJETIVO. Não use saudações robóticas, introduções desnecessárias ou enrolação.\n"
                "3. Use formatação Markdown limpa (tópicos com marcadores, destaques em negrito e blocos de código para comandos/IPs).\n"
                "4. Se o técnico perguntar ou pedir uma ação operacional, indique claramente o comando slash correspondente:\n"
                "   - `/bancada` (ver computadores ativos)\n"
                "   - `/preparar <IP> <cliente>` (iniciar esteira completa)\n"
                "   - `/diagnostico <IP>` (testar hardware/SMART)\n"
                "   - `/ativar <IP>` (ativar Windows e Office)\n"
                "   - `/backup <IP>` (fazer backup para Storage)\n"
                "   - `/erro <código>` (decodificar erro Windows)\n"
                "   - `/clientes` (listar perfis de empresas)\n"
                "   - `/laudos` (listar laudos técnicos)\n"
                "5. NUNCA gere tags <think> ou blocos de pensamento interno."
            )

            prompt = (
                f"CONTEXTO ATUAL DO LABORATÓRIO:\n"
                f"- Máquinas na Bancada: {bench_summary}\n"
                f"- Perfis de Clientes: {client_summary}\n"
                f"- Temperatura do Lab: {weather.get('temperature_c')}°C (Margem: {weather.get('thermal_headroom_rating')})\n\n"
                f"Mensagem do Técnico ({user_id}): \"{text}\"\n\n"
                "Instrução: Responda diretamente ao técnico com a informação técnica solicitada ou comando sugerido."
            )

            self._ensure_orchestrator()
            reply = self.orchestrator.analyzer.generate(prompt, system_prompt=system_prompt)
            if reply and not reply.startswith("⚠️"):
                return f"🤖 **Ultron:**\n\n{reply}"
            elif reply and reply.startswith("⚠️"):
                return f"{reply}\n\n💡 *Dica:* Você pode usar comandos diretos como `/bancada`, `/clientes` ou `/ajuda`."
        except Exception:
            pass

        return (
            f"🤖 Não reconheci o comando `{text}`.\n\n"
            "Envie `/ajuda` para ver todos os comandos disponíveis ou `/bancada` para listar os PCs ativos."
        )

    # ------------------------------------------------------------------
    # Utilitários Internos
    # ------------------------------------------------------------------

    def _ensure_orchestrator(self):
        """Instancia o LabOrchestrator sob demanda (evita import circular no módulo)."""
        if not self.orchestrator:
            from core.orchestrator import LabOrchestrator
            self.orchestrator = LabOrchestrator()
