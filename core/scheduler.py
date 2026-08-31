"""
Módulo de Agendamento e Controle Mestre do Ultron
Gerencia tarefas temporizadas, agendamento de mensagens para colaboradores da empresa no TrueConf,
e comandos de superadministrador exclusivos para Nicolas Silva.
"""

import threading
import time
import re
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

logger = logging.getLogger("ultron_scheduler")


class ScheduledMessage:
    def __init__(self, task_id: str, sender_id: str, target_user: str, message: str, trigger_time: datetime):
        self.task_id = task_id
        self.sender_id = sender_id
        self.target_user = target_user
        self.message = message
        self.trigger_time = trigger_time
        self.executed = False


class UltronScheduler:
    def __init__(self, bot=None):
        self.bot = bot
        self.tasks: List[ScheduledMessage] = []
        self._lock = threading.Lock()
        self._running = True
        self._worker_thread = threading.Thread(target=self._loop, daemon=True, name="UltronSchedulerWorker")
        self._worker_thread.start()

    def set_bot(self, bot):
        self.bot = bot

    def schedule_message(self, sender_id: str, target_user: str, message: str, trigger_time: datetime) -> str:
        """Agenda uma mensagem no TrueConf para ser entregue no horário programado."""
        task_id = f"sch_{int(time.time() * 1000)}"
        task = ScheduledMessage(task_id, sender_id, target_user, message, trigger_time)
        with self._lock:
            self.tasks.append(task)
        logger.info(f"⏰ Mensagem agendada [{task_id}] de {sender_id} para @{target_user} às {trigger_time.strftime('%H:%M:%S (%d/%m)')}")
        return task_id

    def list_scheduled(self, sender_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            now = datetime.now()
            res = []
            for t in self.tasks:
                if not t.executed:
                    if not sender_id or t.sender_id == sender_id:
                        res.append({
                            "id": t.task_id,
                            "target": t.target_user,
                            "time": t.trigger_time.strftime("%H:%M (%d/%m)"),
                            "message": t.message,
                            "remaining_sec": max(0, int((t.trigger_time - now).total_seconds()))
                        })
            return res

    def cancel_task(self, task_id: str) -> bool:
        with self._lock:
            for t in self.tasks:
                if t.task_id == task_id and not t.executed:
                    t.executed = True
                    return True
        return False

    def _loop(self):
        while self._running:
            try:
                now = datetime.now()
                due_tasks = []
                with self._lock:
                    for t in self.tasks:
                        if not t.executed and t.trigger_time <= now:
                            t.executed = True
                            due_tasks.append(t)

                for t in due_tasks:
                    self._dispatch_task(t)

            except Exception as e:
                logger.error(f"Erro no loop do scheduler: {e}")

            time.sleep(1)

    def _dispatch_task(self, task: ScheduledMessage):
        """Envia a mensagem para o destinatário e notifica o remetente Master"""
        try:
            if not self.bot:
                logger.warning(f"Bot não vinculado para disparar mensagem agendada {task.task_id}")
                return

            logger.info(f"🚀 Disparando mensagem agendada para @{task.target_user}...")
            
            # Envia a mensagem agendada para o usuário alvo
            formatted_msg = (
                f"📢 Mensagem de {task.sender_id.capitalize()}:\n\n"
                f"{task.message}"
            )
            success = self.bot.send_direct_message(task.target_user, formatted_msg)

            # Notifica o Nicolas (Master) sobre o envio
            confirm_msg = (
                f"⏰ MENSAGEM AGENDADA ENTREGUE!\n\n"
                f"✅ Destinatário: @{task.target_user}\n"
                f"📝 Conteúdo: \"{task.message}\"\n"
                f"🕒 Horário: {datetime.now().strftime('%H:%M:%S')}"
            ) if success else (
                f"⚠️ Falha ao entregar mensagem agendada para @{task.target_user}."
            )
            self.bot.send_direct_message(task.sender_id, confirm_msg)

        except Exception as e:
            logger.error(f"Erro ao despachar tarefa agendada: {e}")
