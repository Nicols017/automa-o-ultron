"""Offline inventory and typed clarification tests. No SDK, LLM or host contacted."""
import ast
import concurrent.futures
import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
from core.clarification import ClarificationStore, DiagnosticClarification
from core.device_inventory import DeviceInventory, InventoryError
from core.trueconf_transport import is_allowed_user

ROOT = Path(__file__).resolve().parents[1]
ENV = {
    "ULTRON_TRUECONF_ALLOWED_USERS": "tech,other",
    "ULTRON_SEMANTIC_ALLOWED_TRUECONF_USERS": "tech,other",
    "ULTRON_SEMANTIC_ROUTER_ENABLED": "1",
    "ULTRON_SEMANTIC_READONLY_ENABLED": "1",
    "ULTRON_SEMANTIC_ALLOWED_SUBNET": "192.168.57.0/24",
}


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.now = [1000000.0]
        self.clock = lambda: self.now[0]
        self.inventory_path = self.base / "inventory.json"
        self.devices = [{"serial": "ABC123", "hostname": "PC-A", "mac": "02:00:00:00:00:01",
                         "ip": "192.168.57.50", "seen_at": self.now[0]}]
        self.write_inventory()
        self.store = ClarificationStore(self.base / "pending.sqlite3", clock=self.clock)
        self.inventory = DeviceInventory(self.inventory_path, clock=self.clock)
        self.flow = DiagnosticClarification(self.store, self.inventory)
        self.env = patch.dict(os.environ, ENV, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def write_inventory(self):
        self.inventory_path.write_text(json.dumps(self.devices), encoding="utf-8")


class InventoryTests(Fixture):
    def test_exact_hostname_serial_and_mac(self):
        for query in ("pc-a", "abc123", "020000000001", "02-00-00-00-00-01"):
            self.assertEqual(self.inventory.resolve(query)["ip"], "192.168.57.50")

    def test_fuzzy_name_never_selects(self):
        with self.assertRaises(InventoryError):
            self.inventory.resolve("PC")

    def test_duplicate_identity_or_ip_rejected(self):
        original = dict(self.devices[0])
        for field in ("serial", "hostname", "mac", "ip"):
            other = {"serial": "OTHER", "hostname": "PC-B", "mac": "02:00:00:00:00:02",
                     "ip": "192.168.57.51", "seen_at": self.now[0]}
            other[field] = original[field]
            self.devices = [original, other]
            self.write_inventory()
            with self.subTest(field=field), self.assertRaises(InventoryError):
                self.inventory.resolve("ABC123")

    def test_stale_or_future_inventory_rejected(self):
        for seen in (self.now[0] - 901, self.now[0] + 1):
            self.devices[0]["seen_at"] = seen
            self.write_inventory()
            with self.assertRaises(InventoryError):
                self.inventory.resolve("PC-A")

    def test_missing_inventory_has_no_path_disclosure(self):
        missing = DeviceInventory(self.base / "private-secret.json")
        with self.assertRaises(InventoryError) as error:
            missing.resolve("PC-A")
        self.assertNotIn("private-secret", str(error.exception))

    def test_invalid_json_or_record_fails_closed(self):
        for value in ("not-json", "null", '[{"hostname": "PC-A"}]'):
            self.inventory_path.write_text(value)
            with self.assertRaises(InventoryError):
                self.inventory.resolve("PC-A")


class ClarificationTests(Fixture):
    def test_explicit_ip_completes_original_diagnosis(self):
        self.flow.start("tech", 0.94)
        self.assertEqual(self.flow.reply("tech", "192.168.57.50"), {"target_ip": "192.168.57.50"})
        self.assertIsNone(self.store.get("tech"))

    def test_hostname_requires_ip_confirmation(self):
        self.flow.start("tech", 0.94)
        response = self.flow.reply("tech", "PC-A")
        self.assertNotIn("target_ip", response)
        self.assertIn("confirme", response["reply"])
        self.assertEqual(self.flow.reply("tech", "192.168.57.50")["target_ip"], "192.168.57.50")

    def test_mapping_changed_before_confirmation_aborts(self):
        self.flow.start("tech", 0.94)
        self.flow.reply("tech", "PC-A")
        self.devices[0]["ip"] = "192.168.57.51"
        self.write_inventory()
        self.assertNotIn("target_ip", self.flow.reply("tech", "192.168.57.50"))

    def test_identity_changed_on_same_ip_aborts(self):
        self.flow.start("tech", 0.94)
        self.flow.reply("tech", "PC-A")
        self.devices[0]["serial"] = "NEWDEVICE"
        self.devices[0]["mac"] = "02:00:00:00:00:02"
        self.write_inventory()
        self.assertNotIn("target_ip", self.flow.reply("tech", "192.168.57.50"))

    def test_wrong_confirmation_aborts(self):
        self.flow.start("tech", 0.94)
        self.flow.reply("tech", "PC-A")
        self.assertNotIn("target_ip", self.flow.reply("tech", "192.168.57.51"))
        self.assertIsNone(self.store.get("tech"))

    def test_other_user_cannot_complete_request(self):
        self.flow.start("tech", 0.94)
        self.assertIsNone(self.flow.reply("other", "192.168.57.50"))
        self.assertIsNotNone(self.store.get("tech"))

    def test_expired_request_is_not_resumed(self):
        self.flow.start("tech", 0.94)
        self.now[0] += 301
        self.assertIn("expirado", self.flow.reply("tech", "192.168.57.50")["reply"])

    def test_cancel_and_new_instruction_discard_old_intent(self):
        for text in ("cancelar", "/cancelar", "menu", "1", "/softwares 192.168.57.50 Chrome",
                     "agora quero outra coisa"):
            self.flow.start("tech", 0.94)
            self.flow.reply("tech", text)
            self.assertIsNone(self.store.get("tech"))

    def test_partial_ip_is_not_expanded(self):
        self.flow.start("tech", 0.94)
        self.assertNotIn("target_ip", self.flow.reply("tech", "57.50"))

    def test_permission_network_and_flags_rechecked_on_reply(self):
        for key, value in (("ULTRON_SEMANTIC_ALLOWED_TRUECONF_USERS", ""),
                           ("ULTRON_SEMANTIC_READONLY_ENABLED", "0"),
                           ("ULTRON_SEMANTIC_ROUTER_ENABLED", "0"),
                           ("ULTRON_SEMANTIC_ALLOWED_SUBNET", "192.168.58.0/24"),
                           ("ULTRON_TRUECONF_ALLOWED_USERS", "")):
            self.flow.start("tech", 0.94)
            with patch.dict(os.environ, {key: value}):
                self.assertNotIn("target_ip", self.flow.reply("tech", "192.168.57.50"))
            self.assertIsNone(self.store.get("tech"))

    def test_infrastructure_targets_remain_blocked(self):
        for ip in ("192.168.57.43", "192.168.57.87", "192.168.57.112"):
            self.flow.start("tech", 0.94)
            self.assertNotIn("target_ip", self.flow.reply("tech", ip))

    def test_atomic_consume_only_one_reply_wins(self):
        self.flow.start("tech", 0.94)
        pending = self.store.get("tech")
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.store.consume("tech", pending["nonce"]), range(16)))
        self.assertEqual(sum(result is not None for result in results), 1)

    def test_restart_clears_unfinished_clarification(self):
        self.flow.start("tech", 0.94)
        ClarificationStore(self.store.path, clock=self.clock).clear_after_restart()
        self.assertIsNone(self.flow.reply("tech", "192.168.57.50"))

    def test_low_confidence_not_stored(self):
        for confidence in (True, 0.4, float("nan"), 2):
            with self.assertRaises(ValueError):
                self.store.start("tech", confidence)
        self.assertIsNone(self.store.get("tech"))

    def test_schema_does_not_store_transcript_or_commands(self):
        with self.store.connect() as db:
            columns = {row[1] for row in db.execute("PRAGMA table_info(pending_diagnosis)")}
        self.assertFalse(columns & {"message", "prompt", "command", "password", "token", "transcript"})


class IntegrationTests(Fixture):
    def setUp(self):
        super().setUp()
        parsed = ast.parse((ROOT / "chatops/chatops.py").read_text(encoding="utf-8"))
        cls = next(node for node in parsed.body if isinstance(node, ast.ClassDef))
        nodes = [node for node in cls.body if isinstance(node, ast.FunctionDef)
                 and node.name in ("handle_incoming_message", "_semantic_route_message")]
        namespace = dict(os=os, re=__import__("re"), logger=Mock(), log=Mock(), new_trace_id=lambda: "trace",
                         _clean_chat_text=lambda s: s.strip(), _normalize_token=lambda s: s.casefold())
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "<clarification-integration>", "exec"), namespace)
        model = Mock(return_value=json.dumps({"intent": "diagnose", "mode": "request", "target_ip": None,
                                            "confidence": 0.94, "missing_fields": ["target_ip"]}))
        self.model = model
        self.client = types.SimpleNamespace(clarifications=self.flow, _pending_message_target={},
            user_sessions={}, _last_user_ip={}, _ensure_orchestrator=lambda: None,
            operational_memory=types.SimpleNamespace(target=lambda user: None),
            orchestrator=types.SimpleNamespace(analyzer=types.SimpleNamespace(generate=model)),
            _cmd_diagnostico=Mock(return_value="SUBMITTED"), _handle_ai_conversation=Mock(return_value="EXPLAIN"))
        self.handle = types.MethodType(namespace["handle_incoming_message"], self.client)
        self.client._semantic_route_message = types.MethodType(namespace["_semantic_route_message"], self.client)

    def test_two_message_request_resumes_without_reclassifying_ip(self):
        question = self.handle("tech", "diagnostica o computador")
        self.assertIn("IP completo", question)
        self.assertEqual(self.handle("tech", "192.168.57.50"), "SUBMITTED")
        self.client._cmd_diagnostico.assert_called_once_with("tech", ["192.168.57.50"])
        self.model.assert_called_once()

    def test_later_bare_ip_cannot_repeat_completed_diagnosis(self):
        self.handle("tech", "diagnostica o computador")
        self.handle("tech", "192.168.57.50")
        self.assertIn("nenhum diagnostico", self.handle("tech", "192.168.57.50"))
        self.client._cmd_diagnostico.assert_called_once()
        self.model.assert_called_once()

    def test_expired_reply_cannot_be_reclassified_as_new_diagnosis(self):
        self.handle("tech", "diagnostica o computador")
        self.now[0] += 301
        self.model.return_value = json.dumps({"intent": "diagnose", "mode": "request",
            "target_ip": "192.168.57.50", "confidence": 0.99, "missing_fields": []})
        self.assertIn("expirado", self.handle("tech", "192.168.57.50"))
        self.client._cmd_diagnostico.assert_not_called()
        self.model.assert_called_once()

    def test_mutating_plan_does_not_start_readonly_clarification(self):
        self.model.return_value = json.dumps({"intent": "install_software", "mode": "request",
            "target_ip": None, "confidence": 0.99, "missing_fields": ["target_ip", "package"]})
        self.handle("tech", "instala Chrome no computador")
        self.assertIsNone(self.store.get("tech"))
        self.client._cmd_diagnostico.assert_not_called()


if __name__ == "__main__":
    unittest.main()
