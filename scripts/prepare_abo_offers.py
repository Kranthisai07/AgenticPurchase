"""Convert Amazon Berkeley Objects listings metadata into offer JSONL.

Usage:
    python scripts/prepare_abo_offers.py \
        --metadata-dir dataset/listings/metadata \
        --out backend/data/abo_offers.jsonl

This script scans every `listings_*.json.gz` file, extracts useful product
fields, synthesises a USD price (ABO metadata does not contain prices), and
emits one JSON object per product compatible with `Offer` creation.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional


def _first_text(entries: Optional[Iterable[dict]]) -> Optional[str]:
    if not entries:
        return None
    for entry in entries:
        value = entry.get("value") if isinstance(entry, dict) else None
        if value:
            return str(value)
    return None


def _collect_text_list(entries: Optional[Iterable[dict]]) -> List[str]:
    values: List[str] = []
    if not entries:
        return values
    for entry in entries:
        value = entry.get("value") if isinstance(entry, dict) else None
        if value:
            values.append(str(value))
    return values


def _estimate_price(item_id: str, product_type: Optional[str]) -> float:
    """Deterministic synthetic price derived from item id and product type."""
    base = 25.0
    if product_type:
        # Roughly scale price buckets by product type prefix
        pt = str(product_type)
        bucket = sum(ord(ch) for ch in pt[:4]) % 50
        base += bucket
    digest = hashlib.sha1(item_id.encode("utf-8")).hexdigest()
    offset = int(digest[:8], 16) % 5000  # 0..4999
    price = base + offset / 100.0  # up to ~=75 more
    return round(min(max(price, 9.99), 9999.0), 2)


def _iter_listing_files(metadata_dir: Path) -> Iterator[Path]:
    for path in sorted(metadata_dir.glob("listings_*.json.gz")):
        yield path


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare ABO offers JSONL")
    parser.add_argument(
        "--metadata-dir",
        type=str,
        required=True,
        help="Path to listings/metadata folder containing listings_*.json.gz",
    )
    parser.add_argument(
        "--out",
        type=str,
        default=str(Path("backend/data/abo_offers.jsonl")),
        help="Output JSONL path (default: backend/data/abo_offers.jsonl)",
    )
    parser.add_argument(
        "--image-prefix",
        type=str,
        default="https://amazon-berkeley-objects.s3.amazonaws.com/images/small/",
        help="Base URL prefix for images (default: ABO S3)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional max number of records to export (for quick tests)",
    )
    args = parser.parse_args()

    metadata_dir = Path(args.metadata_dir)
    if not metadata_dir.exists():
        raise FileNotFoundError(f"metadata dir not found: {metadata_dir}")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    count = 0
    with out_path.open("w", encoding="utf-8") as out_file:
        for gz_path in _iter_listing_files(metadata_dir):
            with gzip.open(gz_path, "rt", encoding="utf-8") as fh:
                for line in fh:
                    record = json.loads(line)
                    item_id = record.get("item_id")
                    domain = record.get("domain_name") or "amazon.com"
                    if not item_id:
                        continue
                    title = _first_text(record.get("item_name")) or item_id
                    brand = _first_text(record.get("brand")) or domain
                    category = None
                    product_type = record.get("product_type")
                    if isinstance(product_type, list) and product_type:
                        entry = product_type[0]
                        if isinstance(entry, dict):
                            category = entry.get("value")
                        else:
                            category = str(entry)
                    elif isinstance(product_type, str):
                        category = product_type
                    description = "\n".join(_collect_text_list(record.get("bullet_point")))
                    keywords = _collect_text_list(record.get("item_keywords"))
                    image_id = record.get("main_image_id")
                    if image_id:
                        prefix = args.image_prefix.rstrip("/")
                        image_url = f"{prefix}/{image_id}.jpg"
                    else:
                        image_url = ""
                    url = f"https://{domain}/dp/{item_id}"
                    dims = record.get("item_dimensions") or {}
                    height = dims.get("height", {}).get("value")
                    width = dims.get("width", {}).get("value")
                    length = dims.get("length", {}).get("value")
                    weight_entries = record.get("item_weight") or []
                    weight = None
                    if weight_entries:
                        first_weight = weight_entries[0]
                        weight = first_weight.get("value") or first_weight.get("normalized_value", {}).get("value")
                    price = _estimate_price(item_id, category)
                    offer = {
                        "vendor": brand,
                        "title": title,
                        "price_usd": price,
                        "shipping_days": 3,
                        "eta_days": 5,
                        "url": url,
                        "category": category,
                        "keywords": keywords,
                        "description": description,
                        "image_url": image_url,
                        "attributes": {
                            "domain_name": domain,
                            "country": record.get("country"),
                            "height": height,
                            "width": width,
                            "length": length,
                            "weight": weight,
                        },
                    }
                    out_file.write(json.dumps(offer, ensure_ascii=False) + "\n")
                    count += 1
                    if args.limit and count >= args.limit:
                        break
            if args.limit and count >= args.limit:
                break

    print(f"Wrote {count:,} offers to {out_path}")


if __name__ == "__main__":
    main()
