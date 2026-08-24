"""
Módulo de Integração com o TrueConf Server & ChatOps Bi-Direcional
Garante que todas as conversas, comandos e relatórios ocorram em MENSAGENS DIRETAS (1-on-1) com o técnico,
permitindo controlar 100% da bancada através do chat do TrueConf.
"""

import requests
import json
import time
import threading
import urllib3
from typing import Optional, Dict, Any

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from trueconf.chatops import TrueConfChatOps

class TrueConfBot:
    def __init__(self, server_url: str, api_token: str, default_tech_user_id: str = "nicolas.silva"):
        self.server_url = server_url.rstrip("/")
        self.api_token = api_token
        self.headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json"
        }
        self.default_tech_user_id = default_tech_user_id
        
        # Inicializa o motor de ChatOps
        self.chatops = TrueConfChatOps(bot=self)
        
        # Controle de Polling de Mensagens
        self._polling_thread = None
        self._is_polling = False

    def send_direct_message(self, user_id: str, message: str) -> bool:
        """
        Envia uma mensagem estritamente no PRIVADO (Direct Message) para o técnico.
        """
        endpoint = f"{self.server_url}/api/v4/chat/users/{user_id}/messages"
        payload = {
            "body": message
        }
        try:
            response = requests.post(endpoint, json=payload, headers=self.headers, verify=False, timeout=5)
            if response.status_code in [200, 201]:
                return True
            else:
                print(f"⚠️ TrueConf API respondeu status {response.status_code}: {response.text}")
                return False
        except Exception as e:
            print(f"❌ Erro ao enviar mensagem privada no TrueConf: {e}")
            return False

    def process_incoming_message(self, user_id: str, message_text: str, reply_directly: bool = True) -> str:
        """
        Processa uma mensagem recebida de um técnico, executa a ação e responde no chat privado.
        """
        user = user_id or self.default_tech_user_id
        response_text = self.chatops.handle_incoming_message(user_id=user, message=message_text)
        
        if reply_directly:
            self.send_direct_message(user_id=user, message=response_text)
            
        return response_text

    def notify_mdt_finished(self, bench_ip: str, serial: str, user_id: str = None):
        """
        Notifica o técnico no privado quando uma máquina termina de formatar no MDT,
        apresentando um menu interativo numerado para escolher o cliente.
        """
        target_user = user_id or self.default_tech_user_id
        msg = self.chatops.register_mdt_arrival(user_id=target_user, ip=bench_ip, serial=serial)
        return self.send_direct_message(target_user, msg)

    def notify_pipeline_finished(
        self,
        user_id: str,
        bench_name: str,
        ip: str,
        serial: str,
        client_name: str,
        burnin_status: str,
        pdf_filename: str,
        anydesk_id: str = ""
    ):
        """Notifica a conclusão da esteira com destaque para o AnyDesk ID e link do Laudo PDF"""
        target_user = user_id or self.default_tech_user_id
        anydesk_line = f"🔑 **AnyDesk ID:** `{anydesk_id}`\n" if anydesk_id and anydesk_id != "NÃO_DETECTADO" else ""
        msg = (
            f"🎉 **Ultron - Automação Concluída com Sucesso!**\n\n"
            f"📍 **Localização:** `{bench_name}`\n"
            f"🌐 **IP:** `{ip}`\n"
            f"🏷️ **Serial:** `{serial}`\n"
            f"🏢 **Cliente:** `{client_name}`\n"
            f"{anydesk_line}"
            f"⚡ **Teste de Estresse:** `{burnin_status}`\n"
            f"📄 **Laudo Técnico:** `{pdf_filename}`\n\n"
            f"Máquina 100% configurada e pronta para entrega.\n"
            f"💡 *Envie `/bancada` para ver as próximas máquinas prontas.*"
        )
        return self.send_direct_message(target_user, msg)

    def start_polling(self, interval_sec: int = 3):
        """Inicia um worker de polling em segundo plano para ler eventos do TrueConf Server"""
        if self._is_polling:
            return
        self._is_polling = True
        
        def _poll_worker():
            last_event_id = None
            while self._is_polling:
                try:
                    if self.api_token:
                        endpoint = f"{self.server_url}/api/v4/chat/events"
                        params = {"last_id": last_event_id} if last_event_id else {}
                        r = requests.get(endpoint, headers=self.headers, params=params, timeout=4)
                        if r.status_code == 200:
                            data = r.json()
                            for event in data.get("events", []):
                                last_event_id = event.get("id")
                                if event.get("type") == "message" and event.get("user_id") != "ultron_bot":
                                    self.process_incoming_message(
                                        user_id=event.get("user_id"),
                                        message_text=event.get("body", "")
                                    )
                except Exception:
                    pass
                time.sleep(interval_sec)

        self._polling_thread = threading.Thread(target=_poll_worker, daemon=True)
        self._polling_thread.start()

    def stop_polling(self):
        """Para o worker de polling do TrueConf"""
        self._is_polling = False
