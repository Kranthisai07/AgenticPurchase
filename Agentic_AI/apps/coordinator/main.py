from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, FastAPI, File, Form, HTTPException, UploadFile, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles
import mimetypes
from pydantic import BaseModel

from ...agentic_graph import (
    run_saga_async as graph_run_saga_async,
    run_saga_preview_async as graph_run_saga_preview_async,
)
from ...agentic_graph.state import SagaState
from ...agentic_graph.utils import state_to_payload
from ...libs.schemas.models import (
    CheckoutProfile,
    Offer,
    PaymentInput,
    ProductHypothesis,
    PurchaseIntent,
    Receipt,
    TrustAssessment,
)
from ..coordinator.profile import DEFAULT_CHECKOUT_PROFILE
from ..agent1_vision.main import intake_image
from ..agent2_intent.main import propose_options
from ..agent4_trust.main import assess as trust_assess
from ..agent5_checkout.main import pay as checkout_pay

CATALOG_CACHE: Optional[list[dict[str, Any]]] = None


def _catalog_path() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "mock_catalog.json"


def _load_catalog() -> list[dict[str, Any]]:
    global CATALOG_CACHE
    if CATALOG_CACHE is None:
        with _catalog_path().open("r", encoding="utf-8") as fh:
            CATALOG_CACHE = json.load(fh)
    return CATALOG_CACHE


def _find_catalog_item(slug: str) -> Optional[dict[str, Any]]:
    slug = slug.strip().strip("/")
    if not slug:
        return None
    for entry in _load_catalog():
        url = (entry.get("url") or "").rstrip("/")
        if url.split("/")[-1] == slug:
            return entry
    return None


def _sample_reviews(title: str, vendor: str) -> list[dict[str, Any]]:
    return [
        {"author": "Alex L.", "rating": 5, "quote": f"Impressed with the {title.lower()} - ships fast and feels premium."},
        {"author": "Priya K.", "rating": 4, "quote": f"The {vendor} quality stands out. Would recommend to friends."},
        {"author": "Jordan S.", "rating": 5, "quote": f"Great value for money. Exactly what I needed."},
    ]


def _offer_from_catalog(item: dict[str, Any]) -> Offer:
    payload = dict(item)
    payload.setdefault("score", 0.0)
    payload.setdefault("category", item.get("category"))
    payload.setdefault("keywords", item.get("keywords", []))
    payload.setdefault("description", item.get("description", ""))
    payload.setdefault("image_url", item.get("image_url", ""))
    payload.setdefault("tags", item.get("keywords", []))
    return Offer(**payload)


class SagaResult(BaseModel):
    hypothesis: ProductHypothesis
    intent: PurchaseIntent
    offer: Offer
    offers: List[Offer]
    trust: TrustAssessment
    receipt: Optional[Receipt]
    profile: CheckoutProfile
    log: List[Dict[str, Any]]


class PromptResponse(BaseModel):
    hypothesis: ProductHypothesis
    prompt: str
    options: List[Dict[str, str]]
    suggested_inputs: Dict[str, str] = {}


app = FastAPI(title="Agentic Purchase - Agent Orchestrator")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ],
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve local evaluation images for use in the UI (e.g., /static_eval/pixel_8.avif)
try:
    mimetypes.add_type("image/avif", ".avif")
except Exception:
    pass
try:
    STATIC_EVAL = Path(__file__).resolve().parents[2] / "evaluation" / "images"
    if STATIC_EVAL.exists():
        app.mount("/static_eval", StaticFiles(directory=str(STATIC_EVAL)), name="static_eval")
except Exception:
    # Non-fatal if static mount fails
    pass


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return """<html><body style="font-family: system-ui; padding: 2rem;">
    <h2>Agentic Purchase - LangGraph Saga</h2>
    <p>Use the React chat UI for the full experience. Quick test form below:</p>
    <form action="/saga/start" method="post" enctype="multipart/form-data">
      <p><input type="file" name="image" required /></p>
      <p><input name="user_text" placeholder="e.g., black cup qty 2" style="width: 320px;" /></p>
      <p><input name="card_number" value="4242424242424242" /></p>
      <p><input name="expiry_mm_yy" value="12/29" /></p>
      <p><input name="cvv" value="123" /></p>
      <button type="submit">Run Saga</button>
    </form></body></html>"""


@app.get("/playground", response_class=HTMLResponse)
def playground() -> str:
    return '''<html><body style="font-family: system-ui; padding: 2rem; max-width:780px;">
    <h2>Agentic Purchase – Playground</h2>
    <p>Quick test form with per-request overrides for compensation and token budgets.</p>
    <form action="/saga/start" method="post" enctype="multipart/form-data" style="display:grid; gap:0.6rem;">
      <label>Image <input type="file" name="image" required /></label>
      <input name="user_text" placeholder="e.g., black cup qty 2" style="width: 100%;" />
      <div style="display:flex; gap:0.5rem;">
        <input name="card_number" value="4242424242424242" placeholder="Card number"/>
        <input name="expiry_mm_yy" value="12/29" placeholder="MM/YY"/>
        <input name="cvv" value="123" placeholder="CVV"/>
      </div>
      <fieldset style="border:1px solid #e2e8f0; padding:0.75rem; border-radius:8px;">
        <legend style="font-weight:600;">Per-request overrides</legend>
        <div style="display:grid; grid-template-columns: repeat(3, 1fr); gap:0.5rem;">
          <input name="comp_topk" placeholder="Comp TopK (e.g., 3)"/>
          <input name="comp_price_pct" placeholder="Price window % (e.g., 10)"/>
          <input name="comp_latency_ms" placeholder="Extra latency ms (e.g., 500)"/>
        </div>
        <div style="display:grid; grid-template-columns: 1fr 1fr; gap:0.5rem; margin-top:0.5rem;">
          <input name="token_policy" placeholder="Token policy (warn|truncate|fallback|block)"/>
          <input name="token_budgets_json" placeholder='Token budgets JSON (e.g., {"S3":{"cap":1500}})'/>
        </div>
      </fieldset>
      <button type="submit" style="padding:0.6rem 1rem; background:#0f172a; color:#fff; border:none; border-radius:8px;">Run Saga</button>
    </form>
    <p style="margin-top:0.5rem; color:#64748b;">Overrides also accepted as headers: X-Comp-TopK, X-Comp-PriceWindowPct, X-Comp-LatencyMs, X-Token-Policy, X-Token-Budgets.</p>
    </body></html>'''


@app.get("/mock/{slug}", response_class=HTMLResponse)
async def mock_product(slug: str):
    item = _find_catalog_item(slug)
    if not item:
        raise HTTPException(status_code=404, detail="product_not_found")
    offer = _offer_from_catalog(item)
    reviews = _sample_reviews(offer.title, offer.vendor)
    inventory = (5 + abs(hash(slug)) % 11) or 3
    html = f"""
    <html><body style='font-family: system-ui; padding:2rem; max-width:720px; margin:auto; background:#f8fafc;'>
      <header style='margin-bottom:1.5rem;'>
        <h1 style='margin:0; font-size:1.75rem;'>{offer.title}</h1>
        <p style='margin:0.25rem 0 0 0; color:#475569;'>Vendor: <strong>{offer.vendor}</strong> · ${(offer.price_usd):.2f}</p>
      </header>
      <section style='display:grid; gap:1.25rem;'>
        <img src='{offer.image_url}' alt='{offer.title}' style='width:100%; border-radius:16px; object-fit:cover; aspect-ratio:4/3;'/>
        <div>
          <p style='margin:0; color:#0f172a;'>{offer.description or "Handpicked by the Agentic Purchase system."}</p>
          <p style='margin-top:0.75rem;'><strong>Inventory:</strong> {inventory} units</p>
        </div>
        <div>
          <h2 style='margin-bottom:0.5rem;'>Reviews</h2>
          {"".join(f"<article style='background:#fff; padding:0.75rem 1rem; border-radius:12px; margin-bottom:0.75rem;'>"
                   f"<strong>{rv['author']}</strong> · {rv['rating']}★<p style='margin:0.35rem 0 0;'>{rv['quote']}</p></article>" for rv in reviews)}
        </div>
        <form method='post' action='/mock/{slug}/checkout' style='display:grid; gap:0.5rem;'>
          <input name='card_number' value='4242424242424242' placeholder='Card number' style='padding:0.5rem; border:1px solid #cbd5f5; border-radius:8px;'>
          <div style='display:flex; gap:0.5rem;'>
            <input name='expiry_mm_yy' value='12/29' placeholder='MM/YY' style='flex:1; padding:0.5rem; border:1px solid #cbd5f5; border-radius:8px;'>
            <input name='cvv' value='123' placeholder='CVV' style='flex:1; padding:0.5rem; border:1px solid #cbd5f5; border-radius:8px;'>
          </div>
          <button type='submit' style='padding:0.65rem 1.25rem; background:#0f172a; color:#fff; border:none; border-radius:10px;'>Complete mock checkout (${offer.price_usd:.2f})</button>
        </form>
      </section>
    </body></html>
    """
    return HTMLResponse(html)


@app.post("/mock/{slug}/checkout", response_class=HTMLResponse)
async def mock_checkout(slug: str, card_number: str = Form(...), expiry_mm_yy: str = Form(...), cvv: str = Form(...)):
    item = _find_catalog_item(slug)
    if not item:
        raise HTTPException(status_code=404, detail="product_not_found")
    offer = _offer_from_catalog(item)
    payment = PaymentInput(
        card_number=card_number.strip(),
        expiry_mm_yy=expiry_mm_yy.strip(),
        cvv=cvv.strip(),
        amount_usd=offer.price_usd,
    )
    try:
        trust = await trust_assess(offer)
        receipt = await checkout_pay(offer, payment, idem_key="")
        html = f"""
        <html><body style='font-family: system-ui; padding:2rem; max-width:600px; margin:auto; background:#f8fafc;'>
          <h2>Mock checkout complete</h2>
          <p>Order ID: <strong>{receipt.order_id}</strong></p>
          <p>Vendor: <strong>{receipt.vendor or offer.vendor}</strong></p>
          <p>Amount: <strong>${receipt.amount_usd:.2f}</strong></p>
          <p>Card: <strong>{receipt.card_brand or 'card'} {receipt.masked_card or ''}</strong></p>
          <p>Trust snapshot: risk {trust.risk.title()} · happy reviews {(trust.happy_reviews_pct or 0)*100:.0f}%</p>
          <a href='/mock/{slug}' style='display:inline-block; margin-top:1rem; text-decoration:none; color:#0f172a;'>&larr; Back to product</a>
        </body></html>
        """
    except ValueError as err:
        html = f"""
        <html><body style='font-family: system-ui; padding:2rem; max-width:600px; margin:auto; background:#fef2f2;'>
          <h2 style='color:#b91c1c;'>Checkout failed</h2>
          <p>{str(err)}</p>
          <a href='/mock/{slug}' style='display:inline-block; margin-top:1rem; text-decoration:none; color:#0f172a;'>&larr; Try again</a>
        </body></html>
        """
    return HTMLResponse(html)


saga_router = APIRouter(prefix="/saga", tags=["saga"])


def _parse_overrides(
    *,
    comp_topk: Optional[str],
    comp_price_pct: Optional[str],
    comp_latency_ms: Optional[str],
    token_policy: Optional[str],
    token_budgets_json: Optional[str],
    header_topk: Optional[str],
    header_price_pct: Optional[str],
    header_latency_ms: Optional[str],
    header_token_policy: Optional[str],
    header_token_budgets: Optional[str],
) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    # prefer form values, fallback to headers
    def _pick(a, b):
        return a if a not in (None, "") else b
    # Compensation
    topk_val = _pick(comp_topk, header_topk)
    price_val = _pick(comp_price_pct, header_price_pct)
    lat_val = _pick(comp_latency_ms, header_latency_ms)
    if topk_val:
        try:
            out["comp_top_k"] = int(topk_val)
        except Exception:
            pass
    if price_val:
        try:
            out["comp_price_window_pct"] = float(price_val)
        except Exception:
            pass
    if lat_val:
        try:
            out.setdefault("latency_caps_ms", {})["S4_COMP_EXTRA_LATENCY_MS"] = int(lat_val)
        except Exception:
            pass
    # Token policy and budgets
    pol_val = _pick(token_policy, header_token_policy)
    if pol_val:
        out["token_policy"] = str(pol_val)
    bud_val = _pick(token_budgets_json, header_token_budgets)
    if bud_val:
        import json as _json
        try:
            obj = _json.loads(bud_val)
            if isinstance(obj, dict):
                out["token_budgets"] = obj
        except Exception:
            pass
    return out


@saga_router.post("/preview", response_model=SagaResult)
async def preview_saga(
    request: Request,
    image: UploadFile = File(...),
    user_text: Optional[str] = Form(None),
    preferred_offer_url: Optional[str] = Form(None),
    # Optional per-request overrides (form)
    comp_topk: Optional[str] = Form(None),
    comp_price_pct: Optional[str] = Form(None),
    comp_latency_ms: Optional[str] = Form(None),
    token_policy: Optional[str] = Form(None),
    token_budgets_json: Optional[str] = Form(None),
    # Optional per-request overrides (headers)
    header_topk: Optional[str] = Header(default=None, alias="X-Comp-TopK"),
    header_price_pct: Optional[str] = Header(default=None, alias="X-Comp-PriceWindowPct"),
    header_latency_ms: Optional[str] = Header(default=None, alias="X-Comp-LatencyMs"),
    header_token_policy: Optional[str] = Header(default=None, alias="X-Token-Policy"),
    header_token_budgets: Optional[str] = Header(default=None, alias="X-Token-Budgets"),
):
    suffix = os.path.splitext(image.filename or "")[1] or ".jpg"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
        tmp_file.write(await image.read())
        tmp_path = tmp_file.name

    try:
        overrides = _parse_overrides(
            comp_topk=comp_topk,
            comp_price_pct=comp_price_pct,
            comp_latency_ms=comp_latency_ms,
            token_policy=token_policy,
            token_budgets_json=token_budgets_json,
            header_topk=header_topk,
            header_price_pct=header_price_pct,
            header_latency_ms=header_latency_ms,
            header_token_policy=header_token_policy,
            header_token_budgets=header_token_budgets,
        )
        state = await graph_run_saga_preview_async(
            image_path=tmp_path,
            user_text=user_text,
            preferred_offer_url=preferred_offer_url,
            **overrides,
        )
        result = state_to_payload(state)
        # Rewrite relative image URLs (e.g., /static_eval/...) to absolute for the browser (UI runs on a different origin)
        try:
            base = str(request.base_url).rstrip("/")
            for o in result.get("offers", []) or []:
                iu = o.get("image_url")
                if isinstance(iu, str) and iu.startswith("/"):
                    o["image_url"] = base + iu
            main_offer = result.get("offer")
            if isinstance(main_offer, dict):
                iu = main_offer.get("image_url")
                if isinstance(iu, str) and iu.startswith("/"):
                    main_offer["image_url"] = base + iu
        except Exception:
            pass
        result["profile"] = DEFAULT_CHECKOUT_PROFILE.model_copy()
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"saga_preview_failed: {exc}") from exc
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


@saga_router.post("/start", response_model=SagaResult)
async def start_saga(
    request: Request,
    image: UploadFile = File(...),
    user_text: Optional[str] = Form(None),
    preferred_offer_url: Optional[str] = Form(None),
    card_number: Optional[str] = Form(None),
    expiry_mm_yy: Optional[str] = Form(None),
    cvv: Optional[str] = Form(None),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    # Optional per-request overrides (form)
    comp_topk: Optional[str] = Form(None),
    comp_price_pct: Optional[str] = Form(None),
    comp_latency_ms: Optional[str] = Form(None),
    token_policy: Optional[str] = Form(None),
    token_budgets_json: Optional[str] = Form(None),
    # Optional per-request overrides (headers)
    header_topk: Optional[str] = Header(default=None, alias="X-Comp-TopK"),
    header_price_pct: Optional[str] = Header(default=None, alias="X-Comp-PriceWindowPct"),
    header_latency_ms: Optional[str] = Header(default=None, alias="X-Comp-LatencyMs"),
    header_token_policy: Optional[str] = Header(default=None, alias="X-Token-Policy"),
    header_token_budgets: Optional[str] = Header(default=None, alias="X-Token-Budgets"),
):
    suffix = os.path.splitext(image.filename or "")[1] or ".jpg"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
        tmp_file.write(await image.read())
        tmp_path = tmp_file.name

    try:
        if not (card_number and expiry_mm_yy and cvv):
            raise HTTPException(status_code=400, detail="missing_payment_fields")
        payment = PaymentInput(
            card_number=card_number.strip(),
            expiry_mm_yy=expiry_mm_yy.strip(),
            cvv=cvv.strip(),
            amount_usd=0.0,
        )
        overrides = _parse_overrides(
            comp_topk=comp_topk,
            comp_price_pct=comp_price_pct,
            comp_latency_ms=comp_latency_ms,
            token_policy=token_policy,
            token_budgets_json=token_budgets_json,
            header_topk=header_topk,
            header_price_pct=header_price_pct,
            header_latency_ms=header_latency_ms,
            header_token_policy=header_token_policy,
            header_token_budgets=header_token_budgets,
        )
        state = await graph_run_saga_async(
            image_path=tmp_path,
            user_text=user_text,
            payment=payment,
            preferred_offer_url=preferred_offer_url,
            idempotency_key=idempotency_key,
            **overrides,
        )
        result = state_to_payload(state)
        # Rewrite relative image URLs to absolute
        try:
            base = str(request.base_url).rstrip("/")
            for o in result.get("offers", []) or []:
                iu = o.get("image_url")
                if isinstance(iu, str) and iu.startswith("/"):
                    o["image_url"] = base + iu
            main_offer = result.get("offer")
            if isinstance(main_offer, dict):
                iu = main_offer.get("image_url")
                if isinstance(iu, str) and iu.startswith("/"):
                    main_offer["image_url"] = base + iu
        except Exception:
            pass
        result["profile"] = DEFAULT_CHECKOUT_PROFILE.model_copy()
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"saga_failed: {exc}") from exc
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


app.include_router(saga_router)


@app.post("/intent/prompt", response_model=PromptResponse)
async def intent_prompt(image: UploadFile = File(...)):
    suffix = os.path.splitext(image.filename or "")[1] or ".jpg"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
        tmp_file.write(await image.read())
        tmp_path = tmp_file.name

    try:
        hypo: ProductHypothesis = await intake_image(tmp_path)
        prompt_pack = propose_options(hypo)
        options = prompt_pack.get("options") or []
        if options and isinstance(options[0], str):
            options = [{"key": o, "label": o} for o in options]
            prompt_pack["options"] = options
        return {"hypothesis": hypo, **prompt_pack}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"intent_prompt_failed: {exc}") from exc
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


@app.on_event("startup")
async def _print_routes() -> None:
    try:
        print("\n=== Registered routes ===")
        for route in app.routes:
            if isinstance(route, APIRoute):
                print(f"{sorted(route.methods)}  {route.path}")
        print("=========================\n")
    except Exception:
        pass
