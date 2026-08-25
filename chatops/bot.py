"""
Módulo de Integração com o TrueConf Server & ChatOps Bi-Direcional
Utiliza a biblioteca oficial python-trueconf-bot com WebSocket e suporte a credenciais.
Garante que o Ultron permaneça ONLINE 24/7 e atenda qualquer técnico em tempo real.
"""

import asyncio
import logging
import threading
import time
from typing import Optional, Dict, Any
import urllib3
import requests

from chatops.chatops import TrueConfChatOps

try:
    from trueconf import Bot, Dispatcher, Router, Message, F, ParseMode
    TRUECONF_LIB_AVAILABLE = True
except ImportError:
    TRUECONF_LIB_AVAILABLE = False

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger("ultron_trueconf_bot")


class TrueConfBot:
    def __init__(
        self,
        server_url: str,
        bot_username: str = "ultron",
        bot_password: str = "",
        api_token: str = "",
        default_tech_user_id: str = "nicolas.silva",
    ):
        # Limpa URL para remover https:// ou trailing slash se necessário
        self.raw_server_url = server_url.rstrip("/")
        self.server_host = self.raw_server_url.replace("https://", "").replace("http://", "").split(":")[0]
        self.bot_username = bot_username
        self.bot_password = bot_password
        self.api_token = api_token
        self.default_tech_user_id = default_tech_user_id

        # Headers para REST fallback
        self.headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json"
        }

        # Inicializa o motor central de ChatOps
        self.chatops = TrueConfChatOps(bot=self)

        # Controle de execução em segundo plano
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._bot: Optional[Any] = None
        self._is_running = False
        self._p2p_chats: Dict[str, str] = {}  # user_id -> chat_id cache

    @property
    def server_url(self) -> str:
        return self.raw_server_url

    def start_polling(self, interval_sec: int = 3):
        """Inicia o Bot do TrueConf em segundo plano conectando via WebSocket"""
        if self._is_running:
            return
        self._is_running = True

        self._thread = threading.Thread(target=self._run_event_loop, daemon=True, name="TrueConfBotWorker")
        self._thread.start()
        logger.info(f"🚀 TrueConf Bot iniciado para {self.server_host} (usuário: {self.bot_username})")

    def stop_polling(self):
        """Para o Bot e encerra as conexões WebSocket"""
        self._is_running = False
        if self._loop and self._loop.is_running():
            if self._bot:
                try:
                    future = asyncio.run_coroutine_threadsafe(self._shutdown_bot(), self._loop)
                    future.result(timeout=4)
                except Exception:
                    pass
            self._loop.call_soon_threadsafe(self._loop.stop)
        logger.info("🛑 TrueConf Bot parado.")

    def _run_event_loop(self):
        """Worker que gerencia o loop assíncrono do Bot"""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        try:
            self._loop.run_until_complete(self._bot_lifecycle())
        except Exception as e:
            logger.error(f"Erro no ciclo de vida do TrueConf Bot: {e}")
        finally:
            self._loop.close()

    async def _shutdown_bot(self):
        try:
            if self._bot:
                await self._bot.shutdown()
        except Exception:
            pass

    async def _bot_lifecycle(self):
        """Mantém o bot conectado e reconecta automaticamente em qualquer caso de queda ou oscilação"""
        while self._is_running:
            try:
                if not TRUECONF_LIB_AVAILABLE:
                    logger.warning("python-trueconf-bot não disponível. Operando apenas em modo REST.")
                    await asyncio.sleep(5)
                    continue

                dp = Dispatcher()
                router = Router()
                dp.include_router(router)

                @router.message()
                async def handle_message(msg: Message):
                    try:
                        text = msg.text or ""
                        if not text and hasattr(msg, "content") and hasattr(msg.content, "text"):
                            text = msg.content.text or ""
                        if not text:
                            return

                        raw_author = None
                        if hasattr(msg, "author") and msg.author:
                            raw_author = getattr(msg.author, "id", None)
                        elif hasattr(msg, "from_user") and msg.from_user:
                            raw_author = getattr(msg.from_user, "id", None)
                        
                        raw_author = raw_author or self.default_tech_user_id
                        user_id = str(raw_author).split("@")[0] if "@" in str(raw_author) else str(raw_author)

                        logger.info(f"📩 Mensagem recebida de {user_id}: {text}")
                        
                        # Executa o ChatOps em thread separada para NUNCA travar os pings do WebSocket
                        reply = await asyncio.to_thread(self.chatops.handle_incoming_message, user_id, text)
                        if reply:
                            try:
                                await msg.answer(reply, parse_mode=ParseMode.TEXT)
                                logger.info(f"📤 Resposta enviada para {user_id}")
                            except Exception as send_err:
                                logger.warning(f"Falha ao responder via msg.answer ({send_err}). Enviando DM direta...")
                                self.send_direct_message(user_id, reply)
                    except Exception as err:
                        logger.error(f"Erro ao processar mensagem do TrueConf: {err}", exc_info=True)

                logger.info(f"🔑 Conectando Ultron Bot em {self.server_host}...")
                
                self._p2p_chats.clear()
                self._bot = Bot.from_credentials(
                    server=self.server_host,
                    username=self.bot_username,
                    password=self.bot_password,
                    dispatcher=dp,
                    receive_unread_messages=True,
                    verify_ssl=False,
                    ws_max_retries=-1,
                    ws_max_delay=5
                )

                # Inicia o loop do bot sem capturar sinais do SO (pois roda em thread de fundo)
                await self._bot.run(handle_signals=False)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Conexão do TrueConf Bot oscilou: {e}. Reconectando em 3 segundos...")
            
            # Aguarda antes da próxima tentativa se ainda estiver rodando
            if self._is_running:
                await asyncio.sleep(3)

    def send_direct_message(self, user_id: str, message: str) -> bool:
        """
        Envia uma mensagem direta (1-on-1) para o técnico via WebSocket (ou REST fallback).
        """
        target_user = user_id or self.default_tech_user_id

        # Se o loop e bot estiverem ativos, envia via WebSocket
        if self._bot and self._loop and self._loop.is_running():
            try:
                future = asyncio.run_coroutine_threadsafe(
                    self._async_send_dm(target_user, message),
                    self._loop
                )
                return future.result(timeout=6)
            except Exception as e:
                logger.warning(f"Falha ao enviar via WebSocket ({e}). Tentando REST API fallback...")

        # Fallback via REST API se WebSocket estiver indisponível
        return self._rest_send_dm(target_user, message)

    async def _async_send_dm(self, user_id: str, message: str) -> bool:
        """Cria chat P2P e envia mensagem via WebSocket"""
        try:
            if not self._bot:
                return False

            # 1. Obtém ou cria chat P2P com o usuário
            chat_id = self._p2p_chats.get(user_id)
            if not chat_id:
                chat_resp = await self._bot.create_personal_chat(user_id=user_id)
                chat_id = getattr(chat_resp, "chat_id", None) or getattr(chat_resp, "id", None)
                if chat_id:
                    self._p2p_chats[user_id] = str(chat_id)

            # 2. Envia a mensagem com formatação de texto limpa
            if chat_id:
                await self._bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode=ParseMode.TEXT
                )
                return True
            return False
        except Exception as e:
            logger.error(f"Erro em _async_send_dm para {user_id}: {e}")
            self._p2p_chats.pop(user_id, None)
            return False

    def _rest_send_dm(self, user_id: str, message: str) -> bool:
        """Fallback REST API"""
        endpoint = f"{self.raw_server_url}/api/v4/chat/users/{user_id}/messages"
        payload = {"body": message}
        try:
            r = requests.post(endpoint, json=payload, headers=self.headers, verify=False, timeout=5)
            return r.status_code in [200, 201]
        except Exception:
            return False

    def process_incoming_message(self, user_id: str, message_text: str, reply_directly: bool = True) -> str:
        """Processa mensagem de forma síncrona/direta"""
        user = user_id or self.default_tech_user_id
        response_text = self.chatops.handle_incoming_message(user_id=user, message=message_text)
        if reply_directly:
            self.send_direct_message(user_id=user, message=response_text)
        return response_text

    def notify_mdt_finished(self, bench_ip: str, serial: str, user_id: str = None):
        """Notifica conclusão de formatação no MDT com menu interativo"""
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
        """Notifica a conclusão da esteira com AnyDesk ID e PDF"""
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
