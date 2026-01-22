#!/usr/bin/env python
"""
Batch evaluation harness for the Agentic Purchase system.

Features:
- Iterates over a YAML dataset of test images and expected attributes.
- Calls either legacy FastAPI endpoints (/saga/preview, /saga/start)
  or LangServe endpoints (/saga/preview/invoke, /saga/start/invoke).
- Logs per-run JSON lines to Agentic_AI/logs/eval.log with:
  - request metadata (image, mode, endpoint)
  - returned hypothesis/intent/offers/trust/receipt
  - stage events with dt_s for latency analysis
  - simple accuracy metrics (brand/category/topK)

Usage examples:
  python scripts/run_eval.py --dataset evaluation/dataset.yaml --mode preview
  python scripts/run_eval.py --dataset evaluation/dataset.yaml --mode start \
    --card-number 4242424242424242 --expiry 12/29 --cvv 123

Notes:
- Keep the backend running (preferred):
    python -m uvicorn backend.apps.coordinator.main:app --reload
  or LangServe:
    python -m uvicorn backend.langserve_app:app --reload

Dataset YAML format (minimal):
  - image: path/to/file.jpg
    user_text: optional text
    expect:
      brand: Apple
      category: phone
      family: iPhone
    preferred_offer_url: optional url
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import mimetypes
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
import yaml


LOG_PATH = Path("backend/logs/eval.log")


def _read_yaml(path: Path) -> List[dict]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or []
    if not isinstance(data, list):
        raise ValueError("dataset YAML must be a list")
    return data


def _to_base64(image_path: Path) -> str:
    data = image_path.read_bytes()
    return base64.b64encode(data).decode("utf-8")


def _mime_type(path: Path) -> str:
    mt, _ = mimetypes.guess_type(str(path))
    return mt or "image/jpeg"


def _legacy_form_call(
    base_url: str,
    endpoint: str,
    image_path: Path,
    user_text: Optional[str],
    preferred_offer_url: Optional[str],
    payment: Optional[dict],
    idempotency_key: Optional[str],
) -> Tuple[dict, float]:
    url = base_url.rstrip("/") + endpoint
    files = {
        "image": (image_path.name, image_path.read_bytes(), _mime_type(image_path)),
    }
    data: Dict[str, Any] = {}
    if user_text:
        data["user_text"] = user_text
    if preferred_offer_url:
        data["preferred_offer_url"] = preferred_offer_url
    headers = {}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    if payment is not None:
        data.update(
            {
                "card_number": payment.get("card_number", ""),
                "expiry_mm_yy": payment.get("expiry_mm_yy", ""),
                "cvv": payment.get("cvv", ""),
            }
        )
    t0 = time.time()
    resp = requests.post(url, files=files, data=data, headers=headers, timeout=120)
    dt = time.time() - t0
    resp.raise_for_status()
    return resp.json(), dt


def _langserve_call(
    base_url: str,
    endpoint: str,  # "/saga/preview/invoke" or "/saga/start/invoke"
    image_path: Path,
    user_text: Optional[str],
    preferred_offer_url: Optional[str],
    payment: Optional[dict],
    idempotency_key: Optional[str],
) -> Tuple[dict, float]:
    url = base_url.rstrip("/") + endpoint
    payload: Dict[str, Any] = {
        "image_base64": _to_base64(image_path),
        "user_text": user_text,
        "preferred_offer_url": preferred_offer_url,
    }
    if payment is not None:
        payload["payment"] = payment
        payload["idempotency_key"] = idempotency_key
    t0 = time.time()
    resp = requests.post(url, json={"input": payload}, timeout=120)
    dt = time.time() - t0
    resp.raise_for_status()
    data = resp.json()
    # LangServe wraps return under { "output": ... }
    return data.get("output", data), dt


def _stage_latencies(events: List[dict]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for ev in events or []:
        stage = ev.get("stage") or ev.get("state")
        dt = ev.get("dt_s")
        if stage and isinstance(dt, (int, float)):
            out[str(stage)] = float(dt)
    return out


def _norm_value(val: Any) -> Optional[str]:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, str):
        cleaned = val.strip()
        return cleaned.lower() if cleaned else None
    return str(val).strip().lower() or None


def _intent_slot_scores(intent: dict, expect_intent: dict) -> Tuple[Dict[str, int], Dict[str, int]]:
    """Return per-slot hits and aggregated tp/fp/fn counts."""
    slots = ("item_name", "color", "quantity", "budget_usd")
    slot_hits: Dict[str, int] = {}
    counts = {"tp": 0, "fp": 0, "fn": 0}
    expect_intent = expect_intent or {}
    for slot in slots:
        gold = _norm_value(expect_intent.get(slot))
        pred = _norm_value(intent.get(slot))
        if gold is None and pred is None:
            continue
        if gold is not None and pred == gold:
            counts["tp"] += 1
            slot_hits[f"intent_{slot}_hit"] = 1
        else:
            if gold is not None:
                counts["fn"] += 1
            if pred is not None and pred != gold:
                counts["fp"] += 1
            slot_hits[f"intent_{slot}_hit"] = 0
    return slot_hits, counts


def _trust_flags(trust: Optional[dict], expect: dict) -> Dict[str, int]:
    trust = trust or {}
    authenticity = _norm_value(expect.get("authenticity"))
    is_fake = authenticity in {"fake", "counterfeit", "scam"}
    risk = _norm_value(trust.get("risk")) or ""
    flagged = risk in {"medium", "high"} or bool(trust.get("replica_terms"))
    tp = int(is_fake and flagged)
    fp = int((not is_fake) and flagged)
    fn = int(is_fake and (not flagged))
    return {
        "trust_truth_fake": int(is_fake),
        "trust_flagged": int(flagged),
        "trust_tp": tp,
        "trust_fp": fp,
        "trust_fn": fn,
    }


def _topk_hits(offers: List[dict], expect_brand: Optional[str], k: int = 3) -> Tuple[bool, bool]:
    if not offers:
        return False, False
    expect_brand_norm = (expect_brand or "").strip().lower()
    top1_hit = False
    topk_hit = False
    for idx, off in enumerate(offers[: max(1, k) ]):
        brand = (off.get("vendor") or off.get("brand") or "").strip().lower()
        if expect_brand_norm and brand and expect_brand_norm == brand:
            if idx == 0:
                top1_hit = True
            topk_hit = True
    return top1_hit, topk_hit


def _recognition_hit(hypothesis: dict, intent: dict, expect: dict) -> bool:
    # Hit if brand or family/category aligns with expectation
    try:
        hypo_label = (hypothesis.get("label") or "").lower().strip()
        hypo_brand = (hypothesis.get("brand") or "").lower().strip()
        intent_item = (intent.get("item_name") or "").lower().strip()
        intent_brand = (intent.get("brand") or "").lower().strip()
        expect_brand = (expect.get("brand") or "").lower().strip()
        expect_family = (expect.get("family") or "").lower().strip()
        expect_cat = (expect.get("category") or "").lower().strip()

        conds = []
        if expect_brand and (hypo_brand == expect_brand or intent_brand == expect_brand):
            conds.append(True)
        if expect_family and (expect_family in hypo_label or expect_family in intent_item):
            conds.append(True)
        if expect_cat and (expect_cat in hypo_label or expect_cat in intent_item):
            conds.append(True)
        return any(conds)
    except Exception:
        return False


def _append_log(line: dict) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, ensure_ascii=False) + "\n")


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Run batch evaluation against saga endpoints")
    ap.add_argument("--dataset", required=True, help="YAML list of test items")
    ap.add_argument("--base", default="http://127.0.0.1:8000", help="Server base URL")
    ap.add_argument(
        "--mode",
        choices=["preview", "start"],
        default="preview",
        help="Which endpoint to call",
    )
    ap.add_argument(
        "--langserve",
        action="store_true",
        help="Use LangServe /invoke endpoints instead of legacy FastAPI",
    )
    ap.add_argument("--card-number", dest="card_number", default=None)
    ap.add_argument("--expiry", dest="expiry_mm_yy", default=None)
    ap.add_argument("--cvv", dest="cvv", default=None)
    ap.add_argument("--idempotency", dest="idempotency_key", default=None)
    ap.add_argument("--label", dest="label", default=None, help="Optional label for this run (e.g., deterministic/llm)")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    dataset_path = Path(args.dataset)
    items = _read_yaml(dataset_path)

    if args.mode == "start":
        if not (args.card_number and args.expiry_mm_yy and args.cvv):
            print("[error] start mode requires --card-number --expiry --cvv", file=sys.stderr)
            return 2
        payment = {
            "card_number": args.card_number,
            "expiry_mm_yy": args.expiry_mm_yy,
            "cvv": args.cvv,
            "amount_usd": 0.0,
        }
    else:
        payment = None

    for idx, row in enumerate(items, start=1):
        image_path = Path(row.get("image", ""))
        if not image_path.exists():
            print(f"[warn] missing image: {image_path}")
            continue
        user_text = row.get("user_text")
        preferred = row.get("preferred_offer_url")
        expect = row.get("expect", {}) or {}

        if args.langserve:
            endpoint = f"/saga/{args.mode}/invoke"
            call = _langserve_call
        else:
            endpoint = f"/saga/{args.mode}"
            call = _legacy_form_call

        run_id = f"{int(time.time())}-{idx}"
        _append_log({
            "type": "RUN_START",
            "run_id": run_id,
            "image": str(image_path),
            "mode": args.mode,
            "endpoint": endpoint,
            "base": args.base,
            "label": args.label,
        })

        try:
            data, wall_dt = call(
                args.base,
                endpoint,
                image_path,
                user_text,
                preferred,
                payment,
                args.idempotency_key,
            )
        except requests.RequestException as e:
            _append_log({
                "type": "RUN_ERROR",
                "run_id": run_id,
                "error": str(e),
            })
            print(f"[error] request failed for {image_path}: {e}")
            continue

        # Extract stage latencies and accuracy metrics
        events = data.get("log") or data.get("events") or []
        lats = _stage_latencies(events)
        offers = data.get("offers") or []
        hypo = data.get("hypothesis") or {}
        intent = data.get("intent") or {}
        trust = data.get("trust") or {}
        expect_intent = expect.get("intent") or {}
        top1, top3 = _topk_hits(offers, expect.get("brand"))
        recog = _recognition_hit(hypo, intent, expect)
        slot_hits, intent_counts = _intent_slot_scores(intent, expect_intent)
        trust_flags = _trust_flags(trust, expect)

        metrics = {
            "recognition_hit": bool(recog),
            "top1_brand_hit": bool(top1),
            "top3_brand_hit": bool(top3),
            "dt_wall_s": round(float(wall_dt), 4),
            "dt_saga_s": round(sum(lats.values()), 4) if lats else None,
            "intent_tp": intent_counts["tp"],
            "intent_fp": intent_counts["fp"],
            "intent_fn": intent_counts["fn"],
            **trust_flags,
        }
        metrics.update({f"lat_{k}": v for k, v in lats.items()})
        metrics.update(slot_hits)

        _append_log({
            "type": "RUN_RESULT",
            "run_id": run_id,
            "image": str(image_path),
            "mode": args.mode,
            "endpoint": endpoint,
            "base": args.base,
            "label": args.label,
            "expect": expect,
            "metrics": metrics,
            "events": events,
            "hypothesis": hypo,
            "intent": intent,
            "offers": offers,
            "offer": data.get("offer"),
            "trust": trust,
            "receipt": data.get("receipt"),
        })

        print(f"[ok] {idx}/{len(items)} {image_path.name}  recog={recog} top1={top1} top3={top3} wall={metrics['dt_wall_s']}s")

    print(f"\nWrote logs to: {LOG_PATH}")
    print("Use: python scripts/eval_report.py --log backend/logs/eval.log")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
