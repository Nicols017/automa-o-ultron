import json
import os
from typing import Dict, Any
from datetime import datetime

class CostTracker:
    def __init__(self, storage_path: str = "reports/cost_tracking.json"):
        self.storage_path = storage_path
        self.stats = self._load()

    def _load(self) -> Dict[str, Any]:
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"total_tokens": 0, "total_cost_usd": 0.0, "sessions": []}

    def _save(self):
        os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
        with open(self.storage_path, "w", encoding="utf-8") as f:
            json.dump(self.stats, f, indent=4)

    def track(self, model: str, prompt_tokens: int, completion_tokens: int, ip: str = "unknown"):
        total = prompt_tokens + completion_tokens
        
        # Simulação de custos (OpenAI vs Ollama local)
        # Ollama local = $0.00
        cost_per_1k = 0.0
        if "gpt-4" in model.lower():
            cost_per_1k = 0.03
        elif "gpt-3.5" in model.lower() or "qwen" in model.lower() and "api" in model:
            cost_per_1k = 0.001
            
        cost = (total / 1000.0) * cost_per_1k
        
        self.stats["total_tokens"] += total
        self.stats["total_cost_usd"] += cost
        self.stats["sessions"].append({
            "timestamp": datetime.now().isoformat(),
            "ip": ip,
            "model": model,
            "tokens": total,
            "cost_usd": cost
        })
        self._save()
        return cost

global_cost_tracker = CostTracker()
