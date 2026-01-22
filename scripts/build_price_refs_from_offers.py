"""Build price, weight, and dimension reference statistics from offers JSONL."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import median
from typing import Dict, List, Tuple

METRICS = ("price", "weight", "height", "width", "length")


def _collect_values(path: Path) -> Dict[Tuple[str, str], Dict[str, List[float]]]:
    buckets: Dict[Tuple[str, str], Dict[str, List[float]]] = {}
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            data = json.loads(line)
            attrs = data.get("attributes") or {}
            category = (data.get("category") or "").strip().lower()
            vendor = (data.get("vendor") or "").strip().lower()

            metric_values = {
                "price": data.get("price_usd"),
                "weight": attrs.get("weight"),
                "height": attrs.get("height"),
                "width": attrs.get("width"),
                "length": attrs.get("length"),
            }

            for metric, raw_value in metric_values.items():
                if raw_value is None:
                    continue
                try:
                    numeric = float(raw_value)
                except Exception:
                    continue
                for key in ((vendor, category), (vendor, ""), ("", category), ("", "")):
                    buckets.setdefault(key, {}).setdefault(metric, []).append(numeric)
    return buckets


def _iqr(values: List[float]) -> float:
    if not values:
        return 0.0
    xs = sorted(values)
    n = len(xs)
    q1 = xs[int(0.25 * (n - 1))]
    q3 = xs[int(0.75 * (n - 1))]
    return max(q3 - q1, 1.0)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build price refs from offers JSONL")
    parser.add_argument("offers", type=str, help="Offers JSONL file (e.g., backend/data/abo_offers.jsonl)")
    parser.add_argument(
        "--out",
        type=str,
        default=str(Path("backend/data/price_refs.json")),
        help="Output JSON path (default: backend/data/price_refs.json)",
    )
    args = parser.parse_args()

    offers_path = Path(args.offers)
    if not offers_path.exists():
        raise FileNotFoundError(offers_path)
    buckets = _collect_values(offers_path)

    refs = {}
    for (vendor, category), metric_map in buckets.items():
        stats = {}
        for metric, values in metric_map.items():
            if not values:
                continue
            med = median(values)
            spread = _iqr(values) / 1.349
            stats[metric] = {"median": round(med, 2), "spread": round(max(spread, 1.0), 2)}
        if stats:
            key = f"{vendor}|{category}"
            refs[key] = stats

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(refs, indent=2), encoding="utf-8")
    print(f"Wrote {len(refs)} price ref entries to {out_path}")


if __name__ == "__main__":
    main()
