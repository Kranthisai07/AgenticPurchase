"""
Intent evaluation — computes F1, precision, recall for the intent agent.

Measures how well the system extracts:
  1. Brand   — from vision_detected_attributes["brand"] (image queries only)
  2. Category — from parsed_intent.category (normalised to 5 standard classes)
  3. Product type — from parsed_intent.primary_query (substring match)

Multimodal F1 computation:
  Image queries (has_image=True):  macro-avg across brand + category + product_type
  Text queries  (has_image=False): macro-avg across category + product_type only
                                   (brand cannot be extracted without vision input)
  Combined F1: weighted average of image_f1 and text_f1 by query count.

For single-label classification: precision = recall = accuracy, so F1 = accuracy.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from backend.evaluation.dataset import EvalQuery


# ── Category normalisation map ────────────────────────────────────────────────
# Maps LLM-emitted category strings → one of the 5 standard eval categories.

_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "footwear": [
        "footwear", "shoe", "sneaker", "boot", "running shoe", "skate",
        "basketball shoe", "sandal", "slipper", "loafer", "trainer",
        "athletic", "heels", "pump",
    ],
    "electronics": [
        "electronics", "electronic", "smartphone", "phone", "mobile",
        "tablet", "laptop", "computer", "headphones", "earbuds", "earphone",
        "speaker", "camera", "charger", "mouse", "keyboard", "monitor",
        "watch" if False else "",   # GPS/smart watches can appear here — handled by watches first
        "gadget", "device", "tech", "e-reader", "ereader",
    ],
    "watches": [
        "watch", "watches", "timepiece", "chronograph", "horology",
        "smartwatch", "digital watch", "analog watch", "dive watch",
        "dress watch", "field watch",
    ],
    "apparel": [
        "apparel", "clothing", "clothes", "jacket", "hoodie", "shirt",
        "jeans", "pants", "trousers", "fleece", "coat", "parka",
        "sweater", "jersey", "backpack", "bag",
    ],
    "home_goods": [
        "home", "home goods", "kitchen", "appliance", "cookware", "blender",
        "vacuum", "coffee", "mug", "mixer", "processor", "light", "lamp",
        "cleaning", "household",
    ],
}


def _normalise_category(raw: str) -> str:
    """
    Map an arbitrary category string to one of the 5 standard eval categories.

    Returns "unknown" when no match is found.
    """
    lowered = (raw or "").lower().strip()
    # Watches before electronics to avoid GPS watch misclassification
    for std_cat in ["watches", "footwear", "apparel", "home_goods", "electronics"]:
        for kw in _CATEGORY_KEYWORDS[std_cat]:
            if kw and kw in lowered:
                return std_cat
    return "unknown"


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class IntentMetrics:
    # Combined / overall metrics (backwards-compatible)
    f1: float
    precision: float
    recall: float
    n_queries: int
    n_correct_brand: int
    n_correct_category: int
    n_correct_product_type: int
    n_brand_checkable: int   # queries where brand was evaluated

    # Multimodal breakdown (defaults=0 so existing callers keep working)
    image_f1: float = 0.0              # F1 for image queries (3 fields)
    text_f1: float = 0.0               # F1 for text queries  (2 fields)
    n_image_queries: int = 0
    n_text_queries: int = 0
    brand_extractable_count: int = 0   # image queries where vision returned a brand
    brand_correct_count: int = 0       # of those, how many matched expected brand


# ── Public entry point ────────────────────────────────────────────────────────

def evaluate_intent(saga_results: list) -> IntentMetrics:
    """
    Compute intent extraction accuracy across all saga eval results.

    Parameters
    ----------
    saga_results:
        list[SagaEvalResult] — imported lazily to avoid circular imports.
        Each result must have:
          .query            EvalQuery
          .intent_output    dict with keys: category, primary_query, brand
          .has_image        bool  (optional, defaults to False if missing)
          .success          bool

    Returns
    -------
    IntentMetrics with per-field counts, per-mode F1, and combined weighted F1.
    """
    # ── Aggregate counters (overall, used for backwards-compat fields) ────────
    n_brand_correct   = 0
    n_cat_correct     = 0
    n_ptype_correct   = 0
    n_brand_checkable = 0
    n_evaluated       = 0

    # ── Per-mode counters ─────────────────────────────────────────────────────
    img_cat_correct        = 0
    img_ptype_correct      = 0
    img_brand_extractable  = 0   # image queries where pred_brand is non-empty
    img_brand_correct      = 0
    n_image                = 0

    txt_cat_correct  = 0
    txt_ptype_correct = 0
    n_text           = 0

    for sr in saga_results:
        if not sr.success:
            continue
        n_evaluated += 1
        has_image: bool = getattr(sr, "has_image", False)

        query: EvalQuery = sr.query
        io:    dict      = sr.intent_output

        # ── Brand match ───────────────────────────────────────────────────────
        pred_brand = (io.get("brand") or "").strip().lower()
        exp_brand  = (query.expected_brand or "").strip().lower()

        if pred_brand and exp_brand:
            n_brand_checkable += 1
            if _brand_match(pred_brand, exp_brand):
                n_brand_correct += 1
        elif not exp_brand:
            # Query has no expected brand — count as correct (nothing to match)
            n_brand_checkable += 1
            n_brand_correct   += 1

        # ── Category match ────────────────────────────────────────────────────
        pred_cat = _normalise_category(io.get("category") or "")
        exp_cat  = (query.expected_category or "").strip().lower()
        cat_ok   = pred_cat == exp_cat
        if cat_ok:
            n_cat_correct += 1

        # ── Product type match ────────────────────────────────────────────────
        pred_ptype = (io.get("primary_query") or "").strip().lower()
        exp_ptype  = (query.expected_product_type or "").strip().lower()
        ptype_ok   = _product_type_match(pred_ptype, exp_ptype)
        if ptype_ok:
            n_ptype_correct += 1

        # ── Per-mode accumulation ─────────────────────────────────────────────
        if has_image:
            n_image           += 1
            img_cat_correct   += int(cat_ok)
            img_ptype_correct += int(ptype_ok)
            # Brand is only evaluated when vision returned a prediction
            if pred_brand:
                img_brand_extractable += 1
                brand_ok = _brand_match(pred_brand, exp_brand) if exp_brand else True
                img_brand_correct += int(brand_ok)
        else:
            n_text            += 1
            txt_cat_correct   += int(cat_ok)
            txt_ptype_correct += int(ptype_ok)

    if n_evaluated == 0:
        return IntentMetrics(
            f1=0.0, precision=0.0, recall=0.0,
            n_queries=0,
            n_correct_brand=0, n_correct_category=0, n_correct_product_type=0,
            n_brand_checkable=0,
        )

    # ── Overall (legacy) accuracy ─────────────────────────────────────────────
    brand_acc = n_brand_correct / n_brand_checkable if n_brand_checkable else 0.0
    cat_acc   = n_cat_correct   / n_evaluated
    ptype_acc = n_ptype_correct / n_evaluated
    macro_acc = (brand_acc + cat_acc + ptype_acc) / 3

    # ── Per-mode F1 ───────────────────────────────────────────────────────────
    if n_image > 0:
        _img_cat_acc   = img_cat_correct   / n_image
        _img_ptype_acc = img_ptype_correct / n_image
        _img_brand_acc = (
            img_brand_correct / img_brand_extractable
            if img_brand_extractable > 0
            else 0.0
        )
        image_f1 = (_img_brand_acc + _img_cat_acc + _img_ptype_acc) / 3
    else:
        image_f1 = 0.0

    if n_text > 0:
        _txt_cat_acc   = txt_cat_correct   / n_text
        _txt_ptype_acc = txt_ptype_correct / n_text
        text_f1 = (_txt_cat_acc + _txt_ptype_acc) / 2
    else:
        text_f1 = 0.0

    # ── Combined F1: weighted by query count ──────────────────────────────────
    combined_f1 = (n_image * image_f1 + n_text * text_f1) / n_evaluated

    return IntentMetrics(
        f1=round(combined_f1, 4),
        precision=round(combined_f1, 4),
        recall=round(combined_f1, 4),
        n_queries=n_evaluated,
        n_correct_brand=n_brand_correct,
        n_correct_category=n_cat_correct,
        n_correct_product_type=n_ptype_correct,
        n_brand_checkable=n_brand_checkable,
        image_f1=round(image_f1, 4),
        text_f1=round(text_f1, 4),
        n_image_queries=n_image,
        n_text_queries=n_text,
        brand_extractable_count=img_brand_extractable,
        brand_correct_count=img_brand_correct,
    )


# ── Private helpers ───────────────────────────────────────────────────────────

def _brand_match(predicted: str, expected: str) -> bool:
    """
    True if predicted and expected brand strings are compatible.

    Match rules (case-insensitive, already lowercased by caller):
      - Either string is a substring of the other (handles "nike" in "nike inc")
      - OR the first meaningful word of predicted is in expected or vice versa
    """
    if predicted in expected or expected in predicted:
        return True
    # First word of each side
    p_word = predicted.split()[0] if predicted else ""
    e_word = expected.split()[0] if expected else ""
    if p_word and e_word and (p_word in expected or e_word in predicted):
        return True
    return False


def _product_type_match(predicted: str, expected: str) -> bool:
    """
    True if predicted and expected product types share meaningful overlap.

    Match rules:
      - Either is a substring of the other
      - OR all words in expected appear in predicted (order-agnostic)
    """
    if not predicted or not expected:
        return False
    if predicted in expected or expected in predicted:
        return True
    exp_words = expected.split()
    if all(w in predicted for w in exp_words):
        return True
    return False
