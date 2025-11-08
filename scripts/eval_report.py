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

try:
    import pandas as pd  # optional; fall back to csv only if missing
except Exception:  # pragma: no cover - optional dependency
    pd = None


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Summarize Agentic_AI logs/eval.log")
    ap.add_argument("--log", default="Agentic_AI/logs/eval.log", help="Path to eval log")
    ap.add_argument("--out", default="Agentic_AI/logs/eval_summary.csv", help="CSV output path (run-level)")
    ap.add_argument("--stages", default="Agentic_AI/logs/stage_latency.csv", help="Stage latency CSV output")
    ap.add_argument("--tokens", default="Agentic_AI/logs/token_summary.csv", help="Token CSV output")
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


def main():
    args = parse_args()
    events = load_events(Path(args.log))
    run_rows, stage_rows, token_rows = summarize(events)
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


if __name__ == "__main__":
    sys.exit(main())
