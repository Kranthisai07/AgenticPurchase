"""
Trust scoring formula — weighted, normalised, fully data-driven.
No hardcoded vendor profiles. Signals come exclusively from real API data.

Weights (sum = 100%):
  seller_rating:        30%
  review_count:         25%
  feedback_percentage:  20%
  has_return_policy:    15%
  account_age_days:     10%

Normalization:
  rating (0-5):        score / 5 * 100
  review_count:        log10(count + 1) / log10(10001) * 100  (caps at 10,000)
  feedback_percentage: as-is (already 0-100)
  has_return_policy:   100 if True, 0 if False
  account_age_days:    min(days / 1825, 1) * 100  (caps at 5 years)

Level thresholds:
  LOW_RISK:          score >= 70
  MEDIUM_RISK:       score >= 40
  HIGH_RISK:         score < 40  AND  review_count >= 10
  INSUFFICIENT_DATA: review_count < 10  OR  all signals None
"""
import math

from backend.models.trust import TrustLevel, TrustSignals, TrustScore

WEIGHTS = {
    "rating": 0.30,
    "review_count": 0.25,
    "feedback_percentage": 0.20,
    "has_return_policy": 0.15,
    "account_age_days": 0.10,
}


def _normalize_rating(rating: float | None) -> float | None:
    if rating is None:
        return None
    return min(max(rating, 0.0), 5.0) / 5.0 * 100.0


def _normalize_review_count(count: int | None) -> float | None:
    if count is None:
        return None
    return math.log10(count + 1) / math.log10(10001) * 100.0


def _normalize_feedback_pct(pct: float | None) -> float | None:
    if pct is None:
        return None
    return min(max(pct, 0.0), 100.0)


def _normalize_return_policy(has_policy: bool | None) -> float | None:
    if has_policy is None:
        return None
    return 100.0 if has_policy else 0.0


def _normalize_account_age(days: int | None) -> float | None:
    if days is None:
        return None
    return min(days / 1825.0, 1.0) * 100.0


def calculate_trust_score(
    signals: TrustSignals,
    data_source: str,
) -> TrustScore:
    """
    Compute a trust score from real API signals.
    Returns INSUFFICIENT_DATA when data is too sparse.
    """
    review_count = signals.review_count

    # Insufficient data check
    all_none = all(
        v is None
        for v in [
            signals.rating,
            signals.review_count,
            signals.has_return_policy,
            signals.account_age_days,
            signals.feedback_percentage,
        ]
    )
    if all_none or (review_count is not None and review_count < 10):
        return TrustScore(
            score=0.0,
            level=TrustLevel.INSUFFICIENT_DATA,
            signals=signals,
            explanation="Insufficient seller data to evaluate trust.",
            data_source="insufficient",
        )

    normalized: dict[str, float | None] = {
        "rating": _normalize_rating(signals.rating),
        "review_count": _normalize_review_count(signals.review_count),
        "feedback_percentage": _normalize_feedback_pct(signals.feedback_percentage),
        "has_return_policy": _normalize_return_policy(signals.has_return_policy),
        "account_age_days": _normalize_account_age(signals.account_age_days),
    }

    # Weighted average — skip None signals, re-weight remaining
    total_weight = 0.0
    weighted_sum = 0.0
    for key, weight in WEIGHTS.items():
        value = normalized[key]
        if value is not None:
            weighted_sum += value * weight
            total_weight += weight

    score = (weighted_sum / total_weight) if total_weight > 0 else 0.0
    score = round(min(max(score, 0.0), 100.0), 2)

    if score >= 70.0:
        level = TrustLevel.LOW_RISK
    elif score >= 40.0:
        level = TrustLevel.MEDIUM_RISK
    else:
        level = TrustLevel.HIGH_RISK

    return TrustScore(
        score=score,
        level=level,
        signals=signals,
        explanation=_build_explanation(score, level, signals),
        data_source=data_source,
    )


def _build_explanation(score: float, level: TrustLevel, signals: TrustSignals) -> str:
    parts = []
    if signals.rating is not None:
        parts.append(f"{signals.rating:.1f}★")
    if signals.review_count is not None:
        parts.append(f"{signals.review_count:,} reviews")
    if signals.feedback_percentage is not None:
        parts.append(f"{signals.feedback_percentage:.0f}% positive feedback")

    signal_str = ", ".join(parts) if parts else "limited data"

    if level == TrustLevel.LOW_RISK:
        return f"Trusted seller ({signal_str})."
    elif level == TrustLevel.MEDIUM_RISK:
        return f"Moderate seller reputation ({signal_str})."
    else:
        return f"Low trust score — proceed with caution ({signal_str})."
