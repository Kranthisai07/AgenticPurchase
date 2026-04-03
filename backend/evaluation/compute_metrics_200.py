"""
Compute paper-ready metrics from the 200-query evaluation raw results.

Invocation:
  python -m backend.evaluation.compute_metrics_200

Reads:  backend/evaluation/results/eval_200_raw.json
        (or eval_200_progress.json if raw not available)
Writes: backend/evaluation/results/eval_200_final.json
        backend/evaluation/results/paper_metrics_200.json

Metrics computed (same formulas as run_eval.py / eval_intent / eval_sourcing / eval_trust):
  - Intent F1 (combined, image, text)
  - NDCG@3, MRR
  - Trust Precision, Recall, VVR, FVDR
  - Latency, token, cost statistics
  - Per-category breakdown
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RESULTS_DIR = Path(__file__).parent / "results"

_BLENDED_RATE = 0.0000065   # 85% input@$5/1M + 15% output@$15/1M


# ── Lightweight proxy objects for compatibility with eval_* modules ────────────

class _PriceProxy:
    __slots__ = ("amount", "currency")
    def __init__(self, amount: float, currency: str = "USD"):
        self.amount   = amount
        self.currency = currency


class _OfferProxy:
    """Minimal offer-like object accepted by eval_sourcing._is_relevant."""
    __slots__ = ("offer_id", "title", "price", "_raw_attrs")
    def __init__(self, d: dict):
        self.offer_id  = d.get("offer_id", "")
        self.title     = d.get("title", "")
        self.price     = _PriceProxy(float(d.get("price", 0.0)))
        self._raw_attrs = {"brand": d.get("brand", "")}

    @property
    def raw_attributes(self) -> dict:
        return self._raw_attrs


class _SagaProxy:
    """
    Proxy that mimics SagaEvalResult for the existing evaluate_* functions.

    Fields required:
      eval_intent  : .query, .intent_output, .has_image, .success
      eval_sourcing: .query, .ranked_offers, .sourced_offers, .success
      eval_trust   : .query, .trust_results, .success
    """
    __slots__ = (
        "query_id", "query", "intent_output", "has_image", "success", "error",
        "duration_ms", "total_tokens",
        "ranked_offers", "sourced_offers", "trust_results",
    )

    def __init__(self, raw: dict, query_map: dict):
        from backend.evaluation.dataset_200 import QUERY_BY_ID_200

        qid = raw["query_id"]
        self.query_id     = qid
        self.query        = query_map.get(qid)
        self.intent_output = raw.get("intent_output", {})
        self.has_image    = raw.get("has_image", False)
        self.success      = raw.get("success", False)
        self.error        = raw.get("error")
        self.duration_ms  = raw.get("duration_ms", 0.0)
        self.total_tokens = raw.get("total_tokens", 0)

        # Build offer proxy objects for sourcing eval
        ranked_raw = raw.get("ranked_offers_data") or []
        self.ranked_offers  = [_OfferProxy(d) for d in ranked_raw]
        self.sourced_offers = self.ranked_offers   # same pool for eval purposes

        # Trust results — pass through dict list directly (eval_trust uses dicts)
        self.trust_results = raw.get("trust_results") or []


# ── Load raw results ───────────────────────────────────────────────────────────

def _load_raw() -> list[dict]:
    raw_path = RESULTS_DIR / "eval_200_raw.json"
    progress_path = RESULTS_DIR / "eval_200_progress.json"

    if raw_path.exists():
        with open(raw_path, encoding="utf-8") as f:
            data = json.load(f)
        print(f"Loaded {len(data['results'])} results from {raw_path.name}")
        return data["results"]
    elif progress_path.exists():
        with open(progress_path, encoding="utf-8") as f:
            data = json.load(f)
        print(f"Loaded {len(data['results'])} results from {progress_path.name} (progress file)")
        return data["results"]
    else:
        raise FileNotFoundError(
            "Neither eval_200_raw.json nor eval_200_progress.json found.\n"
            "Run: python -m backend.evaluation.run_eval_200"
        )


# ── Category median for price proxy (needed by eval_sourcing) ─────────────────

def _patch_offer_prices(proxies: list[_SagaProxy]) -> None:
    """
    The _is_relevant function in eval_sourcing needs batch_offers with real price
    objects to compute the 3× median filter.  We ensure each offer proxy has a
    consistent USD price object — the raw data already stores the float.
    """
    # Nothing extra needed — _OfferProxy already sets .price = _PriceProxy(amount)


# ── Main compute function ──────────────────────────────────────────────────────

def compute_metrics() -> None:
    from backend.evaluation.dataset_200 import QUERY_BY_ID_200
    from backend.evaluation.eval_intent   import evaluate_intent
    from backend.evaluation.eval_sourcing import evaluate_sourcing
    from backend.evaluation.eval_trust    import evaluate_trust

    raw_results = _load_raw()
    query_map   = QUERY_BY_ID_200

    # Build proxy objects
    proxies = [_SagaProxy(r, query_map) for r in raw_results]

    n_success = sum(1 for p in proxies if p.success)
    n_fail    = len(proxies) - n_success
    print(f"  Success: {n_success}  Failed: {n_fail}\n")

    if n_success == 0:
        print("ERROR: No successful runs — cannot compute metrics.")
        return

    # ── Core metrics ──────────────────────────────────────────────────────────
    intent_m   = evaluate_intent(proxies)
    sourcing_m = evaluate_sourcing(proxies)
    trust_m    = evaluate_trust(proxies)

    # ── Latency / cost ────────────────────────────────────────────────────────
    successful  = [p for p in proxies if p.success]
    img_results = [p for p in successful if p.has_image]
    txt_results = [p for p in successful if not p.has_image]

    avg_latency_s     = sum(p.duration_ms for p in successful) / len(successful) / 1000
    avg_img_latency_s = (
        sum(p.duration_ms for p in img_results) / len(img_results) / 1000
        if img_results else 0.0
    )
    avg_txt_latency_s = (
        sum(p.duration_ms for p in txt_results) / len(txt_results) / 1000
        if txt_results else 0.0
    )
    avg_tokens        = sum(p.total_tokens for p in successful) / len(successful)
    avg_cost_usd      = avg_tokens * _BLENDED_RATE
    total_cost_usd    = sum(p.total_tokens for p in successful) * _BLENDED_RATE

    n_img = len(img_results)
    n_txt = len(txt_results)

    # ── Per-category breakdown ────────────────────────────────────────────────
    categories = ["footwear", "electronics", "watches", "apparel", "home_goods"]
    cat_metrics: dict[str, dict] = {}
    for cat in categories:
        cat_proxies = [p for p in successful if p.query and p.query.category == cat]
        if not cat_proxies:
            continue
        ci = evaluate_intent(cat_proxies)
        cs = evaluate_sourcing(cat_proxies)
        ct = evaluate_trust(cat_proxies)
        cat_metrics[cat] = {
            "n": len(cat_proxies),
            "intent_f1":  ci.f1,
            "ndcg_at_3":  cs.ndcg_at_3,
            "mrr":        cs.mrr,
            "trust_precision": ct.precision,
            "trust_recall":    ct.recall,
        }

    # ── Print report ──────────────────────────────────────────────────────────
    W = 64
    print()
    print("=" * W)
    print("  AGENTIC PURCHASE 200-QUERY EVALUATION REPORT")
    print("=" * W)
    print(f"  Queries evaluated: {len(successful)}  (image={n_img}, text={n_txt})")
    print()
    print("  INTENT MODELING")
    print(f"    Combined F1:                   {intent_m.f1:.4f}")
    print(f"    Image-mode F1  (n={n_img:<3d}):      {intent_m.image_f1:.4f}  "
          f"[brand+cat+type]")
    print(f"    Text-mode  F1  (n={n_txt:<3d}):      {intent_m.text_f1:.4f}  "
          f"[cat+type]")
    print(f"    Brand accuracy (image):        "
          f"{intent_m.brand_correct_count}/{intent_m.brand_extractable_count}")
    print(f"    Category accuracy (all):       "
          f"{intent_m.n_correct_category}/{len(successful)}")
    print(f"    Product type accuracy (all):   "
          f"{intent_m.n_correct_product_type}/{len(successful)}")
    print()
    print("  SOURCING QUALITY")
    print(f"    NDCG@3: {sourcing_m.ndcg_at_3:.4f}")
    print(f"    MRR:    {sourcing_m.mrr:.4f}")
    print(f"    Avg offers returned: {sourcing_m.avg_offers_returned:.1f}")
    print()
    print("  TRUST EVALUATION")
    print(f"    Precision: {trust_m.precision:.4f}   Recall: {trust_m.recall:.4f}")
    print(f"    VVR  (Vendor Verification Rate):     {trust_m.vvr:.4f}")
    print(f"    FVDR (False Vendor Detection Rate):  {trust_m.fvdr:.4f}")
    print(f"    TP={trust_m.tp}  TN={trust_m.tn}  FP={trust_m.fp}  FN={trust_m.fn}")
    print()
    print("  SYSTEM PERFORMANCE")
    print(f"    Avg latency (image): {avg_img_latency_s:.1f}s")
    print(f"    Avg latency (text):  {avg_txt_latency_s:.1f}s")
    print(f"    Avg latency (all):   {avg_latency_s:.1f}s")
    print(f"    Avg tokens/run:      {avg_tokens:.0f}")
    print(f"    Avg cost/run:        ${avg_cost_usd:.6f}")
    print(f"    Total eval cost:     ${total_cost_usd:.4f}")
    print()
    print("  BY CATEGORY")
    for cat, cm in cat_metrics.items():
        print(f"    {cat:12s}: F1={cm['intent_f1']:.3f}  NDCG={cm['ndcg_at_3']:.3f}  "
              f"MRR={cm['mrr']:.3f}  (n={cm['n']})")
    print("=" * W)

    # ── Save eval_200_final.json ───────────────────────────────────────────────
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    RESULTS_DIR.mkdir(exist_ok=True)

    final = {
        "timestamp": ts,
        "n_queries":  len(successful),
        "n_failed":   n_fail,
        "n_image":    n_img,
        "n_text":     n_txt,
        "intent": {
            "f1":          intent_m.f1,
            "image_f1":    intent_m.image_f1,
            "text_f1":     intent_m.text_f1,
            "precision":   intent_m.precision,
            "recall":      intent_m.recall,
            "n_correct_category":     intent_m.n_correct_category,
            "n_correct_product_type": intent_m.n_correct_product_type,
            "brand_extractable":      intent_m.brand_extractable_count,
            "brand_correct":          intent_m.brand_correct_count,
        },
        "sourcing": {
            "ndcg_at_3":          sourcing_m.ndcg_at_3,
            "mrr":                sourcing_m.mrr,
            "avg_offers_returned": sourcing_m.avg_offers_returned,
        },
        "trust": {
            "precision": trust_m.precision,
            "recall":    trust_m.recall,
            "vvr":       trust_m.vvr,
            "fvdr":      trust_m.fvdr,
            "tp": trust_m.tp, "tn": trust_m.tn,
            "fp": trust_m.fp, "fn": trust_m.fn,
        },
        "performance": {
            "avg_latency_s":      round(avg_latency_s, 2),
            "avg_img_latency_s":  round(avg_img_latency_s, 2),
            "avg_txt_latency_s":  round(avg_txt_latency_s, 2),
            "avg_tokens":         round(avg_tokens, 1),
            "avg_cost_usd":       round(avg_cost_usd, 6),
            "total_cost_usd":     round(total_cost_usd, 4),
        },
        "by_category": cat_metrics,
    }

    final_path = RESULTS_DIR / "eval_200_final.json"
    with open(final_path, "w", encoding="utf-8") as f:
        json.dump(final, f, indent=2)
    print(f"\n  Full metrics saved to: {final_path}")

    # ── Save paper_metrics_200.json (compact, human-readable) ─────────────────
    paper = {
        "dataset":        "200-query multimodal (80 image / 120 text)",
        "categories":     5,
        "queries_per_cat": 40,
        "timestamp":      ts,
        "intent_f1":      intent_m.f1,
        "intent_f1_image": intent_m.image_f1,
        "intent_f1_text":  intent_m.text_f1,
        "ndcg_at_3":      sourcing_m.ndcg_at_3,
        "mrr":            sourcing_m.mrr,
        "trust_precision": trust_m.precision,
        "trust_recall":    trust_m.recall,
        "vvr":             trust_m.vvr,
        "fvdr":            trust_m.fvdr,
        "avg_latency_s":   round(avg_latency_s, 2),
        "avg_tokens":      round(avg_tokens, 0),
        "total_cost_usd":  round(total_cost_usd, 2),
        "n_evaluated":     len(successful),
    }

    paper_path = RESULTS_DIR / "paper_metrics_200.json"
    with open(paper_path, "w", encoding="utf-8") as f:
        json.dump(paper, f, indent=2)
    print(f"  Paper metrics saved to: {paper_path}")


def main() -> None:
    compute_metrics()


if __name__ == "__main__":
    main()
