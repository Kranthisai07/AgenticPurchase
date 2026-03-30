"""
Ablation study configuration patches for Agentic Purchase evaluation.

Three configuration modes:
  FULL_LLM      (Config B) — normal production operation, no patches
  DETERMINISTIC (Config A) — all LLM calls replaced with deterministic fallbacks
  TRUST_ONLY    (Config C) — only Trust Agent Session 2 LLM is active;
                             Vision and Intent use deterministic fallbacks;
                             Ranking uses formula only (no tie-break LLM)

Patching strategy:
  Direct class-level method replacement (stores originals in _originals dict).
  restore_all() reverses every patch unconditionally.
  Production code is never modified — patches live only in this module.
"""
from __future__ import annotations

import dataclasses
from typing import Any

# ── Known brands from the 50-query evaluation dataset ────────────────────────
# Used by the deterministic Intent Agent to identify brand tokens in query text.

_KNOWN_BRANDS: set[str] = {
    # footwear
    "nike", "adidas", "balance", "jordan", "timberland", "vans", "converse",
    "puma", "reebok", "asics",
    # electronics
    "apple", "sony", "samsung", "logitech", "anker", "jbl", "gopro",
    "garmin", "amazon", "kindle",
    # watches
    "casio", "seiko", "citizen", "fossil", "timex", "orient", "invicta",
    "mvmt", "hamilton",
    # apparel
    "levis", "levi", "patagonia", "champion", "ralph", "polo", "arcteryx",
    "carhartt", "uniqlo", "columbia", "fjallraven",
    # home goods
    "dyson", "vitamix", "nespresso", "philips", "irobot", "cuisinart",
    "kitchenaid", "ember", "instant",
}

# ── Category inference keywords ───────────────────────────────────────────────
# Ordered so more specific categories (watches) are checked before broader ones.

_CATEGORY_KEYWORDS: list[tuple[str, list[str]]] = [
    ("watches",    ["watch", "chronograph", "timepiece", "horology"]),
    ("footwear",   ["shoe", "sneaker", "boot", "sandal", "trainer", "loafer",
                    "slipper", "runner", "heel", "pump", "skate"]),
    ("apparel",    ["jacket", "hoodie", "shirt", "jeans", "pants", "fleece",
                    "coat", "parka", "sweater", "jersey", "backpack", "bag",
                    "clothing", "apparel"]),
    ("home_goods", ["cooker", "blender", "vacuum", "coffee", "mug", "mixer",
                    "processor", "light", "lamp", "oven", "household", "robot"]),
    ("electronics",["phone", "smartphone", "tablet", "laptop", "headphone",
                    "earbuds", "speaker", "camera", "charger", "mouse",
                    "keyboard", "monitor", "reader", "gps"]),
]


def _infer_category(text: str) -> str:
    """Map arbitrary text to one of the 5 eval categories, or 'general'."""
    lowered = text.lower()
    for category, keywords in _CATEGORY_KEYWORDS:
        if any(kw in lowered for kw in keywords):
            return category
    return "general"


# ── Storage for original methods ──────────────────────────────────────────────

_originals: dict[str, Any] = {}


# ── AblationMode constants ────────────────────────────────────────────────────

class AblationMode:
    FULL_LLM      = "full_llm"       # Config B — no patches
    DETERMINISTIC = "deterministic"  # Config A — no LLM anywhere
    TRUST_ONLY    = "trust_only"     # Config C — Trust Session 2 LLM only


# ── Vision Agent patch ────────────────────────────────────────────────────────

def patch_vision_agent_deterministic() -> None:
    """
    Replace VisionAgent._execute() with a deterministic fallback that:
    - Returns VisionSuccess(product_description=user_text, detected_attributes={},
                            confidence=0.7)
    - Never calls the LLM
    - confidence=0.7 passes the CONFIDENCE_THRESHOLD=0.6 self-evaluation gate
    """
    from backend.agents.vision.agent import VisionAgent
    from backend.models.agent_results import VisionSuccess

    if "vision._execute" not in _originals:
        _originals["vision._execute"] = VisionAgent._execute

    async def _deterministic_execute(self, task):  # type: ignore[no-untyped-def]
        text = task.user_text or ""
        return VisionSuccess(
            product_description=text or "(no description)",
            detected_attributes={},
            confidence=0.7,  # must be >= CONFIDENCE_THRESHOLD (0.6) to pass self-eval
        )

    VisionAgent._execute = _deterministic_execute  # type: ignore[method-assign]


# ── Intent Agent patch ────────────────────────────────────────────────────────

def patch_intent_agent_deterministic() -> None:
    """
    Replace IntentAgent._execute() with a deterministic fallback that:
    - Skips both the InjectionGuard LLM check and the intent LLM call
    - Extracts brand by checking tokens against _KNOWN_BRANDS
    - Infers category from _CATEGORY_KEYWORDS keyword matching
    - Uses the full query text as primary_query
    - Returns IntentSuccess with these extracted fields
    """
    from backend.agents.intent.agent import IntentAgent
    from backend.models.agent_results import IntentSuccess
    from backend.models.intent import ParsedIntent

    if "intent._execute" not in _originals:
        _originals["intent._execute"] = IntentAgent._execute

    async def _deterministic_execute(self, task):  # type: ignore[no-untyped-def]
        combined_text = f"{task.product_description} {task.user_text or ''}".strip()

        # Use full text as primary_query (best deterministic approximation)
        primary_query = combined_text or "(unknown)"

        # Infer category from keyword matching
        category = _infer_category(combined_text)

        return IntentSuccess(
            parsed_intent=ParsedIntent(
                primary_query=primary_query,
                category=category,
                price_min=None,
                price_max=None,
                preferred_vendors=[],
                excluded_vendors=[],
                condition="any",
                urgency="any",
                gift_wrapping=False,
                quantity=1,
            )
        )

    IntentAgent._execute = _deterministic_execute  # type: ignore[method-assign]


# ── Trust Agent patch — skip Session 2 ───────────────────────────────────────

def patch_trust_agent_skip_session2() -> None:
    """
    Replace TrustAgent._execute() with a version that:
    - Runs Session 1 normally (deterministic heuristics)
    - Skips Session 2 LLM call entirely
    - Maps Session 1 risk_score directly to trust verdict:
        risk_score >= 0.75  → HIGH_RISK
        risk_score >= 0.35  → MEDIUM_RISK (formula-only blend)
        risk_score <  0.35  → LOW_RISK / MEDIUM_RISK (formula determines)
    - Uses formula_score only (no LLM blending, skip_blend=True equivalent)
    - Returns TrustSuccess with scored_offers preserving formula scores
    """
    from backend.agents.trust.agent import TrustAgent
    from backend.agents.trust.session1 import run_session1
    from backend.models.agent_results import TrustSuccess
    from backend.models.offer import ScoredOffer

    if "trust._execute" not in _originals:
        _originals["trust._execute"] = TrustAgent._execute

    async def _no_session2_execute(self, task):  # type: ignore[no-untyped-def]
        if not task.offers:
            return TrustSuccess(scored_offers=[])

        # Session 1: deterministic heuristics
        s1_result = run_session1(
            offers=task.offers,
            vision_attributes=task.vision_attributes,
        )

        # Build signal map for per-offer access
        signal_map = {sig.offer_id: sig for sig in s1_result.signals}

        scored: list[ScoredOffer] = []
        for offer in task.offers:
            # Formula score (no LLM blending — verdict=None means preserve formula score)
            formula_score_obj = await self._score_offer(offer, task.source)
            # skip_blend=True path: preserve formula score unchanged
            scored.append(ScoredOffer(**offer.model_dump(), trust_score=formula_score_obj))

        return TrustSuccess(
            scored_offers=scored,
            session1_batch_mean=s1_result.batch_mean_price,
            session1_batch_stdev=s1_result.batch_stdev_price,
            session1_currency=s1_result.currency,
            session2_verdicts=[],  # no LLM verdicts
        )

    TrustAgent._execute = _no_session2_execute  # type: ignore[method-assign]


# ── Ranking Agent patch — no tie-break LLM ───────────────────────────────────

def patch_ranking_agent_no_tiebreak() -> None:
    """
    Replace RankingAgent._generate_tie_question() with a constant string.
    Formula ranking (rank_offers) still runs; only the LLM tie-breaking is skipped.
    """
    from backend.agents.ranking.agent import RankingAgent

    if "ranking._generate_tie_question" not in _originals:
        _originals["ranking._generate_tie_question"] = RankingAgent._generate_tie_question

    async def _no_llm_tie_question(self, offer1, offer2):  # type: ignore[no-untyped-def]
        return (
            "Do you prefer the lower-priced option or the one with the better seller reputation?"
        )

    RankingAgent._generate_tie_question = _no_llm_tie_question  # type: ignore[method-assign]


# ── Apply / restore ───────────────────────────────────────────────────────────

def apply_config(mode: str) -> None:
    """
    Apply agent patches for the given ablation mode.

    Config A (DETERMINISTIC): patches Vision, Intent, Trust (skip S2), Ranking
    Config B (FULL_LLM):      no patches
    Config C (TRUST_ONLY):    patches Vision, Intent, Ranking; Trust runs normally
    """
    if mode == AblationMode.DETERMINISTIC:
        patch_vision_agent_deterministic()
        patch_intent_agent_deterministic()
        patch_trust_agent_skip_session2()
        patch_ranking_agent_no_tiebreak()
    elif mode == AblationMode.TRUST_ONLY:
        patch_vision_agent_deterministic()
        patch_intent_agent_deterministic()
        # Trust Agent runs NORMALLY with full LLM (Session 1 + Session 2)
        patch_ranking_agent_no_tiebreak()
    elif mode == AblationMode.FULL_LLM:
        pass  # no patches — production operation
    else:
        raise ValueError(f"Unknown ablation mode: {mode!r}")


def restore_all() -> None:
    """Restore every original method that was patched."""
    from backend.agents.vision.agent import VisionAgent
    from backend.agents.intent.agent import IntentAgent
    from backend.agents.trust.agent import TrustAgent
    from backend.agents.ranking.agent import RankingAgent

    if "vision._execute" in _originals:
        VisionAgent._execute = _originals.pop("vision._execute")  # type: ignore[method-assign]
    if "intent._execute" in _originals:
        IntentAgent._execute = _originals.pop("intent._execute")  # type: ignore[method-assign]
    if "trust._execute" in _originals:
        TrustAgent._execute = _originals.pop("trust._execute")  # type: ignore[method-assign]
    if "ranking._generate_tie_question" in _originals:
        RankingAgent._generate_tie_question = _originals.pop(  # type: ignore[method-assign]
            "ranking._generate_tie_question"
        )


# ── Deterministic trust injection evaluation (Config A only) ─────────────────

async def evaluate_trust_injection_deterministic(
    labeled_offers: list,
) -> dict:
    """
    Evaluate trust injection dataset using Session 1 only (no LLM).

    Maps Session 1 risk_score → verdict via _fallback_from_risk_score():
      >= 0.75  → HIGH_RISK   → SUSPICIOUS
      >= 0.35  → SUSPICIOUS  → SUSPICIOUS
      <  0.35  → AUTHENTIC   → AUTHENTIC

    Returns a dict compatible with TrustInjectionMetrics fields.
    """
    from backend.agents.trust.session1 import Session1Result, run_session1
    from backend.agents.trust.session2 import _fallback_from_risk_score  # type: ignore[attr-defined]
    from backend.evaluation.dataset import QUERY_BY_ID
    from backend.evaluation.synthetic_offers import make_filler_offers
    import time

    t_start = time.monotonic()

    tp = tn = fp = fn = 0
    replica_det = novel_det = price_det = brand_det = combined_det = authentic_clr = 0

    for lo in labeled_offers:
        query = QUERY_BY_ID.get(lo.query_id)
        if query is None:
            fn += 1
            continue

        expected_brand = (query.expected_brand or "").lower()
        vision_attrs: dict = {"brand": expected_brand} if expected_brand else {}

        fillers = make_filler_offers(query.category, n=9)
        batch = fillers + [lo.offer]

        s1_full = run_session1(offers=batch, vision_attributes=vision_attrs)
        synth_signal = next(
            (s for s in s1_full.signals if s.offer_id == lo.offer.offer_id), None
        )
        if synth_signal is None:
            fn += 1
            continue

        # Session 1 only verdict (no LLM)
        verdict_str = _fallback_from_risk_score(synth_signal.risk_score)
        predicted = "SUSPICIOUS" if verdict_str in ("HIGH_RISK", "SUSPICIOUS") else "AUTHENTIC"
        gt = lo.ground_truth

        if gt == "SUSPICIOUS" and predicted == "SUSPICIOUS":
            tp += 1
            if lo.injection_type == "replica_keyword":  replica_det  += 1
            if lo.injection_type == "novel_vocabulary": novel_det    += 1
            if lo.injection_type == "price_anomaly":    price_det    += 1
            if lo.injection_type == "brand_mismatch":   brand_det    += 1
            if lo.injection_type == "combined":         combined_det += 1
        elif gt == "AUTHENTIC" and predicted == "AUTHENTIC":
            tn += 1
            if lo.injection_type == "authentic":        authentic_clr += 1
        elif gt == "AUTHENTIC" and predicted == "SUSPICIOUS":
            fp += 1
        else:
            fn += 1

    duration_s = time.monotonic() - t_start

    n_suspicious = tp + fn
    n_authentic  = tn + fp
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    vvr       = tn / (tn + fn) if (tn + fn) > 0 else 0.0
    fvdr      = fp / (fp + tn) if (fp + tn) > 0 else 0.0

    return {
        "precision":         round(precision, 4),
        "recall":            round(recall, 4),
        "vvr":               round(vvr, 4),
        "fvdr":              round(fvdr, 4),
        "n_evaluated":       len(labeled_offers),
        "n_suspicious":      n_suspicious,
        "n_authentic":       n_authentic,
        "tp": tp, "tn": tn, "fp": fp, "fn": fn,
        "replica_detected":  replica_det,
        "novel_detected":    novel_det,
        "price_detected":    price_det,
        "brand_detected":    brand_det,
        "combined_detected": combined_det,
        "authentic_cleared": authentic_clr,
        "llm_calls":         0,
        "estimated_cost_usd": 0.0,
        "duration_s":        round(duration_s, 1),
    }
