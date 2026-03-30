from __future__ import annotations

import json
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Deque, Dict

_MAX_SAMPLES = 500


class _StateStats:
    def __init__(self):
        self.ok = 0
        self.err = 0
        self.times: Deque[float] = deque(maxlen=_MAX_SAMPLES)

    def add(self, ok: bool, dt_s: float | None):
        if ok: self.ok += 1
        else: self.err += 1
        if dt_s is not None: self.times.append(float(dt_s))

    def summary(self) -> dict:
        if not self.times:
            return {"count_ok": self.ok, "count_err": self.err, "avg_s": 0.0, "p95_s": 0.0}
        arr = sorted(self.times)
        avg = sum(arr) / len(arr)
        p95_idx = max(0, int(0.95*len(arr)) - 1)
        return {"count_ok": self.ok, "count_err": self.err,
                "avg_s": round(avg,4), "p95_s": round(arr[p95_idx],4)}

class Metrics:
    def __init__(self):
        self._states: Dict[str, _StateStats] = defaultdict(_StateStats)
        self._start = time.time()
        self._recognition_total = 0
        self._recognition_hits = 0
        self._ranking_total = 0
        self._ranking_hits = 0
        self._events_logged = 0
        logs_dir = Path(__file__).resolve().parents[2] / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        self._eval_log = logs_dir / "eval.log"

    def record(self, state: str, dt_s: float | None, ok: bool):
        self._states[state].add(ok, dt_s)
    def mark(self, state: str, ok: bool, dt_s: float | None):
        return self.record(state, dt_s, ok)
    def summary(self) -> Dict[str, dict]:
        return {k:v.summary() for k,v in self._states.items()}
    @property
    def uptime_s(self): return time.time() - self._start

    # ---- evaluation harness helpers ----
    def record_recognition(self, hypothesis: Dict[str, Any], intent: Dict[str, Any]):
        self._recognition_total += 1
        hit = False
        try:
            hypo_label = (hypothesis.get("label") or "").lower().strip()
            hypo_brand = (hypothesis.get("brand") or "").lower().strip()
            hypo_color = (hypothesis.get("color") or "").lower().strip()
            intent_item = (intent.get("item_name") or "").lower().strip()
            intent_brand = (intent.get("brand") or "").lower().strip()
            intent_color = (intent.get("color") or "").lower().strip()
            if hypo_label and intent_item and (hypo_label in intent_item or intent_item in hypo_label):
                hit = True
            elif hypo_brand and intent_brand and hypo_brand == intent_brand:
                hit = True
            elif hypo_color and intent_color and hypo_color == intent_color:
                hit = True
        except Exception:
            hit = False
        if hit:
            self._recognition_hits += 1

    def record_ranking(self, offers: list[Dict[str, Any]]):
        if not offers:
            return
        self._ranking_total += 1
        try:
            scores = [float(o.get("score")) for o in offers if o.get("score") is not None]
        except Exception:
            scores = []
        if not scores:
            return
        try:
            top_score = float(offers[0].get("score"))
        except Exception:
            top_score = None
        if top_score is None:
            return
        if top_score >= max(scores) - 1e-6:
            self._ranking_hits += 1

    def log_event(self, payload: Dict[str, Any]):
        try:
            line = json.dumps(payload, default=_json_serialize, ensure_ascii=False)
            with self._eval_log.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            self._events_logged += 1
        except Exception:
            pass

    def evaluation_summary(self) -> Dict[str, Any]:
        def _ratio(h, t):
            return round(h / t, 4) if t else None

        return {
            "recognition": {
                "total": self._recognition_total,
                "hits": self._recognition_hits,
                "accuracy": _ratio(self._recognition_hits, self._recognition_total),
            },
            "ranking": {
                "total": self._ranking_total,
                "hits": self._ranking_hits,
                "accuracy": _ratio(self._ranking_hits, self._ranking_total),
            },
            "events_logged": self._events_logged,
            "log_path": str(self._eval_log),
        }

METRICS = Metrics()


def _json_serialize(obj: Any):
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict"):
        return obj.dict()
    if isinstance(obj, (set, tuple)):
        return list(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

# ---- Token counters (live) ----
class TokenCounters:
    def __init__(self):
        self.by_state = {s: {"prompt": 0, "completion": 0, "calls": 0} for s in ["S1","S2","S3","S4","S5"]}
    def add(self, state: str, role: str, n: int):
        if state not in self.by_state:
            self.by_state[state] = {"prompt": 0, "completion": 0, "calls": 0}
        if role not in ("prompt","completion"):
            return
        self.by_state[state][role] += int(n)
        if role == "completion":
            self.by_state[state]["calls"] += 1
    def summary(self):
        return self.by_state

TOKENS = TokenCounters()
