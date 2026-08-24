"""
TrueConf ChatOps — Ultron Lab Automation
Processa comandos slash, diálogos interativos e conversação com IA no chat do TrueConf.
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

import unicodedata

def _normalize_token(s: str) -> str:
    """Remove acentos e converte para minúsculas"""
    if not s:
        return ""
    n = unicodedata.normalize('NFKD', s)
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

        # Serviços públicos / consultas externas
        self.weather_svc = LabWeatherService()
        self.error_svc   = WindowsErrorLookupService()
        self.cve_svc     = CveSecurityService()
        self.wan_svc     = NetworkDiagnosticsService()

        # Sessões interativas pendentes por técnico
        self.user_sessions: Dict[str, Dict[str, Any]] = {}

    def handle_incoming_message(self, user_id: str, message: str) -> str:
        """
        Recebe qualquer mensagem enviada ao bot no chat privado do TrueConf.
        """
        text = (message or "").strip()
        if not text:
            return "Olá! Envie /ajuda para ver os comandos disponíveis."

        # 1. Sessão interativa pendente (ex: escolha de cliente pós-MDT)
        if user_id in self.user_sessions:
            session = self.user_sessions[user_id]
            if session.get("type") == "pending_mdt":
                result = self._handle_pending_mdt_choice(user_id, session, text)
                if result:
                    return result

        # 2. Roteamento de comandos slash explícitos (com suporte a acentuação)
        parts = text.split()
        first_token = parts[0] if parts else ""
        norm_token = _normalize_token(first_token)
        norm_text = _normalize_token(text)

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
                lambda: self._cmd_ativar(user_id, parts[1:]),
            frozenset(["/backup", "/storage"]):
                lambda: self._cmd_backup(user_id, parts[1:]),
            frozenset(["/dominio", "/domain", "/ad"]):
                lambda: self._cmd_dominio(user_id, parts[1:]),
            frozenset(["/softwares", "/apps", "/instalar"]):
                lambda: self._cmd_softwares(user_id, parts[1:]),
            frozenset(["/reiniciar", "/reboot"]):
                lambda: self._cmd_power(user_id, parts[1:], "restart"),
            frozenset(["/desligar", "/shutdown"]):
                lambda: self._cmd_power(user_id, parts[1:], "shutdown"),
            frozenset(["/msg", "/mensagem", "/notificar", "/alerta", "/aviso", "/popup"]):
                lambda: self._cmd_message(user_id, parts[1:]),
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
            if norm_token in keywords:
                return handler()

        # 3. Disparo de mensagem para o usuário por linguagem natural
        # Ex: "manda uma mensagem para o IP 192.168.57.59 'Ultron está rodando'"
        ip_match = re.search(r"\b(192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3})\b", text)
        msg_action_kws = ["manda uma mensagem", "mandar mensagem", "enviar mensagem", "avisa o ip", "notifica o ip", "avise o ip", "mande uma mensagem"]
        if ip_match and any(kw in norm_text for kw in msg_action_kws):
            target_ip = ip_match.group(1)
            # Extrai o texto da mensagem (entre aspas ou o resto da frase)
            quoted = re.search(r'["\']([^"\']+)["\']', text)
            if quoted:
                clean_msg = quoted.group(1)
            else:
                # Remove o prefixo do comando para pegar o texto
                clean_msg = re.sub(r'^(?:.*?)' + re.escape(target_ip) + r'[:\s-]*', '', text, flags=re.IGNORECASE).strip()
            if clean_msg:
                return self._cmd_message(user_id, [target_ip] + clean_msg.split())

        # 4. Erro hexadecimal Windows em texto livre (ex: 0x80070005)
        hex_match = re.search(r"\b(0x[0-9a-fA-F]{8})\b", text)
        if hex_match:
            return self._cmd_erro([hex_match.group(1)])

        # 5. Consulta rápida de bancada por linguagem natural
        bench_kws = [
            "tem maquina", "pcs na bancada", "bancada ta cheia",
            "computadores no lab", "quantas maquinas",
            "maquinas na bancada", "quais maquinas"
        ]
        for kw in bench_kws:
            if kw in norm_text:
                return self._cmd_bancada(user_id)

        # 6. IA Conversacional
        return self._handle_ai_conversation(user_id, text)

    # ------------------------------------------------------------------
    # Comandos
    # ------------------------------------------------------------------

    def _cmd_help(self) -> str:
        return (
            "🤖 Ultron ChatOps - Central de Comando de Bancada\n\n"
            "💻 Bancada & Máquinas:\n"
            "• /bancada — Lista computadores ativos no lab\n"
            "• /preparar <IP> <cliente> — Inicia esteira completa de automação\n"
            "• /diagnostico <IP> — Diagnóstico de hardware e S.M.A.R.T\n"
            "• /msg <IP> <texto> — Exibe mensagem na tela do usuário remoto (Pop-up/Alerta)\n"
            "• /ativar <IP> — Ativação do Windows e Office via MAS\n"
            "• /backup <IP> — Backup de dados do usuário para o Storage\n"
            "• /dominio <IP> <cliente> — Ingressa o computador no domínio\n"
            "• /softwares <IP> <apps> — Instala softwares avulsos (ex: chrome,anydesk)\n"
            "• /reiniciar <IP> ou /desligar <IP> — Controle remoto de energia\n\n"
            "🏢 Clientes & Chamados:\n"
            "• /clientes — Lista empresas cadastradas e domínios\n"
            "• /chamados — Consulta chamados pendentes no Milvus\n"
            "• /laudos — Lista laudos técnicos em PDF gerados\n\n"
            "🛠️ Diagnóstico & Segurança:\n"
            "• /erro <código> — Decodifica erros do Windows (ex: /erro 0x80070005)\n"
            "• /cve <programa> — Consulta falhas de segurança conhecidas\n"
            "• /clima — Telemetria térmica do laboratório\n"
            "• /wan — IP público e link de internet\n\n"
            "💬 Dica: Você também pode fazer perguntas técnicas em linguagem natural ou mandar avisos (ex: 'manda uma mensagem para o IP 192.168.57.59 reiniciando em 5min')."
        )

    def _cmd_bancada(self, user_id: str) -> str:
        devices = self.scanner.scan_network()
        if not devices:
            return (
                "🔍 Status da Bancada:\n\n"
                "⚠️ Nenhum computador ativo detectado na rede 192.168.57.0/24.\n"
                "Verifique se os equipamentos estão ligados e conectados."
            )

        lines = [f"💻 Bancada Ultron — {len(devices)} Máquina(s) Detectada(s):\n"]
        for d in devices:
            status   = "🟢" if d.get("winrm_ready") else "🟡"
            winrm    = "WinRM Pronto" if d.get("winrm_ready") else "Sem WinRM"
            vendor   = f" [{d.get('vendor')}]" if d.get("vendor") not in (None, "Desconhecido") else ""
            bench    = f" ({d.get('bench_name')})" if d.get("bench_name") else ""
            ip       = d.get("ip", "?")
            hostname = d.get("hostname") or "Host"
            lines.append(
                f"{status} {hostname}{vendor}{bench}\n"
                f"   📍 IP: {ip} | {winrm}\n"
                f"   ⚡ /preparar {ip} <cliente> | /diagnostico {ip}\n"
            )

        return "\n".join(lines)

    def _cmd_clientes(self) -> str:
        clients = self.profile_mgr.list_clients()
        if not clients:
            return "🏢 Nenhum cliente cadastrado no sistema."

        lines = ["🏢 Perfis de Clientes Cadastrados:\n"]
        for idx, c in enumerate(clients[:15], 1):
            dom = f" | AD: {c.get('dominio')}" if c.get("dominio") else ""
            token_icon = "🔑 Milvus OK" if c.get("milvus_token") else "⚠️ Sem Token"
            lines.append(f"{idx:02d}. {c.get('nome')} ({c.get('id')}){dom} | {token_icon}")

        lines.append("\n💡 Para preparar um PC, use: /preparar <IP> <id_do_cliente>")
        return "\n".join(lines)

    def _cmd_chamados(self) -> str:
        tickets = self.profile_mgr.milvus.get_open_tickets()
        if not tickets:
            return "📋 Nenhum chamado pendente na Dashboard Milvus no momento."

        lines = [f"📋 Chamados Abertos no Milvus ({len(tickets)}):\n"]
        for t in tickets[:8]:
            status_badge = "🔴" if t.get("status") == "Aberto" else "🟡"
            lines.append(
                f"{status_badge} #{t.get('numero')} — {t.get('cliente')}\n"
                f"   Assunto: {t.get('assunto')} (Técnico: {t.get('tecnico')})\n"
            )

        return "\n".join(lines)

    def _cmd_preparar(self, user_id: str, args: List[str]) -> str:
        if not args:
            return "⚠️ Uso: /preparar <IP> <cliente>\nExemplo: /preparar 192.168.57.25 nova_via"

        ip        = args[0]
        client_id = args[1] if len(args) > 1 else "cliente_padrao"

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
            f"🚀 Esteira de Preparação Iniciada!\n\n"
            f"📍 IP: {ip}\n"
            f"🏢 Cliente: {client_id}\n\n"
            f"Etapas em andamento:\n"
            f"1. Conexão WinRM & Telemetria inicial\n"
            f"2. Agente Milvus & Softwares Padrão\n"
            f"3. Softwares do cliente (Winget)\n"
            f"4. Domínio Active Directory (se configurado)\n"
            f"5. Ativação permanente Windows/Office (MAS)\n"
            f"6. Teste de Estresse Térmico & CPU\n"
            f"7. Emissão do Laudo Técnico em PDF\n\n"
            f"📱 O AnyDesk ID e o laudo em PDF serão enviados aqui assim que concluir."
        )

    def _cmd_diagnostico(self, user_id: str, args: List[str]) -> str:
        if not args:
            return "⚠️ Uso: /diagnostico <IP>\nExemplo: /diagnostico 192.168.57.25"

        ip = args[0]
        self._ensure_orchestrator()

        def _worker():
            try:
                diag = self.orchestrator.run_diagnostics_only(ip=ip)
                if not diag.get("success", True) or diag.get("error"):
                    err = diag.get("error", "Host inacessível via WinRM na porta 5985.")
                    reply = (
                        f"❌ Falha de Conexão WinRM com a Máquina {ip}\n\n"
                        f"⚠️ Motivo: {err}\n\n"
                        f"🔍 O que verificar na máquina alvo:\n"
                        f"1. A máquina está ligada e com o Windows ativo na rede 192.168.57.X?\n"
                        f"2. O WinRM está habilitado? (Execute 'Enable-PSRemoting -Force' no PowerShell)\n"
                        f"3. A senha do Administrador local bate com o settings.yaml ('SenhaTemporariaLab123!')?"
                    )
                else:
                    telem   = diag.get("telemetry", {})
                    ai_diag = diag.get("ai_diagnosis", "")

                    disks_list = []
                    for d in telem.get("disks", []):
                        health_icon = "🟢" if d.get("health") in ["Healthy", "OK", "0"] else "🔴"
                        disks_list.append(
                            f"\n   • {health_icon} {d.get('model')} ({d.get('size_gb')} GB, {d.get('type')}) — Saúde: {d.get('health', 'OK')}"
                        )
                    disks_str = "".join(disks_list)

                    bsods = telem.get("bsod_dumps", [])
                    bsod_str = f"\n⚠️ Telas Azuis (BSOD) recentes: {len(bsods)} detectada(s)" if bsods else "\n🛡️ Telas Azuis (BSOD): Nenhuma detectada"

                    dev_errs = telem.get("device_errors", [])
                    dev_str = f"\n⚠️ Dispositivos com erro de driver: {len(dev_errs)}" if dev_errs else "\n🛡️ Gerenciador de Dispositivos: Todos drivers operacionais"

                    reply = (
                        f"🩺 DIAGNÓSTICO COMPLETO DE HARDWARE\n\n"
                        f"📍 IP: {ip} | Host: {telem.get('computer_name', 'N/A')}\n"
                        f"🏷️ Serial: {telem.get('serial_number', 'N/A')}\n"
                        f"🧠 Processador (CPU): {telem.get('cpu', 'N/A')}\n"
                        f"💾 Memória RAM: {telem.get('ram_gb', 'N/A')} GB\n"
                        f"💽 Armazenamento (S.M.A.R.T):{disks_str or ' Não detectado'}"
                        f"{bsod_str}"
                        f"{dev_str}\n\n"
                        f"🤖 PARECER TÉCNICO DA IA:\n\n"
                        f"{ai_diag}\n\n"
                        f"💡 Para preparar a máquina: /preparar {ip} <cliente>"
                    )
            except Exception as e:
                reply = f"❌ Erro inesperado ao diagnosticar {ip}: {e}"

            if self.bot:
                self.bot.send_direct_message(user_id, reply)

        threading.Thread(target=_worker, daemon=True).start()
        return f"🔍 Coletando telemetria e S.M.A.R.T em {ip}...\nAssim que o laudo da IA estiver pronto, enviarei aqui."

    def _cmd_ativar(self, user_id: str, args: List[str]) -> str:
        if not args:
            return "⚠️ Uso: /ativar <IP>\nExemplo: /ativar 192.168.57.25"
        ip = args[0]

        def _worker():
            res = self.winrm.run_script_file(ip, "Activate-WindowsOffice.ps1")
            if res["success"]:
                reply = f"🔑 Ativação MAS Concluída em {ip}!\nWindows e Office ativados permanentemente."
            else:
                reply = f"⚠️ Falha na ativação em {ip}: {res.get('stderr') or 'Erro de conexão WinRM'}"
            if self.bot:
                self.bot.send_direct_message(user_id, reply)

        threading.Thread(target=_worker, daemon=True).start()
        return f"🔑 Executando ativação permanente (MAS) em {ip}..."

    def _cmd_backup(self, user_id: str, args: List[str]) -> str:
        if not args:
            return "⚠️ Uso: /backup <IP>\nExemplo: /backup 192.168.57.25"
        ip = args[0]

        def _worker():
            res = self.winrm.run_script_file(ip, "Backup-UserProfile.ps1")
            if res["success"]:
                reply = f"💾 Backup Concluído em {ip}!\nDados transferidos para o Storage (192.168.57.112)."
            else:
                reply = f"⚠️ Falha no backup em {ip}: {res.get('stderr') or 'Erro de conexão'}"
            if self.bot:
                self.bot.send_direct_message(user_id, reply)

        threading.Thread(target=_worker, daemon=True).start()
        return f"💾 Iniciando backup de dados do usuário em {ip} para o Storage..."

    def _cmd_dominio(self, user_id: str, args: List[str]) -> str:
        if len(args) < 2:
            return "⚠️ Uso: /dominio <IP> <cliente|domínio>\nExemplo: /dominio 192.168.57.25 penserede.local"
        ip = args[0]
        dom_target = args[1]

        def _worker():
            profile     = self.profile_mgr.get_client_profile(dom_target)
            domain_name = profile.get("dominio", dom_target) if profile else dom_target

            res = self.winrm.run_script_file(
                ip,
                "Join-ActiveDirectory.ps1",
                params={"DomainName": domain_name, "OUPath": "OU=Workstations,DC=penserede,DC=local"},
            )
            if res["success"]:
                reply = f"🛡️ Ingresso no Domínio Concluído!\n{ip} conectada ao domínio {domain_name}."
            else:
                reply = f"⚠️ Falha no ingresso ao domínio em {ip}: {res.get('stderr') or 'Verifique DNS e credenciais'}"
            if self.bot:
                self.bot.send_direct_message(user_id, reply)

        threading.Thread(target=_worker, daemon=True).start()
        return f"🛡️ Ingressando {ip} no domínio {dom_target}..."

    def _cmd_softwares(self, user_id: str, args: List[str]) -> str:
        if len(args) < 2:
            return (
                "⚠️ Uso: /softwares <IP> <app1,app2>\n"
                "Exemplo: /softwares 192.168.57.25 Google.Chrome,AnyDeskSoftwareGmbH.AnyDesk"
            )
        ip   = args[0]
        pkgs = [p.strip() for p in args[1].split(",") if p.strip()]

        def _worker():
            res = self.winrm.run_script_file(ip, "Install-CustomPackages.ps1", params={"Packages": ",".join(pkgs)})
            if res["success"]:
                reply = f"📦 Softwares Instalados em {ip}!\nPacotes: {', '.join(pkgs)}"
            else:
                reply = f"⚠️ Falha na instalação em {ip}: {res.get('stderr') or 'Erro Winget'}"
            if self.bot:
                self.bot.send_direct_message(user_id, reply)

        threading.Thread(target=_worker, daemon=True).start()
        return f"📦 Instalando pacotes ({', '.join(pkgs)}) em {ip} via Winget..."

    def _cmd_power(self, user_id: str, args: List[str], action: str) -> str:
        if not args:
            return f"⚠️ Uso: /{action} <IP>"
        ip  = args[0]
        cmd = "Restart-Computer -Force" if action == "restart" else "Stop-Computer -Force"
        act = "reiniciada" if action == "restart" else "desligada"

        def _worker():
            res = self.winrm.execute_powershell(ip, cmd)
            if res["success"]:
                reply = f"🔌 Máquina {ip} foi {act} com sucesso."
            else:
                reply = f"⚠️ Falha ao executar comando de energia em {ip}."
            if self.bot:
                self.bot.send_direct_message(user_id, reply)

        threading.Thread(target=_worker, daemon=True).start()
        return f"🔌 Enviando comando para {act} {ip}..."

    def _cmd_message(self, user_id: str, args: List[str]) -> str:
        if len(args) < 2:
            return (
                "⚠️ Uso: /msg <IP> <mensagem>\n"
                "Exemplo: /msg 192.168.57.59 O laboratório está preparando a sua máquina."
            )
        ip = args[0]
        msg_text = " ".join(args[1:]).strip('\'"')

        def _worker():
            res = self.winrm.run_script_file(
                ip,
                "Send-UserMessage.ps1",
                params={
                    "Message": msg_text,
                    "Title": f"🤖 ULTRON SUPORTE (Técnico: {user_id.capitalize()})"
                }
            )
            if res["success"]:
                reply = f"📢 Mensagem exibida na tela do usuário em {ip} com sucesso!\n💬 Texto: \"{msg_text}\""
            else:
                reply = f"⚠️ Falha ao exibir mensagem na tela de {ip}: {res.get('stderr') or 'Máquina inacessível'}"

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

        lines = [f"📄 Últimos Laudos Técnicos Gerados ({len(reports)}):\n"]
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
            f"🐞 Decodificador de Erro do Windows\n\n"
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

        lines = [f"🛡️ Vulnerabilidades Encontradas para {pkg} ({len(vulns)}):\n"]
        for v in vulns[:4]:
            lines.append(
                f"• {v.get('id')} [{v.get('severity')}] ({v.get('published')})\n"
                f"  {v.get('summary')}\n"
            )
        return "\n".join(lines)

    def _cmd_clima(self) -> str:
        data = self.weather_svc.get_ambient_conditions()
        return (
            f"🌡️ Telemetria Térmica do Laboratório\n\n"
            f"• Temperatura Atual: {data.get('temperature_c')}°C (Sensação: {data.get('apparent_temperature_c')}°C)\n"
            f"• Umidade Relativa: {data.get('relative_humidity_pct')}%\n"
            f"• Margem Térmica: {data.get('thermal_headroom_rating')}\n\n"
            f"📝 {data.get('thermal_delta_note')}"
        )

    def _cmd_wan(self) -> str:
        data = self.wan_svc.get_wan_telemetry()
        return (
            f"🌐 Telemetria de Conexão WAN do Lab\n\n"
            f"• IP Público: {data.get('wan_ip')}\n"
            f"• Provedor (ISP): {data.get('isp')} (ASN: {data.get('asn')})\n"
            f"• Localização: {data.get('city')}, {data.get('region')} - {data.get('country')}\n"
            f"• Latência DNS DoH: {data.get('ping_ms')} ms"
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
    # IA Conversacional Local
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
            client_summary = ", ".join(f"{c.get('nome')} ({c.get('id')})" for c in clients[:8])

            system_prompt = (
                "Você é o ULTRON, Inteligência Artificial de Automação de Bancada e Suporte Técnico da Pense Rede.\n"
                "Você conversa diretamente com os técnicos de TI do laboratório no chat do TrueConf.\n\n"
                "REGRAS OBRIGATÓRIAS:\n"
                "1. Responda em Português do Brasil (pt-BR) com perfeição gramatical e precisão técnica.\n"
                "2. Seja DIRETO, CONCISO e OBJETIVO.\n"
                "3. Use formatação limpa com tópicos e marcadores simples.\n"
                "4. Se o técnico pedir uma ação, indique o comando correspondente (/bancada, /preparar, /diagnostico, etc).\n"
                "5. NUNCA gere tags <think> ou blocos de pensamento interno."
            )

            prompt = (
                f"CONTEXTO ATUAL DO LABORATÓRIO:\n"
                f"- Máquinas na Bancada: {bench_summary}\n"
                f"- Perfis de Clientes: {client_summary}\n"
                f"- Temperatura do Lab: {weather.get('temperature_c')}°C\n\n"
                f"Mensagem do Técnico ({user_id}): \"{text}\"\n\n"
                "Instrução: Responda diretamente ao técnico com a informação técnica solicitada ou comando sugerido."
            )

            self._ensure_orchestrator()
            reply = self.orchestrator.analyzer.generate(prompt, system_prompt=system_prompt)
            if reply and not reply.startswith("⚠️"):
                # Limpa eventuais tags HTML ou Markdown que possam ter sido geradas
                clean_reply = reply.replace("<br />", "\n").replace("<br/>", "\n").replace("<br>", "\n")
                return f"🤖 Ultron:\n\n{clean_reply}"
            elif reply and reply.startswith("⚠️"):
                return f"{reply}\n\n💡 Dica: Você pode usar comandos diretos como /bancada, /clientes ou /ajuda."
        except Exception:
            pass

        return (
            f"🤖 Não reconheci o comando '{text}'.\n\n"
            "Envie /ajuda para ver os comandos disponíveis ou /bancada para listar os PCs ativos."
        )

    # ------------------------------------------------------------------
    # Utilitários Internos
    # ------------------------------------------------------------------

    def _ensure_orchestrator(self):
        if not self.orchestrator:
            from core.orchestrator import LabOrchestrator
            self.orchestrator = LabOrchestrator()
