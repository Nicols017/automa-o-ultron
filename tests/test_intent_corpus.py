"""Regression corpus: simple, anonymized and safe to run without network."""
import importlib.util
import json
from pathlib import Path
import unittest

from core.intent_preflight import preflight_request
from core.structured_intent import INTENTS

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tests" / "intent_examples.json"


class IntentCorpusTests(unittest.TestCase):
    def setUp(self):
        self.cases = json.loads(DATA.read_text(encoding="utf-8"))

    def test_examples_have_expected_fields_and_unique_ids(self):
        self.assertGreaterEqual(len(self.cases), 20)
        seen = set()
        for x in self.cases:
            self.assertEqual(set(x), {
                "id", "message", "intent", "mode", "preflight", "target_ip"
            })
            self.assertNotIn(x["id"], seen)
            self.assertIn(x["intent"], INTENTS)
            self.assertIn(x["mode"], ("question", "request", "unknown"))
            seen.add(x["id"])

    def test_preflight_matches_checked_examples(self):
        failed = {}
        for example in self.cases:
            actual = preflight_request(example["message"]).kind
            if actual != example["preflight"]:
                failed[example["id"]] = {
                    "expected": example["preflight"],
                    "actual": actual,
                }
        self.assertFalse(failed, failed)

    def test_evaluator_cannot_run_remote_actions(self):
        spec = importlib.util.spec_from_file_location(
            "evaluate_intents", ROOT / "scripts" / "evaluate_intents.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        report = module.evaluate(self.cases)
        self.assertEqual(report["total_cases"], len(self.cases))
        self.assertFalse(report["remote_actions_executed"])
        self.assertFalse(report["model_inference_performed"])
        self.assertEqual(report["preflight_failed_ids"], [])


if __name__ == "__main__":
    unittest.main()
