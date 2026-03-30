"""
Standalone trust injection evaluation runner.

Usage:
  python -m backend.evaluation.run_trust_eval

Loads the most recent multimodal eval results for context, generates 115
synthetic labeled offers, runs the two-session trust pipeline on each, then
prints a full confusion matrix and breakdown by injection type.

Offer set (115 total):
  15 replica_keyword   — titles use exact words from session1._REPLICA_PATTERNS
  15 novel_vocabulary  — titles use ZERO words from _REPLICA_PATTERNS (LLM-only test)
  15 price_anomaly     — clean titles, price at ~8% of market
  15 brand_mismatch    — listing brand disagrees with vision-detected brand
  15 combined          — replica keywords + anomalously low price
  40 authentic         — clean controls at normal prices

VVR reported here is from the injection eval (75 suspicious / 40 authentic).
It is NOT the trivially-true VVR=1.00 that appears in the main eval (where
eBay returns no counterfeit listings, making FN=0 always).

Does NOT re-run the full saga — completely standalone from the main eval.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path


def _find_latest_results() -> Path | None:
    """Return the most recent eval_results_multimodal_*.json path, or None."""
    results_dir = Path(__file__).parent / "results"
    files = sorted(results_dir.glob("eval_results_multimodal_*.json"))
    return files[-1] if files else None


def _print_report(m) -> None:
    W = 62
    print()
    print("=" * W)
    print("  TRUST EVALUATION REPORT (INJECTION METHOD, v2 — 115 offers)")
    print("=" * W)
    print(f"Synthetic offers evaluated: {m.n_evaluated}")
    print(f"  Suspicious injected: {m.n_suspicious}"
          f"  (replica:15, novel:15, price:15, brand:15, combined:15)")
    print(f"  Authentic controls:  {m.n_authentic}")
    print()
    print("CONFUSION MATRIX")
    print(f"  TP (correctly flagged suspicious): {m.tp:3d}")
    print(f"  TN (correctly cleared authentic):  {m.tn:3d}")
    print(f"  FP (wrongly flagged authentic):    {m.fp:3d}")
    print(f"  FN (missed suspicious):            {m.fn:3d}")
    print()
    print("TRUST METRICS")
    print(f"  Precision: {m.precision:.4f}")
    print(f"  Recall:    {m.recall:.4f}")
    print(f"  VVR (injection eval, TN/(TN+FN)):  {m.vvr:.4f}")
    print(f"  FVDR (injection eval, FP/(FP+TN)): {m.fvdr:.4f}")
    print()
    print("  NOTE: VVR above is computed within this injection eval only.")
    print("        Main-eval VVR=1.00 is trivially true (eBay returns no")
    print("        counterfeit listings) and does NOT reflect capability.")
    print()
    print("BREAKDOWN BY INJECTION TYPE")
    print(f"  Replica keywords (Session 1 pattern):  {m.replica_detected:2d}/15 detected")
    print(f"  Novel vocabulary (LLM reasoning only): {m.novel_detected:2d}/15 detected")
    print(f"    NOTE: 1 of 15 novel titles contains 'replica' (per spec)")
    print(f"          and is detectable by Session 1 — not a pure LLM test.")
    print(f"  Price anomaly:                         {m.price_detected:2d}/15 detected")
    print(f"  Brand mismatch:                        {m.brand_detected:2d}/15 detected")
    print(f"  Combined signals:                      {m.combined_detected:2d}/15 detected")
    print(f"  Authentic controls:                    {m.authentic_cleared:2d}/40 correctly cleared")
    print()
    print("PERFORMANCE")
    print(f"  LLM calls:            {m.total_llm_calls}")
    print(f"  Input tokens:         {m.total_input_tokens:,}")
    print(f"  Output tokens:        {m.total_output_tokens:,}")
    print(f"  Estimated cost:       ${m.estimated_cost_usd:.4f}")
    print(f"  Wall-clock time:      {m.duration_s:.1f}s")
    print("=" * W)


def _save_results(m, latest_results_path: Path | None) -> None:
    out_dir = Path(__file__).parent / "results"
    out_dir.mkdir(exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    payload = {
        "timestamp": ts,
        "version": "v2_115_offers",
        "source_eval": str(latest_results_path) if latest_results_path else None,
        "metrics": {
            "precision":    m.precision,
            "recall":       m.recall,
            "vvr":          m.vvr,
            "vvr_note":     "injection eval only — main eval VVR=1.00 is trivially true",
            "fvdr":         m.fvdr,
            "n_evaluated":  m.n_evaluated,
            "n_suspicious": m.n_suspicious,
            "n_authentic":  m.n_authentic,
            "tp": m.tp, "tn": m.tn, "fp": m.fp, "fn": m.fn,
        },
        "breakdown": {
            "replica_keyword":    {"detected": m.replica_detected,  "total": 15,
                                   "note": "uses exact words from session1._REPLICA_PATTERNS"},
            "novel_vocabulary":   {"detected": m.novel_detected,    "total": 15,
                                   "note": "LLM-only test; 1/15 contains 'replica' per spec"},
            "price_anomaly":      {"detected": m.price_detected,    "total": 15},
            "brand_mismatch":     {"detected": m.brand_detected,    "total": 15},
            "combined":           {"detected": m.combined_detected,  "total": 15},
            "authentic_controls": {"cleared": m.authentic_cleared,  "total": 40},
        },
        "llm_usage": {
            "calls":              m.total_llm_calls,
            "input_tokens":       m.total_input_tokens,
            "output_tokens":      m.total_output_tokens,
            "estimated_cost_usd": m.estimated_cost_usd,
        },
        "duration_s": m.duration_s,
        "details": m.details,
    }

    out_path = out_dir / "trust_injection_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print(f"\nResults saved to: {out_path}")


async def run() -> None:
    from backend.evaluation.synthetic_offers import generate_labeled_offers
    from backend.evaluation.eval_trust_injection import evaluate_trust_injection

    # Locate the reference multimodal results (for provenance only)
    latest = _find_latest_results()
    if latest:
        print(f"Reference eval: {latest.name}")
    else:
        print("No prior multimodal results found — running injection standalone.")

    # Generate 115 synthetic labeled offers
    print("\nGenerating 115 synthetic labeled offers...")
    labeled_offers = generate_labeled_offers()
    n_susp = sum(1 for lo in labeled_offers if lo.ground_truth == "SUSPICIOUS")
    n_auth = sum(1 for lo in labeled_offers if lo.ground_truth == "AUTHENTIC")
    by_type: dict[str, int] = {}
    for lo in labeled_offers:
        by_type[lo.injection_type] = by_type.get(lo.injection_type, 0) + 1
    print(f"  Suspicious: {n_susp}  |  Authentic: {n_auth}")
    for t, c in sorted(by_type.items()):
        print(f"    {t:25s}: {c}")

    print("\nRunning two-session trust pipeline (1 LLM call per offer)...")
    print("Progress updates every 10 offers.\n")

    metrics = await evaluate_trust_injection(labeled_offers)

    _print_report(metrics)
    _save_results(metrics, latest)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
