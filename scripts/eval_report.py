#!/usr/bin/env python
"""Summarize logs/eval.log into CSV/plots for research reporting.

Compatible with both legacy coordinator logs (event-based) and the
new evaluation harness logs produced by scripts/run_eval.py (RUN_*).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import statistics

try:
    import pandas as pd  # optional; fall back to csv only if missing
except Exception:  # pragma: no cover - optional dependency
    pd = None


TOKEN_PRICING_PER_KTOK = {
    # USD per 1K tokens (adjust to match your provider pricing)
    "gpt-4o-mini": {"prompt": 0.15, "completion": 0.60, "system": 0.15},
    "gpt-4o": {"prompt": 5.00, "completion": 15.00, "system": 5.00},
    "gpt-4.1": {"prompt": 3.00, "completion": 9.00, "system": 3.00},
}


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Summarize backend logs/eval.log")
    ap.add_argument("--log", default="backend/logs/eval.log", help="Path to eval log")
    ap.add_argument("--out", default="backend/logs/eval_summary.csv", help="CSV output path (run-level)")
    ap.add_argument("--stages", default="backend/logs/stage_latency.csv", help="Stage latency CSV output")
    ap.add_argument("--tokens", default="backend/logs/token_summary.csv", help="Token CSV output")
    ap.add_argument("--compare", nargs=2, metavar=("LOG_A","LOG_B"), help="Optional: compare two logs (e.g., deterministic vs llm)")
    ap.add_argument("--bootstrap", type=int, default=0, help="Optional: bootstrap iterations for CI (printed to stdout)")
    return ap.parse_args()


def load_events(path: Path):
    events = []
    if not path.exists():
        print(f"[warn] log not found: {path}")
        return events
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def _expand_run_results(events: list[dict]):
    """Extract per-run metrics and per-stage latency rows from RUN_RESULT lines.

    Returns (run_rows, stage_rows).
    """
    run_rows = []
    stage_rows = []
    for ev in events:
        if ev.get("type") != "RUN_RESULT":
            continue
        run_id = ev.get("run_id")
        metrics = ev.get("metrics", {})
        run_rows.append(
            {
                "run_id": run_id,
                "image": ev.get("image"),
                "mode": ev.get("mode"),
                "endpoint": ev.get("endpoint"),
                "base": ev.get("base"),
                **{k: v for k, v in metrics.items()},
            }
        )
        # Expand stage latencies
        for st in (ev.get("events") or []):
            stage = st.get("stage") or st.get("state")
            dt = st.get("dt_s")
            if stage and isinstance(dt, (int, float)):
                stage_rows.append(
                    {
                        "run_id": run_id,
                        "stage": stage,
                        "dt_s": float(dt),
                    }
                )
    return run_rows, stage_rows


def summarize(events: list[dict]):
    """Split events into (run_rows, stage_rows, token_rows).

    - RUN_RESULT entries come from scripts/run_eval.py and contain full context.
    - TOKEN entries come from TokenBudgeter (optional if LLM used).
    - Legacy event lines may use 'event' instead of 'type'; these are ignored
      here but can be inspected manually if present.
    """
    token_rows = [ev for ev in events if ev.get("type") == "TOKEN"]
    run_rows, stage_rows = _expand_run_results(events)
    return run_rows, stage_rows, token_rows


def _norm(s: str | None) -> str:
    return (s or "").strip().lower()


def _relevance_for_offer(offer: dict, expect: dict) -> int:
    """
    Derive a graded relevance from dataset expectations and an offer.
    2 = brand + family match; 1 = brand-only; 0 = otherwise.
    """
    brand = _norm(offer.get("vendor") or offer.get("brand"))
    title = _norm(offer.get("title"))
    exp_brand = _norm(expect.get("brand"))
    exp_family = _norm(expect.get("family"))
    if not exp_brand:
        return 0
    if brand != exp_brand:
        return 0
    if exp_family and exp_family and (exp_family in title):
        return 2
    return 1


def _dcg(gains: list[int], k: int) -> float:
    from math import log2
    s = 0.0
    for i, g in enumerate(gains[:k], start=1):
        s += (2**g - 1) / log2(i + 1)
    return s


def _ndcg_at_k(rels: list[int], k: int) -> float:
    gains = [int(r) for r in rels]
    dcg = _dcg(gains, k)
    ideal = sorted(gains, reverse=True)
    idcg = _dcg(ideal, k)
    return (dcg / idcg) if idcg > 0 else 0.0


def _mrr(rels: list[int]) -> float:
    for i, r in enumerate(rels, start=1):
        if r > 0:
            return 1.0 / i
    return 0.0


def _compute_rank_metrics(run_events: list[dict]) -> list[dict]:
    rows = []
    for ev in run_events:
        if ev.get("type") != "RUN_RESULT":
            continue
        offers = ev.get("offers") or []
        expect = ev.get("expect") or {}
        rels = [_relevance_for_offer(o, expect) for o in offers]
        ndcg3 = _ndcg_at_k(rels, 3)
        mrr = _mrr(rels)
        rows.append({
            "run_id": ev.get("run_id"),
            "image": ev.get("image"),
            "label": ev.get("label"),
            "ndcg3": ndcg3,
            "mrr": mrr,
        })
    return rows


def _bootstrap_ci(values: list[float], iters: int = 1000, alpha: float = 0.05):
    if not values:
        return None
    import random
    n = len(values)
    samples = []
    for _ in range(max(1, iters)):
        draw = [values[random.randrange(0, n)] for _ in range(n)]
        samples.append(sum(draw) / len(draw))
    samples.sort()
    lo_idx = int((alpha/2) * len(samples))
    hi_idx = max(0, int((1 - alpha/2) * len(samples)) - 1)
    return samples[lo_idx], samples[hi_idx]


def write_csv(rows: list[dict], out_path: Path):
    if not rows:
        print(f"[info] no rows to write -> {out_path}")
        return
    keys = sorted({k for row in rows for k in row.keys()})
    out_path.parent.mkdir(parents=True, exist_ok=True)
    import csv
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k) for k in keys})
    print(f"[ok] wrote {out_path}")


def _token_usage_by_run(token_rows: List[dict]) -> Dict[str, Dict[str, float]]:
    usage: Dict[str, Dict[str, float]] = {}
    for row in token_rows or []:
        run_id = row.get("run_id")
        if not run_id:
            continue
        entry = usage.setdefault(run_id, {"prompt": 0, "completion": 0, "system": 0, "total": 0, "usd_cost": 0.0})
        role = (row.get("role") or "prompt").lower()
        n_tokens = int(row.get("n_tokens") or 0)
        entry[role] = entry.get(role, 0) + n_tokens
        entry["total"] += n_tokens
        model = (row.get("model") or "").lower()
        pricing = TOKEN_PRICING_PER_KTOK.get(model)
        if pricing and role in pricing:
            entry["usd_cost"] += (n_tokens / 1000.0) * pricing[role]
    return usage


def _percentile(values: List[float], pct: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    k = (len(ordered) - 1) * pct
    f = int(k)
    c = min(len(ordered) - 1, f + 1)
    if f == c:
        return float(ordered[f])
    d0 = ordered[f] * (c - k)
    d1 = ordered[c] * (k - f)
    return float(d0 + d1)


def _safe_div(num: float, denom: float) -> Optional[float]:
    return (num / denom) if denom else None


def _aggregate_metrics(run_rows: List[dict], stage_rows: List[dict], rank_rows: List[dict], token_usage: Dict[str, Dict[str, float]]):
    if not run_rows:
        return {}
    agg: Dict[str, Optional[float]] = {"runs": len(run_rows)}

    trust_tp = sum(row.get("trust_tp") or 0 for row in run_rows)
    trust_fp = sum(row.get("trust_fp") or 0 for row in run_rows)
    trust_fn = sum(row.get("trust_fn") or 0 for row in run_rows)
    agg["trust_precision"] = _safe_div(trust_tp, trust_tp + trust_fp)
    agg["trust_recall"] = _safe_div(trust_tp, trust_tp + trust_fn)
    if agg["trust_precision"] is not None and agg["trust_recall"] is not None:
        tp = agg["trust_precision"]
        tr = agg["trust_recall"]
        agg["trust_f1"] = (2 * tp * tr / (tp + tr)) if (tp + tr) else None

    intent_tp = sum(row.get("intent_tp") or 0 for row in run_rows)
    intent_fp = sum(row.get("intent_fp") or 0 for row in run_rows)
    intent_fn = sum(row.get("intent_fn") or 0 for row in run_rows)
    agg["intent_precision"] = _safe_div(intent_tp, intent_tp + intent_fp)
    agg["intent_recall"] = _safe_div(intent_tp, intent_tp + intent_fn)
    if agg["intent_precision"] is not None and agg["intent_recall"] is not None:
        ip = agg["intent_precision"]
        ir = agg["intent_recall"]
        agg["intent_f1"] = (2 * ip * ir / (ip + ir)) if (ip + ir) else None

    # Latency stats
    stage_map: Dict[str, List[float]] = defaultdict(list)
    for row in stage_rows or []:
        stage_map[row["stage"]].append(float(row["dt_s"]))
    for stage, vals in stage_map.items():
        p95 = _percentile(vals, 0.95)
        agg[f"latency_{stage}_p95_s"] = round(p95, 4) if p95 is not None else None
        agg[f"latency_{stage}_mean_s"] = round(statistics.mean(vals), 4)
    wall = [float(row.get("dt_wall_s")) for row in run_rows if isinstance(row.get("dt_wall_s"), (int, float))]
    if wall:
        p95_wall = _percentile(wall, 0.95)
        agg["latency_wall_p95_s"] = round(p95_wall, 4) if p95_wall is not None else None
        agg["latency_wall_mean_s"] = round(statistics.mean(wall), 4)

    # Token stats
    prompt_vals = [usage.get("prompt", 0) for usage in token_usage.values()]
    completion_vals = [usage.get("completion", 0) for usage in token_usage.values()]
    total_vals = [usage.get("total", 0) for usage in token_usage.values()]
    cost_vals = [usage.get("usd_cost", 0.0) for usage in token_usage.values()]
    if prompt_vals:
        agg["tokens_prompt_avg"] = round(statistics.mean(prompt_vals), 2)
    if completion_vals:
        agg["tokens_completion_avg"] = round(statistics.mean(completion_vals), 2)
    if total_vals:
        agg["tokens_total_avg"] = round(statistics.mean(total_vals), 2)
    if cost_vals:
        agg["usd_cost_avg"] = round(statistics.mean(cost_vals), 6)

    if rank_rows:
        ndcg_vals = [row.get("ndcg3", 0.0) for row in rank_rows]
        mrr_vals = [row.get("mrr", 0.0) for row in rank_rows]
        agg["ndcg3_mean"] = round(statistics.mean(ndcg_vals), 4)
        agg["mrr_mean"] = round(statistics.mean(mrr_vals), 4)

    return agg


def main():
    args = parse_args()
    events = load_events(Path(args.log))
    run_rows, stage_rows, token_rows = summarize(events)
    token_usage = _token_usage_by_run(token_rows)
    for row in run_rows:
        usage = token_usage.get(row.get("run_id"), {})
        row["tokens_prompt"] = usage.get("prompt", 0)
        row["tokens_completion"] = usage.get("completion", 0)
        row["tokens_system"] = usage.get("system", 0)
        row["tokens_total"] = usage.get("total", 0)
        row["usd_cost"] = round(usage.get("usd_cost", 0.0), 6)
    write_csv(run_rows, Path(args.out))
    write_csv(stage_rows, Path(args.stages))
    write_csv(token_rows, Path(args.tokens))

    if pd is not None and run_rows:
        df = pd.DataFrame(run_rows)
        print("\nRun-level metrics (means):")
        num_cols = [c for c in df.columns if c.startswith("dt_") or c.endswith("_hit")]
        if num_cols:
            print(df[num_cols].mean(numeric_only=True))
        if stage_rows:
            sdf = pd.DataFrame(stage_rows)
            print("\nStage latency p95:")
            print(sdf.groupby("stage")["dt_s"].quantile(0.95))
        if token_rows:
            tdf = pd.DataFrame(token_rows)
            print("\nToken usage by state:")
            print(tdf.groupby(["state", "role"]).agg({"n_tokens": "sum"}))

    # Ranking metrics (NDCG@3, MRR)
    rank_rows = _compute_rank_metrics(events)
    if rank_rows:
        write_csv(rank_rows, Path(str(Path(args.out).with_name("ranking_metrics.csv"))))
        if pd is not None:
            rdf = pd.DataFrame(rank_rows)
            print("\nRanking metrics (means):")
            print(rdf[["ndcg3", "mrr"]].mean(numeric_only=True))
            if args.bootstrap and args.bootstrap > 0:
                for col in ("ndcg3", "mrr"):
                    vals = rdf[col].dropna().tolist()
                    ci = _bootstrap_ci(vals, iters=args.bootstrap)
                    if ci:
                        print(f"  {col} bootstrap {args.bootstrap} iters CI95: {ci}")

    # Optional compare mode: summarize differences between two logs
    if args.compare and len(args.compare) == 2:
        a_events = load_events(Path(args.compare[0]))
        b_events = load_events(Path(args.compare[1]))
        a_rank = _compute_rank_metrics(a_events)
        b_rank = _compute_rank_metrics(b_events)
        if pd is not None and a_rank and b_rank:
            adf = pd.DataFrame(a_rank)
            bdf = pd.DataFrame(b_rank)
            # Merge on image if present, fallback to index
            key = "image" if "image" in adf.columns and "image" in bdf.columns else "run_id"
            m = adf[[key, "ndcg3", "mrr"]].merge(bdf[[key, "ndcg3", "mrr"]], on=key, suffixes=("_A","_B"))
            print("\nCompare mode (A vs B) means:")
            print(m[["ndcg3_A","ndcg3_B","mrr_A","mrr_B"]].mean(numeric_only=True))
            cmp_path = Path(str(Path(args.out).with_name("ranking_compare.csv")))
            write_csv(m.to_dict(orient="records"), cmp_path)

    aggregate = _aggregate_metrics(run_rows, stage_rows, rank_rows, token_usage)
    if aggregate:
        agg_path = Path(str(Path(args.out).with_name("aggregate_metrics.csv")))
        write_csv([aggregate], agg_path)
        print("\nAggregate metrics:")
        for key, value in aggregate.items():
            if value is None:
                continue
            if key == "runs":
                print(f"  runs: {value}")
                continue
            print(f"  {key}: {value}")


if __name__ == "__main__":
    sys.exit(main())
