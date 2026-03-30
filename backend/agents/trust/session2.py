"""
Trust Framework — Session 2: LLM-based authenticity reasoning.

Takes Session1Result and calls an LLM once per offer, synthesising all
Session 1 heuristic signals into an interpretable authenticity verdict.

The LLM is given:
  - The buyer's product intent (product_description)
  - The listing title
  - All 4 Session 1 signals and their anomaly flags
  - Batch price context (mean / stdev)
  - Composite risk score and active risk flags

Expected JSON response schema:
  {"verdict": "AUTHENTIC"|"SUSPICIOUS"|"HIGH_RISK", "confidence": 0.0-1.0, "reasoning": "..."}

Fallback chain on failure:
  1. JSON parse error → derive verdict from risk_score, confidence=0.4
  2. LLM call error   → verdict=SUSPICIOUS, confidence=0.3
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import structlog

from backend.agents.trust.session1 import OfferSignals, Session1Result

logger = structlog.get_logger(__name__)

# ── Prompts ───────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a counterfeit product detection analyst reviewing e-commerce listings.
Your task: decide whether a listing is AUTHENTIC, SUSPICIOUS, or HIGH_RISK.

You will receive:
- The buyer's purchase intent
- The listing title
- Four heuristic signals (price anomaly, replica keywords, brand consistency, weight anomaly)
- A composite risk score (0.0 = clean, 1.0 = fully flagged)

Respond ONLY with a single valid JSON object — no markdown, no prose outside JSON.

Required schema:
{"verdict": "AUTHENTIC" | "SUSPICIOUS" | "HIGH_RISK", "confidence": <float 0.0-1.0>, "reasoning": "<one sentence specific to this listing>"}

CRITICAL — Title-first independent reasoning:
Even when no Session 1 signals are present, you MUST independently evaluate the
listing title and description for language patterns that suggest non-genuine,
grey-market, parallel-import, factory-second, or unauthorized products.
Session 1 heuristics detect known vocabulary patterns — your role is to catch
what Session 1 misses by reasoning about meaning, not just matching keywords.
Do NOT let a clean statistical score override suspicious title language.

Suspicious language categories to recognise in listing titles:
- Quality-tier descriptors implying non-original manufacture
  (e.g. numeric grade designations such as "Grade 5A", "Class-A", "AAA quality";
   batch-grade labels; quality tier rankings applied to branded goods)
- Manufacturing or sourcing provenance terms suggesting unauthorized production
  (e.g. "factory second", "factory overrun", "production surplus", "B-grade",
   "exhibition unit", "prop replica", "display copy")
- Market-channel terms suggesting unauthorized or non-authorized distribution
  (e.g. "grey market", "parallel import", "unauthorized reseller")
- Similarity or alternative language positioning the item as a substitute
  rather than the genuine product
  (e.g. "Nike-style", "inspired", "alternative", "super copy", "mirror image")

IMPORTANT calibration — do NOT flag these patterns:
- A title that simply states brand + product type is AUTHENTIC unless other
  signals are present.
- An explicit assertion of genuineness ("genuine", "authentic", "original")
  standing alone in a title without other suspicious language is NOT sufficient
  to flag a listing SUSPICIOUS. Sellers do use these words legitimately.
- Standard marketing adjectives ("premium", "professional", "high quality")
  alone, without a grade designation or provenance qualifier, are NOT suspicious.
- Only flag SUSPICIOUS when the suspicious language category is clearly present,
  not when the title is ambiguous or simply assertive.

Decision guidelines:
- AUTHENTIC   : No significant flags; listing data is internally consistent.
                Title language matches what a genuine authorized seller would use,
                or contains only generic marketing language without suspicious tiers
                or provenance qualifiers.
- SUSPICIOUS  : Title clearly contains one of the suspicious language categories
                above, OR one statistical signal warrants caution. Clean price and
                absent keyword flags do NOT override clearly suspicious title language.
- HIGH_RISK   : Multiple strong signals (replica keywords + brand mismatch,
                extreme price anomaly) or title language that unambiguously and
                explicitly indicates inauthenticity.
- Be calibrated: reserve confidence > 0.85 for very clear-cut cases.
- reasoning must be specific to this listing, not a generic statement.

--- Example 1: novel-vocabulary suspicious listing (correct = SUSPICIOUS) ---
Title: "Grade 5A Sony wireless headphones — premium quality"
Session 1 signals: price Z-score=0.12 (normal), replica_flag=False,
no brand mismatch, no weight anomaly. Composite risk score: 0.000
Correct output:
{"verdict": "SUSPICIOUS", "confidence": 0.78, "reasoning": "The title uses a quality grade designation (Grade 5A) that genuine authorized sellers do not apply to their products; this language pattern is associated with unauthorized manufacture or grey-market distribution, warranting a SUSPICIOUS verdict despite clean statistical signals."}

--- Example 2: authentic listing that asserts genuineness (correct = AUTHENTIC) ---
Title: "Sony WH-1000XM5 Headphones — Genuine Authentic"
Session 1 signals: price Z-score=0.05 (normal), replica_flag=False,
no brand mismatch, no weight anomaly. Composite risk score: 0.000
Correct output:
{"verdict": "AUTHENTIC", "confidence": 0.82, "reasoning": "The title names the exact model with the brand and asserts genuine authenticity; no quality-tier grades, market-channel terms, or similarity language are present, and all statistical signals are clean."}\
"""


def _build_user_prompt(
    *,
    product_description: str,
    title: str,
    price: float,
    currency: str,
    batch_mean: float,
    batch_stdev: float,
    price_zscore: str,
    price_anomaly: bool,
    replica_flag: bool,
    matched_keywords: object,
    vision_brand: str,
    listing_brand: str,
    brand_mismatch: bool,
    brand_check_possible: bool,
    weight_anomaly: bool,
    weight_check_possible: bool,
    risk_score: float,
    active_risk_flags: str,
) -> str:
    """
    Build the per-offer user prompt.

    Title appears FIRST so the LLM forms an independent impression before
    seeing the structured Session 1 signals, which previously caused the
    LLM to anchor on statistical evidence and ignore suspicious title language.
    """
    return f"""\
Purchase intent: {product_description}

Listing title: {title}

Step 1 — Title analysis:
Does this listing title contain specific language suggesting it may not be
the genuine branded product? Look for: numeric quality-tier grades (e.g.
"Grade 5A", "Class-A"), manufacturing provenance terms (factory second,
B-grade, exhibition unit), market-channel indicators (grey market, parallel
import), or similarity language (style, copy, inspired, mirror image).
Do NOT flag a title solely because it asserts "genuine" or "authentic" —
those words alone are NOT suspicious. Only flag when a suspicious category
is clearly present.

Step 2 — Statistical signals (Session 1 heuristics):
  Price:           ${price:.2f} {currency}
  Batch mean:      ${batch_mean:.2f}  |  Batch stdev: ${batch_stdev:.2f}
  Price Z-score:   {price_zscore}  →  anomaly={price_anomaly}
  Replica keyword: flagged={replica_flag}  →  matched: {matched_keywords}
  Brand check:     vision={vision_brand}  listing={listing_brand}  mismatch={brand_mismatch}  checkable={brand_check_possible}
  Weight check:    anomaly={weight_anomaly}  checkable={weight_check_possible}

Composite risk score: {risk_score:.3f} / 1.0
Active risk flags:    {active_risk_flags}

Step 3 — Synthesize:
Consider both the title language assessment from Step 1 and the statistical
signals from Step 2. If the title raises concerns in Step 1, do not let
clean statistical signals override that judgment.

Return ONLY a JSON object with verdict, confidence, and reasoning.\
"""


# ── Result dataclasses ────────────────────────────────────────────────────────

@dataclass
class OfferVerdict:
    """Session 2 output for a single offer."""

    offer_id:   str
    verdict:    str    # "AUTHENTIC" | "SUSPICIOUS" | "HIGH_RISK"
    confidence: float  # 0.0 – 1.0
    reasoning:  str
    risk_flags: list[str] = field(default_factory=list)  # S1 active_risk_flags
    risk_score: float = 0.0                               # S1 composite risk
    skip_blend: bool  = False  # True when LLM was unreachable; caller keeps formula score


@dataclass
class Session2Result:
    """Aggregate output of Session 2 for the full offer batch."""

    verdicts: list[OfferVerdict]


# ── Public entry point ────────────────────────────────────────────────────────

async def run_session2(
    s1_result: Session1Result,
    offers: list[Any],
    product_description: str,
    llm_caller: Callable[[str, str], Awaitable[str]],
) -> Session2Result:
    """
    Run LLM-based authenticity reasoning for every offer in the batch.

    Parameters
    ----------
    s1_result:
        Session 1 heuristic signals (one OfferSignals per offer).
    offers:
        list[Offer] — the original offer batch (for title / price).
    product_description:
        The buyer's stated product intent; gives the LLM purchase context.
    llm_caller:
        Async callable: ``async (system_prompt: str, user_prompt: str) -> str``
        Must return the raw LLM response text (JSON expected).

    Returns
    -------
    Session2Result with one OfferVerdict per offer.
    """
    offer_map: dict[str, Any]           = {o.offer_id: o for o in offers}
    signal_map: dict[str, OfferSignals] = {s.offer_id: s for s in s1_result.signals}

    verdicts: list[OfferVerdict] = []

    for offer_id, sig in signal_map.items():
        offer = offer_map.get(offer_id)
        if offer is None:
            continue

        verdict = await _evaluate_offer(
            sig=sig,
            offer=offer,
            product_description=product_description,
            s1_result=s1_result,
            llm_caller=llm_caller,
        )
        verdicts.append(verdict)

    return Session2Result(verdicts=verdicts)


# ── Private helpers ───────────────────────────────────────────────────────────

async def _evaluate_offer(
    sig: OfferSignals,
    offer: Any,
    product_description: str,
    s1_result: Session1Result,
    llm_caller: Callable[[str, str], Awaitable[str]],
) -> OfferVerdict:
    """Build the per-offer prompt, call the LLM, parse the response."""
    user_prompt = _build_user_prompt(
        product_description=product_description or "(not specified)",
        title=offer.title,
        price=float(offer.price.amount),
        currency=s1_result.currency,
        batch_mean=s1_result.batch_mean_price,
        batch_stdev=s1_result.batch_stdev_price,
        price_zscore=(
            f"{sig.price_zscore:.3f}" if sig.price_zscore is not None else "N/A"
        ),
        price_anomaly=sig.price_anomaly,
        replica_flag=sig.replica_flag,
        matched_keywords=sig.matched_keywords if sig.matched_keywords else "none",
        vision_brand=sig.vision_brand or "unknown",
        listing_brand=sig.listing_brand or "unknown",
        brand_mismatch=sig.brand_mismatch,
        brand_check_possible=sig.brand_check_possible,
        weight_anomaly=sig.weight_anomaly,
        weight_check_possible=sig.weight_check_possible,
        risk_score=sig.risk_score,
        active_risk_flags=(
            ", ".join(sig.active_risk_flags) if sig.active_risk_flags else "none"
        ),
    )

    try:
        raw_response = await llm_caller(_SYSTEM_PROMPT, user_prompt)
        return _parse_verdict(raw_response, sig)
    except Exception as exc:
        logger.warning(
            "trust.session2.llm_call_failed",
            offer_id=sig.offer_id,
            error=str(exc),
        )
        return OfferVerdict(
            offer_id=sig.offer_id,
            verdict="SUSPICIOUS",
            confidence=0.3,
            reasoning="LLM evaluation unavailable; formula score preserved.",
            risk_flags=sig.active_risk_flags,
            risk_score=sig.risk_score,
            skip_blend=True,  # tell TrustAgent._blend_scores to keep formula score intact
        )


def _parse_verdict(raw: str, sig: OfferSignals) -> OfferVerdict:
    """
    Parse LLM JSON response into OfferVerdict.

    On parse failure, derive a fallback verdict from risk_score.
    """
    try:
        cleaned = raw.strip()

        # Strip markdown code fences if present (```json ... ```)
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            cleaned = "\n".join(
                line
                for line in lines
                if not line.strip().startswith("```")
                and line.strip() != "json"
            ).strip()

        data = json.loads(cleaned)

        verdict_str = str(data.get("verdict", "SUSPICIOUS")).upper()
        if verdict_str not in ("AUTHENTIC", "SUSPICIOUS", "HIGH_RISK"):
            verdict_str = "SUSPICIOUS"

        confidence = float(data.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence))

        reasoning = str(data.get("reasoning", "No reasoning provided."))

        return OfferVerdict(
            offer_id=sig.offer_id,
            verdict=verdict_str,
            confidence=confidence,
            reasoning=reasoning,
            risk_flags=sig.active_risk_flags,
            risk_score=sig.risk_score,
        )

    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        verdict_str = _fallback_from_risk_score(sig.risk_score)
        return OfferVerdict(
            offer_id=sig.offer_id,
            verdict=verdict_str,
            confidence=0.4,
            reasoning=(
                "Verdict derived from heuristic risk score "
                "(LLM response could not be parsed)."
            ),
            risk_flags=sig.active_risk_flags,
            risk_score=sig.risk_score,
        )


def _fallback_from_risk_score(risk_score: float) -> str:
    """Deterministic verdict fallback when LLM response is unavailable or unparseable."""
    if risk_score >= 0.75:
        return "HIGH_RISK"
    if risk_score >= 0.35:
        return "SUSPICIOUS"
    return "AUTHENTIC"
