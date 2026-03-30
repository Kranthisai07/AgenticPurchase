"""
Ablation study for Agentic Purchase v2.

Evaluates three configurations across the same 50-query dataset and 115 synthetic offers:

  Config A — Deterministic Baseline (no LLM anywhere)
  Config B — Full LLM (loaded from eval_definitive_final.json, no re-run)
  Config C — LLM + Trust Only (Trust Session 2 LLM active, all others deterministic)

Invocation:
  python -m backend.evaluation.run_ablation

Results saved to:
  backend/evaluation/results/ablation_config_a.json
  backend/evaluation/results/ablation_config_c.json
  backend/evaluation/results/ablation_final.json
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

RESULTS_DIR = Path(__file__).parent / "results"
_BLENDED_RATE = 0.0000065  # $0.0000065/token blended


# ── Per-config results container ──────────────────────────────────────────────

@dataclass
class AblationResult:
    config:         str
    label:          str

    # Intent / Sourcing / Trust (in-pipeline)
    intent_f1:       float
    ndcg_at_3:       float
    mrr:             float
    trust_precision: float
    trust_recall:    float
    trust_vvr:       float
    trust_fvdr:      float

    # Trust injection
    inj_precision:   float
    inj_recall:      float
    inj_vvr:         float
    inj_fvdr:        float
    inj_tp:          int
    inj_tn:          int
    inj_fp:          int
    inj_fn:          int
    inj_replica:     int
    inj_novel:       int
    inj_price:       int
    inj_brand:       int
    inj_combined:    int
    inj_authentic:   int

    # Performance
    avg_latency_s:   float
    avg_tokens:      float
    avg_cost_usd:    float
    total_cost_usd:  float
    n_success:       int
    n_fail:          int

    # Trust injection cost
    inj_cost_usd:    float = 0.0
    llm_calls:       int = 0


# ── Load Config B from canonical file ────────────────────────────────────────

def _load_config_b() -> AblationResult:
    """Load Config B from eval_definitive_final.json and trust_definitive_final.json."""
    eval_path  = RESULTS_DIR / "eval_definitive_final.json"
    trust_path = RESULTS_DIR / "trust_definitive_final.json"

    with open(eval_path, encoding="utf-8") as f:
        ev = json.load(f)
    with open(trust_path, encoding="utf-8") as f:
        tr = json.load(f)

    perf     = ev["system_performance"]
    inj      = tr["trust_metrics"]
    brk      = tr.get("breakdown_by_injection_type", {})
    llm_use  = tr.get("llm_usage", {})

    return AblationResult(
        config="B",
        label="Full LLM",
        intent_f1       = ev["intent_modeling"]["combined_weighted_f1"],
        ndcg_at_3       = ev["sourcing_quality"]["ndcg_at_3"],
        mrr             = ev["sourcing_quality"]["mrr"],
        trust_precision = ev["trust_evaluation_in_pipeline"]["precision"],
        trust_recall    = ev["trust_evaluation_in_pipeline"]["recall"],
        trust_vvr       = ev["trust_evaluation_in_pipeline"]["vvr"],
        trust_fvdr      = ev["trust_evaluation_in_pipeline"]["fvdr"],
        inj_precision   = inj["precision"],
        inj_recall      = inj["recall"],
        inj_vvr         = inj["vvr"],
        inj_fvdr        = inj["fvdr"],
        inj_tp          = inj["tp"],
        inj_tn          = inj["tn"],
        inj_fp          = inj["fp"],
        inj_fn          = inj["fn"],
        inj_replica     = brk.get("replica_keyword", {}).get("detected", 0),
        inj_novel       = brk.get("novel_vocabulary", {}).get("detected", 0),
        inj_price       = brk.get("price_anomaly", {}).get("detected", 0),
        inj_brand       = brk.get("brand_mismatch", {}).get("detected", 0),
        inj_combined    = brk.get("combined", {}).get("detected", 0),
        inj_authentic   = brk.get("authentic_controls", {}).get("cleared", 0),
        avg_latency_s   = perf["avg_latency_overall_s"],
        avg_tokens      = perf["avg_tokens_per_run"],
        avg_cost_usd    = perf["avg_cost_per_run_usd"],
        total_cost_usd  = perf["total_evaluation_cost_usd"],
        n_success       = ev["saga_evaluation"]["succeeded"],
        n_fail          = ev["saga_evaluation"]["failed"],
        inj_cost_usd    = llm_use.get("estimated_cost_usd", 0.0),
        llm_calls       = llm_use.get("calls", 0),
    )


# ── Run one saga eval pass ────────────────────────────────────────────────────

async def _run_saga_pass(config_label: str) -> tuple[list, object, object]:
    """
    Run the full 50-query evaluation using the currently patched agent classes.
    Returns (saga_results, intent_metrics, sourcing_metrics).
    """
    from backend.evaluation.run_eval import (
        _build_orchestrator,
        _run_one_query,
        _IMAGE_QUERY_IDS,
        load_image_bytes,
    )
    from backend.evaluation.dataset import QUERIES
    from backend.evaluation.eval_intent import evaluate_intent
    from backend.evaluation.eval_sourcing import evaluate_sourcing
    from backend.evaluation.eval_trust import evaluate_trust

    orchestrator, bus = _build_orchestrator()
    results = []

    print(f"\n  Running Config {config_label} — 50 queries...")
    for i, query in enumerate(QUERIES):
        image_bytes = load_image_bytes(query.query_id)
        mode = "[IMG]" if image_bytes is not None else "[TXT]"
        print(f"  [{i+1:2d}/50] {mode} {query.query_id}: {query.text[:45]}...")
        result = await _run_one_query(orchestrator, bus, query, image_bytes=image_bytes)
        status = "OK" if result.success else f"FAIL ({result.error or 'unknown'})"
        print(f"         -> {status}  | {result.duration_ms:.0f}ms | {result.total_tokens} tok")
        results.append(result)

    n_success = sum(1 for r in results if r.success)
    n_fail    = len(results) - n_success
    print(f"\n  Config {config_label}: {n_success}/50 succeeded, {n_fail} failed")

    intent_m   = evaluate_intent(results)
    sourcing_m = evaluate_sourcing(results)
    trust_m    = evaluate_trust(results)
    return results, intent_m, sourcing_m, trust_m


# ── Run trust injection eval for Config A ─────────────────────────────────────

async def _run_trust_injection_config_a(labeled_offers: list) -> dict:
    """Config A: Session 1 only (no LLM) for the injection evaluation."""
    from backend.evaluation.ablation_configs import evaluate_trust_injection_deterministic
    print("\n  Running trust injection (Config A — Session 1 only)...")
    result = await evaluate_trust_injection_deterministic(labeled_offers)
    print(f"  Config A injection: TP={result['tp']} TN={result['tn']} "
          f"FP={result['fp']} FN={result['fn']}")
    return result


# ── Run trust injection eval for Config C ─────────────────────────────────────

async def _run_trust_injection_config_c(labeled_offers: list) -> dict:
    """Config C: full Session 1 + Session 2 LLM — identical to Config B."""
    from backend.evaluation.eval_trust_injection import evaluate_trust_injection
    print("\n  Running trust injection (Config C — full Session 1+2, same as Config B)...")
    metrics = await evaluate_trust_injection(labeled_offers)
    brk = {
        "tp": metrics.tp, "tn": metrics.tn, "fp": metrics.fp, "fn": metrics.fn,
        "precision":         metrics.precision,
        "recall":            metrics.recall,
        "vvr":               metrics.vvr,
        "fvdr":              metrics.fvdr,
        "n_evaluated":       metrics.n_evaluated,
        "n_suspicious":      metrics.n_suspicious,
        "n_authentic":       metrics.n_authentic,
        "replica_detected":  metrics.replica_detected,
        "novel_detected":    metrics.novel_detected,
        "price_detected":    metrics.price_detected,
        "brand_detected":    metrics.brand_detected,
        "combined_detected": metrics.combined_detected,
        "authentic_cleared": metrics.authentic_cleared,
        "llm_calls":         metrics.total_llm_calls,
        "estimated_cost_usd": metrics.estimated_cost_usd,
        "duration_s":        metrics.duration_s,
    }
    print(f"  Config C injection: TP={metrics.tp} TN={metrics.tn} "
          f"FP={metrics.fp} FN={metrics.fn}")
    return brk


# ── Build AblationResult from saga + injection results ────────────────────────

def _build_result(
    config: str,
    label: str,
    results: list,
    intent_m,
    sourcing_m,
    trust_m,
    inj: dict,
) -> AblationResult:
    successful  = [r for r in results if r.success]
    avg_lat     = sum(r.duration_ms for r in successful) / len(successful) / 1000 if successful else 0.0
    avg_tokens  = sum(r.total_tokens for r in successful) / len(successful) if successful else 0.0
    avg_cost    = avg_tokens * _BLENDED_RATE
    total_cost  = sum(r.total_tokens for r in successful) * _BLENDED_RATE

    return AblationResult(
        config=config,
        label=label,
        intent_f1       = intent_m.f1,
        ndcg_at_3       = sourcing_m.ndcg_at_3,
        mrr             = sourcing_m.mrr,
        trust_precision = trust_m.precision,
        trust_recall    = trust_m.recall,
        trust_vvr       = trust_m.vvr,
        trust_fvdr      = trust_m.fvdr,
        inj_precision   = inj["precision"],
        inj_recall      = inj["recall"],
        inj_vvr         = inj["vvr"],
        inj_fvdr        = inj["fvdr"],
        inj_tp          = inj["tp"],
        inj_tn          = inj["tn"],
        inj_fp          = inj["fp"],
        inj_fn          = inj["fn"],
        inj_replica     = inj.get("replica_detected", 0),
        inj_novel       = inj.get("novel_detected", 0),
        inj_price       = inj.get("price_detected", 0),
        inj_brand       = inj.get("brand_detected", 0),
        inj_combined    = inj.get("combined_detected", 0),
        inj_authentic   = inj.get("authentic_cleared", 0),
        avg_latency_s   = round(avg_lat, 1),
        avg_tokens      = round(avg_tokens, 1),
        avg_cost_usd    = round(avg_cost, 6),
        total_cost_usd  = round(total_cost, 4),
        n_success       = sum(1 for r in results if r.success),
        n_fail          = sum(1 for r in results if not r.success),
        inj_cost_usd    = inj.get("estimated_cost_usd", 0.0),
        llm_calls       = inj.get("llm_calls", 0),
    )


# ── Save individual config results ────────────────────────────────────────────

def _save_config_result(
    config: str,
    results: list,
    intent_m,
    sourcing_m,
    trust_m,
    inj: dict,
    ablation_result: AblationResult,
) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    per_query = []
    for r in results:
        per_query.append({
            "query_id": r.query_id,
            "query_text": r.query.text,
            "has_image": r.has_image,
            "success": r.success,
            "error": r.error,
            "duration_ms": r.duration_ms,
            "total_tokens": r.total_tokens,
            "intent_output": r.intent_output,
            "n_ranked_offers": len(r.ranked_offers),
        })

    data = {
        "code_version": "post_security_fixes",
        "ablation_config": config,
        "test_suite": "53/53",
        "timestamp": ts,
        "intent": {"f1": intent_m.f1, "image_f1": intent_m.image_f1, "text_f1": intent_m.text_f1},
        "sourcing": {"ndcg_at_3": sourcing_m.ndcg_at_3, "mrr": sourcing_m.mrr},
        "trust_in_pipeline": {
            "precision": trust_m.precision,
            "recall": trust_m.recall,
            "vvr": trust_m.vvr,
            "fvdr": trust_m.fvdr,
        },
        "trust_injection": inj,
        "performance": {
            "avg_latency_s": ablation_result.avg_latency_s,
            "avg_tokens": ablation_result.avg_tokens,
            "avg_cost_usd": ablation_result.avg_cost_usd,
            "total_cost_usd": ablation_result.total_cost_usd,
        },
        "saga": {"succeeded": ablation_result.n_success, "failed": ablation_result.n_fail},
        "per_query": per_query,
    }

    out_path = RESULTS_DIR / f"ablation_config_{config.lower()}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"\n  Saved: {out_path}")


# ── Print comparison table ────────────────────────────────────────────────────

def _print_ablation_table(a: AblationResult, b: AblationResult, c: AblationResult) -> None:
    W = 70

    def row(label: str, va, vb, vc, fmt=".4f") -> None:
        print(f"  {label:<26} {va:{fmt}}        {vb:{fmt}}        {vc:{fmt}}")

    print()
    print("=" * W)
    print("  ABLATION STUDY RESULTS — Agentic Purchase v2")
    print("=" * W)
    print(f"  {'Metric':<26} {'Config A':^12}  {'Config B':^12}  {'Config C':^12}")
    print(f"  {'':26} {'Deterministic':^12}  {'Full LLM':^12}  {'Trust Only':^12}")
    print(f"  {'':26} {'(No LLM)':^12}  {'':^12}  {'':^12}")
    print("-" * W)
    print("  INTENT + SOURCING")
    row("  Recall (F1)",   a.intent_f1,  b.intent_f1,  c.intent_f1)
    row("  NDCG@3",        a.ndcg_at_3,  b.ndcg_at_3,  c.ndcg_at_3)
    row("  MRR",           a.mrr,        b.mrr,        c.mrr)
    print()
    print("  TRUST (injection eval, 115 offers)")
    row("  Precision",     a.inj_precision, b.inj_precision, c.inj_precision)
    row("  Recall",        a.inj_recall,    b.inj_recall,    c.inj_recall)
    row("  VVR",           a.inj_vvr,       b.inj_vvr,       c.inj_vvr)
    row("  FVDR",          a.inj_fvdr,      b.inj_fvdr,      c.inj_fvdr)
    print()
    print("  TRUST INJECTION BREAKDOWN (detected / 15)")
    def brow(label, va, vb, vc):
        print(f"  {label:<26} {va:>5}/15       {vb:>5}/15       {vc:>5}/15")
    brow("  Replica keywords",  a.inj_replica, b.inj_replica, c.inj_replica)
    brow("  Novel vocabulary",  a.inj_novel,   b.inj_novel,   c.inj_novel)
    brow("  Price anomaly",     a.inj_price,   b.inj_price,   c.inj_price)
    brow("  Brand mismatch",    a.inj_brand,   b.inj_brand,   c.inj_brand)
    brow("  Combined",          a.inj_combined,b.inj_combined,c.inj_combined)
    def arow(label, va, vb, vc):
        print(f"  {label:<26} {va:>5}/40       {vb:>5}/40       {vc:>5}/40")
    arow("  Authentic cleared", a.inj_authentic,b.inj_authentic,c.inj_authentic)
    print()
    print("  SYSTEM PERFORMANCE")
    print(f"  {'Avg time (s)':<26} {a.avg_latency_s:>8.1f}      {b.avg_latency_s:>8.1f}      {c.avg_latency_s:>8.1f}")
    print(f"  {'Avg tokens':<26} {a.avg_tokens:>8.0f}      {b.avg_tokens:>8.0f}      {c.avg_tokens:>8.0f}")
    print(f"  {'Avg cost/run ($)':<26} {a.avg_cost_usd:>8.6f}  {b.avg_cost_usd:>8.6f}  {c.avg_cost_usd:>8.6f}")
    print("=" * W)


# ── Sanity checks ─────────────────────────────────────────────────────────────

def _run_sanity_checks(a: AblationResult, b: AblationResult, c: AblationResult) -> list[str]:
    """
    Verify expected ordering across configs.
    Returns a list of warning messages (empty = all pass).
    """
    warnings: list[str] = []

    def check(metric, a_val, b_val, c_val, label: str, higher_is_better: bool = True):
        if higher_is_better:
            if a_val > b_val:
                warnings.append(
                    f"FAIL [{label}]: Config A ({a_val:.4f}) > Config B ({b_val:.4f}) — "
                    "expected A < B (no LLM should underperform full LLM)"
                )
            if c_val < a_val:
                warnings.append(
                    f"WARN [{label}]: Config C ({c_val:.4f}) < Config A ({a_val:.4f}) — "
                    "Trust-only should at least match deterministic"
                )
        else:  # lower is better (e.g. FVDR, cost)
            if a_val < b_val:
                warnings.append(
                    f"WARN [{label}]: Config A ({a_val:.4f}) < Config B ({b_val:.4f}) — "
                    "expected A >= B for this metric"
                )

    check("intent_f1",    a.intent_f1, b.intent_f1, c.intent_f1, "Intent F1")
    check("ndcg_at_3",    a.ndcg_at_3, b.ndcg_at_3, c.ndcg_at_3, "NDCG@3")
    check("mrr",          a.mrr,       b.mrr,       c.mrr,       "MRR")
    check("inj_recall",   a.inj_recall, b.inj_recall, c.inj_recall, "Injection Recall")
    check("latency",      a.avg_latency_s, b.avg_latency_s, c.avg_latency_s,
          "Avg latency", higher_is_better=False)  # lower = better for A

    return warnings


# ── Save final ablation table ─────────────────────────────────────────────────

def _save_ablation_final(
    a: AblationResult,
    b: AblationResult,
    c: AblationResult,
    sanity_warnings: list[str],
    total_new_cost_usd: float,
) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    def _row(r: AblationResult) -> dict:
        return asdict(r)

    data = {
        "code_version":     "post_security_fixes",
        "test_suite":       "53/53",
        "timestamp":        ts,
        "note": (
            "Config B loaded from eval_definitive_final.json + trust_definitive_final.json. "
            "Configs A and C were re-run from scratch with agent patches."
        ),
        "total_new_eval_cost_usd": round(total_new_cost_usd, 4),
        "sanity_checks": {
            "passed": len(sanity_warnings) == 0,
            "warnings": sanity_warnings,
        },
        "config_a": _row(a),
        "config_b": _row(b),
        "config_c": _row(c),
        "comparison_table": {
            "metrics": ["intent_f1", "ndcg_at_3", "mrr", "inj_recall",
                        "inj_vvr", "inj_fvdr", "avg_latency_s"],
            "config_a": [a.intent_f1, a.ndcg_at_3, a.mrr, a.inj_recall,
                         a.inj_vvr, a.inj_fvdr, a.avg_latency_s],
            "config_b": [b.intent_f1, b.ndcg_at_3, b.mrr, b.inj_recall,
                         b.inj_vvr, b.inj_fvdr, b.avg_latency_s],
            "config_c": [c.intent_f1, c.ndcg_at_3, c.mrr, c.inj_recall,
                         c.inj_vvr, c.inj_fvdr, c.avg_latency_s],
        },
    }

    out_path = RESULTS_DIR / "ablation_final.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"\nFinal ablation table saved to: {out_path}")


# ── Main orchestration ────────────────────────────────────────────────────────

async def run_ablation() -> None:
    from backend.evaluation.ablation_configs import apply_config, restore_all, AblationMode
    from backend.evaluation.synthetic_offers import generate_labeled_offers

    RESULTS_DIR.mkdir(exist_ok=True)
    ts_start = datetime.now(timezone.utc)
    t_global_start = time.monotonic()

    print(f"\n{'='*70}")
    print("  ABLATION STUDY — Agentic Purchase v2")
    print(f"  Started: {ts_start.isoformat()}")
    print(f"{'='*70}")

    # ── Config B: load from canonical file (no re-run) ────────────────────────
    print("\n[Config B — Full LLM] Loading from eval_definitive_final.json...")
    config_b = _load_config_b()
    print(f"  Loaded: intent_f1={config_b.intent_f1:.4f}  "
          f"ndcg={config_b.ndcg_at_3:.4f}  mrr={config_b.mrr:.4f}")

    # ── Generate synthetic offers (shared across Config A and C injection evals)
    print("\nGenerating 115 synthetic labeled offers for trust injection...")
    labeled_offers = generate_labeled_offers()
    print(f"  Generated {len(labeled_offers)} offers")

    # ─────────────────────────────────────────────────────────────────────────
    # Config A — Deterministic Baseline
    # ─────────────────────────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print("  CONFIG A — Deterministic Baseline (No LLM)")
    print(f"{'='*70}")

    print("  Applying Config A patches...")
    apply_config(AblationMode.DETERMINISTIC)
    try:
        t0 = time.monotonic()
        results_a, intent_a, sourcing_a, trust_a = await _run_saga_pass("A")
        inj_a = await _run_trust_injection_config_a(labeled_offers)
        elapsed_a = time.monotonic() - t0
    finally:
        restore_all()
        print("  Config A patches restored.")

    config_a = _build_result("A", "Deterministic (No LLM)",
                              results_a, intent_a, sourcing_a, trust_a, inj_a)
    _save_config_result("A", results_a, intent_a, sourcing_a, trust_a, inj_a, config_a)

    # ─────────────────────────────────────────────────────────────────────────
    # Config C — LLM + Trust Only
    # ─────────────────────────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print("  CONFIG C — LLM + Trust Only")
    print(f"{'='*70}")

    print("  Applying Config C patches...")
    apply_config(AblationMode.TRUST_ONLY)
    try:
        t0 = time.monotonic()
        results_c, intent_c, sourcing_c, trust_c = await _run_saga_pass("C")
        inj_c = await _run_trust_injection_config_c(labeled_offers)
        elapsed_c = time.monotonic() - t0
    finally:
        restore_all()
        print("  Config C patches restored.")

    config_c = _build_result("C", "LLM + Trust Only",
                              results_c, intent_c, sourcing_c, trust_c, inj_c)
    _save_config_result("C", results_c, intent_c, sourcing_c, trust_c, inj_c, config_c)

    # ─────────────────────────────────────────────────────────────────────────
    # Print comparison table
    # ─────────────────────────────────────────────────────────────────────────
    _print_ablation_table(config_a, config_b, config_c)

    # ─────────────────────────────────────────────────────────────────────────
    # Sanity checks
    # ─────────────────────────────────────────────────────────────────────────
    warnings = _run_sanity_checks(config_a, config_b, config_c)
    print()
    if warnings:
        print("SANITY CHECK WARNINGS:")
        for w in warnings:
            print(f"  {w}")
    else:
        print("SANITY CHECKS: All passed.")

    # ─────────────────────────────────────────────────────────────────────────
    # Cost summary
    # ─────────────────────────────────────────────────────────────────────────
    total_new_cost = (
        config_a.total_cost_usd + config_a.inj_cost_usd +
        config_c.total_cost_usd + config_c.inj_cost_usd
    )

    print()
    print("COST SUMMARY")
    print(f"  Config A saga eval:           ${config_a.total_cost_usd:.4f} (no LLM calls)")
    print(f"  Config A trust injection:     ${config_a.inj_cost_usd:.4f} (no LLM calls)")
    print(f"  Config C saga eval:           ${config_c.total_cost_usd:.4f}")
    print(f"  Config C trust injection:     ${config_c.inj_cost_usd:.4f}")
    print(f"  Total new cost (A+C):         ${total_new_cost:.4f}")

    # ─────────────────────────────────────────────────────────────────────────
    # Save final ablation JSON
    # ─────────────────────────────────────────────────────────────────────────
    _save_ablation_final(config_a, config_b, config_c, warnings, total_new_cost)

    total_elapsed = time.monotonic() - t_global_start
    print()
    print("ABLATION STUDY COMPLETE")
    print(f"  Total runtime: {total_elapsed:.0f}s  "
          f"(Config A: {elapsed_a:.0f}s, Config C: {elapsed_c:.0f}s)")


def main() -> None:
    asyncio.run(run_ablation())


if __name__ == "__main__":
    main()
