"""Short-lived typed diagnostic clarification. Never stores original chat text."""
from contextlib import contextmanager
import ipaddress
import os
from pathlib import Path
import re
import sqlite3
import time
import uuid
from core.task_registry import actor
from core.device_inventory import DeviceInventory, InventoryError, device_binding
from core.structured_intent import IntentPlan, decide_action
from core.trueconf_transport import is_allowed_user


class ClarificationStore:
    def __init__(self, path=None, clock=time.time, ttl=300):
        if not 30 <= ttl <= 900:
            raise ValueError("TTL invalido.")
        self.path = Path(path or os.environ.get("ULTRON_CLARIFICATION_DB") or
                         Path(__file__).resolve().parents[1] / "data/clarifications.sqlite3")
        self.clock, self.ttl = clock, ttl

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        db = sqlite3.connect(str(self.path), timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute("""CREATE TABLE IF NOT EXISTS pending_diagnosis (
                owner TEXT PRIMARY KEY, nonce TEXT NOT NULL, confidence REAL NOT NULL,
                candidate_ip TEXT, lookup_key TEXT, binding TEXT, expires_at REAL NOT NULL)""")
            columns = {row[1] for row in db.execute("PRAGMA table_info(pending_diagnosis)")}
            if "binding" not in columns:
                db.execute("ALTER TABLE pending_diagnosis ADD COLUMN binding TEXT")
            if os.name == "posix":
                self.path.chmod(0o600)
            with db:
                yield db
        finally:
            db.close()

    def start(self, owner, confidence):
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0.85 <= confidence <= 1:
            raise ValueError("Pedido nao confirmado.")
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO pending_diagnosis "
                "(owner,nonce,confidence,candidate_ip,lookup_key,binding,expires_at) VALUES (?,?,?,?,?,?,?)",
                (actor(owner), uuid.uuid4().hex, confidence, None, None, None, self.clock() + self.ttl))

    def get(self, owner, include_expired=False):
        with self.connect() as db:
            row = db.execute("SELECT * FROM pending_diagnosis WHERE owner=?", (actor(owner),)).fetchone()
            if row is None or (not include_expired and row["expires_at"] <= self.clock()):
                return None
            return dict(row)

    def select(self, owner, nonce, ip, key, binding):
        with self.connect() as db:
            return db.execute("UPDATE pending_diagnosis SET candidate_ip=?,lookup_key=?,binding=?,nonce=? "
                "WHERE owner=? AND nonce=? AND expires_at>?",
                (ip, key, binding, uuid.uuid4().hex, actor(owner), nonce, self.clock())).rowcount == 1

    def consume(self, owner, nonce):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM pending_diagnosis WHERE owner=? AND nonce=? AND expires_at>?",
                (actor(owner), nonce, self.clock())).fetchone()
            if row:
                db.execute("DELETE FROM pending_diagnosis WHERE owner=? AND nonce=?", (actor(owner), nonce))
            return dict(row) if row else None

    def clear(self, owner):
        with self.connect() as db:
            db.execute("DELETE FROM pending_diagnosis WHERE owner=?", (actor(owner),))

    def clear_after_restart(self):
        with self.connect() as db:
            db.execute("DELETE FROM pending_diagnosis")


def enabled(owner):
    allowed = {value.strip().casefold() for value in
               os.environ.get("ULTRON_SEMANTIC_ALLOWED_TRUECONF_USERS", "").split(",") if value.strip()}
    return (is_allowed_user(owner) and owner.casefold() in allowed
            and os.environ.get("ULTRON_SEMANTIC_ROUTER_ENABLED", "").lower() in ("1", "true"))


class DiagnosticClarification:
    def __init__(self, store=None, inventory=None):
        self.store = store or ClarificationStore()
        self.inventory = inventory or DeviceInventory()

    def start(self, owner, confidence):
        if not enabled(owner):
            return "Esclarecimento indisponivel para este tecnico; nada executado."
        self.store.start(owner, confidence)
        return "Qual e o IP completo do computador a diagnosticar? Pode informar hostname, serial ou MAC cadastrado; pedirei confirmacao do IP."

    def reply(self, owner, text):
        pending = self.store.get(owner, include_expired=True)
        if not pending:
            return None
        text = text.strip()
        if pending["expires_at"] <= self.store.clock():
            self.store.clear(owner)
            if re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", text):
                return {"reply": "Pedido expirado; informe novamente a acao e o equipamento. Nada executado."}
            return None
        if text.casefold() in ("cancelar", "cancela", "deixa pra la", "/cancelar"):
            self.store.clear(owner)
            return {"reply": "Pedido de diagnostico descartado; nada executado."}
        if not enabled(owner):
            self.store.clear(owner)
            return {"reply": "Permissao ou roteador alterados; pedido descartado sem executar."}
        if text.startswith("/") or text.casefold() in ("menu", "ajuda", "help") or text in {str(n) for n in range(1, 15)} or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", text):
            self.store.clear(owner)
            return None  # New request is handled normally; never appended to an old intent.
        try:
            ip = str(ipaddress.IPv4Address(text))
        except ValueError:
            if pending["candidate_ip"]:
                return {"reply": "Confirme digitando o IP completo apresentado ou cancele o pedido."}
            try:
                device = self.inventory.resolve(text)
            except InventoryError as error:
                return {"reply": str(error)}
            if not self.store.select(owner, pending["nonce"], device["ip"], text.casefold(), device_binding(device)):
                return {"reply": "Pedido alterado ou expirado; solicite novamente."}
            return {"reply": "Inventario aponta " + device["hostname"] + " para " + device["ip"] +
                            ". Confira o equipamento e confirme digitando esse IP completo. Nada executado."}
        consumed = self.store.consume(owner, pending["nonce"])
        if consumed is None:
            return {"reply": "Pedido ja respondido ou expirado; nada executado."}
        if consumed["candidate_ip"]:
            try:
                current = self.inventory.resolve(consumed["lookup_key"])
                consistent = (current["ip"] == ip == consumed["candidate_ip"]
                              and device_binding(current) == consumed["binding"])
            except InventoryError:
                consistent = False
            if not consistent:
                return {"reply": "Alvo ou inventario alterados; faca um novo pedido. Nada executado."}
        plan = IntentPlan("diagnose", "request", ip, consumed["confidence"], ())
        decision = decide_action(plan, text,
            read_only_enabled=os.environ.get("ULTRON_SEMANTIC_READONLY_ENABLED", "").lower() in ("1", "true"),
            allowed_subnet=os.environ.get("ULTRON_SEMANTIC_ALLOWED_SUBNET"))
        if decision.kind != "allow_readonly" or decision.action != "diagnose":
            return {"reply": decision.reason}
        return {"target_ip": ip}
