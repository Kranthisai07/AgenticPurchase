"""
TrustAgent — two-session authenticity evaluation pipeline.

Session 1 (deterministic, no I/O):
  Runs run_session1() to compute price Z-scores, replica keyword flags,
  brand-metadata consistency, and dimensional/weight anomaly checks
  for every offer in the batch.

Session 2 (LLM reasoning):
  Runs run_session2() to call the LLM once per offer, synthesising
  Session 1 signals into a structured authenticity verdict:
    AUTHENTIC | SUSPICIOUS | HIGH_RISK + confidence + reasoning

Score blending:
  blended = 0.4 * formula_score_norm + 0.6 * llm_component
    where formula_score_norm = formula_score / 100
    and   llm_component      = confidence       if verdict == AUTHENTIC
                             = 1 - confidence   otherwise

If the LLM is unavailable (no API key / test mode), Session 2 falls back to
the heuristic risk_score to produce a verdict, preserving saga continuity.

Sources: ebay, serpapi
"""
import dataclasses
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from backend.agents.base import BaseAgent
from backend.agents.trust.scorer import calculate_trust_score
from backend.agents.trust.session1 import run_session1
from backend.agents.trust.session2 import OfferVerdict, run_session2
from backend.core.config import get_settings
from backend.core.redis import cache_vendor_profile, get_cached_vendor_profile
from backend.integrations.ebay.client import EbayClient
from backend.models.agent_messages import AgentType
from backend.models.agent_results import TrustSuccess
from backend.models.agent_tasks import TrustTask
from backend.models.offer import Offer, ScoredOffer
from backend.models.trust import TrustLevel, TrustScore, TrustSignals

# Blending weights (must sum to 1.0)
_FORMULA_WEIGHT = 0.4
_LLM_WEIGHT     = 0.6


class TrustAgent(BaseAgent):
    agent_type = AgentType.TRUST
    timeout = 20  # raised from 15 to accommodate Session 2 LLM calls

    def __init__(
        self,
        ebay_client: EbayClient | None = None,
        llm: Any | None = None,
    ) -> None:
        settings = get_settings()
        _llm = llm or ChatOpenAI(
            model=settings.openai_model_executor,
            api_key=settings.openai_api_key,
            temperature=0,
        )
        super().__init__(llm=_llm)
        self._ebay = ebay_client or EbayClient()

    # ── LLM caller passed into session2 ──────────────────────────────────────

    async def _llm_call(self, system_prompt: str, user_prompt: str) -> str:
        """Async callable satisfying session2's llm_caller signature."""
        response = await self._invoke_llm([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ])
        return response.content

    # ── Main execute ──────────────────────────────────────────────────────────

    async def _execute(self, task: TrustTask) -> TrustSuccess:
        if not task.offers:
            return TrustSuccess(scored_offers=[])

        # ── Session 1: deterministic heuristics ───────────────────────────────
        s1_result = run_session1(
            offers=task.offers,
            vision_attributes=task.vision_attributes,
        )

        n_flagged = sum(1 for s in s1_result.signals if s.active_risk_flags)
        self._logger.info(
            "trust.session1_complete",
            n_offers=len(task.offers),
            n_flagged=n_flagged,
            batch_mean=s1_result.batch_mean_price,
            batch_stdev=s1_result.batch_stdev_price,
            currency=s1_result.currency,
        )

        # ── Session 2: LLM authenticity reasoning ─────────────────────────────
        s2_result = await run_session2(
            s1_result=s1_result,
            offers=task.offers,
            product_description=task.product_description,
            llm_caller=self._llm_call,
        )

        self._logger.info(
            "trust.session2_complete",
            verdicts={v.offer_id: v.verdict for v in s2_result.verdicts},
        )

        verdict_map: dict[str, OfferVerdict] = {
            v.offer_id: v for v in s2_result.verdicts
        }

        # ── Per-offer: formula scoring + score blending ───────────────────────
        scored: list[ScoredOffer] = []

        for offer in task.offers:
            formula_score_obj = await self._score_offer(offer, task.source)
            verdict           = verdict_map.get(offer.offer_id)
            blended           = self._blend_scores(formula_score_obj, verdict)
            scored.append(ScoredOffer(**offer.model_dump(), trust_score=blended))

        return TrustSuccess(
            scored_offers=scored,
            session1_batch_mean=s1_result.batch_mean_price,
            session1_batch_stdev=s1_result.batch_stdev_price,
            session1_currency=s1_result.currency,
            session2_verdicts=[dataclasses.asdict(v) for v in s2_result.verdicts],
        )

    # ── Score blending ────────────────────────────────────────────────────────

    def _blend_scores(
        self,
        formula_score: TrustScore,
        verdict: OfferVerdict | None,
    ) -> TrustScore:
        """
        Combine the deterministic formula score with the LLM verdict.

        formula_score_norm = formula_score.score / 100  (maps 0-100 → 0-1)
        llm_component      = confidence         if AUTHENTIC
                           = 1 - confidence     if SUSPICIOUS or HIGH_RISK
        blended_norm       = 0.4 * formula_score_norm + 0.6 * llm_component
        blended_score      = blended_norm * 100  (back to 0-100)
        """
        if verdict is None or verdict.skip_blend:
            # No LLM verdict available — preserve formula score intact
            return formula_score

        formula_norm  = formula_score.score / 100.0
        llm_component = (
            verdict.confidence if verdict.verdict == "AUTHENTIC"
            else 1.0 - verdict.confidence
        )

        blended_norm  = _FORMULA_WEIGHT * formula_norm + _LLM_WEIGHT * llm_component
        blended_score = round(min(max(blended_norm * 100.0, 0.0), 100.0), 2)

        # Level from blended score (same thresholds as scorer.py)
        if formula_score.level == TrustLevel.INSUFFICIENT_DATA:
            # Preserve INSUFFICIENT_DATA — formula said there's too little seller data
            level = TrustLevel.INSUFFICIENT_DATA
        elif blended_score >= 70.0:
            level = TrustLevel.LOW_RISK
        elif blended_score >= 40.0:
            level = TrustLevel.MEDIUM_RISK
        else:
            level = TrustLevel.HIGH_RISK

        flag_str = (
            f"  Risk flags: {', '.join(verdict.risk_flags)}."
            if verdict.risk_flags else ""
        )
        explanation = (
            f"{formula_score.explanation} "
            f"[{verdict.verdict} — {verdict.confidence:.0%} confidence. "
            f"{verdict.reasoning}{flag_str}]"
        ).strip()

        return TrustScore(
            score=blended_score,
            level=level,
            signals=formula_score.signals,
            explanation=explanation,
            data_source=formula_score.data_source,
        )

    # ── Formula scoring (preserved from original) ─────────────────────────────

    async def _score_offer(
        self, offer: Offer, source: Literal["ebay", "serpapi"]
    ) -> TrustScore:
        cached = await get_cached_vendor_profile(source, offer.seller_id)
        if cached:
            signals     = TrustSignals(**cached.get("signals", {}))
            data_source = cached.get("data_source", "insufficient")
            return calculate_trust_score(signals, data_source)

        signals, data_source = await self._fetch_signals(offer, source)
        score = calculate_trust_score(signals, data_source)

        await cache_vendor_profile(
            source,
            offer.seller_id,
            {"signals": signals.model_dump(), "data_source": data_source},
        )
        return score

    async def _fetch_signals(
        self, offer: Offer, source: str
    ) -> tuple[TrustSignals, str]:
        try:
            if source == "ebay":
                return await self._fetch_ebay_signals(offer)
            else:
                rating_raw  = offer.raw_attributes.get("rating")
                reviews_raw = offer.raw_attributes.get("reviews")
                signals = TrustSignals(
                    rating=float(rating_raw) if rating_raw else None,
                    review_count=int(reviews_raw) if reviews_raw else None,
                )
                return signals, "insufficient"
        except Exception as exc:
            self._logger.warning(
                "trust.fetch_signals.failed",
                seller_id=offer.seller_id,
                source=source,
                error=str(exc),
            )
            return TrustSignals(), "insufficient"

    async def _fetch_ebay_signals(self, offer: Offer) -> tuple[TrustSignals, str]:
        feedback  = await self._ebay.ebay_get_seller_feedback(offer.seller_id)
        score_raw = feedback.get("feedback_score", 0)
        pct_raw   = feedback.get("feedback_percentage")
        signals = TrustSignals(
            rating=None,
            review_count=int(score_raw) if score_raw else None,
            feedback_percentage=float(pct_raw) if pct_raw else None,
            has_return_policy=None,
            account_age_days=None,
        )
        return signals, "ebay_api"

    # ── Self-evaluation (preserved from original) ─────────────────────────────

    async def _self_evaluate(self, result: Any) -> tuple[bool, str]:
        if not isinstance(result, TrustSuccess):
            return False, "unexpected result type"

        for offer in result.scored_offers:
            ts = offer.trust_score
            # Consistency check: high rating + many reviews cannot produce HIGH_RISK
            if (
                ts.signals.rating is not None
                and ts.signals.rating >= 4.5
                and ts.signals.review_count is not None
                and ts.signals.review_count >= 100
                and ts.level == TrustLevel.HIGH_RISK
            ):
                return False, (
                    f"Inconsistent trust score: seller has {ts.signals.rating}★ "
                    f"with {ts.signals.review_count} reviews but scored HIGH_RISK"
                )

        return True, ""
