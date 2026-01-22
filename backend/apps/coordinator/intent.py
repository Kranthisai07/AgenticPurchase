# apps/coordinator/intent.py
from ...libs.schemas.models import ProductHypothesis

async def intake_image(image_path: str) -> ProductHypothesis:
    # Minimal stub (replace with Agent 1 logic if needed)
    return ProductHypothesis(
        label="object",
        brand=None,
        bbox={"x1": 0, "y1": 0, "x2": 0, "y2": 0},
        confidence=0.75,
        item_type=None,
        color=None,
    )

def propose_options(hypo: ProductHypothesis):
    # Minimal stub (replace with real option generation)
    return {
        "prompt": f"Is this the item you want to purchase? ({hypo.label})",
        "options": ["yes", "no", "different color", "different brand"],
        "suggested_inputs": {"quantity": 1, "budget_usd": None},
    }
