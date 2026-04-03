"""
Agentic Purchase — 200-query evaluation harness (resumable).

Invocation:
  python -m backend.evaluation.run_eval_200            # full 200-query eval
  python -m backend.evaluation.run_eval_200 --dry-run  # first 5 queries only
  python -m backend.evaluation.run_eval_200 --resume   # skip already-completed IDs

Progress is saved every 10 queries to:
  backend/evaluation/results/eval_200_progress.json

Final results are saved to:
  backend/evaluation/results/eval_200_raw.json

Image queries: new query IDs (fw-011, etc.) are mapped to existing image files
via dataset_200.IMAGE_MAP — the same 20 physical images are reused.

Retry policy: on rate-limit exceptions (HTTP 429 / RateLimitError) the runner
sleeps 30 s and retries once before recording a failure.

Sleep: 2 s between every query to stay within API rate limits.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

RESULTS_DIR = Path(__file__).parent / "results"
PROGRESS_PATH = RESULTS_DIR / "eval_200_progress.json"
IMAGE_DIR = Path(__file__).parent / "images"

_SLEEP_BETWEEN_QUERIES = 2.0   # seconds
_RATE_LIMIT_SLEEP      = 30.0  # seconds on 429 / RateLimitError
_PROGRESS_SAVE_EVERY   = 10    # queries


# ── Result dataclass (JSON-serialisable) ──────────────────────────────────────

@dataclass
class QueryResult:
    query_id: str
    query_text: str
    category: str
    has_image: bool
    success: bool
    error: str | None
    duration_ms: float
    total_tokens: int
    intent_output: dict
    n_sourced_offers: int
    n_ranked_offers: int
    trust_results: list[dict]
    ranked_offers_data: list[dict]


# ── Image loading (explicit map for new query IDs) ────────────────────────────

def _load_image_bytes(query_id: str, image_map: dict[str, str]) -> bytes | None:
    """
    Return image bytes for query_id.
    - For original query IDs (fw-01..fw-10 etc.): look for {query_id}.jpg directly.
    - For new query IDs in image_map: resolve via the mapped stem first.
    - Returns None if no image file exists.
    """
    # Try the query's own filename first (original queries)
    for ext in ("jpg", "jpeg", "png", "webp"):
        p = IMAGE_DIR / f"{query_id}.{ext}"
        if p.exists():
            return p.read_bytes()

    # Try the mapped image stem (new queries)
    mapped_stem = image_map.get(query_id)
    if mapped_stem:
        for ext in ("jpg", "jpeg", "png", "webp"):
            p = IMAGE_DIR / f"{mapped_stem}.{ext}"
            if p.exists():
                return p.read_bytes()

    return None


# ── Orchestrator builder (mirrors run_eval._build_orchestrator) ───────────────

def _build_orchestrator():
    import backend.agents.orchestrator.agent as _orch_mod
    import backend.agents.orchestrator.graph as _graph_mod
    from backend.agents.bus import get_agent_bus
    from backend.agents.checkout.agent import CheckoutAgent
    from backend.agents.intent.agent import IntentAgent
    from backend.agents.orchestrator.agent import OrchestratorAgent
    from backend.agents.ranking.agent import RankingAgent
    from backend.agents.sourcing.agent import SourcingAgent
    from backend.agents.trust.agent import TrustAgent
    from backend.agents.vision.agent import VisionAgent
    from backend.models.saga import SagaStatus

    _orig_after_offer_selection = _graph_mod.after_offer_selection
    _orig_after_ranking         = _graph_mod.after_ranking
    _orig_node_checkout         = _graph_mod.node_checkout

    def _eval_after_offer_selection(state):
        return "checkout"

    def _eval_after_ranking(state):
        if state.get("terminal_error"):
            return "end_failed"
        return "await_offer_selection"

    async def _eval_node_checkout(state):
        return {"saga_status": SagaStatus.COMPLETE}

    _graph_mod.after_offer_selection = _eval_after_offer_selection
    _graph_mod.after_ranking         = _eval_after_ranking
    _graph_mod.node_checkout         = _eval_node_checkout

    _orch_mod._compiled_graph = None

    bus = get_agent_bus()
    bus.register(VisionAgent())
    bus.register(IntentAgent())
    bus.register(SourcingAgent())
    bus.register(TrustAgent())
    bus.register(RankingAgent())
    bus.register(CheckoutAgent())

    orchestrator = OrchestratorAgent(bus=bus)

    _graph_mod.after_offer_selection = _orig_after_offer_selection
    _graph_mod.after_ranking         = _orig_after_ranking
    _graph_mod.node_checkout         = _orig_node_checkout

    return orchestrator, bus


# ── Single-query runner (with rate-limit retry) ───────────────────────────────

async def _run_one_query(
    orchestrator,
    bus,
    query,
    image_bytes: bytes | None,
) -> QueryResult:
    from unittest.mock import AsyncMock, patch
    from backend.agents.trust.session1 import run_session1
    from backend.models.trust import TrustLevel

    saga_id   = str(uuid.uuid4())
    has_image = image_bytes is not None

    async def noop_emitter(event):
        pass

    _noop_set = AsyncMock(return_value=None)
    _noop_get = AsyncMock(return_value=None)
    _minimal_vendor_profile = {
        "rating": 4.5,
        "review_count": 150,
        "account_age_days": 365,
        "has_return_policy": True,
        "fulfilled_orders": 500,
        "feedback_percentage": 97.0,
    }
    _mock_get_vendor   = AsyncMock(return_value=_minimal_vendor_profile)
    _mock_cache_vendor = AsyncMock(return_value=None)

    for attempt in range(2):
        start = time.monotonic()
        try:
            with (
                patch("backend.core.redis.set_saga_state", _noop_set),
                patch("backend.agents.orchestrator.agent.set_saga_state", _noop_set),
                patch("backend.agents.orchestrator.agent.get_saga_state", _noop_get),
                patch("backend.agents.trust.agent.get_cached_vendor_profile", _mock_get_vendor),
                patch("backend.agents.trust.agent.cache_vendor_profile", _mock_cache_vendor),
            ):
                final_state: dict = await orchestrator.start_saga(
                    saga_id=saga_id,
                    session_id=f"eval200-{saga_id[:8]}",
                    user_id="eval-user",
                    user_text=query.text,
                    image_bytes=image_bytes,
                    conversation_history=[],
                    user_preferences=None,
                    sse_emitter=noop_emitter,
                )
            break  # success
        except Exception as exc:
            duration_ms = (time.monotonic() - start) * 1000
            exc_str = str(exc)
            is_rate_limit = (
                "429" in exc_str
                or "RateLimitError" in type(exc).__name__
                or "rate_limit" in exc_str.lower()
                or "rate limit" in exc_str.lower()
            )
            if is_rate_limit and attempt == 0:
                print(f"    [rate-limit] sleeping {_RATE_LIMIT_SLEEP}s then retrying...")
                await asyncio.sleep(_RATE_LIMIT_SLEEP)
                saga_id = str(uuid.uuid4())  # fresh ID for retry
                continue
            # Non-rate-limit failure or second attempt also failed
            bus.get_saga_tokens(saga_id)
            return QueryResult(
                query_id=query.query_id,
                query_text=query.text,
                category=query.category,
                has_image=has_image,
                success=False,
                error=exc_str[:300],
                duration_ms=round(duration_ms, 1),
                total_tokens=0,
                intent_output={},
                n_sourced_offers=0,
                n_ranked_offers=0,
                trust_results=[],
                ranked_offers_data=[],
            )

    duration_ms = (time.monotonic() - start) * 1000

    tokens_by_agent = bus.get_saga_tokens(saga_id)
    total_tokens    = sum(tokens_by_agent.values())

    parsed_intent  = final_state.get("parsed_intent")
    vision_attrs   = final_state.get("vision_detected_attributes") or {}
    brand_from_vision = (
        vision_attrs.get("brand_if_visible")
        or vision_attrs.get("brand")
        or ""
    )
    intent_output = {
        "category":      getattr(parsed_intent, "category", "") if parsed_intent else "",
        "primary_query": getattr(parsed_intent, "primary_query", "") if parsed_intent else "",
        "brand":         brand_from_vision,
    }

    scored_offers = final_state.get("scored_offers") or []
    ranked_offers = final_state.get("ranked_offers") or []
    all_offers    = final_state.get("all_offers") or []

    # Build trust results
    trust_results: list[dict] = []
    if scored_offers:
        try:
            s1 = run_session1(offers=scored_offers, vision_attributes=vision_attrs)
            signal_map = {sig.offer_id: sig for sig in s1.signals}
        except Exception:
            signal_map = {}

        for offer in scored_offers:
            sig = signal_map.get(getattr(offer, "offer_id", ""), None)
            trust_level = getattr(getattr(offer, "trust_score", None), "level", None)
            verdict = "HIGH_RISK" if trust_level == TrustLevel.HIGH_RISK else "AUTHENTIC"
            trust_results.append({
                "offer_id":      getattr(offer, "offer_id", ""),
                "title":         getattr(offer, "title", ""),
                "verdict":       verdict,
                "trust_level":   trust_level.value if trust_level else "UNKNOWN",
                "trust_score":   getattr(getattr(offer, "trust_score", None), "score", 0.0),
                "price_anomaly":  bool(sig.price_anomaly)  if sig else False,
                "replica_flag":   bool(sig.replica_flag)   if sig else False,
                "brand_mismatch": bool(sig.brand_mismatch) if sig else False,
            })

    # Ranked offers data for NDCG/MRR computation
    ranked_offers_data: list[dict] = []
    for ro in ranked_offers:
        offer = getattr(ro, "offer", ro)
        ranked_offers_data.append({
            "offer_id": getattr(offer, "offer_id", ""),
            "title":    getattr(offer, "title", ""),
            "price":    getattr(getattr(offer, "price", None), "amount", 0.0),
            "brand":    getattr(offer, "raw_attributes", {}).get("brand", ""),
        })

    return QueryResult(
        query_id=query.query_id,
        query_text=query.text,
        category=query.category,
        has_image=has_image,
        success=True,
        error=None,
        duration_ms=round(duration_ms, 1),
        total_tokens=total_tokens,
        intent_output=intent_output,
        n_sourced_offers=len(all_offers),
        n_ranked_offers=len(ranked_offers),
        trust_results=trust_results,
        ranked_offers_data=ranked_offers_data,
    )


# ── Progress persistence ──────────────────────────────────────────────────────

def _load_progress() -> dict[str, dict]:
    """Return {query_id: result_dict} from the progress file, or {} if absent."""
    if PROGRESS_PATH.exists():
        try:
            data = json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
            return {r["query_id"]: r for r in data.get("results", [])}
        except Exception:
            pass
    return {}


def _save_progress(completed: list[QueryResult]) -> None:
    RESULTS_DIR.mkdir(exist_ok=True)
    data = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "n_completed": len(completed),
        "results": [asdict(r) for r in completed],
    }
    PROGRESS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ── Main evaluation loop ──────────────────────────────────────────────────────

async def run_evaluation_200(dry_run: bool = False, resume: bool = False) -> None:
    from backend.evaluation.dataset_200 import ALL_QUERIES, IMAGE_MAP

    queries = ALL_QUERIES[:5] if dry_run else ALL_QUERIES
    mode_label = "DRY-RUN (5 queries)" if dry_run else f"FULL ({len(queries)} queries)"

    # Determine image-enabled query IDs (original files + new mapped files)
    image_query_ids: set[str] = set()
    # Original: scan images directory for files matching existing query stems
    if IMAGE_DIR.exists():
        for p in IMAGE_DIR.iterdir():
            if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                image_query_ids.add(p.stem)
    # New: any query in IMAGE_MAP whose mapped file actually exists
    for qid, stem in IMAGE_MAP.items():
        for ext in ("jpg", "jpeg", "png", "webp"):
            if (IMAGE_DIR / f"{stem}.{ext}").exists():
                image_query_ids.add(qid)
                break

    n_img_total = sum(1 for q in queries if q.query_id in image_query_ids)
    n_txt_total = len(queries) - n_img_total

    print(f"\n{'='*62}")
    print(f"  AGENTIC PURCHASE 200-QUERY EVALUATION — {mode_label}")
    print(f"  Image-assisted: {n_img_total}   Text-only: {n_txt_total}")
    print(f"  Started: {datetime.now(timezone.utc).isoformat()}")
    print(f"{'='*62}\n")

    # Resume: skip already-completed query IDs
    completed_map: dict[str, dict] = {}
    if resume and not dry_run:
        completed_map = _load_progress()
        if completed_map:
            print(f"  [resume] Found {len(completed_map)} previously completed queries — skipping.\n")

    orchestrator, bus = _build_orchestrator()

    completed: list[QueryResult] = []
    # Re-hydrate already-completed results from progress
    for q in queries:
        if q.query_id in completed_map:
            d = completed_map[q.query_id]
            completed.append(QueryResult(**d))

    pending_queries = [q for q in queries if q.query_id not in completed_map]
    total = len(queries)
    n_done = len(completed)

    for i, query in enumerate(pending_queries):
        n_done += 1
        image_bytes = _load_image_bytes(query.query_id, IMAGE_MAP)
        mode = "[IMG]" if image_bytes is not None else "[TXT]"
        print(f"[{n_done:3d}/{total}] {mode} {query.query_id}: {query.text[:55]}...")

        result = await _run_one_query(orchestrator, bus, query, image_bytes=image_bytes)
        status = "OK" if result.success else f"FAIL ({result.error or 'unknown'})"
        print(f"          -> {status}  | {result.duration_ms:.0f}ms | {result.total_tokens} tok")

        completed.append(result)

        # Save progress every N queries
        if not dry_run and n_done % _PROGRESS_SAVE_EVERY == 0:
            _save_progress(completed)
            print(f"  [progress saved: {n_done}/{total}]")

        # Sleep between queries (skip after the last one)
        if i < len(pending_queries) - 1:
            await asyncio.sleep(_SLEEP_BETWEEN_QUERIES)

    n_success = sum(1 for r in completed if r.success)
    n_fail    = len(completed) - n_success
    print(f"\nCompleted: {n_success}/{len(completed)} succeeded, {n_fail} failed\n")

    if dry_run:
        print("[Dry-run: results not saved]")
        return

    # Final save
    _save_progress(completed)

    # Write canonical raw output
    RESULTS_DIR.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    raw_path = RESULTS_DIR / "eval_200_raw.json"
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": ts,
            "n_queries": len(completed),
            "n_success": n_success,
            "n_image":   n_img_total,
            "n_text":    n_txt_total,
            "results":   [asdict(r) for r in completed],
        }, f, indent=2)

    print(f"Raw results saved to: {raw_path}")
    print(f"Run compute_metrics_200.py to generate paper metrics.")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run 200-query Agentic Purchase evaluation (resumable)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Evaluate only the first 5 queries (no results saved)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip query IDs already present in eval_200_progress.json",
    )
    args = parser.parse_args()
    asyncio.run(run_evaluation_200(dry_run=args.dry_run, resume=args.resume))


if __name__ == "__main__":
    main()
