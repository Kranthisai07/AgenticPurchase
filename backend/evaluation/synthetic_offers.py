"""
Synthetic offer generator for trust injection evaluation.

Generates 100 labeled offers (60 suspicious + 40 authentic controls) covering
four injection types that exercise the full Session 1 + Session 2 trust pipeline.

Injection types:
  REPLICA_KEYWORD  (15): titles contain explicit counterfeit keywords
  PRICE_ANOMALY    (15): legitimate-looking titles but price is ~8% of market
  BRAND_MISMATCH   (15): listing brand disagrees with vision-detected brand
  COMBINED         (15): replica keywords AND anomalously low price
  AUTHENTIC        (40): clean titles, correct brand, realistic price (controls)

None of the generated offers contain real seller data — vendor signals are
bypassed by calling session1/session2 directly (no TrustAgent, no eBay API).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from backend.evaluation.dataset import EvalQuery, QUERY_BY_ID
from backend.models.common import Money
from backend.models.offer import Offer


# ── Market price ranges by category ───────────────────────────────────────────
# (low, high) in USD for generating realistic filler + authentic offers.

_MARKET_PRICE_RANGES: dict[str, tuple[float, float]] = {
    "footwear":    (90.0,  150.0),
    "electronics": (100.0, 300.0),
    "watches":     (60.0,  200.0),
    "apparel":     (40.0,  120.0),
    "home_goods":  (50.0,  180.0),
}

# Suspicious prices ≈ 8% of category midpoint → guarantee z-score < -2.0
_SUSPICIOUS_PRICE: dict[str, float] = {
    "footwear":    10.0,
    "electronics": 16.0,
    "watches":     10.0,
    "apparel":     7.0,
    "home_goods":  9.0,
}

# When brand_mismatch is the signal, the listing brand disagrees with the
# vision-detected expected brand.  Pick a plausible wrong brand per category.
_MISMATCH_LISTING_BRAND: dict[str, str] = {
    "footwear":    "adidas",
    "electronics": "sony",
    "watches":     "seiko",
    "apparel":     "champion",
    "home_goods":  "philips",
}


# ── LabeledOffer ──────────────────────────────────────────────────────────────

@dataclass
class LabeledOffer:
    offer: Offer               # synthetic Offer object (passed to session1/2)
    ground_truth: str          # "AUTHENTIC" or "SUSPICIOUS"
    trigger_signals: list[str] # Session 1 signals expected to fire
    query_id: str              # eval query this belongs to (for product context)
    injection_type: str        # "replica_keyword" | "price_anomaly" |
                               #   "brand_mismatch" | "combined" | "authentic"


# ── Public entry point ────────────────────────────────────────────────────────

def generate_labeled_offers() -> list[LabeledOffer]:
    """
    Return exactly 100 LabeledOffer objects:
      15 replica_keyword  (suspicious)
      15 price_anomaly    (suspicious)
      15 brand_mismatch   (suspicious)
      15 combined         (suspicious)
      40 authentic        (controls)
    """
    labeled: list[LabeledOffer] = []
    counter = [1]  # mutable counter for sequential offer IDs

    def next_id() -> str:
        oid = f"synthetic_{counter[0]:03d}"
        counter[0] += 1
        return oid

    categories = ["footwear", "electronics", "watches", "apparel", "home_goods"]

    # One row of 3 query IDs per category for each injection type
    _QUERY_ROWS: dict[str, dict[str, list[str]]] = {
        "footwear": {
            "replica":     ["fw-01", "fw-02", "fw-03"],
            "price":       ["fw-04", "fw-05", "fw-06"],
            "brand":       ["fw-07", "fw-08", "fw-09"],
            "combined":    ["fw-01", "fw-03", "fw-05"],
            "authentic":   ["fw-02", "fw-04", "fw-06", "fw-07", "fw-08",
                            "fw-09", "fw-10", "fw-01"],
        },
        "electronics": {
            "replica":     ["el-01", "el-02", "el-03"],
            "price":       ["el-04", "el-05", "el-06"],
            "brand":       ["el-07", "el-08", "el-09"],
            "combined":    ["el-01", "el-03", "el-05"],
            "authentic":   ["el-02", "el-04", "el-06", "el-07", "el-08",
                            "el-09", "el-10", "el-01"],
        },
        "watches": {
            "replica":     ["wa-01", "wa-02", "wa-03"],
            "price":       ["wa-04", "wa-05", "wa-06"],
            "brand":       ["wa-07", "wa-08", "wa-09"],
            "combined":    ["wa-01", "wa-03", "wa-05"],
            "authentic":   ["wa-02", "wa-04", "wa-06", "wa-07", "wa-08",
                            "wa-09", "wa-10", "wa-01"],
        },
        "apparel": {
            "replica":     ["ap-01", "ap-02", "ap-03"],
            "price":       ["ap-04", "ap-05", "ap-06"],
            "brand":       ["ap-07", "ap-08", "ap-09"],
            "combined":    ["ap-01", "ap-03", "ap-05"],
            "authentic":   ["ap-02", "ap-04", "ap-06", "ap-07", "ap-08",
                            "ap-09", "ap-10", "ap-01"],
        },
        "home_goods": {
            "replica":     ["hg-01", "hg-02", "hg-03"],
            "price":       ["hg-04", "hg-05", "hg-06"],
            "brand":       ["hg-07", "hg-08", "hg-09"],
            "combined":    ["hg-01", "hg-03", "hg-05"],
            "authentic":   ["hg-02", "hg-04", "hg-06", "hg-07", "hg-08",
                            "hg-09", "hg-10", "hg-01"],
        },
    }

    for cat in categories:
        q_rows = _QUERY_ROWS[cat]
        lo, hi  = _MARKET_PRICE_RANGES[cat]
        mid     = (lo + hi) / 2.0
        susp_px = _SUSPICIOUS_PRICE[cat]
        mismatch_brand = _MISMATCH_LISTING_BRAND[cat]

        # ── REPLICA_KEYWORD (3 per category) ──────────────────────────────────
        replica_titles = [
            f"AAA+ {_expected_brand(q_rows['replica'][0]).title()} Replica "
            f"{_product_type(q_rows['replica'][0]).title()} — High Quality Copy",
            f"High Quality Fake {_expected_brand(q_rows['replica'][1]).title()} "
            f"{_product_type(q_rows['replica'][1]).title()} Knockoff",
            f"1:1 Clone {_expected_brand(q_rows['replica'][2]).title()} "
            f"{_product_type(q_rows['replica'][2]).title()} Bootleg",
        ]
        for i, qid in enumerate(q_rows["replica"]):
            q = QUERY_BY_ID[qid]
            labeled.append(LabeledOffer(
                offer=_make_offer(
                    offer_id=next_id(),
                    title=replica_titles[i],
                    price=mid,
                    raw_attributes={"brand": q.expected_brand or ""},
                ),
                ground_truth="SUSPICIOUS",
                trigger_signals=["replica_keywords"],
                query_id=qid,
                injection_type="replica_keyword",
            ))

        # ── PRICE_ANOMALY (3 per category) ────────────────────────────────────
        for qid in q_rows["price"]:
            q = QUERY_BY_ID[qid]
            title = (
                f"{_expected_brand(qid).title()} "
                f"{_product_type(qid).title()}"
            )
            labeled.append(LabeledOffer(
                offer=_make_offer(
                    offer_id=next_id(),
                    title=title,
                    price=susp_px,
                    raw_attributes={"brand": q.expected_brand or ""},
                ),
                ground_truth="SUSPICIOUS",
                trigger_signals=["price_anomaly"],
                query_id=qid,
                injection_type="price_anomaly",
            ))

        # ── BRAND_MISMATCH (3 per category) ───────────────────────────────────
        for qid in q_rows["brand"]:
            q = QUERY_BY_ID[qid]
            # Title is clean (correct brand), but raw_attributes declares a
            # different brand → vision vs listing mismatch fires in Session 1.
            title = (
                f"{_expected_brand(qid).title()} "
                f"{_product_type(qid).title()} — New Arrival"
            )
            labeled.append(LabeledOffer(
                offer=_make_offer(
                    offer_id=next_id(),
                    title=title,
                    price=mid,
                    raw_attributes={"brand": mismatch_brand},
                ),
                ground_truth="SUSPICIOUS",
                trigger_signals=["brand_mismatch"],
                query_id=qid,
                injection_type="brand_mismatch",
            ))

        # ── COMBINED: replica keyword + price anomaly (3 per category) ────────
        combined_titles = [
            f"Premium Quality {_expected_brand(q_rows['combined'][0]).title()}-Inspired "
            f"{_product_type(q_rows['combined'][0]).title()} Replica",
            f"AAA+ {_expected_brand(q_rows['combined'][1]).title()} "
            f"{_product_type(q_rows['combined'][1]).title()} High Quality Dupe",
            f"{_expected_brand(q_rows['combined'][2]).title()} "
            f"{_product_type(q_rows['combined'][2]).title()} 1:1 Copy Bootleg",
        ]
        for i, qid in enumerate(q_rows["combined"]):
            q = QUERY_BY_ID[qid]
            labeled.append(LabeledOffer(
                offer=_make_offer(
                    offer_id=next_id(),
                    title=combined_titles[i],
                    price=susp_px,
                    raw_attributes={"brand": q.expected_brand or ""},
                ),
                ground_truth="SUSPICIOUS",
                trigger_signals=["replica_keywords", "price_anomaly"],
                query_id=qid,
                injection_type="combined",
            ))

        # ── AUTHENTIC controls (8 per category) ───────────────────────────────
        # Spread prices across the normal range for realism.
        price_steps = [
            lo + (hi - lo) * i / 7
            for i in range(8)
        ]
        for i, qid in enumerate(q_rows["authentic"]):
            q = QUERY_BY_ID[qid]
            title = (
                f"{_expected_brand(qid).title()} "
                f"{_product_type(qid).title()} — Genuine Authentic"
            )
            labeled.append(LabeledOffer(
                offer=_make_offer(
                    offer_id=next_id(),
                    title=title,
                    price=round(price_steps[i], 2),
                    raw_attributes={"brand": q.expected_brand or ""},
                ),
                ground_truth="AUTHENTIC",
                trigger_signals=[],
                query_id=qid,
                injection_type="authentic",
            ))

    assert len(labeled) == 100, f"Expected 100 labeled offers, got {len(labeled)}"

    # ── NOVEL_VOCABULARY (15 offers, added in v2) ──────────────────────────────
    # These titles intentionally use ZERO words from session1._REPLICA_PATTERNS
    # and ZERO words from dataset._DEFAULT_SUSPICIOUS_KEYWORDS, so Session 1
    # replica_flag cannot fire.  Detection must come from Session 2 LLM reasoning.
    #
    # Exception: offer 009 contains "replica" (from spec) which IS in both lists.
    # It is included as given but will be flagged by Session 1, not purely by LLM.
    # Prices are at normal market rates so price_anomaly cannot help either.
    # raw_attributes={} so brand_mismatch cannot fire.
    _NOVEL_OFFERS: list[tuple[str, str, str, str, float]] = [
        # (offer_id,              title,                                              query_id,  category,     price)
        ("synthetic_novel_001", "Class-A quality Nike-style running shoe",           "fw-01", "footwear",    120.0),
        ("synthetic_novel_002", "Super copy Adidas trainer premium grade",           "fw-02", "footwear",    120.0),
        ("synthetic_novel_003", "Mirror image Jordan high top 1:1 accuracy",        "fw-04", "footwear",    120.0),
        ("synthetic_novel_004", "Grade 5A Sony wireless headphones",                "el-02", "electronics", 200.0),
        ("synthetic_novel_005", "HDR quality Casio timepiece",                      "wa-01", "watches",     130.0),
        ("synthetic_novel_006", "First layer cowhide Timberland boot style",        "fw-05", "footwear",    120.0),
        ("synthetic_novel_007", "Premium inspired Vans sk8 hi alternative",         "fw-06", "footwear",    120.0),
        ("synthetic_novel_008", "Superfake Converse canvas shoe",                   "fw-07", "footwear",    120.0),
        ("synthetic_novel_009", "Prop replica Seiko movement watch",                "wa-02", "watches",     130.0),
        ("synthetic_novel_010", "Factory second Citizen solar alternative",         "wa-03", "watches",     130.0),
        ("synthetic_novel_011", "Unauthorized Levis denim jean style",              "ap-01", "apparel",      80.0),
        ("synthetic_novel_012", "Parallel import North Face puffer",                "ap-03", "apparel",      80.0),
        ("synthetic_novel_013", "Grey market Ralph Lauren polo",                    "ap-05", "apparel",      80.0),
        ("synthetic_novel_014", "B-grade Dyson motor vacuum alternative",           "hg-02", "home_goods",  115.0),
        ("synthetic_novel_015", "Exhibition copy KitchenAid mixer",                 "hg-09", "home_goods",  115.0),
    ]

    for oid, title, qid, cat, price in _NOVEL_OFFERS:
        labeled.append(LabeledOffer(
            offer=_make_offer(
                offer_id=oid,
                title=title,
                price=price,
                raw_attributes={},   # no brand metadata → brand_mismatch cannot fire
            ),
            ground_truth="SUSPICIOUS",
            trigger_signals=["novel_vocabulary"],
            query_id=qid,
            injection_type="novel_vocabulary",
        ))

    assert len(labeled) == 115, f"Expected 115 labeled offers, got {len(labeled)}"
    return labeled


# ── Filler offer factory ──────────────────────────────────────────────────────

def make_filler_offers(category: str, n: int = 9) -> list[Offer]:
    """
    Generate n filler offers with varied normal prices for the given category.

    Fillers are used to create a realistic price distribution in the batch so
    that Session 1's Z-score computation has batch_stdev > 0.  Only the
    target synthetic offer's verdict is evaluated — fillers are context only.
    """
    lo, hi = _MARKET_PRICE_RANGES.get(category, (50.0, 200.0))
    # Spread evenly across the normal range
    prices = [lo + (hi - lo) * i / max(n - 1, 1) for i in range(n)]

    return [
        _make_offer(
            offer_id=f"filler_{category[:2]}_{i:02d}",
            title=f"Authentic {category.replace('_', ' ').title()} Product {i}",
            price=round(prices[i], 2),
            raw_attributes={},
        )
        for i in range(n)
    ]


# ── Private helpers ───────────────────────────────────────────────────────────

def _make_offer(
    offer_id: str,
    title: str,
    price: float,
    raw_attributes: dict,
) -> Offer:
    return Offer(
        offer_id=offer_id,
        source="serpapi",
        title=title,
        description=None,
        price=Money(amount=price, currency="USD"),
        url=f"https://synthetic.eval/offer/{offer_id}",
        image_urls=[],
        seller_id=f"seller_{offer_id}",
        seller_name="SyntheticSeller",
        free_shipping=False,
        condition="new",
        raw_attributes=raw_attributes,
    )


def _expected_brand(query_id: str) -> str:
    q = QUERY_BY_ID.get(query_id)
    return (q.expected_brand or "brand") if q else "brand"


def _product_type(query_id: str) -> str:
    q = QUERY_BY_ID.get(query_id)
    return (q.expected_product_type or "product") if q else "product"
