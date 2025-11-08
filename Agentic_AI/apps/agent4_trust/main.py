# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass
from typing import Dict

from ...libs.agents.trust_chain import llm_adjust_trust
from ...libs.schemas.models import Offer, TrustAssessment


@dataclass(frozen=True)
class VendorProfile:
    tls: bool
    domain_age_days: int
    has_policy_pages: bool
    historical_issues: bool = False
    happy_reviews_pct: float = 0.7
    accepts_returns: bool = True
    average_refund_time_days: int = 7


VENDOR_PROFILES: Dict[str, VendorProfile] = {
    "Mockazon": VendorProfile(tls=True, domain_age_days=2400, has_policy_pages=True, happy_reviews_pct=0.92, accepts_returns=True, average_refund_time_days=5),
    "Shoply": VendorProfile(tls=True, domain_age_days=1100, has_policy_pages=True, happy_reviews_pct=0.88, accepts_returns=True, average_refund_time_days=7),
    "SuperMart": VendorProfile(tls=True, domain_age_days=3200, has_policy_pages=True, happy_reviews_pct=0.85, accepts_returns=True, average_refund_time_days=6),
    "MegaBuy": VendorProfile(tls=True, domain_age_days=650, has_policy_pages=True, happy_reviews_pct=0.81, accepts_returns=True, average_refund_time_days=8),
    "GigaDeal": VendorProfile(tls=True, domain_age_days=120, has_policy_pages=False, historical_issues=True, happy_reviews_pct=0.64, accepts_returns=False, average_refund_time_days=14),
}

logger = logging.getLogger(__name__)


def _suspicious_vendor_name(vendor: str) -> bool:
    lower = vendor.lower()
    return any(trigger in lower for trigger in ["scam", "fraud", "unknown", "dealz", "click"])


def _suspicious_url(url: str) -> bool:
    lower = url.lower()
    return any(trigger in lower for trigger in ["scam", "click", "malware", "unknown"])


def _compute_risk(profile: VendorProfile, offer: Offer) -> str:
    score = 0

    if not profile.tls:
        score += 2
    if not profile.has_policy_pages:
        score += 1
    if profile.domain_age_days < 365:
        score += 1
    if profile.domain_age_days < 90:
        score += 1

    if profile.historical_issues:
        score += 2
    if profile.happy_reviews_pct < 0.75:
        score += 1
    if profile.happy_reviews_pct < 0.6:
        score += 1

    if not profile.accepts_returns:
        score += 2
    elif profile.average_refund_time_days > 14:
        score += 1
    elif profile.average_refund_time_days > 10:
        score += 0.5

    if _suspicious_vendor_name(offer.vendor) or _suspicious_url(offer.url):
        score += 2

    if score <= 1:
        return "low"
    if score <= 3.5:
        return "medium"
    return "high"


async def assess(offer: Offer) -> TrustAssessment:
    profile = VENDOR_PROFILES.get(
        offer.vendor,
        VendorProfile(
            tls=False,
            domain_age_days=45,
            has_policy_pages=False,
            historical_issues=True,
            happy_reviews_pct=0.5,
            accepts_returns=False,
            average_refund_time_days=21,
        ),
    )
    risk = _compute_risk(profile, offer)
    assessment = TrustAssessment(
        vendor=offer.vendor,
        tls=profile.tls,
        domain_age_days=profile.domain_age_days,
        has_policy_pages=profile.has_policy_pages,
        risk=risk,
        happy_reviews_pct=profile.happy_reviews_pct,
        accepts_returns=profile.accepts_returns,
        average_refund_time_days=profile.average_refund_time_days,
        historical_issues=profile.historical_issues,
    )
    if _langchain_enabled():
        try:
            assessment = await llm_adjust_trust(offer, assessment, asdict(profile))
        except Exception as exc:
            logger.warning("LangChain trust adjustment failed: %s", exc, exc_info=True)
    return assessment


def _langchain_enabled() -> bool:
    flag = os.getenv("USE_LANGCHAIN_TRUST", os.getenv("USE_LANGCHAIN", "0"))
    return flag is not None and flag.strip().lower() in {"1", "true", "yes"}
