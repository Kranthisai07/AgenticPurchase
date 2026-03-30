"""
Real-world trust evaluation — runs the two-session trust pipeline against
real marketplace listings labeled by real_listing_dataset.py.

Invocation:
  python -m backend.evaluation.eval_trust_real

Reads:  backend/evaluation/results/real_listings_labeled.json
Writes: backend/evaluation/results/eval_trust_real.json

Pipeline per listing:
  1. Group by category to build a realistic price distribution for Z-score.
  2. Run session1.run_session1() on the full category batch.
  3. Extract the target listing's OfferSignals.
  4. Wrap that signal in a focused Session1Result.
  5. Run session2.run_session2() → get one LLM verdict per listing.
  6. Map verdict → SUSPICIOUS / AUTHENTIC → compare to ground_truth.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RESULTS_DIR = Path(__file__).parent / "results"

_SYNTHETIC_RECALL = 0.96
_SYNTHETIC_PRECISION = 1.00

# Neutral product descriptions by category — mirrors what the Intent Agent
# produces after normalizing user intent. Avoids contaminating Session 2 with
# suspicious query terms (e.g. "grade 5A", "replica") that were never part of
# the buyer's stated intent in production.
NEUTRAL_DESCRIPTIONS: dict[str, str] = {
    "footwear":    "branded athletic footwear",
    "electronics": "branded consumer electronics",
    "watches":     "branded wristwatch",
    "apparel":     "branded clothing and outerwear",
    "home_goods":  "branded kitchen and home appliance",
}


# ── Offer builder from labeled listing ───────────────────────────────────────

def _listing_to_offer(listing: dict) -> Any:
    """Convert a labeled listing dict to an Offer model instance."""
    from backend.models.offer import Offer
    from backend.models.common import Money

    return Offer(
        offer_id=listing.get("listing_id", str(uuid.uuid4())),
        source=listing.get("source", "serpapi"),  # type: ignore[arg-type]
        title=listing.get("title", ""),
        description=None,
        price=Money(
            amount=listing.get("price_amount", 0.0),
            currency=listing.get("price_currency", "USD"),
        ),
        url=listing.get("url", ""),
        image_urls=[listing["image_url"]] if listing.get("image_url") else [],
        seller_id=listing.get("seller_id", "unknown"),
        seller_name=listing.get("seller_name", "unknown"),
        free_shipping=listing.get("free_shipping", False),
        condition=listing.get("condition", "unknown"),  # type: ignore[arg-type]
        raw_attributes={
            "brand": listing.get("expected_brand", ""),
        },
    )


# ── Per-category evaluation ────────────────────────────────────────────────────

@dataclass
class CategoryResult:
    category: str
    tp: int = 0
    tn: int = 0
    fp: int = 0
    fn: int = 0
    n_listings: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) > 0 else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) > 0 else 0.0


# ── Main evaluation ───────────────────────────────────────────────────────────

async def evaluate_trust_real(labeled_listings: list[dict]) -> dict:
    """
    Run the full two-session trust pipeline on all labeled listings.
    Returns a results dict for JSON serialisation.
    """
    from backend.agents.trust.session1 import Session1Result, run_session1
    from backend.agents.trust.session2 import run_session2
    from backend.core.config import get_settings
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI

    settings = get_settings()
    llm = ChatOpenAI(
        model=settings.openai_model_executor,
        api_key=settings.openai_api_key,
        temperature=0,
    )
    token_counter: dict[str, int] = {"calls": 0, "input": 0, "output": 0}

    async def llm_caller(system_prompt: str, user_prompt: str) -> str:
        token_counter["calls"] += 1
        response = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ])
        meta = getattr(response, "usage_metadata", None) or {}
        token_counter["input"]  += int(meta.get("input_tokens", 0))
        token_counter["output"] += int(meta.get("output_tokens", 0))
        return response.content

    # Group listings by category for batch Z-score context
    by_category: dict[str, list[dict]] = {}
    for listing in labeled_listings:
        cat = listing.get("category", "unknown")
        by_category.setdefault(cat, []).append(listing)

    t_start = time.monotonic()
    tp = tn = fp = fn = 0
    cat_results: dict[str, CategoryResult] = {}
    details: list[dict] = []

    total = len(labeled_listings)
    evaluated = 0

    for category, cat_listings in by_category.items():
        cat_results[category] = CategoryResult(category=category, n_listings=len(cat_listings))

        # Build Offer objects for the entire category batch
        cat_offers = [_listing_to_offer(l) for l in cat_listings]
        offer_map = {o.offer_id: (o, l) for o, l in zip(cat_offers, cat_listings)}

        # Vision attributes: use the expected brand for the category
        # (since we know the target brand for each query)
        # We run S1 per-listing with the correct brand context
        for offer, listing in zip(cat_offers, cat_listings):
            evaluated += 1
            if evaluated % 10 == 0:
                print(f"  [{evaluated:3d}/{total}] TP={tp} TN={tn} FP={fp} FN={fn} "
                      f"| LLM calls={token_counter['calls']}")

            expected_brand = listing.get("expected_brand", "").lower()
            vision_attrs = {"brand": expected_brand} if expected_brand else {}
            # Use a neutral description derived from category — NOT the raw search
            # query — to replicate Intent Agent normalization in production.
            product_description = NEUTRAL_DESCRIPTIONS.get(
                listing.get("category", ""), "branded product"
            )

            # Session 1: run on full category batch for Z-score context
            try:
                s1_full = run_session1(offers=cat_offers, vision_attributes=vision_attrs)
                target_signal = next(
                    (s for s in s1_full.signals if s.offer_id == offer.offer_id),
                    None,
                )
            except Exception as exc:
                print(f"    S1 error for {listing.get('listing_id', '?')}: {exc}")
                target_signal = None

            if target_signal is None:
                fn += 1 if listing["ground_truth"] == "SUSPICIOUS" else 0
                tn += 1 if listing["ground_truth"] == "AUTHENTIC" else 0
                details.append({
                    "listing_id": listing.get("listing_id"),
                    "query_id": listing.get("query_id"),
                    "category": category,
                    "ground_truth": listing["ground_truth"],
                    "predicted": "AUTHENTIC",
                    "correct": listing["ground_truth"] == "AUTHENTIC",
                    "title": listing.get("title", ""),
                    "price": listing.get("price_amount", 0.0),
                    "s1_signal": None,
                    "s2_verdict": None,
                    "error": "s1_signal_not_found",
                })
                continue

            # Session 2: one LLM call for this listing
            s1_focused = Session1Result(
                signals=[target_signal],
                batch_mean_price=s1_full.batch_mean_price,
                batch_stdev_price=s1_full.batch_stdev_price,
                currency=s1_full.currency,
            )

            try:
                s2_result = await run_session2(
                    s1_result=s1_focused,
                    offers=[offer],
                    product_description=product_description,
                    llm_caller=llm_caller,
                )
                verdict_obj = s2_result.verdicts[0] if s2_result.verdicts else None
                verdict = verdict_obj.verdict if verdict_obj else "AUTHENTIC"
                reasoning = verdict_obj.reasoning if verdict_obj else ""
                confidence = verdict_obj.confidence if verdict_obj else 0.0
            except Exception as exc:
                verdict = "AUTHENTIC"
                reasoning = f"ERROR: {exc}"
                confidence = 0.0

            # Map to binary label
            predicted = "SUSPICIOUS" if verdict.upper() in ("SUSPICIOUS", "HIGH_RISK") else "AUTHENTIC"
            gt = listing["ground_truth"]
            correct = predicted == gt

            # Confusion matrix
            if gt == "SUSPICIOUS" and predicted == "SUSPICIOUS":
                tp += 1
                cat_results[category].tp += 1
            elif gt == "AUTHENTIC" and predicted == "AUTHENTIC":
                tn += 1
                cat_results[category].tn += 1
            elif gt == "AUTHENTIC" and predicted == "SUSPICIOUS":
                fp += 1
                cat_results[category].fp += 1
            else:
                fn += 1
                cat_results[category].fn += 1

            details.append({
                "listing_id":    listing.get("listing_id"),
                "query_id":      listing.get("query_id"),
                "category":      category,
                "source":        listing.get("source"),
                "ground_truth":  gt,
                "predicted":     predicted,
                "correct":       correct,
                "title":         listing.get("title", ""),
                "price":         listing.get("price_amount", 0.0),
                "seller":        listing.get("seller_name", ""),
                "label_reason":  listing.get("label_reason", ""),
                "s1_price_anomaly":  target_signal.price_anomaly,
                "s1_replica_flag":   target_signal.replica_flag,
                "s1_brand_mismatch": target_signal.brand_mismatch,
                "s1_risk_score":     target_signal.risk_score,
                "s1_active_flags":   target_signal.active_risk_flags,
                "s2_verdict":        verdict,
                "s2_confidence":     confidence,
                "s2_reasoning":      reasoning,
            })

    duration_s = time.monotonic() - t_start

    # Aggregate metrics
    n_total     = tp + tn + fp + fn
    n_susp      = tp + fn
    n_auth      = tn + fp
    precision   = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall      = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    vvr         = tn / (tn + fn) if (tn + fn) > 0 else 0.0
    fvdr        = fp / (fp + tn) if (fp + tn) > 0 else 0.0

    # Cost estimate
    inp_tok = token_counter["input"]
    out_tok = token_counter["output"]
    if inp_tok == 0 and token_counter["calls"] > 0:
        inp_tok = token_counter["calls"] * 600
        out_tok = token_counter["calls"] * 120
    estimated_cost = inp_tok * 5e-6 + out_tok * 15e-6

    return {
        "timestamp": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "n_evaluated": n_total,
        "n_suspicious": n_susp,
        "n_authentic":  n_auth,
        "label_method": "rule_based_auto",
        "confusion_matrix": {"tp": tp, "tn": tn, "fp": fp, "fn": fn},
        "metrics": {
            "precision": round(precision, 4),
            "recall":    round(recall, 4),
            "vvr":       round(vvr, 4),
            "fvdr":      round(fvdr, 4),
        },
        "by_category": {
            cat: {
                "n_listings": r.n_listings,
                "precision":  round(r.precision, 4),
                "recall":     round(r.recall, 4),
                "tp": r.tp, "tn": r.tn, "fp": r.fp, "fn": r.fn,
            }
            for cat, r in cat_results.items()
        },
        "comparison": {
            "synthetic_precision": _SYNTHETIC_PRECISION,
            "synthetic_recall":    _SYNTHETIC_RECALL,
            "real_precision":      round(precision, 4),
            "real_recall":         round(recall, 4),
        },
        "llm_usage": {
            "calls":          token_counter["calls"],
            "input_tokens":   inp_tok,
            "output_tokens":  out_tok,
            "estimated_cost_usd": round(estimated_cost, 4),
        },
        "duration_s": round(duration_s, 1),
        "details": details,
    }


def _print_report(results: dict) -> None:
    m   = results["metrics"]
    cm  = results["confusion_matrix"]
    cmp = results["comparison"]
    llu = results["llm_usage"]

    W = 60
    print()
    print("=" * W)
    print("  REAL-WORLD TRUST EVALUATION REPORT")
    print("=" * W)
    print(f"  Total listings evaluated: {results['n_evaluated']}")
    print(f"    Suspicious (ground truth): {results['n_suspicious']}")
    print(f"    Authentic  (ground truth): {results['n_authentic']}")
    print(f"    Label method: {results['label_method']}")
    print()
    print("  CONFUSION MATRIX")
    print(f"    TP={cm['tp']}  TN={cm['tn']}  FP={cm['fp']}  FN={cm['fn']}")
    print()
    print("  TRUST METRICS (real-world listings)")
    print(f"    Precision: {m['precision']:.4f}")
    print(f"    Recall:    {m['recall']:.4f}")
    print(f"    VVR:       {m['vvr']:.4f}")
    print(f"    FVDR:      {m['fvdr']:.4f}")
    print()
    print("  BREAKDOWN BY CATEGORY")
    for cat, cr in results["by_category"].items():
        print(f"    {cat:15s}: precision={cr['precision']:.2f}  "
              f"recall={cr['recall']:.2f}  ({cr['n_listings']} listings)")
    print()
    print("  COMPARISON: Synthetic vs Real-World")
    print(f"    Synthetic precision: {cmp['synthetic_precision']:.2f}  "
          f"Real-world precision: {cmp['real_precision']:.2f}")
    print(f"    Synthetic recall:    {cmp['synthetic_recall']:.2f}  "
          f"Real-world recall:    {cmp['real_recall']:.2f}")
    print()
    print("  LLM USAGE")
    print(f"    Calls:         {llu['calls']}")
    print(f"    Estimated cost: ${llu['estimated_cost_usd']:.4f}")
    print(f"    Duration:       {results['duration_s']:.1f}s")
    print("=" * W)


async def run_evaluation() -> None:
    labeled_path = RESULTS_DIR / "real_listings_labeled.json"
    if not labeled_path.exists():
        print(f"ERROR: {labeled_path} not found.")
        print("Run: python -m backend.evaluation.real_listing_dataset first.")
        return

    with open(labeled_path, encoding="utf-8") as f:
        data = json.load(f)

    labeled_listings = data.get("listings", [])
    print(f"\n  Loaded {len(labeled_listings)} labeled listings.")
    print(f"  Running two-session trust pipeline (1 LLM call per listing)...")
    print(f"  Estimated cost: ~${len(labeled_listings) * 0.006:.2f} "
          f"({len(labeled_listings)} LLM calls @ ~$0.006 each)\n")

    results = await evaluate_trust_real(labeled_listings)

    _print_report(results)

    out_path = RESULTS_DIR / "eval_trust_real_fixed.json"
    RESULTS_DIR.mkdir(exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n  Results saved to: {out_path}")


def main() -> None:
    asyncio.run(run_evaluation())


if __name__ == "__main__":
    main()
