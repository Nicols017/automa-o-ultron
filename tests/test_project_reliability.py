"""Offline regressions: no app startup, SDK, remote machine or actual messages."""
import ast
import json
import asyncio
import concurrent.futures
import os
from pathlib import Path
import re
import tempfile
import threading
import types
import typing
import unittest
from unittest.mock import Mock, AsyncMock, patch
from core.message_inbox import MessageInbox
from core.trueconf_transport import https_origin, trueconf_request, incoming_author, is_master_user, is_allowed_user

ROOT = Path(__file__).resolve().parents[1]
CHAT = ast.parse((ROOT / "chatops/chatops.py").read_text(encoding="utf-8"))
CLASS = next(n for n in CHAT.body if isinstance(n, ast.ClassDef) and n.name == "TrueConfChatOps")


def load_methods(names):
    selected = [n for n in CLASS.body if isinstance(n, ast.FunctionDef) and n.name in names]
    namespace = dict(vars(typing), os=os, re=re, threading=threading,
                     new_trace_id=lambda: "test", log=Mock(),
                     _clean_chat_text=lambda s: s.strip(), _normalize_token=lambda s: s.lower().strip())
    exec(compile(ast.Module(body=selected, type_ignores=[]), "<offline-chatops>", "exec"), namespace)
    return namespace


class TransportTests(unittest.TestCase):
    def test_trueconf_credentials_are_loaded_from_environment(self):
        source = ast.parse((ROOT / "core/profile_manager.py").read_text(encoding="utf-8"))
        cls = next(n for n in source.body if isinstance(n, ast.ClassDef))
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "get_settings")
        namespace = dict(vars(typing), os=os)
        exec(compile(ast.Module(body=[method], type_ignores=[]), "<settings>", "exec"), namespace)
        fake = types.SimpleNamespace(_load_dotenv=lambda: None, settings_file="/nonexistent/ultron-fixture.yaml")
        with patch.dict(os.environ, {"ULTRON_TRUECONF_BOT_PASSWORD": "", "ULTRON_TRUECONF_API_TOKEN": "fixture-token"}, clear=True):
            config = namespace["get_settings"](fake)
        self.assertEqual(config["trueconf"]["api_token"], "fixture-token")
        self.assertEqual(config["trueconf"]["bot_password"], "")

    def test_config_save_does_not_persist_environment_secrets(self):
        source = ast.parse((ROOT / "core/profile_manager.py").read_text(encoding="utf-8"))
        cls = next(n for n in source.body if isinstance(n, ast.ClassDef))
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "save_milvus_config")
        namespace = dict(vars(typing), os=os, yaml=types.SimpleNamespace(
            safe_load=lambda file: json.load(file),
            safe_dump=lambda data, file, **kwargs: json.dump(data, file)))
        exec(compile(ast.Module(body=[method], type_ignores=[]), "<settings-save>", "exec"), namespace)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "settings.yaml"
            path.write_text('{"trueconf": {"bot_password": ""}}')
            fake = types.SimpleNamespace(settings_file=str(path), milvus=types.SimpleNamespace(update_config=Mock()),
                                         get_settings=Mock(side_effect=AssertionError("Do not save runtime overlays")))
            with patch.dict(os.environ, {"ULTRON_TRUECONF_BOT_PASSWORD": "fixture-private-password"}):
                self.assertTrue(namespace["save_milvus_config"](fake, "https://example.invalid", "fixture-milvus"))
            self.assertNotIn("fixture-private-password", path.read_text())
            fake.get_settings.assert_not_called()

    def test_https_origin_and_port(self):
        self.assertEqual(https_origin("https://example.invalid:8443/"), "https://example.invalid:8443")

    def test_invalid_origins(self):
        for url in ("http://example.invalid", "https://user:secret@example.invalid", "https://example.invalid/path", ""):
            with self.subTest(url=url), self.assertRaises(ValueError):
                https_origin(url)

    def test_rest_cannot_disable_tls_or_follow_redirects(self):
        sender = Mock()
        with patch.dict(os.environ, {}, clear=True):
            trueconf_request("POST", "https://example.invalid/api", sender=sender,
                             verify=False, allow_redirects=True)
        self.assertIs(sender.call_args.kwargs["verify"], True)
        self.assertIs(sender.call_args.kwargs["allow_redirects"], False)
        sender.assert_called_once()

    def test_custom_ca_bundle(self):
        sender = Mock()
        with patch.dict(os.environ, {"ULTRON_TRUECONF_CA_BUNDLE": "fixture-ca.pem"}):
            trueconf_request("GET", "https://example.invalid/api", sender=sender)
        self.assertEqual(sender.call_args.kwargs["verify"], "fixture-ca.pem")

    def test_http_rejected_before_transport(self):
        sender = Mock()
        with self.assertRaises(ValueError):
            trueconf_request("POST", "http://example.invalid/api", sender=sender)
        sender.assert_not_called()

    def test_missing_identity_does_not_become_admin(self):
        self.assertEqual(incoming_author(types.SimpleNamespace()), "")

    def test_full_authenticated_identity_preserved(self):
        msg = types.SimpleNamespace(author=types.SimpleNamespace(id="Tech@Example"))
        self.assertEqual(incoming_author(msg), "tech@example")

    def test_privilege_requires_explicit_exact_identity(self):
        with patch.dict(os.environ, {"ULTRON_MASTER_TRUECONF_USERS": "tech@example"}, clear=True):
            self.assertTrue(is_master_user("Tech@Example"))
            for identity in ("admin", "nicolas", "tech", "tech@other"):
                self.assertFalse(is_master_user(identity))
            self.assertTrue(is_allowed_user("tech@example"))

    def test_empty_access_list_denies_operations(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(is_allowed_user("admin"))
        with patch.dict(os.environ, {"ULTRON_TRUECONF_ALLOWED_USERS": "operator"}, clear=True):
            self.assertTrue(is_allowed_user("operator"))
            self.assertFalse(is_master_user("operator"))


class InboxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "inbox.sqlite3"

    def test_restart_does_not_replay_event(self):
        self.assertTrue(MessageInbox(self.path).claim("server", "user", "event"))
        self.assertFalse(MessageInbox(self.path).claim("server", "user", "event"))

    def test_parallel_delivery_claimed_once(self):
        inbox = MessageInbox(self.path)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: inbox.claim("server", "user", "event"), range(16)))
        self.assertEqual(sum(results), 1)

    def test_separate_users_and_servers(self):
        inbox = MessageInbox(self.path)
        self.assertTrue(inbox.claim("a", "u", "1"))
        self.assertTrue(inbox.claim("a", "v", "1"))
        self.assertTrue(inbox.claim("b", "u", "1"))

    def test_missing_identity_or_event_rejected(self):
        inbox = MessageInbox(self.path)
        for values in (("", "u", "1"), ("s", "", "1"), ("s", "u", None)):
            self.assertFalse(inbox.claim(*values))

    def test_no_user_or_message_identifier_stored_in_plaintext(self):
        MessageInbox(self.path).claim("server-secret", "person-secret", "event-secret")
        self.assertNotIn(b"person-secret", self.path.read_bytes())
        self.assertNotIn(b"event-secret", self.path.read_bytes())


class BotIntegrationTests(unittest.TestCase):
    def test_sdk_events_are_deduplicated_and_logs_do_not_echo_text(self):
        source = ast.parse((ROOT / "chatops/bot.py").read_text(encoding="utf-8"))
        cls = next(n for n in source.body if isinstance(n, ast.ClassDef))
        method = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_bot_lifecycle")
        router = types.SimpleNamespace()
        def decorate():
            def register(function):
                router.handler = function
                return function
            return register
        router.message = decorate
        logger = Mock()
        logger.warning.side_effect = AssertionError("Unexpected SDK lifecycle failure")
        with tempfile.TemporaryDirectory() as temp:
            client = types.SimpleNamespace(_is_running=True, _bot=None, _p2p_chats={},
                raw_server_url="https://example.invalid", server_host="example.invalid",
                bot_username="fixture", bot_password="fixture-password",
                inbox=MessageInbox(Path(temp) / "inbox.sqlite3"),
                chatops=types.SimpleNamespace(handle_incoming_message=Mock(return_value="OK")))
            event = types.SimpleNamespace(text="sensitive fixture password", id="id-1",
                author=types.SimpleNamespace(id="Tech@Realm"), chat_id="chat-1", answer=AsyncMock())
            anonymous = types.SimpleNamespace(text="restart", id="id-2", author=None)
            async def run(**kwargs):
                await router.handler(anonymous)
                await router.handler(event)
                await router.handler(event)
                client._is_running = False
            sdk = types.SimpleNamespace(run=run)
            factory = Mock(return_value=sdk)
            async def immediate(function, *args):
                return function(*args)
            async def no_sleep(*args):
                raise AssertionError("Unexpected reconnect in fake SDK test")
            fake_asyncio = types.SimpleNamespace(to_thread=immediate, sleep=no_sleep,
                                                CancelledError=asyncio.CancelledError)
            namespace = dict(asyncio=fake_asyncio, TRUECONF_LIB_AVAILABLE=True,
                Dispatcher=lambda: types.SimpleNamespace(include_router=lambda _: None),
                Router=lambda: router, Message=object, incoming_author=incoming_author,
                _clean_chat_text=lambda text: text, _split_message=lambda text: [text], logger=logger,
                Bot=types.SimpleNamespace(from_credentials=factory),
                ParseMode=types.SimpleNamespace(TEXT="TEXT"))
            exec(compile(ast.Module(body=[method], type_ignores=[]), "<fake-sdk>", "exec"), namespace)
            # All awaited fakes complete synchronously: no event-loop socket is created.
            coroutine = namespace["_bot_lifecycle"](client)
            with self.assertRaises(StopIteration):
                coroutine.send(None)
            client.chatops.handle_incoming_message.assert_called_once_with("tech@realm", event.text)
            event.answer.assert_awaited_once()
            self.assertIs(factory.call_args.kwargs["verify_ssl"], True)
            self.assertIs(factory.call_args.kwargs["receive_unread_messages"], False)
            self.assertNotIn(event.text, str(logger.mock_calls))
            self.assertNotIn(client.bot_password, str(logger.mock_calls))


class RoutingTests(unittest.TestCase):
    def test_all_self_call_keywords_match_method_signatures(self):
        methods = {n.name: n for n in CLASS.body if isinstance(n, ast.FunctionDef)}
        for call in ast.walk(CLASS):
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                    and isinstance(call.func.value, ast.Name) and call.func.value.id == "self"
                    and call.func.attr in methods):
                continue
            args = methods[call.func.attr].args
            if args.kwarg:
                continue
            accepted = {a.arg for a in args.args + args.kwonlyargs}
            for keyword in call.keywords:
                if keyword.arg:
                    self.assertIn(keyword.arg, accepted, (call.lineno, call.func.attr))

    def test_numeric_and_slash_routes_use_real_method_signatures(self):
        handle = load_methods({"handle_incoming_message"})["handle_incoming_message"]
        fake = types.SimpleNamespace(_pending_message_target={}, user_sessions={},
                                     _extract_target_ip=lambda text: None,
                                     _handle_master_intent=lambda *a: None)
        # Stub bodies with exact original signatures. Calling a mismatched route still raises.
        stubs = []
        for node in CLASS.body:
            if isinstance(node, ast.FunctionDef) and node.name != "handle_incoming_message":
                clone = ast.FunctionDef(name=node.name, args=node.args,
                                       body=[ast.Return(ast.Constant(node.name))],
                                       decorator_list=[], returns=None)
                stubs.append(clone)
        ns = dict(vars(typing))
        code = ast.fix_missing_locations(ast.Module(body=stubs, type_ignores=[]))
        exec(compile(code, "<stub-methods>", "exec"), ns)
        for name, value in ns.items():
            if name.startswith("_") and callable(value):
                setattr(fake, name, types.MethodType(value, fake))
        fake._extract_target_ip = lambda text: None
        fake._handle_master_intent = lambda *a: None
        expected = {"1": "_cmd_bancada", "2": "_start_wizard_diagnostico", "3": "_start_wizard_msg",
                    "4": "_start_wizard_preparar", "5": "_start_wizard_ativar",
                    "6": "_start_wizard_backup", "7": "_start_wizard_dominio",
                    "8": "_start_wizard_softwares", "9": "_start_wizard_power",
                    "10": "_cmd_clientes", "11": "_cmd_chamados", "12": "_cmd_laudos",
                    "13": "_cmd_download_agent", "14": "_start_wizard_limpar",
                    "/bancada": "_cmd_bancada", "/clientes": "_cmd_clientes",
                    "/chamados": "_cmd_chamados", "/download": "_cmd_download_agent"}
        with patch.dict(os.environ, {"ULTRON_TRUECONF_ALLOWED_USERS": "operator"}, clear=True):
            for text, method in expected.items():
                with self.subTest(text=text):
                    self.assertEqual(handle(fake, "operator", text), method)

    def test_unauthorized_input_does_not_reach_a_handler(self):
        handle = load_methods({"handle_incoming_message"})["handle_incoming_message"]
        with patch.dict(os.environ, {}, clear=True):
            self.assertIn("nao autorizado", handle(object(), "unknown", "/reiniciar 192.0.2.1"))

    def test_cancellation_does_not_kill_remote_processes_or_claim_abort(self):
        cancel = load_methods({"_handle_master_intent"})["_handle_master_intent"]
        event = threading.Event()
        client = types.SimpleNamespace(_is_master_user=lambda _: True,
                    active_jobs={"operator": {"event": event, "ip": "192.0.2.1"}}, winrm=Mock())
        result = cancel(client, "operator", "cancela", "cancela")
        self.assertTrue(event.is_set())
        client.winrm.run_powershell_code.assert_not_called()
        self.assertIn("nao foi confirmado", result)
        self.assertNotIn("sucesso", result)


if __name__ == "__main__":
    unittest.main()
