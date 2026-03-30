"""
Real listing dataset builder — loads collected raw listings, applies auto-labeling,
and saves the labeled dataset.

Invocation:
  python -m backend.evaluation.real_listing_dataset

Reads:  backend/evaluation/results/real_listings_raw.json
Writes: backend/evaluation/results/real_listings_labeled.json

Labeling logic:
  1. Strong suspicious terms in title → SUSPICIOUS (rule_based)
  2. Price below 15% of category-clean-query median AND suspicious query → SUSPICIOUS
  3. Suspicious seller name terms → flagged for manual review
  4. Clean query with no suspicious signals → AUTHENTIC (rule_based)
  5. Suspicious query with no flags → AUTHENTIC (rule_based, system returned genuine listing)
"""
from __future__ import annotations

import json
import statistics
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RESULTS_DIR = Path(__file__).parent / "results"

# ── Suspicious title terms ────────────────────────────────────────────────────

_SUSPICIOUS_TITLE_TERMS: list[str] = [
    "replica",
    "fake",
    "counterfeit",
    "knockoff",
    "knock-off",
    "knock off",
    "aaa",
    "aaa+",
    "aaa grade",
    "grade 5a",
    "grade a ",          # "grade a" followed by space (avoid "grade a+" in legitimate ratings)
    "grade-a ",
    "bootleg",
    "imitation",
    "dupe",
    "1:1",
    "super copy",
    "high quality copy",
    "parallel import",
    "grey market",
    "gray market",
    "factory second",
    "factory-second",
    "exhibition copy",
    "exhibition unit",
    "display copy",
    "inspired by",
    "mirror image",
    "b-grade",
    "b grade",
    "factory overrun",
    "production surplus",
    "not authentic",
    "not genuine",
    "not original",
]

# ── Suspicious seller name terms ──────────────────────────────────────────────

_SUSPICIOUS_SELLER_TERMS: list[str] = [
    "replica",
    "fake",
    "copy",
    "knockoff",
    "aaa",
    "grade5a",
    "superfake",
    "bestcopy",
]


# ── RealListing dataclass ─────────────────────────────────────────────────────

@dataclass
class RealListing:
    listing_id: str
    query_id: str
    query_text: str
    query_type: str          # "suspicious" | "clean"
    category: str
    expected_brand: str
    source: str              # "ebay" | "serpapi"
    title: str
    price_amount: float
    price_currency: str
    seller_id: str
    seller_name: str
    url: str
    image_url: str
    condition: str
    free_shipping: bool
    ground_truth: str        # "SUSPICIOUS" | "AUTHENTIC"
    label_method: str        # "rule_based"
    label_reason: str
    needs_manual_review: bool = False
    manual_review_reason: str = ""


# ── Category median prices (from clean-query listings) ───────────────────────

def _compute_category_medians(
    listings: list[dict],
) -> dict[str, float]:
    """
    Compute the median price per category using only clean-query listings
    with non-zero prices. Used to detect price anomalies.
    """
    cat_prices: dict[str, list[float]] = {}
    for l in listings:
        if l["query_type"] == "clean" and l["price_amount"] > 0:
            cat = l["category"]
            cat_prices.setdefault(cat, []).append(l["price_amount"])

    medians: dict[str, float] = {}
    for cat, prices in cat_prices.items():
        if prices:
            sorted_p = sorted(prices)
            mid = len(sorted_p) // 2
            medians[cat] = sorted_p[mid]

    return medians


# ── Auto-labeling ─────────────────────────────────────────────────────────────

def auto_label(
    title: str,
    seller_name: str,
    price_amount: float,
    query_type: str,
    category: str,
    category_medians: dict[str, float],
) -> tuple[str, str, bool, str]:
    """
    Apply conservative automatic labels based on observable signals.

    Returns:
        (ground_truth, label_reason, needs_manual_review, manual_review_reason)

    ground_truth: "SUSPICIOUS" | "AUTHENTIC"
    label_reason: human-readable explanation
    needs_manual_review: True when a signal is present but ambiguous
    manual_review_reason: description of the flag
    """
    title_lower = (title or "").lower()
    seller_lower = (seller_name or "").lower()

    # ── Rule 1: Strong suspicious terms in title → SUSPICIOUS ─────────────────
    for term in _SUSPICIOUS_TITLE_TERMS:
        if term in title_lower:
            return (
                "SUSPICIOUS",
                f"title contains suspicious term: '{term}'",
                False,
                "",
            )

    # ── Rule 2: Price anomaly + suspicious query → SUSPICIOUS ─────────────────
    median = category_medians.get(category)
    price_anomaly_flag = False
    price_anomaly_reason = ""
    if median and median > 0 and price_amount > 0:
        price_ratio = price_amount / median
        if price_ratio < 0.15:
            price_anomaly_flag = True
            price_anomaly_reason = (
                f"price ${price_amount:.2f} is {price_ratio:.1%} of category median "
                f"${median:.2f} (< 15%)"
            )
            if query_type == "suspicious":
                return (
                    "SUSPICIOUS",
                    f"suspicious query + extreme price anomaly: {price_anomaly_reason}",
                    False,
                    "",
                )
        elif price_ratio < 0.20 and query_type == "suspicious":
            # Flagged for manual review — not auto-labeled suspicious
            price_anomaly_flag = True
            price_anomaly_reason = (
                f"price ${price_amount:.2f} is {price_ratio:.1%} of category median "
                f"${median:.2f} (< 20%, suspicious query)"
            )

    # ── Rule 3: Suspicious seller name ────────────────────────────────────────
    seller_flag = any(t in seller_lower for t in _SUSPICIOUS_SELLER_TERMS)
    seller_reason = ""
    if seller_flag:
        matched = next(t for t in _SUSPICIOUS_SELLER_TERMS if t in seller_lower)
        seller_reason = f"seller name '{seller_name}' contains suspicious term '{matched}'"

    # ── Aggregate manual review flags ─────────────────────────────────────────
    needs_review = price_anomaly_flag or seller_flag
    review_reasons = []
    if price_anomaly_flag:
        review_reasons.append(price_anomaly_reason)
    if seller_flag:
        review_reasons.append(seller_reason)
    manual_review_reason = "; ".join(review_reasons)

    # ── Rule 4: Clean query with no suspicious signals → AUTHENTIC ────────────
    if query_type == "clean":
        return "AUTHENTIC", "clean query with no suspicious title signals", needs_review, manual_review_reason

    # ── Rule 5: Suspicious query but no flags → AUTHENTIC ─────────────────────
    return (
        "AUTHENTIC",
        "suspicious query but no suspicious signals detected in listing title",
        needs_review,
        manual_review_reason,
    )


# ── Build labeled dataset ─────────────────────────────────────────────────────

def build_labeled_dataset(raw_listings: list[dict]) -> list[RealListing]:
    """
    Apply auto-labeling to all raw listings.
    Returns a list of RealListing objects.
    """
    # Compute category medians from clean-query listings
    category_medians = _compute_category_medians(raw_listings)
    print(f"\n  Category price medians (from clean queries):")
    for cat, med in sorted(category_medians.items()):
        print(f"    {cat:15s}: ${med:.2f}")

    labeled: list[RealListing] = []

    for raw in raw_listings:
        gt, reason, needs_review, review_reason = auto_label(
            title=raw["title"],
            seller_name=raw.get("seller_name", ""),
            price_amount=raw.get("price_amount", 0.0),
            query_type=raw["query_type"],
            category=raw["category"],
            category_medians=category_medians,
        )

        labeled.append(RealListing(
            listing_id=raw.get("listing_id", str(uuid.uuid4())),
            query_id=raw["query_id"],
            query_text=raw["query_text"],
            query_type=raw["query_type"],
            category=raw["category"],
            expected_brand=raw.get("expected_brand", ""),
            source=raw.get("source", "serpapi"),
            title=raw["title"],
            price_amount=raw.get("price_amount", 0.0),
            price_currency=raw.get("price_currency", "USD"),
            seller_id=raw.get("seller_id", ""),
            seller_name=raw.get("seller_name", ""),
            url=raw.get("url", ""),
            image_url=raw.get("image_url", ""),
            condition=raw.get("condition", "unknown"),
            free_shipping=raw.get("free_shipping", False),
            ground_truth=gt,
            label_method="rule_based",
            label_reason=reason,
            needs_manual_review=needs_review,
            manual_review_reason=review_reason,
        ))

    return labeled


# ── Save labeled dataset ──────────────────────────────────────────────────────

def save_labeled(labeled: list[RealListing]) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    RESULTS_DIR.mkdir(exist_ok=True)
    out_path = RESULTS_DIR / "real_listings_labeled.json"

    data = {
        "timestamp": ts,
        "total": len(labeled),
        "n_suspicious": sum(1 for l in labeled if l.ground_truth == "SUSPICIOUS"),
        "n_authentic": sum(1 for l in labeled if l.ground_truth == "AUTHENTIC"),
        "n_needs_review": sum(1 for l in labeled if l.needs_manual_review),
        "listings": [asdict(l) for l in labeled],
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return out_path


# ── Print summary ─────────────────────────────────────────────────────────────

def print_summary(labeled: list[RealListing]) -> None:
    n_susp   = sum(1 for l in labeled if l.ground_truth == "SUSPICIOUS")
    n_auth   = sum(1 for l in labeled if l.ground_truth == "AUTHENTIC")
    n_review = sum(1 for l in labeled if l.needs_manual_review)

    print(f"\n{'='*64}")
    print("  AUTO-LABELING SUMMARY")
    print(f"{'='*64}")
    print(f"  Total listings:           {len(labeled)}")
    print(f"  Auto-labeled SUSPICIOUS:  {n_susp}")
    print(f"  Auto-labeled AUTHENTIC:   {n_auth}")
    print(f"  Flagged for review:       {n_review}")

    # By category
    cats = sorted({l.category for l in labeled})
    print(f"\n  By category:")
    for cat in cats:
        cat_listings = [l for l in labeled if l.category == cat]
        susp = sum(1 for l in cat_listings if l.ground_truth == "SUSPICIOUS")
        print(f"    {cat:15s}: {len(cat_listings):3d} total  "
              f"{susp:2d} SUSPICIOUS  {len(cat_listings)-susp:2d} AUTHENTIC")

    # By source
    print(f"\n  By source:")
    for source in ["ebay", "serpapi"]:
        src_listings = [l for l in labeled if l.source == source]
        susp = sum(1 for l in src_listings if l.ground_truth == "SUSPICIOUS")
        print(f"    {source:10s}: {len(src_listings):3d} total  "
              f"{susp:2d} SUSPICIOUS  {len(src_listings)-susp:2d} AUTHENTIC")

    # Manual review flags
    if n_review > 0:
        print(f"\n  Manual review flags ({n_review}):")
        for l in labeled:
            if l.needs_manual_review:
                print(f"    [{l.query_id}] {l.title[:55]}")
                print(f"      Reason: {l.manual_review_reason}")
                print(f"      Auto-label: {l.ground_truth} | ${l.price_amount:.2f}")

    # 5 interesting samples
    print(f"\n  Sample listings (most interesting — suspicious auto-labeled):")
    samples = [l for l in labeled if l.ground_truth == "SUSPICIOUS"][:5]
    if not samples:
        samples = labeled[:5]
    for i, l in enumerate(samples, 1):
        print(f"\n  [{i}] {l.query_id} ({l.source})")
        print(f"      Title:  {l.title[:65]}")
        print(f"      Price:  ${l.price_amount:.2f}  |  Seller: {l.seller_name[:30]}")
        print(f"      Query:  {l.query_text[:60]}")
        print(f"      Label:  {l.ground_truth} ({l.label_method})")
        print(f"      Reason: {l.label_reason}")

    print(f"\n{'='*64}\n")


# ── Main ──────────────────────────────────────────────────────────────────────

def build_and_save() -> list[RealListing]:
    raw_path = RESULTS_DIR / "real_listings_raw.json"
    if not raw_path.exists():
        print(f"ERROR: {raw_path} not found.")
        print("Run: python -m backend.evaluation.collect_real_listings first.")
        return []

    with open(raw_path, encoding="utf-8") as f:
        data = json.load(f)

    raw_listings = data.get("listings", [])
    print(f"\n  Loaded {len(raw_listings)} raw listings from {raw_path}")

    labeled = build_labeled_dataset(raw_listings)
    out_path = save_labeled(labeled)

    print_summary(labeled)
    print(f"  Labeled dataset saved to: {out_path}")

    return labeled


def main() -> None:
    build_and_save()


if __name__ == "__main__":
    main()
