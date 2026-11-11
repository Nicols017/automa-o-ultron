"""Evaluate anonymized TrueConf utterances without touching any machines.

Usage (offline baseline):
    python scripts/evaluate_intents.py --strict

Optional: compare a file of model predictions, not a live remote model:
    python scripts/evaluate_intents.py --predictions path/to/answers.jsonl

Prediction lines: {"id":"diagnose","output":{"intent":"diagnose", ...}}
Never paste production chat logs with passwords or customer data into a dataset.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.intent_preflight import preflight_request
from core.structured_intent import validate_plan, IntentPlanError

DEFAULT_DATA = Path(__file__).resolve().parents[1] / "tests" / "intent_examples.json"


def evaluate(cases: list, predictions: dict = None) -> dict:
    if not isinstance(cases, list) or not cases:
        raise ValueError("Corpus vazio ou inválido.")
    ids = set()
    check = []
    semantics = []
    for example in cases:
        if not isinstance(example, dict):
            raise ValueError("Exemplo inválido.")
        key = example.get("id")
        if not isinstance(key, str) or key in ids:
            raise ValueError("Identificador ausente ou duplicado.")
        ids.add(key)
        utterance = example.get("message")
        if not isinstance(utterance, str) or not utterance.strip():
            raise ValueError("Mensagem inválida.")
        observed = preflight_request(utterance).kind
        if observed != example.get("preflight"):
            check.append(key)
        if predictions is None:
            continue
        raw = predictions.get(key)
        if raw is None:
            semantics.append({"id": key, "error": "missing_prediction"})
            continue
        try:
            value = raw if isinstance(raw, str) else json.dumps(raw)
            plan = validate_plan(value, utterance)
        except (IntentPlanError, TypeError):
            semantics.append({"id": key, "error": "invalid_plan"})
            continue
        if (plan.intent != example.get("intent")
                or plan.mode != example.get("mode")
                or plan.target_ip != example.get("target_ip")):
            semantics.append({"id": key, "error": "misclassified"})
    return {
        "total_cases": len(cases),
        "preflight_correct": len(cases) - len(check),
        "preflight_failed_ids": check,
        "semantic_prediction_count": len(predictions) if predictions is not None else None,
        "semantic_failed_ids": semantics,
        "model_inference_performed": False,
        "remote_actions_executed": False,
    }


def main():
    parser = argparse.ArgumentParser(description="Testes de compreensão Ultron — sem rede.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--predictions", type=Path)
    parser.add_argument("--strict", action="store_true",
                        help="Código !=0 se houver divergências.")
    args = parser.parse_args()
    cases = json.loads(args.dataset.read_text(encoding="utf-8"))
    predictions = None
    if args.predictions:
        predictions = {}
        for line in args.predictions.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            if record["id"] in predictions:
                raise ValueError("Predição duplicada.")
            predictions[record["id"]] = record["output"]
    result = evaluate(cases, predictions)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.strict and (result["preflight_failed_ids"] or result["semantic_failed_ids"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
