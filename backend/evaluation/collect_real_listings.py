"""
Real listing collector — fetches live product listings from eBay and SerpApi.

Invocation:
  python -m backend.evaluation.collect_real_listings

Output:
  backend/evaluation/results/real_listings_raw.json

Resumable: if the output file already exists, previously fetched queries are
skipped and only missing ones are fetched.

Design:
  30 queries × 2 sources × up to 5 results = up to 300 raw listings.
  eBay uses the sandbox API (SBX keys) — results may be sparse.
  SerpApi uses Google Shopping (real results).
  Rate-limiting: 1.5s delay between eBay calls, 1.0s between SerpApi calls.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RESULTS_DIR = Path(__file__).parent / "results"

# ── Query definitions ─────────────────────────────────────────────────────────

@dataclass
class CollectionQuery:
    query_id: str
    query_text: str
    query_type: str   # "suspicious" | "clean"
    category: str
    expected_brand: str


COLLECTION_QUERIES: list[CollectionQuery] = [
    # ── FOOTWEAR — suspicious ─────────────────────────────────────────────────
    CollectionQuery("fw-s-01", "AAA grade Nike Air Max running shoe",       "suspicious", "footwear",    "nike"),
    CollectionQuery("fw-s-02", "replica Adidas Ultraboost sneaker",         "suspicious", "footwear",    "adidas"),
    CollectionQuery("fw-s-03", "super copy Jordan 1 Retro high",            "suspicious", "footwear",    "jordan"),
    # ── FOOTWEAR — clean ─────────────────────────────────────────────────────
    CollectionQuery("fw-c-01", "Nike Air Max running shoe size 10",         "clean",      "footwear",    "nike"),
    CollectionQuery("fw-c-02", "Adidas Ultraboost white sneakers",          "clean",      "footwear",    "adidas"),
    CollectionQuery("fw-c-03", "Jordan 1 Retro High OG",                   "clean",      "footwear",    "jordan"),

    # ── ELECTRONICS — suspicious ──────────────────────────────────────────────
    CollectionQuery("el-s-01", "grade 5A Sony WH-1000XM5 headphones",      "suspicious", "electronics", "sony"),
    CollectionQuery("el-s-02", "parallel import Apple AirPods Pro",         "suspicious", "electronics", "apple"),
    CollectionQuery("el-s-03", "factory second Samsung Galaxy S24",         "suspicious", "electronics", "samsung"),
    # ── ELECTRONICS — clean ───────────────────────────────────────────────────
    CollectionQuery("el-c-01", "Sony WH-1000XM5 wireless headphones",      "clean",      "electronics", "sony"),
    CollectionQuery("el-c-02", "Apple AirPods Pro 2nd generation",         "clean",      "electronics", "apple"),
    CollectionQuery("el-c-03", "Samsung Galaxy S24 unlocked",              "clean",      "electronics", "samsung"),

    # ── WATCHES — suspicious ──────────────────────────────────────────────────
    CollectionQuery("wa-s-01", "super copy Casio G-Shock GA-2100",         "suspicious", "watches",     "casio"),
    CollectionQuery("wa-s-02", "inspired by Seiko 5 Sports automatic",     "suspicious", "watches",     "seiko"),
    CollectionQuery("wa-s-03", "exhibition copy Daniel Wellington watch",   "suspicious", "watches",     "daniel wellington"),
    # ── WATCHES — clean ───────────────────────────────────────────────────────
    CollectionQuery("wa-c-01", "Casio G-Shock GA-2100 black",              "clean",      "watches",     "casio"),
    CollectionQuery("wa-c-02", "Seiko 5 Sports automatic watch",           "clean",      "watches",     "seiko"),
    CollectionQuery("wa-c-03", "Daniel Wellington Classic 40mm",           "clean",      "watches",     "daniel wellington"),

    # ── APPAREL — suspicious ──────────────────────────────────────────────────
    CollectionQuery("ap-s-01", "inspired by North Face Nuptse jacket",     "suspicious", "apparel",     "north face"),
    CollectionQuery("ap-s-02", "1:1 quality Levi 501 jeans",               "suspicious", "apparel",     "levis"),
    CollectionQuery("ap-s-03", "mirror image Patagonia Better Sweater",    "suspicious", "apparel",     "patagonia"),
    # ── APPAREL — clean ───────────────────────────────────────────────────────
    CollectionQuery("ap-c-01", "The North Face Nuptse puffer jacket",      "clean",      "apparel",     "north face"),
    CollectionQuery("ap-c-02", "Levis 501 original fit jeans",             "clean",      "apparel",     "levis"),
    CollectionQuery("ap-c-03", "Patagonia Better Sweater fleece",          "clean",      "apparel",     "patagonia"),

    # ── HOME GOODS — suspicious ───────────────────────────────────────────────
    CollectionQuery("hg-s-01", "grade A KitchenAid stand mixer alternative","suspicious","home_goods",  "kitchenaid"),
    CollectionQuery("hg-s-02", "factory second Dyson V15 vacuum",           "suspicious","home_goods",  "dyson"),
    CollectionQuery("hg-s-03", "exhibition copy Le Creuset dutch oven",     "suspicious","home_goods",  "le creuset"),
    # ── HOME GOODS — clean ────────────────────────────────────────────────────
    CollectionQuery("hg-c-01", "KitchenAid stand mixer tilt head",         "clean",      "home_goods",  "kitchenaid"),
    CollectionQuery("hg-c-02", "Dyson V15 Detect cordless vacuum",         "clean",      "home_goods",  "dyson"),
    CollectionQuery("hg-c-03", "Le Creuset dutch oven 5.5 qt",             "clean",      "home_goods",  "le creuset"),
]

# Max offers to take per query per source
_MAX_PER_SOURCE = 5


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class RawCollectedOffer:
    listing_id: str
    query_id: str
    query_text: str
    query_type: str
    category: str
    expected_brand: str
    source: str          # "ebay" | "serpapi"
    title: str
    price_amount: float
    price_currency: str
    seller_id: str
    seller_name: str
    url: str
    image_url: str
    condition: str
    free_shipping: bool
    raw_api_response: dict  # full raw dict from the API


# ── eBay collection ───────────────────────────────────────────────────────────

async def _fetch_ebay(query: CollectionQuery, ebay_client) -> list[RawCollectedOffer]:
    """Fetch up to _MAX_PER_SOURCE results from eBay for one query."""
    from backend.integrations.ebay.normalizer import normalize_ebay_item

    try:
        items = await ebay_client.ebay_search(query.query_text)
    except Exception as exc:
        print(f"    [eBay ERROR] {query.query_id}: {exc}")
        return []

    results = []
    for raw in items[:_MAX_PER_SOURCE]:
        try:
            offer = normalize_ebay_item(raw)
            results.append(RawCollectedOffer(
                listing_id=str(uuid.uuid4()),
                query_id=query.query_id,
                query_text=query.query_text,
                query_type=query.query_type,
                category=query.category,
                expected_brand=query.expected_brand,
                source="ebay",
                title=offer.title,
                price_amount=float(offer.price.amount),
                price_currency=offer.price.currency,
                seller_id=offer.seller_id,
                seller_name=offer.seller_name,
                url=offer.url,
                image_url=offer.image_urls[0] if offer.image_urls else "",
                condition=offer.condition,
                free_shipping=offer.free_shipping,
                raw_api_response=raw,
            ))
        except Exception:
            continue

    return results


# ── SerpApi collection ────────────────────────────────────────────────────────

async def _fetch_serpapi(query: CollectionQuery, serpapi_client) -> list[RawCollectedOffer]:
    """Fetch up to _MAX_PER_SOURCE results from SerpApi for one query."""
    from backend.integrations.serpapi.normalizer import normalize_serpapi_result

    try:
        items = await serpapi_client.google_shopping_search(query.query_text)
    except Exception as exc:
        print(f"    [SerpApi ERROR] {query.query_id}: {exc}")
        return []

    results = []
    for raw in items[:_MAX_PER_SOURCE]:
        try:
            offer = normalize_serpapi_result(raw)
            results.append(RawCollectedOffer(
                listing_id=str(uuid.uuid4()),
                query_id=query.query_id,
                query_text=query.query_text,
                query_type=query.query_type,
                category=query.category,
                expected_brand=query.expected_brand,
                source="serpapi",
                title=offer.title,
                price_amount=float(offer.price.amount),
                price_currency=offer.price.currency,
                seller_id=offer.seller_id,
                seller_name=offer.seller_name,
                url=offer.url,
                image_url=offer.image_urls[0] if offer.image_urls else "",
                condition=offer.condition,
                free_shipping=offer.free_shipping,
                raw_api_response=raw,
            ))
        except Exception:
            continue

    return results


# ── Deduplication ─────────────────────────────────────────────────────────────

def _deduplicate(listings: list[RawCollectedOffer]) -> list[RawCollectedOffer]:
    """
    Remove near-duplicate listings within the same query_id.
    Two listings are duplicates if:
    - Same query_id
    - Title similarity: one title is a substring of the other after lowercasing,
      OR both share >= 80% of their words (Jaccard similarity on word sets).
    """
    seen: list[RawCollectedOffer] = []

    def _words(s: str) -> set[str]:
        return set(s.lower().split())

    def _is_dup(a: RawCollectedOffer, b: RawCollectedOffer) -> bool:
        if a.query_id != b.query_id:
            return False
        ta, tb = a.title.lower().strip(), b.title.lower().strip()
        if ta == tb:
            return True
        if ta in tb or tb in ta:
            return True
        wa, wb = _words(a.title), _words(b.title)
        if not wa or not wb:
            return False
        jaccard = len(wa & wb) / len(wa | wb)
        return jaccard >= 0.80

    for listing in listings:
        if not any(_is_dup(listing, s) for s in seen):
            seen.append(listing)

    return seen


# ── Save / load ───────────────────────────────────────────────────────────────

def _save_raw(listings: list[RawCollectedOffer], timestamp: str) -> Path:
    RESULTS_DIR.mkdir(exist_ok=True)
    out_path = RESULTS_DIR / "real_listings_raw.json"
    data = {
        "timestamp": timestamp,
        "total": len(listings),
        "listings": [asdict(l) for l in listings],
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return out_path


def _load_existing() -> tuple[list[RawCollectedOffer], set[str]]:
    """Load previously collected listings; return (listings, fetched_query_source_pairs)."""
    raw_path = RESULTS_DIR / "real_listings_raw.json"
    if not raw_path.exists():
        return [], set()
    try:
        with open(raw_path, encoding="utf-8") as f:
            data = json.load(f)
        listings = [RawCollectedOffer(**item) for item in data.get("listings", [])]
        # Track which (query_id, source) pairs were already fetched
        fetched = {f"{l.query_id}:{l.source}" for l in listings}
        return listings, fetched
    except Exception as exc:
        print(f"  Warning: could not load existing data: {exc}")
        return [], set()


# ── Main collection logic ─────────────────────────────────────────────────────

async def collect_listings() -> list[RawCollectedOffer]:
    from backend.integrations.ebay.client import EbayClient
    from backend.integrations.serpapi.client import SerpApiClient

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    print(f"\n{'='*64}")
    print("  REAL LISTING COLLECTION")
    print(f"  Started: {ts}")
    print(f"  Queries: {len(COLLECTION_QUERIES)}  (15 suspicious + 15 clean)")
    print(f"  Max per query per source: {_MAX_PER_SOURCE}")
    print(f"{'='*64}\n")

    # Resumability: load previously collected listings
    existing_listings, already_fetched = _load_existing()
    if already_fetched:
        print(f"  Resuming: {len(existing_listings)} listings already collected, "
              f"{len(already_fetched)} (query,source) pairs done.\n")

    ebay_client   = EbayClient()
    serpapi_client = SerpApiClient()

    new_listings: list[RawCollectedOffer] = []
    ebay_count = serpapi_count = 0
    ebay_errors = serpapi_errors = 0

    for i, query in enumerate(COLLECTION_QUERIES):
        print(f"[{i+1:2d}/{len(COLLECTION_QUERIES)}] [{query.query_type.upper():9s}] "
              f"{query.query_id}: {query.query_text[:55]}...")

        # ── eBay ──────────────────────────────────────────────────────────────
        ebay_key = f"{query.query_id}:ebay"
        if ebay_key in already_fetched:
            existing_count = sum(1 for l in existing_listings
                                 if l.query_id == query.query_id and l.source == "ebay")
            print(f"    eBay:    SKIP (already have {existing_count})")
        else:
            ebay_results = await _fetch_ebay(query, ebay_client)
            new_listings.extend(ebay_results)
            ebay_count += len(ebay_results)
            if ebay_results:
                print(f"    eBay:    {len(ebay_results)} results")
                for r in ebay_results[:2]:
                    print(f"             - {r.title[:60]} (${r.price_amount:.2f})")
            else:
                ebay_errors += 1
                print(f"    eBay:    0 results (sandbox may be sparse)")
            await asyncio.sleep(1.5)  # rate limit

        # ── SerpApi ───────────────────────────────────────────────────────────
        serpapi_key = f"{query.query_id}:serpapi"
        if serpapi_key in already_fetched:
            existing_count = sum(1 for l in existing_listings
                                 if l.query_id == query.query_id and l.source == "serpapi")
            print(f"    SerpApi: SKIP (already have {existing_count})")
        else:
            serp_results = await _fetch_serpapi(query, serpapi_client)
            new_listings.extend(serp_results)
            serpapi_count += len(serp_results)
            if serp_results:
                print(f"    SerpApi: {len(serp_results)} results")
                for r in serp_results[:2]:
                    print(f"             - {r.title[:60]} (${r.price_amount:.2f})")
            else:
                serpapi_errors += 1
                print(f"    SerpApi: 0 results")
            await asyncio.sleep(1.0)  # rate limit

        print()

    await ebay_client.close()
    await serpapi_client.close()

    # Merge with existing
    all_listings = existing_listings + new_listings

    # Deduplicate
    before_dedup = len(all_listings)
    all_listings = _deduplicate(all_listings)
    removed = before_dedup - len(all_listings)

    # Save
    out_path = _save_raw(all_listings, ts)

    # Summary
    total_ebay   = sum(1 for l in all_listings if l.source == "ebay")
    total_serp   = sum(1 for l in all_listings if l.source == "serpapi")
    susp_queries = sum(1 for l in all_listings if l.query_type == "suspicious")
    clean_queries= sum(1 for l in all_listings if l.query_type == "clean")

    print(f"\n{'='*64}")
    print("  COLLECTION SUMMARY")
    print(f"{'='*64}")
    print(f"  New this run:        {len(new_listings)}")
    print(f"    From eBay:         {ebay_count}  ({ebay_errors} queries returned 0)")
    print(f"    From SerpApi:      {serpapi_count}  ({serpapi_errors} queries returned 0)")
    print(f"  Before dedup:        {before_dedup}")
    print(f"  Removed as dups:     {removed}")
    print(f"  Final unique total:  {len(all_listings)}")
    print(f"    eBay listings:     {total_ebay}")
    print(f"    SerpApi listings:  {total_serp}")
    print(f"    Suspicious query:  {susp_queries}")
    print(f"    Clean query:       {clean_queries}")
    print(f"\n  Saved to: {out_path}")
    print(f"{'='*64}\n")

    return all_listings


def main() -> None:
    asyncio.run(collect_listings())


if __name__ == "__main__":
    main()
