"""
Trust injection evaluation — confusion matrix via synthetic offer injection.

This module evaluates the two-session trust pipeline (Session 1 heuristics +
Session 2 LLM) against 115 labeled synthetic offers whose ground truth is known.

Pipeline per labeled offer
--------------------------
1. Build a mini batch: 9 filler offers at normal prices + the synthetic offer.
   (Fillers create a realistic price distribution so Session 1's Z-score has
   batch_stdev > 0, which is required for price_anomaly to fire.)
2. Run session1.run_session1() on the full mini batch.
3. Extract the synthetic offer's OfferSignals from the S1 result.
4. Wrap just that signal in a Session1Result — so Session 2 makes exactly
   1 LLM call per labeled offer.
5. Run session2.run_session2() → get the verdict for the synthetic offer.
6. Map verdict → SUSPICIOUS (HIGH_RISK or SUSPICIOUS) / AUTHENTIC.
7. Compare to ground_truth → TP / TN / FP / FN.

This approach is completely standalone: it does not re-run the full saga,
does not touch Redis, Stripe, eBay, or the orchestrator.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Callable, Awaitable

from backend.agents.trust.session1 import Session1Result, run_session1
from backend.agents.trust.session2 import run_session2
from backend.evaluation.dataset import EvalQuery, QUERY_BY_ID
from backend.evaluation.synthetic_offers import LabeledOffer, make_filler_offers
from backend.models.offer import Offer


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class TrustInjectionMetrics:
    precision: float
    recall: float
    vvr: float      # Vendor Verification Rate  = TN / (TN + FN)
    fvdr: float     # False Vendor Detection Rate = FP / (FP + TN)

    n_evaluated: int
    n_suspicious: int
    n_authentic: int

    tp: int
    tn: int
    fp: int
    fn: int

    # Per-injection-type detection counts (numerator over 15 or 40)
    replica_detected:   int = 0    # TP among replica_keyword offers (15)
    novel_detected:     int = 0    # TP among novel_vocabulary offers (15, LLM-only test)
    price_detected:     int = 0    # TP among price_anomaly offers (15)
    brand_detected:     int = 0    # TP among brand_mismatch offers (15)
    combined_detected:  int = 0    # TP among combined offers (15)
    authentic_cleared:  int = 0    # TN among authentic control offers (40)

    # LLM usage summary
    total_llm_calls:   int = 0
    total_input_tokens:  int = 0
    total_output_tokens: int = 0
    estimated_cost_usd:  float = 0.0
    duration_s: float = 0.0

    # Per-offer detail (for saved JSON)
    details: list[dict] = field(default_factory=list)


# ── Public entry point ────────────────────────────────────────────────────────

async def evaluate_trust_injection(
    labeled_offers: list[LabeledOffer],
) -> TrustInjectionMetrics:
    """
    Run the two-session trust pipeline on all labeled_offers.

    Parameters
    ----------
    labeled_offers:
        115 LabeledOffer objects from synthetic_offers.generate_labeled_offers().

    Returns
    -------
    TrustInjectionMetrics with full confusion matrix and per-type breakdown.
    """
    llm_caller, token_counter = _build_llm_caller()

    t_start = time.monotonic()

    tp = tn = fp = fn = 0
    replica_det = novel_det = price_det = brand_det = combined_det = authentic_clr = 0
    details: list[dict] = []

    total = len(labeled_offers)
    for idx, lo in enumerate(labeled_offers, start=1):
        query = QUERY_BY_ID.get(lo.query_id)
        if query is None:
            continue  # defensive — all query_ids should exist

        # ── Build context for vision_attributes ───────────────────────────────
        expected_brand = (query.expected_brand or "").lower()
        vision_attrs: dict = {"brand": expected_brand} if expected_brand else {}

        # ── Build mini batch: fillers (9) + synthetic offer (1) ───────────────
        # 9 fillers ensure stdev > 0 and the cheap offer yields a genuine z-score
        fillers = make_filler_offers(query.category, n=9)
        batch: list[Offer] = fillers + [lo.offer]

        # ── Session 1: deterministic signals (full batch for price context) ────
        s1_full = run_session1(offers=batch, vision_attributes=vision_attrs)

        # Extract only the synthetic offer's signal
        synth_signal = next(
            (s for s in s1_full.signals if s.offer_id == lo.offer.offer_id),
            None,
        )
        if synth_signal is None:
            # Shouldn't happen; treat as missed
            fn += 1
            details.append(_make_detail(lo, "AUTHENTIC", "signal_not_found"))
            continue

        # ── Session 2: one LLM call for the synthetic offer only ──────────────
        s1_focused = Session1Result(
            signals=[synth_signal],
            batch_mean_price=s1_full.batch_mean_price,
            batch_stdev_price=s1_full.batch_stdev_price,
            currency=s1_full.currency,
        )

        product_description = query.text

        try:
            s2_result = await run_session2(
                s1_result=s1_focused,
                offers=[lo.offer],
                product_description=product_description,
                llm_caller=llm_caller,
            )
            verdict_obj = s2_result.verdicts[0] if s2_result.verdicts else None
            verdict     = verdict_obj.verdict if verdict_obj else "AUTHENTIC"
            reasoning   = verdict_obj.reasoning if verdict_obj else ""
        except Exception as exc:
            verdict   = "AUTHENTIC"
            reasoning = f"ERROR: {exc}"

        # ── Map verdict → binary label ─────────────────────────────────────────
        predicted = "SUSPICIOUS" if verdict.upper() in ("SUSPICIOUS", "HIGH_RISK") else "AUTHENTIC"
        gt        = lo.ground_truth

        # ── Confusion matrix ───────────────────────────────────────────────────
        if gt == "SUSPICIOUS" and predicted == "SUSPICIOUS":
            tp += 1
            if lo.injection_type == "replica_keyword":   replica_det  += 1
            if lo.injection_type == "novel_vocabulary":  novel_det    += 1
            if lo.injection_type == "price_anomaly":     price_det    += 1
            if lo.injection_type == "brand_mismatch":    brand_det    += 1
            if lo.injection_type == "combined":          combined_det += 1
        elif gt == "AUTHENTIC" and predicted == "AUTHENTIC":
            tn += 1
            if lo.injection_type == "authentic":         authentic_clr += 1
        elif gt == "AUTHENTIC" and predicted == "SUSPICIOUS":
            fp += 1
        elif gt == "SUSPICIOUS" and predicted == "AUTHENTIC":
            fn += 1

        details.append(_make_detail(
            lo, predicted, reasoning,
            price_anomaly=synth_signal.price_anomaly,
            replica_flag=synth_signal.replica_flag,
            brand_mismatch=synth_signal.brand_mismatch,
            risk_score=synth_signal.risk_score,
            active_flags=synth_signal.active_risk_flags,
        ))

        if idx % 10 == 0:
            print(f"  [{idx:3d}/{total}] TP={tp} TN={tn} FP={fp} FN={fn} "
                  f"| calls={token_counter['calls']}")

    duration_s = time.monotonic() - t_start

    # ── Aggregate metrics ──────────────────────────────────────────────────────
    n_suspicious = tp + fn
    n_authentic  = tn + fp
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    vvr       = tn / (tn + fn) if (tn + fn) > 0 else 0.0
    fvdr      = fp / (fp + tn) if (fp + tn) > 0 else 0.0

    # Cost estimate: gpt-4o pricing (~$5/$15 per 1M in/out tokens)
    inp_tok = token_counter["input"]
    out_tok = token_counter["output"]
    if inp_tok == 0 and token_counter["calls"] > 0:
        # Fallback estimate if usage_metadata unavailable
        inp_tok = token_counter["calls"] * 600
        out_tok = token_counter["calls"] * 120
    estimated_cost = inp_tok * 5e-6 + out_tok * 15e-6

    return TrustInjectionMetrics(
        precision=round(precision, 4),
        recall=round(recall, 4),
        vvr=round(vvr, 4),
        fvdr=round(fvdr, 4),
        n_evaluated=len(details),
        n_suspicious=n_suspicious,
        n_authentic=n_authentic,
        tp=tp, tn=tn, fp=fp, fn=fn,
        replica_detected=replica_det,
        novel_detected=novel_det,
        price_detected=price_det,
        brand_detected=brand_det,
        combined_detected=combined_det,
        authentic_cleared=authentic_clr,
        total_llm_calls=token_counter["calls"],
        total_input_tokens=inp_tok,
        total_output_tokens=out_tok,
        estimated_cost_usd=round(estimated_cost, 4),
        duration_s=round(duration_s, 1),
        details=details,
    )


# ── Private helpers ───────────────────────────────────────────────────────────

def _build_llm_caller():
    """
    Return (llm_caller, token_counter).

    llm_caller: async (system_prompt, user_prompt) -> str
    token_counter: mutable dict tracking {"calls", "input", "output"}
    """
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI
    from backend.core.config import get_settings

    settings = get_settings()
    llm = ChatOpenAI(
        model=settings.openai_model_executor,
        api_key=settings.openai_api_key,
        temperature=0,
    )

    counter: dict[str, int] = {"calls": 0, "input": 0, "output": 0}

    async def caller(system_prompt: str, user_prompt: str) -> str:
        counter["calls"] += 1
        response = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ])
        # Collect token usage when available
        meta = getattr(response, "usage_metadata", None) or {}
        counter["input"]  += int(meta.get("input_tokens", 0))
        counter["output"] += int(meta.get("output_tokens", 0))
        return response.content

    return caller, counter


def _make_detail(
    lo: LabeledOffer,
    predicted: str,
    reasoning: str,
    price_anomaly: bool = False,
    replica_flag: bool = False,
    brand_mismatch: bool = False,
    risk_score: float = 0.0,
    active_flags: list[str] | None = None,
) -> dict:
    return {
        "offer_id":       lo.offer.offer_id,
        "query_id":       lo.query_id,
        "injection_type": lo.injection_type,
        "ground_truth":   lo.ground_truth,
        "predicted":      predicted,
        "correct":        lo.ground_truth == predicted,
        "offer_title":    lo.offer.title,
        "offer_price":    lo.offer.price.amount,
        "s1_price_anomaly":  price_anomaly,
        "s1_replica_flag":   replica_flag,
        "s1_brand_mismatch": brand_mismatch,
        "s1_risk_score":     risk_score,
        "s1_active_flags":   active_flags or [],
        "s2_reasoning":      reasoning,
    }
