from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Dict, Optional
import hashlib, json, os, time

try:
    import tiktoken  # type: ignore
except Exception:
    tiktoken = None


def _rough_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


def count_tokens(model: str, text: str) -> int:
    if not text:
        return 0
    if tiktoken is None or not model or ("gpt" not in model):
        return _rough_tokens(text)
    try:
        enc = tiktoken.encoding_for_model(model)
    except Exception:
        from tiktoken import get_encoding  # type: ignore
        enc = get_encoding("cl100k_base")
    return len(enc.encode(text))


@dataclass
class TokenEvent:
    ts: float
    run_id: str
    state: str
    provider: str
    model: str
    role: str  # "prompt" | "completion" | "system"
    n_tokens: int
    budget_cap: int
    over_budget: bool
    policy: str  # "warn" | "truncate" | "fallback" | "block"


class TokenBudgeter:
    """Tracks per-run token usage and enforces caps before provider calls."""

    def __init__(self, run_id: str, budgets: Dict[str, Dict[str, int]], policy: str, out_path: str = "logs/eval.log"):
        self.run_id = run_id
        self.budgets = budgets
        self.policy = policy
        self.used: Dict[str, int] = {k: 0 for k in budgets.keys()}
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        self.out_path = out_path

    def remaining(self, state: str) -> int:
        return max(0, self.budgets[state]["cap"] - self.used[state])

    def charge(self, state: str, provider: str, model: str, role: str, n_tokens: int) -> None:
        cap = self.budgets[state]["cap"]
        over = (self.used[state] + n_tokens) > cap
        # never exceed cap
        self.used[state] += min(n_tokens, max(0, cap - self.used[state]))
        self._log(TokenEvent(time.time(), self.run_id, state, provider, model, role, n_tokens, cap, over, self.policy))
        # live counters, best effort
        try:
            from apps.coordinator.metrics import TOKENS  # type: ignore
            if TOKENS is not None:
                TOKENS.add(state, role, n_tokens)  # type: ignore
        except Exception:
            pass

    def enforce_before_call(self, state: str, planned_prompt_tokens: int) -> str:
        cap = self.budgets[state]["cap"]
        if self.used[state] + planned_prompt_tokens <= cap:
            return "ok"
        return self.policy

    def _log(self, ev: TokenEvent):
        with open(self.out_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"type": "TOKEN", **asdict(ev)}, ensure_ascii=False) + "\n")


def prompt_cache_key(text: str, model: str) -> str:
    h = hashlib.sha256()
    h.update((model + "||" + (text or "")).encode("utf-8"))
    return h.hexdigest()[:16]
