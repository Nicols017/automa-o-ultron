"""
Módulo de Integração com o TrueConf Server & ChatOps Bi-Direcional
Utiliza a biblioteca oficial python-trueconf-bot com WebSocket e suporte a credenciais.
Garante que o Ultron permaneça ONLINE 24/7 e atenda qualquer técnico em tempo real.
"""

import os
import asyncio
import logging
import threading
import time
from typing import Optional, Dict, Any, List
import urllib3
import requests

from chatops.chatops import TrueConfChatOps, _normalize_token

try:
    from trueconf import Bot, Dispatcher, Router, Message, F, ParseMode
    from trueconf.types.input_file import FSInputFile
    TRUECONF_LIB_AVAILABLE = True
except ImportError:
    TRUECONF_LIB_AVAILABLE = False

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger("ultron_trueconf_bot")

import html
import re

def _clean_chat_text(s: str) -> str:
    """Higieniza tags HTML (<br>, <span>, etc.) e decodifica entidades HTML (&quot;, &#39;, &amp;) do TrueConf"""
    if not s:
        return ""
    t = re.sub(r"<\s*br\s*/?\s*>", "\n", s, flags=re.IGNORECASE)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t)
    return t.strip()

def _split_message(text: str, max_chars: int = 3800) -> List[str]:
    """Divide mensagens longas em blocos seguros para o limite do TrueConf (4096 chars)."""
    if not text or len(text) <= max_chars:
        return [text] if text else []

    chunks = []
    lines = text.split("\n")
    current = []
    current_len = 0

    for line in lines:
        if current_len + len(line) + 1 > max_chars:
            if current:
                chunks.append("\n".join(current))
                current = []
                current_len = 0
        current.append(line)
        current_len += len(line) + 1

    if current:
        chunks.append("\n".join(current))

    return chunks


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
        self._processed_msg_ids: Dict[str, float] = {}

    @property
    def server_url(self) -> str:
        return self.raw_server_url

    def _ensure_avatar(self):
        """Garante que a foto de perfil oficial do Ultron esteja aplicada no TrueConf Server"""
        try:
            logo_path = os.path.join("static", "img", "ultron_logo.jpg")
            if not os.path.exists(logo_path):
                logo_path = os.path.join("static", "img", "ultron_logo.png")
            if os.path.exists(logo_path) and self.api_token:
                url = f"{self.raw_server_url}/api/v4/users/{self.bot_username}/avatar"
                headers = {"Authorization": f"Bearer {self.api_token}"}
                with open(logo_path, "rb") as img_f:
                    files = {"image": ("ultron_logo.jpg", img_f, "image/jpeg")}
                    requests.put(url, headers=headers, files=files, verify=False, timeout=5)
                logger.info("🎨 Avatar oficial do Ultron verificado e atualizado no TrueConf Server!")
        except Exception as e:
            logger.debug(f"Não foi possível sincronizar avatar do TrueConf: {e}")

    def start_polling(self, interval_sec: int = 3):
        """Inicia o Bot do TrueConf em segundo plano conectando via WebSocket"""
        if self._is_running:
            return
        self._is_running = True

        # Sincroniza avatar em background
        threading.Thread(target=self._ensure_avatar, daemon=True).start()

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
                        text = _clean_chat_text(msg.text or "")
                        if not text and hasattr(msg, "content") and hasattr(msg.content, "text"):
                            text = _clean_chat_text(msg.content.text or "")
                        if not text:
                            return

                        raw_author = None
                        if hasattr(msg, "author") and msg.author:
                            raw_author = getattr(msg.author, "id", None)
                        elif hasattr(msg, "from_user") and msg.from_user:
                            raw_author = getattr(msg.from_user, "id", None)
                        
                        raw_author = raw_author or self.default_tech_user_id
                        user_id = str(raw_author).split("@")[0] if "@" in str(raw_author) else str(raw_author)

                        # Armazena chat_id da mensagem para este usuário
                        chat_id = getattr(msg, "chat_id", None) or getattr(getattr(msg, "chat", None), "id", None)
                        if chat_id:
                            self._p2p_chats[user_id] = str(chat_id)
                            self._p2p_chats[str(raw_author)] = str(chat_id)

                        # Deduplicação de eventos repetidos do WebSocket
                        msg_id = getattr(msg, "id", None) or f"{user_id}_{text}_{int(time.time() // 3)}"
                        now = time.time()
                        if msg_id in self._processed_msg_ids and (now - self._processed_msg_ids[msg_id]) < 4:
                            logger.debug(f"Mensagem duplicada ignorada: {msg_id}")
                            return
                        self._processed_msg_ids[msg_id] = now
                        if len(self._processed_msg_ids) > 200:
                            self._processed_msg_ids = {k: v for k, v in self._processed_msg_ids.items() if now - v < 60}

                        logger.info(f"📩 Mensagem recebida de {user_id} (chat_id: {chat_id}): {text}")

                        # Executa o ChatOps e responde com a instrução/menu
                        reply = await asyncio.to_thread(self.chatops.handle_incoming_message, user_id, text)
                        if reply:
                            chunks = _split_message(reply)
                            for chunk in chunks:
                                try:
                                    await msg.answer(chunk, parse_mode=ParseMode.TEXT)
                                    logger.info(f"📤 Resposta enviada para {user_id}")
                                except Exception as send_err:
                                    logger.warning(f"Falha ao responder via msg.answer ({send_err}). Enviando DM direta...")
                                    self.send_direct_message(user_id, chunk)
                    except Exception as err:
                        logger.error(f"Erro ao processar mensagem do TrueConf: {err}", exc_info=True)

                logger.info(f"🔑 Conectando Ultron Bot em {self.server_host}...")
                
                if self._bot:
                    try:
                        await self._bot.shutdown()
                    except Exception:
                        pass

                self._p2p_chats.clear()
                self._bot = Bot.from_credentials(
                    server=self.server_host,
                    username=self.bot_username,
                    password=self.bot_password,
                    dispatcher=dp,
                    receive_unread_messages=True,
                    verify_ssl=False,
                    ws_max_retries=-1,
                    ws_max_delay=5,
                    timeout=30.0
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
        """Cria chat P2P e envia mensagem via WebSocket com suporte a mensagens longas"""
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

            # 2. Envia a mensagem (dividida em blocos se ultrapassar o limite)
            if chat_id:
                chunks = _split_message(message)
                for chunk in chunks:
                    await self._bot.send_message(
                        chat_id=chat_id,
                        text=chunk,
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

    def send_direct_file(self, user_id: str, file_path: str, caption: Optional[str] = None, filename: Optional[str] = None) -> bool:
        """
        Envia um arquivo diretamente como anexo no chat privado do TrueConf.
        """
        target_user = user_id or self.default_tech_user_id

        if not os.path.exists(file_path):
            logger.warning(f"Arquivo para envio não encontrado: {file_path}")
            return False

        if self._bot and self._loop and self._loop.is_running():
            try:
                future = asyncio.run_coroutine_threadsafe(
                    self._async_send_file(target_user, file_path, caption, filename),
                    self._loop
                )
                return future.result(timeout=15)
            except Exception as e:
                logger.warning(f"Falha ao enviar arquivo via WebSocket ({e}).")
        return False

    async def _async_send_file(self, user_id: str, file_path: str, caption: Optional[str] = None, filename: Optional[str] = None) -> bool:
        """Cria chat P2P e envia documento/anexo via WebSocket"""
        try:
            if not self._bot or not os.path.exists(file_path):
                return False

            chat_id = self._p2p_chats.get(user_id)
            if not chat_id:
                chat_resp = await self._bot.create_personal_chat(user_id=user_id)
                chat_id = getattr(chat_resp, "chat_id", None) or getattr(chat_resp, "id", None)
                if chat_id:
                    self._p2p_chats[user_id] = str(chat_id)

            if chat_id:
                input_file = FSInputFile(path=file_path, filename=filename or os.path.basename(file_path))
                await self._bot.send_document(
                    chat_id=chat_id,
                    file=input_file,
                    caption=caption or ""
                )
                return True
            return False
        except Exception as e:
            logger.error(f"Erro em _async_send_file para {user_id}: {e}")
            self._p2p_chats.pop(user_id, None)
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
        anydesk_line = f"🔑 AnyDesk ID: {anydesk_id}\n" if anydesk_id and anydesk_id != "NÃO_DETECTADO" else ""
        msg = (
            f"🎉 ULTRON — AUTOMAÇÃO CONCLUÍDA COM SUCESSO!\n\n"
            f"📍 Localização: {bench_name}\n"
            f"🌐 IP: {ip}\n"
            f"🏷️ Serial: {serial}\n"
            f"🏢 Cliente: {client_name}\n"
            f"{anydesk_line}"
            f"⚡ Teste de Estresse: {burnin_status}\n"
            f"📄 Laudo Técnico: {pdf_filename}\n\n"
            f"Máquina 100% configurada e pronta para entrega.\n"
            f"💡 Envie /bancada para ver as próximas máquinas."
        )
        self.send_direct_message(target_user, msg)

        # Envia também o PDF diretamente como anexo no TrueConf
        pdf_path = os.path.join("reports", pdf_filename)
        if os.path.exists(pdf_path):
            self.send_direct_file(
                user_id=target_user,
                file_path=pdf_path,
                caption=f"📄 Laudo Técnico: {pdf_filename}",
                filename=pdf_filename
            )
