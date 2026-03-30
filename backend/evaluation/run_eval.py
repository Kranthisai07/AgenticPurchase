"""
Agentic Purchase — end-to-end evaluation harness.

Invocation:
  python -m backend.evaluation.run_eval            # full 50-query eval (20 img + 30 text)
  python -m backend.evaluation.run_eval --dry-run  # first 5 queries only, no save

Evaluation modes:
  Image queries: 20 queries have a real product image in backend/evaluation/images/
                 Vision Agent extracts brand from the image; F1 uses 3 fields.
  Text queries:  30 queries have no image; brand is not extracted; F1 uses 2 fields.
  Combined F1:   weighted average of image_f1 and text_f1 by query count.

Infrastructure requirements (must be running before eval):
  - OpenAI API key: required for Vision, Intent, Trust (Session 2), Ranking agents
  - eBay / SerpApi keys: required for Sourcing agent
  - Redis is patched to a no-op for eval; no Redis instance needed.

Saga invocation pattern (same as _run_saga_background in backend/api/routes/saga.py):
  final_state = await orchestrator.start_saga(...)
This is a direct call to the orchestration logic — no HTTP layer involved.

Token extraction:
  get_agent_bus().get_saga_tokens(saga_id) pops and returns per-agent token counts
  accumulated by AgentBus.dispatch() during the saga run.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

# ── Image directory ────────────────────────────────────────────────────────────
IMAGE_DIR = Path(__file__).parent / "images"

# Set of query IDs that have an image file (populated at module load)
_IMAGE_QUERY_IDS: set[str] = set()


def _discover_image_ids() -> None:
    """Scan IMAGE_DIR once at startup and cache the set of image query IDs."""
    if IMAGE_DIR.exists():
        for p in IMAGE_DIR.iterdir():
            if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                _IMAGE_QUERY_IDS.add(p.stem)


_discover_image_ids()


def load_image_bytes(query_id: str) -> bytes | None:
    """
    Return raw image bytes for query_id if an image file exists, else None.
    Tries jpg, jpeg, png, webp in order. Reads in binary mode (rb).
    """
    for ext in ["jpg", "jpeg", "png", "webp"]:
        path = IMAGE_DIR / f"{query_id}.{ext}"
        if path.exists():
            return path.read_bytes()
    return None


# ── SagaEvalResult definition ─────────────────────────────────────────────────


@dataclass
class SagaEvalResult:
    query_id: str
    query: object                    # EvalQuery
    intent_output: dict              # {category, primary_query, brand}
    trust_results: list[dict]        # [{title, verdict, price_anomaly, replica_flag, brand_mismatch, trust_level, trust_score}, ...]
    sourced_offers: list             # list[Offer]
    ranked_offers: list              # list[RankedOffer]
    total_tokens: int
    duration_ms: float
    success: bool
    error: str | None = None
    has_image: bool = False          # True when image_bytes were passed to the saga


# ── Main entry points ─────────────────────────────────────────────────────────

async def run_evaluation(dry_run: bool = False) -> None:
    """
    Run the full evaluation pipeline.

    Parameters
    ----------
    dry_run : bool
        If True, only evaluates the first 5 queries and does not save results.
    """
    from backend.evaluation.dataset import QUERIES
    from backend.evaluation.eval_intent import evaluate_intent
    from backend.evaluation.eval_sourcing import evaluate_sourcing
    from backend.evaluation.eval_trust import evaluate_trust

    queries = QUERIES[:5] if dry_run else QUERIES
    mode_label = "DRY-RUN (5 queries)" if dry_run else f"FULL ({len(queries)} queries)"

    n_img_total = sum(1 for q in queries if q.query_id in _IMAGE_QUERY_IDS)
    n_txt_total = len(queries) - n_img_total

    print(f"\n{'='*60}")
    print(f"  AGENTIC PURCHASE EVALUATION (MULTIMODAL) — {mode_label}")
    print(f"  Image-assisted: {n_img_total}   Text-only: {n_txt_total}")
    print(f"  Started: {datetime.now(timezone.utc).isoformat()}")
    print(f"{'='*60}\n")

    # ── Build orchestrator and bus ────────────────────────────────────────────
    orchestrator, bus = _build_orchestrator()

    # ── Run each query ────────────────────────────────────────────────────────
    results: list[SagaEvalResult] = []

    for i, query in enumerate(queries):
        image_bytes = load_image_bytes(query.query_id)
        mode = "[IMG]" if image_bytes is not None else "[TXT]"
        print(f"[{i+1:2d}/{len(queries)}] {mode} {query.query_id}: {query.text[:50]}...")
        result = await _run_one_query(orchestrator, bus, query, image_bytes=image_bytes)
        status = "OK" if result.success else f"FAIL ({result.error or 'unknown'})"
        print(f"         -> {status}  | {result.duration_ms:.0f}ms | {result.total_tokens} tokens")
        results.append(result)

    n_success = sum(1 for r in results if r.success)
    n_fail    = len(results) - n_success
    print(f"\nCompleted: {n_success}/{len(results)} succeeded, {n_fail} failed\n")

    if n_success == 0:
        print("WARNING: No successful runs — metrics are not meaningful.")
        print("Check API keys and agent configuration.")
        return

    # ── Compute metrics ───────────────────────────────────────────────────────
    intent_m   = evaluate_intent(results)
    sourcing_m = evaluate_sourcing(results)
    trust_m    = evaluate_trust(results)

    # ── Latency and cost ──────────────────────────────────────────────────────
    successful  = [r for r in results if r.success]
    img_results = [r for r in successful if r.has_image]
    txt_results = [r for r in successful if not r.has_image]

    avg_latency_s     = sum(r.duration_ms for r in successful) / len(successful) / 1000
    avg_img_latency_s = (sum(r.duration_ms for r in img_results) / len(img_results) / 1000) if img_results else 0.0
    avg_txt_latency_s = (sum(r.duration_ms for r in txt_results) / len(txt_results) / 1000) if txt_results else 0.0
    avg_tokens        = sum(r.total_tokens for r in successful) / len(successful)
    # Blended cost: 85% assumed input at $5/1M + 15% assumed output at $15/1M.
    # Previous formula used $5/1M on all tokens, understating output-token cost.
    # Blended rate: 0.85 * 0.000005 + 0.15 * 0.000015 = 0.0000065
    _BLENDED_RATE  = 0.0000065
    avg_cost_usd   = avg_tokens * _BLENDED_RATE
    total_cost_usd = sum(r.total_tokens for r in successful) * _BLENDED_RATE

    # ── Load previous text-only baseline for comparison ───────────────────────
    prev_summary = _load_prev_summary()

    # ── Print report ──────────────────────────────────────────────────────────
    _print_report(
        intent_m, sourcing_m, trust_m,
        avg_latency_s, avg_img_latency_s, avg_txt_latency_s,
        avg_tokens, avg_cost_usd, total_cost_usd,
        n_queries=len(successful),
        n_img=len(img_results),
        n_txt=len(txt_results),
        prev_summary=prev_summary,
    )

    if dry_run:
        print("\n[Dry-run: results not saved]")
        return

    # ── Save results ──────────────────────────────────────────────────────────
    _save_results(
        results, intent_m, sourcing_m, trust_m,
        avg_latency_s, avg_tokens, avg_cost_usd, total_cost_usd,
        n_img=len(img_results), n_txt=len(txt_results),
    )


# ── Saga invocation ───────────────────────────────────────────────────────────

def _build_orchestrator():
    """
    Build a fully-wired OrchestratorAgent with all agents registered in the bus.
    This mirrors the lifespan() setup in backend/main.py.

    Eval-mode graph patches (applied before graph compilation):

      1. after_offer_selection → always returns "checkout" so the graph doesn't
         loop waiting for a human to pick an offer.

      2. after_ranking → always returns "await_offer_selection" so the graph
         never loops waiting for a tie-breaking answer from a human.

      3. node_checkout → replaced with a no-op that immediately marks the saga
         complete, avoiding Stripe / Redis calls that would fail without
         production credentials.

    Both patches are baked into a freshly compiled graph so they don't affect
    any production-mode OrchestratorAgent instance running in the same process.

    Returns (orchestrator, bus).
    """
    import backend.agents.orchestrator.agent as _orch_mod
    import backend.agents.orchestrator.graph as _graph_mod
    import backend.agents.orchestrator.nodes as _nodes_mod
    from backend.agents.bus import get_agent_bus
    from backend.agents.checkout.agent import CheckoutAgent
    from backend.agents.intent.agent import IntentAgent
    from backend.agents.orchestrator.agent import OrchestratorAgent
    from backend.agents.ranking.agent import RankingAgent
    from backend.agents.sourcing.agent import SourcingAgent
    from backend.agents.trust.agent import TrustAgent
    from backend.agents.vision.agent import VisionAgent
    from backend.models.saga import SagaStatus

    # ── Patch 1: after_offer_selection ────────────────────────────────────────
    # graph.py imports `after_offer_selection` by name at module load, so we
    # must patch the name in graph.py's namespace (not just in edges.py) so
    # that build_graph() picks up the eval version when the graph is recompiled.
    _orig_after_offer_selection = _graph_mod.after_offer_selection

    def _eval_after_offer_selection(state):
        return "checkout"  # skip human selection step

    _graph_mod.after_offer_selection = _eval_after_offer_selection

    # ── Patch 2: after_ranking ────────────────────────────────────────────────
    # In production, a near-tie triggers await_tie_breaking which loops back to
    # ranking until user provides a tie-breaking answer.  In eval mode there is
    # no user, so skip straight to await_offer_selection every time.
    _orig_after_ranking = _graph_mod.after_ranking

    def _eval_after_ranking(state):
        if state.get("terminal_error"):
            return "end_failed"
        return "await_offer_selection"  # skip tie-breaking in eval

    _graph_mod.after_ranking = _eval_after_ranking

    # ── Patch 3: node_checkout ────────────────────────────────────────────────
    # Same reasoning: patch graph.py's local reference to node_checkout.
    # The no-op marks the saga complete without hitting Stripe / Redis.
    _orig_node_checkout = _graph_mod.node_checkout

    async def _eval_node_checkout(state):
        return {"saga_status": SagaStatus.COMPLETE}

    _graph_mod.node_checkout = _eval_node_checkout

    # ── Force fresh graph compilation with the patched functions ──────────────
    _orch_mod._compiled_graph = None  # clear the module-level singleton

    # Use the global AgentBus singleton — node functions call get_agent_bus()
    # directly, so registrations must land in the same global instance that
    # nodes.py resolves at dispatch time.
    bus = get_agent_bus()
    bus.register(VisionAgent())
    bus.register(IntentAgent())
    bus.register(SourcingAgent())
    bus.register(TrustAgent())
    bus.register(RankingAgent())
    bus.register(CheckoutAgent())

    orchestrator = OrchestratorAgent(bus=bus)  # compiles graph with patched functions

    # ── Restore originals so re-runs/imports see the real functions ───────────
    _graph_mod.after_offer_selection = _orig_after_offer_selection
    _graph_mod.after_ranking         = _orig_after_ranking
    _graph_mod.node_checkout         = _orig_node_checkout

    return orchestrator, bus


async def _run_one_query(
    orchestrator,
    bus,
    query,
    image_bytes: bytes | None = None,
) -> SagaEvalResult:
    """
    Run one query through the full saga and return a SagaEvalResult.

    Never raises — failures are captured in result.success=False.

    Redis state persistence (set_saga_state / get_saga_state) is patched to a
    no-op for eval runs: the eval harness captures the final state directly from
    start_saga()'s return value and doesn't need Redis checkpointing.  This also
    avoids a JSON-serialization issue with Pydantic models in the initial state dict.
    """
    from unittest.mock import AsyncMock, patch

    from backend.evaluation.dataset import EvalQuery
    from backend.agents.trust.session1 import run_session1
    from backend.models.trust import TrustLevel

    saga_id   = str(uuid.uuid4())
    start     = time.monotonic()
    has_image = image_bytes is not None

    # No-op SSE emitter — eval doesn't need real-time streaming
    async def noop_emitter(event: object) -> None:  # noqa: ARG001
        pass

    # ── Redis patches ─────────────────────────────────────────────────────────
    # 1. Saga state: set_saga_state serialises Pydantic models via json.dumps
    #    (a latent bug) — patch to no-ops; eval captures state from return value.
    # 2. Vendor profile cache: TrustAgent calls get_cached_vendor_profile() which
    #    hits Redis.  Return a minimal profile dict (cache hit) so TrustAgent can
    #    score without calling the eBay API or a live Redis.
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
                session_id=f"eval-session-{saga_id[:8]}",
                user_id="eval-user",
                user_text=query.text,
                image_bytes=image_bytes,
                conversation_history=[],
                user_preferences=None,
                sse_emitter=noop_emitter,
            )
    except Exception as exc:
        duration_ms = (time.monotonic() - start) * 1000
        # Pop tokens even on failure so the bus accumulator doesn't leak
        bus.get_saga_tokens(saga_id)
        return SagaEvalResult(
            query_id=query.query_id,
            query=query,
            intent_output={},
            trust_results=[],
            sourced_offers=[],
            ranked_offers=[],
            total_tokens=0,
            duration_ms=round(duration_ms, 1),
            success=False,
            error=str(exc)[:200],
            has_image=has_image,
        )

    duration_ms = (time.monotonic() - start) * 1000

    # ── Token aggregation (pops from bus — call exactly once per saga) ────────
    tokens_by_agent = bus.get_saga_tokens(saga_id)
    total_tokens    = sum(tokens_by_agent.values())

    # ── Extract intent output ─────────────────────────────────────────────────
    parsed_intent  = final_state.get("parsed_intent")
    vision_attrs   = final_state.get("vision_detected_attributes") or {}

    # VisionAgent stores brand as "brand_if_visible" inside detected_attributes
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

    # ── Extract scored / ranked offers ────────────────────────────────────────
    scored_offers: list = final_state.get("scored_offers") or []
    ranked_offers: list = final_state.get("ranked_offers") or []
    all_offers:    list = final_state.get("all_offers") or []

    # ── Build trust_results with Session-1 signals (no LLM, pure Python) ─────
    trust_results = _build_trust_results(scored_offers, vision_attrs)

    return SagaEvalResult(
        query_id=query.query_id,
        query=query,
        intent_output=intent_output,
        trust_results=trust_results,
        sourced_offers=all_offers,
        ranked_offers=ranked_offers,
        total_tokens=total_tokens,
        duration_ms=round(duration_ms, 1),
        success=True,
        has_image=has_image,
    )


def _build_trust_results(scored_offers: list, vision_attrs: dict) -> list[dict]:
    """
    Build the trust_results list from ScoredOffer objects.

    For each offer:
      - verdict is derived from TrustLevel (HIGH_RISK → "HIGH_RISK", else "AUTHENTIC")
      - Session-1 signals are re-computed deterministically from the offer data
    """
    from backend.agents.trust.session1 import run_session1
    from backend.models.trust import TrustLevel

    if not scored_offers:
        return []

    # Run Session 1 on the scored offers to get structured signals for eval
    try:
        s1 = run_session1(offers=scored_offers, vision_attributes=vision_attrs)
        signal_map = {sig.offer_id: sig for sig in s1.signals}
    except Exception:
        signal_map = {}

    results = []
    for offer in scored_offers:
        sig = signal_map.get(getattr(offer, "offer_id", ""), None)

        # Map TrustLevel → eval verdict
        trust_level = getattr(getattr(offer, "trust_score", None), "level", None)
        if trust_level == TrustLevel.HIGH_RISK:
            verdict = "HIGH_RISK"
        else:
            verdict = "AUTHENTIC"

        results.append({
            "offer_id":      getattr(offer, "offer_id", ""),
            "title":         getattr(offer, "title", ""),
            "verdict":       verdict,
            "trust_level":   trust_level.value if trust_level else "UNKNOWN",
            "trust_score":   getattr(getattr(offer, "trust_score", None), "score", 0.0),
            # Session-1 signals — used by eval_trust ground-truth logic
            "price_anomaly":  bool(sig.price_anomaly)  if sig else False,
            "replica_flag":   bool(sig.replica_flag)   if sig else False,
            "brand_mismatch": bool(sig.brand_mismatch) if sig else False,
        })

    return results


# ── Report printing ───────────────────────────────────────────────────────────

def _print_report(
    intent_m,
    sourcing_m,
    trust_m,
    avg_latency_s: float,
    avg_img_latency_s: float,
    avg_txt_latency_s: float,
    avg_tokens: float,
    avg_cost_usd: float,
    total_cost_usd: float,
    n_queries: int,
    n_img: int,
    n_txt: int,
    prev_summary: dict | None = None,
) -> None:
    W = 56

    print("=" * W)
    print("  AGENTIC PURCHASE EVALUATION REPORT (MULTIMODAL)")
    print("=" * W)
    print(f"Queries evaluated: {n_queries}")
    print(f"  Image-assisted: {n_img}   Text-only: {n_txt}")
    print()

    print("INTENT MODELING")
    print(f"  Combined F1:               {intent_m.f1:.4f}")
    if n_img > 0:
        print(f"  Image-mode F1  (n={n_img:<3d}):   {intent_m.image_f1:.4f}  [brand + category + product_type]")
    if n_txt > 0:
        print(f"  Text-mode  F1  (n={n_txt:<3d}):   {intent_m.text_f1:.4f}  [category + product_type only]")
    if n_img > 0:
        print(f"  Brand accuracy (image queries):    {intent_m.brand_correct_count}/{intent_m.brand_extractable_count} extracted")
    print(f"  Category accuracy (all):       {intent_m.n_correct_category}/{n_queries}")
    print(f"  Product type accuracy (all):   {intent_m.n_correct_product_type}/{n_queries}")
    print()

    print("SOURCING QUALITY")
    print(f"  NDCG@3: {sourcing_m.ndcg_at_3:.4f}")
    print(f"  MRR:    {sourcing_m.mrr:.4f}")
    print(f"  Avg offers returned: {sourcing_m.avg_offers_returned:.1f}")
    print()

    print("TRUST EVALUATION")
    print(f"  Precision: {trust_m.precision:.4f}   Recall: {trust_m.recall:.4f}")
    print(f"  VVR (Vendor Verification Rate):     {trust_m.vvr:.4f}")
    print(f"  FVDR (False Vendor Detection Rate): {trust_m.fvdr:.4f}")
    print(f"  Offers evaluated: {trust_m.n_offers_evaluated}")
    print(f"  Authentic: {trust_m.n_authentic}   Suspicious/High-risk: {trust_m.n_suspicious}")
    print(f"  TP={trust_m.tp}  TN={trust_m.tn}  FP={trust_m.fp}  FN={trust_m.fn}")
    print()

    print("SYSTEM PERFORMANCE")
    if n_img > 0:
        print(f"  Avg latency (image queries): {avg_img_latency_s:.1f}s")
    if n_txt > 0:
        print(f"  Avg latency (text  queries): {avg_txt_latency_s:.1f}s")
    print(f"  Avg latency (overall):       {avg_latency_s:.1f}s")
    print(f"  Avg tokens per run:          {avg_tokens:.0f}")
    print(f"  Avg cost per run:            ${avg_cost_usd:.6f}")
    print(f"  Total evaluation cost:       ${total_cost_usd:.4f}")

    # ── Comparison to previous text-only baseline ─────────────────────────────
    if prev_summary:
        print()
        print("COMPARISON TO PREVIOUS RUN (text-only baseline)")
        _cmp("  NDCG@3", prev_summary.get("sourcing", {}).get("ndcg_at_3"), sourcing_m.ndcg_at_3)
        _cmp("  MRR   ", prev_summary.get("sourcing", {}).get("mrr"),       sourcing_m.mrr)
        _cmp("  F1    ", prev_summary.get("intent", {}).get("f1"),          intent_m.f1)

    print("=" * W)


def _cmp(label: str, prev: float | None, curr: float) -> None:
    if prev is None:
        print(f"{label}:  (no baseline)  ->  {curr:.4f}")
        return
    delta = curr - prev
    arrow = "+" if delta >= 0 else ""
    print(f"{label}:  {prev:.4f}  ->  {curr:.4f}  ({arrow}{delta:+.4f})")


# ── Previous summary loader ───────────────────────────────────────────────────

def _load_prev_summary() -> dict | None:
    """Load the most recent text-only eval_summary.json if it exists."""
    summary_path = Path(__file__).parent / "results" / "eval_summary.json"
    if summary_path.exists():
        try:
            return json.loads(summary_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None


# ── Result serialisation ──────────────────────────────────────────────────────

def _save_results(
    results: list,
    intent_m,
    sourcing_m,
    trust_m,
    avg_latency_s: float,
    avg_tokens: float,
    avg_cost_usd: float,
    total_cost_usd: float,
    n_img: int,
    n_txt: int,
) -> None:
    out_dir = Path(__file__).parent / "results"
    out_dir.mkdir(exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    # ── Full results (per-query detail) ───────────────────────────────────────
    full_data = []
    for r in results:
        full_data.append({
            "query_id":     r.query_id,
            "query_text":   r.query.text,
            "category":     r.query.category,
            "has_image":    r.has_image,
            "success":      r.success,
            "error":        r.error,
            "duration_ms":  r.duration_ms,
            "total_tokens": r.total_tokens,
            "intent_output": r.intent_output,
            "n_sourced_offers": len(r.sourced_offers),
            "n_ranked_offers":  len(r.ranked_offers),
            "n_trust_results":  len(r.trust_results),
        })

    full_path = out_dir / f"eval_results_multimodal_{ts}.json"
    with open(full_path, "w", encoding="utf-8") as f:
        json.dump({"timestamp": ts, "evaluation_mode": "multimodal_20img_30txt", "runs": full_data}, f, indent=2)

    # ── Multimodal summary ────────────────────────────────────────────────────
    summary = {
        "timestamp": ts,
        "evaluation_mode": "multimodal_20img_30txt",
        "n_queries":   len(results),
        "n_success":   sum(1 for r in results if r.success),
        "n_image":     n_img,
        "n_text":      n_txt,
        "intent": {
            "f1":          intent_m.f1,
            "image_f1":    intent_m.image_f1,
            "text_f1":     intent_m.text_f1,
            "precision":   intent_m.precision,
            "recall":      intent_m.recall,
        },
        "sourcing": {
            "ndcg_at_3": sourcing_m.ndcg_at_3,
            "mrr":       sourcing_m.mrr,
        },
        "trust": {
            "precision": trust_m.precision,
            "recall":    trust_m.recall,
            "vvr":       trust_m.vvr,
            "fvdr":      trust_m.fvdr,
        },
        "performance": {
            "avg_latency_s":  round(avg_latency_s, 2),
            "avg_tokens":     round(avg_tokens, 1),
            "avg_cost_usd":   round(avg_cost_usd, 6),
            "total_cost_usd": round(total_cost_usd, 4),
        },
    }

    summary_path = out_dir / "eval_summary_multimodal.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(f"\nResults saved to: {full_path}")
    print(f"Summary saved to: {summary_path}")


# ── CLI entry point ───────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Agentic Purchase evaluation (multimodal: 20 image + 30 text queries)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Evaluate only the first 5 queries (no results saved)",
    )
    args = parser.parse_args()
    asyncio.run(run_evaluation(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
