"""Unit tests for the trust scoring formula."""
import pytest
from backend.agents.trust.scorer import calculate_trust_score
from backend.models.trust import TrustLevel, TrustSignals


def test_excellent_seller_is_low_risk():
    signals = TrustSignals(
        rating=4.9,
        review_count=500,
        account_age_days=1200,
        has_return_policy=True,
        feedback_percentage=99.0,
    )
    result = calculate_trust_score(signals, "ebay_api")
    assert result.level == TrustLevel.LOW_RISK
    assert result.score >= 70.0


def test_poor_seller_is_high_risk():
    signals = TrustSignals(
        rating=2.0,
        review_count=15,
        account_age_days=30,
        has_return_policy=False,
        feedback_percentage=60.0,
    )
    result = calculate_trust_score(signals, "ebay_api")
    assert result.level == TrustLevel.HIGH_RISK
    assert result.score < 40.0


def test_new_seller_with_few_reviews_is_insufficient():
    signals = TrustSignals(
        rating=5.0,
        review_count=3,  # < 10
    )
    result = calculate_trust_score(signals, "ebay_api")
    assert result.level == TrustLevel.INSUFFICIENT_DATA


def test_all_none_signals_is_insufficient():
    signals = TrustSignals()
    result = calculate_trust_score(signals, "insufficient")
    assert result.level == TrustLevel.INSUFFICIENT_DATA


def test_score_is_between_0_and_100():
    signals = TrustSignals(
        rating=4.5,
        review_count=100,
        has_return_policy=True,
    )
    result = calculate_trust_score(signals, "ebay_api")
    assert 0.0 <= result.score <= 100.0


def test_score_increases_with_more_reviews():
    signals_few = TrustSignals(rating=4.5, review_count=20, has_return_policy=True)
    signals_many = TrustSignals(rating=4.5, review_count=5000, has_return_policy=True)
    result_few = calculate_trust_score(signals_few, "ebay_api")
    result_many = calculate_trust_score(signals_many, "ebay_api")
    assert result_many.score > result_few.score


def test_return_policy_increases_score():
    base = TrustSignals(rating=4.0, review_count=50, has_return_policy=False)
    with_policy = TrustSignals(rating=4.0, review_count=50, has_return_policy=True)
    score_base = calculate_trust_score(base, "ebay_api")
    score_policy = calculate_trust_score(with_policy, "ebay_api")
    assert score_policy.score > score_base.score
