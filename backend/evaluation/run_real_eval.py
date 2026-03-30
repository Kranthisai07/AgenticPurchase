"""
Master script for the real-world trust evaluation pipeline.

Invocation:
  python -m backend.evaluation.run_real_eval               # full pipeline
  python -m backend.evaluation.run_real_eval --collect-only  # collect + label only
  python -m backend.evaluation.run_real_eval --eval-only     # eval on existing labeled data

Pipeline:
  1. collect_real_listings.py  — fetch from eBay + SerpApi, deduplicate
  2. real_listing_dataset.py   — auto-label with rule-based logic
  3. eval_trust_real.py        — run Session 1 + Session 2 against labeled data
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

RESULTS_DIR = Path(__file__).parent / "results"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Real-world trust evaluation pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--collect-only",
        action="store_true",
        help="Only collect listings and apply auto-labeling (no trust eval)",
    )
    parser.add_argument(
        "--eval-only",
        action="store_true",
        help="Skip collection; run trust eval on existing real_listings_labeled.json",
    )
    args = parser.parse_args()

    if args.collect_only and args.eval_only:
        print("ERROR: --collect-only and --eval-only are mutually exclusive.")
        sys.exit(1)

    if args.eval_only:
        # Phase 3 only
        _check_file(RESULTS_DIR / "real_listings_labeled.json", step="real_listing_dataset")
        asyncio.run(_run_eval())
        return

    # Phase 1: Collection
    if not args.eval_only:
        print("\n[PHASE 1] Collecting real listings from eBay and SerpApi...")
        asyncio.run(_run_collection())

    # Phase 2: Auto-labeling
    print("\n[PHASE 2] Building labeled dataset...")
    _run_labeling()

    if args.collect_only:
        print("\n[collect-only] Done. Run with --eval-only to run trust evaluation.")
        return

    # Phase 3: Trust evaluation
    print("\n[PHASE 3] Running real-world trust evaluation...")
    asyncio.run(_run_eval())

    print("\nPipeline complete.")
    print(f"  Results directory: {RESULTS_DIR}")
    for fname in ["real_listings_raw.json", "real_listings_labeled.json", "eval_trust_real.json"]:
        p = RESULTS_DIR / fname
        if p.exists():
            import os
            print(f"    {fname}: {os.path.getsize(p):,} bytes")


async def _run_collection() -> None:
    from backend.evaluation.collect_real_listings import collect_listings
    await collect_listings()


def _run_labeling() -> None:
    from backend.evaluation.real_listing_dataset import build_and_save
    build_and_save()


async def _run_eval() -> None:
    from backend.evaluation.eval_trust_real import run_evaluation
    await run_evaluation()


def _check_file(path: Path, step: str) -> None:
    if not path.exists():
        print(f"ERROR: {path} not found.")
        print(f"Run: python -m backend.evaluation.{step} first.")
        sys.exit(1)


if __name__ == "__main__":
    main()
