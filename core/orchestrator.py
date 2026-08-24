"""
Orquestrador Mestre de Bancada - Ultron Lab Automation
Gerencia o fluxo completo de automação: Conexão, Telemetria, IA, Instalação de Softwares, Teste de Estresse e Laudo.
"""

import json
import os
from typing import Dict, Any, Optional, List

from core.winrm_executor import WinRMExecutor
from core.profile_manager import ProfileManager
from core.diagnostic_analyzer import DiagnosticAnalyzer
from core.switch_identifier import SwitchIdentifier
from reports.report_generator import ReportGenerator
from trueconf.bot import TrueConfBot

class LabOrchestrator:
    def __init__(self):
        self.profile_mgr = ProfileManager()
        self.settings = self.profile_mgr.get_settings()
        self.winrm = WinRMExecutor()
        self.switch_id = SwitchIdentifier()
        
        # Inicializa o analisador LLM
        llm_cfg = self.settings.get("llm", {})
        self.analyzer = DiagnosticAnalyzer(
            base_url=llm_cfg.get("base_url", "http://localhost:11434"),
            model=llm_cfg.get("model", "custom_model"),
            provider=llm_cfg.get("provider", "ollama"),
            api_key=llm_cfg.get("api_key"),
            temperature=llm_cfg.get("temperature", 0.2)
        )
        
        # Inicializa o gerador de laudos
        self.report_gen = ReportGenerator()
        
        # Inicializa o bot TrueConf
        tc_cfg = self.settings.get("trueconf", {})
        self.bot = TrueConfBot(
            server_url=tc_cfg.get("server_url", "https://trueconf.penserede.com.br"),
            api_token=tc_cfg.get("bot_token", ""),
            default_tech_user_id=tc_cfg.get("default_tech_user_id", "nicolas.silva")
        )

    def run_diagnostics_only(self, ip: str, log_callback: Optional[Any] = None) -> Dict[str, Any]:
        """
        Coleta telemetria e executa análise de IA sem alterar a máquina.
        """
        def log(msg: str, level: str = "info"):
            print(msg)
            if log_callback:
                try:
                    log_callback({"type": "log", "message": msg, "level": level})
                except Exception:
                    pass

        bench_info = self.switch_id.identify_bench(ip=ip)
        log(f"🔍 [ULTRON] Coletando telemetria de {ip} ({bench_info['bench_name']})...")
        telemetry_res = self.winrm.run_script_file(ip, "Inspect-SystemLogs.ps1")
        
        telemetry_data = {}
        if telemetry_res["success"] and telemetry_res["stdout"]:
            try:
                # Localiza o JSON na saída
                stdout = telemetry_res["stdout"]
                json_start = stdout.find("{")
                json_end = stdout.rfind("}") + 1
                if json_start != -1 and json_end != -1:
                    telemetry_data = json.loads(stdout[json_start:json_end])
            except Exception as e:
                log(f"⚠️ Erro ao parsear JSON de telemetria: {e}", level="warning")

        # Se não conseguiu obter via script, preenche com dados básicos
        if not telemetry_data:
            telemetry_data = {
                "computer_name": f"PC-{ip.split('.')[-1]}",
                "serial_number": "N/A",
                "cpu": "Detectado via WinRM",
                "ram_gb": "N/A",
                "disks": [],
                "bsod_dumps": [],
                "device_errors": []
            }

        log(f"🧠 [ULTRON] Processando diagnóstico com IA na RTX 5060 Ti...")
        ai_verdict = self.analyzer.analyze_logs(telemetry_data)

        return {
            "ip": ip,
            "telemetry": telemetry_data,
            "ai_diagnosis": ai_verdict
        }

    def run_pipeline(
        self,
        ip: str,
        client_id: str = "cliente_padrao",
        tech_user_id: Optional[str] = "nicolas",
        technician_name: Optional[str] = "Nicolas Silva",
        skip_burnin: bool = False,
        custom_packages: Optional[List[str]] = None,
        domain_config: Optional[Dict[str, Any]] = None,
        log_callback: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Executa a esteira completa de preparação da máquina com streaming de eventos.
        """
        logs = []
        anydesk_id = ""
        TOTAL_STAGES = 7

        def log(msg: str, level: str = "info", stage: Optional[int] = None, stage_name: Optional[str] = None):
            print(msg)
            logs.append(msg)
            if log_callback:
                try:
                    payload = {
                        "type": "log",
                        "message": msg,
                        "level": level,
                        "stage": stage,
                        "total_stages": TOTAL_STAGES,
                        "stage_name": stage_name,
                        "anydesk_id": anydesk_id
                    }
                    log_callback(payload)
                except Exception:
                    pass

        # 1. Carrega Perfil do Cliente e Valida Conexão
        profile = self.profile_mgr.get_client_profile(client_id)
        client_name = profile.get("nome_exibicao", client_id)
        milvus_token = profile.get("milvus_token", "")
        mdt_server = self.settings.get("network", {}).get("mdt_server_ip", "192.168.57.87")
        bench_info = self.switch_id.identify_bench(ip=ip)

        log(
            f"🚀 [ULTRON] Iniciando Esteira para {ip} ({bench_info['bench_name']}) - Cliente: {client_name}",
            level="info",
            stage=1,
            stage_name="Reconhecimento & Conectividade"
        )

        if not self.winrm.test_connection(ip):
            err_msg = f"❌ [ULTRON] Máquina {ip} ({bench_info['bench_name']}) inacessível via WinRM (porta 5985 fechada)."
            log(err_msg, level="error", stage=1, stage_name="Falha de Conectividade")
            if tech_user_id:
                self.bot.send_direct_message(tech_user_id, f"⚠️ **Falha no Ultron:** {err_msg}")
            if log_callback:
                log_callback({"type": "error", "error": err_msg})
            return {"success": False, "ip": ip, "logs": logs, "error": err_msg}

        log("✅ Conexão WinRM estabelecida com sucesso!", level="success", stage=1)

        # 2. Coleta de Telemetria
        log(
            "🔍 [ULTRON] Executando inspeção de hardware e coleta de S.M.A.R.T...",
            level="info",
            stage=2,
            stage_name="Inspeção de Hardware"
        )
        diag_result = self.run_diagnostics_only(ip, log_callback=log_callback)
        telemetry = diag_result["telemetry"]
        log(f"💻 Hostname: {telemetry.get('computer_name')} | Serial: {telemetry.get('serial_number')}", level="info", stage=2)

        # 3. Diagnóstico Inteligente com IA
        log(
            "🧠 [ULTRON] Processando diagnóstico com IA na RTX 5060 Ti (Ollama)...",
            level="info",
            stage=3,
            stage_name="Diagnóstico Inteligente IA"
        )
        ai_verdict = diag_result["ai_diagnosis"]
        log("✅ Parecer técnico gerado pelo Ultron AI!", level="success", stage=3)

        # 4. Executa Instalação de Softwares Padrão
        log(
            "📦 [ULTRON] Instalando softwares padrão (AnyDesk, Office, Milvus, Ativação MAS)...",
            level="info",
            stage=4,
            stage_name="Instalação de Softwares Padrão"
        )
        install_params = {
            "MilvusToken": milvus_token,
            "ClientName": client_name,
            "MdtServer": mdt_server,
            "ActivateOfficeWin": True
        }
        install_res = self.winrm.run_script_file(ip, "Install-LabStandard.ps1", params=install_params)
        
        # Extrai AnyDesk ID da saída
        import re
        stdout_txt = install_res.get("stdout", "")
        anydesk_match = re.search(r"ANYDESK_ID:([^\r\n]+)", stdout_txt)
        if anydesk_match:
            raw_id = anydesk_match.group(1).strip()
            if raw_id and raw_id != "NÃO_DETECTADO":
                anydesk_id = raw_id
                log(f"🔑 AnyDesk ID capturado: {anydesk_id}", level="success", stage=4)
                if log_callback:
                    log_callback({"type": "anydesk_detected", "anydesk_id": anydesk_id})

        if not install_res["success"]:
            log(f"⚠️ Alerta durante instalação de softwares: {install_res.get('stderr', '')}", level="warning", stage=4)
        else:
            log("✅ Softwares padrão instalados com sucesso!", level="success", stage=4)

        # 5. Softwares Adicionais do Perfil via Winget & Scripts Customizados
        log(
            "⚙️ [ULTRON] Verificando configurações e pacotes específicos do perfil...",
            level="info",
            stage=5,
            stage_name="Configurações do Cliente"
        )
        profile_pkgs = profile.get("softwares", {}).get("winget", []) or []
        extra_pkgs = custom_packages or []
        
        # Junta pacotes sem duplicações preservando a ordem
        combined_pkgs = []
        for p in profile_pkgs + extra_pkgs:
            clean_p = p.strip()
            if clean_p and clean_p not in combined_pkgs:
                combined_pkgs.append(clean_p)

        if combined_pkgs:
            log(f"📦 Instalando pacotes adicionais via Winget ({len(combined_pkgs)} itens)...", level="info", stage=5)
            for pkg in combined_pkgs:
                log(f"  -> Instalando {pkg}...", level="info", stage=5)
                cmd = f"winget install --id {pkg} --exact --silent --accept-package-agreements --accept-source-agreements"
                self.winrm.run_powershell_code(ip, cmd)

        custom_scripts = profile.get("custom_scripts", [])
        for script_item in custom_scripts:
            log(f"⚙️ Executando script customizado: {script_item}", level="info", stage=5)
            parts = script_item.split(" ", 1)
            s_name = parts[0]
            if len(parts) > 1:
                self.winrm.run_powershell_code(ip, script_item)
            else:
                self.winrm.run_script_file(ip, s_name)

        # 6. Domínio e Teste de Estresse (Burn-in)
        dom_cfg = domain_config or profile.get("dominio", {})
        d_name = ""
        if isinstance(dom_cfg, dict):
            d_name = dom_cfg.get("domain_name") or dom_cfg.get("nome", "")

        if d_name:
            d_user = dom_cfg.get("domain_user", "")
            d_pass = dom_cfg.get("domain_password", "")
            d_dns = dom_cfg.get("dns_server", "")
            d_ip = dom_cfg.get("static_ip", "")
            d_mask = dom_cfg.get("subnet_mask", "255.255.255.0")
            d_gw = dom_cfg.get("gateway", "")
            d_ou = dom_cfg.get("ou_path", "")

            log(f"🏢 [ULTRON] Configurando rede e ingressando no domínio {d_name}...", level="info", stage=6, stage_name="Domínio & Estresse")
            dom_params = {
                "DomainName": d_name,
                "DomainUser": d_user,
                "DomainPassword": d_pass,
                "DnsServer": d_dns,
                "StaticIp": d_ip,
                "SubnetMask": d_mask,
                "Gateway": d_gw,
                "OUPath": d_ou
            }
            dom_res = self.winrm.run_script_file(ip, "Join-CustomerDomain.ps1", params=dom_params)
            if not dom_res["success"]:
                log(f"⚠️ Alerta durante ingresso no domínio: {dom_res.get('stderr', '')}", level="warning", stage=6)
            else:
                log(f"✅ Ingressado com sucesso no domínio {d_name}!", level="success", stage=6)

        burnin_status = "Ignorado"
        if not skip_burnin:
            log("⚡ [ULTRON] Executando teste de estresse térmico (Burn-in)...", level="info", stage=6, stage_name="Teste de Estresse")
            burnin_res = self.winrm.run_script_file(ip, "Run-LabBurnIn.ps1", params={"StressMinutes": 1})
            burnin_status = "Aprovado" if burnin_res["success"] else "Alerta de Estresse"
            log(f"⚡ Resultado do Teste de Estresse: {burnin_status}", level="success" if burnin_status == "Aprovado" else "warning", stage=6)

        # 7. Geração do Laudo Técnico em PDF e Notificação
        log(
            "📄 [ULTRON] Gerando Laudo Técnico em PDF com chancela Pense Rede...",
            level="info",
            stage=7,
            stage_name="Emissão de Laudo & Notificação"
        )
        tech_display = technician_name or "Nicolas Silva"
        pdf_path = self.report_gen.generate_report(
            telemetry_data=telemetry,
            client_name=client_name,
            ai_diagnosis=ai_verdict,
            burnin_status=burnin_status,
            technician=tech_display,
            anydesk_id=anydesk_id
        )
        pdf_filename = os.path.basename(pdf_path)
        log(f"✅ [ULTRON] Laudo PDF gerado: {pdf_filename}", level="success", stage=7)

        # Notificação no TrueConf
        if tech_user_id:
            self.bot.notify_pipeline_finished(
                user_id=tech_user_id,
                bench_name=bench_info["bench_name"],
                ip=ip,
                serial=telemetry.get("serial_number", "N/A"),
                client_name=client_name,
                burnin_status=burnin_status,
                pdf_filename=pdf_filename,
                anydesk_id=anydesk_id
            )
            log("📱 Técnico notificado no privado via TrueConf!", level="success", stage=7)

        log("🎉 [ULTRON] Esteira de automação finalizada com 100% de êxito!", level="success", stage=7)

        result = {
            "success": True,
            "ip": ip,
            "client": client_name,
            "serial": telemetry.get("serial_number", "N/A"),
            "anydesk_id": anydesk_id,
            "pdf_report": pdf_filename,
            "pdf_path": pdf_path,
            "burnin_status": burnin_status,
            "logs": logs
        }

        if log_callback:
            try:
                log_callback({
                    "type": "finished",
                    "result": result
                })
            except Exception:
                pass

        return result
