# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any

import numpy as np
from google.cloud import vision
from google.protobuf.json_format import MessageToDict
from PIL import Image

from ...libs.schemas.models import BBox, ProductHypothesis
from ...libs.utils.colors import rgb_to_name
from ...libs.agents.vision_chain import refine_hypothesis_with_llm

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ObjectConfig:
    display_name: str
    category: Optional[str]


OBJECT_CONFIG: dict[str, ObjectConfig] = {
    "bottle": ObjectConfig(display_name="water bottle", category="drinkware"),
    "cup": ObjectConfig(display_name="cup", category="drinkware"),
    "pen": ObjectConfig(display_name="pen", category="office_supplies"),
    "book": ObjectConfig(display_name="book", category="media"),
    "laptop": ObjectConfig(display_name="laptop", category="electronics"),
    "keyboard": ObjectConfig(display_name="keyboard", category="electronics"),
    "mouse": ObjectConfig(display_name="computer mouse", category="electronics"),
    "cell phone": ObjectConfig(display_name="smartphone", category="electronics"),
    "backpack": ObjectConfig(display_name="backpack", category="bags"),
    "sneaker": ObjectConfig(display_name="sneaker", category="footwear"),
}

ALLOW_LABELS = set(OBJECT_CONFIG.keys())

BRANDS = {
    "nike": "Nike",
    "adidas": "Adidas",
    "puma": "Puma",
    "reebok": "Reebok",
    "under armour": "Under Armour",
    "new balance": "New Balance",
    "camelbak": "CamelBak",
    "contigo": "Contigo",
    "pilot": "Pilot",
    "bic": "BIC",
    "sharpie": "Sharpie",
    "stabilo": "Stabilo",
    "logitech": "Logitech",
    "razer": "Razer",
    "hp": "HP",
    "hewlett": "HP",
    "lenovo": "Lenovo",
    "dell": "Dell",
    "asus": "ASUS",
    "acer": "Acer",
    "apple": "Apple",
    "samsung": "Samsung",
    "sony": "Sony",
    "anker": "Anker",
}

BRAND_DEFAULT_LABEL = {
    "nike": "sneaker",
    "adidas": "sneaker",
    "puma": "sneaker",
    "reebok": "sneaker",
    "under armour": "sneaker",
    "new balance": "sneaker",
}

_LOG_RESPONSES = os.getenv("VISION_LOG_RESPONSES", "0").lower() in {"1", "true", "yes"}
_LOG_DIR = Path(os.getenv("VISION_LOG_DIR", "logs/vision"))

_vision_client: Optional[vision.ImageAnnotatorClient] = None


def _service_account_path() -> Optional[str]:
    candidate = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if candidate and os.path.exists(candidate) and "path\\to\\service-account.json" not in candidate.lower():
        return candidate
    override = os.getenv("VISION_SERVICE_ACCOUNT_FILE")
    if override and os.path.exists(override):
        return override
    project_default = Path(__file__).resolve().parents[2] / "service-account.json"
    if project_default.exists():
        return str(project_default)
    return None


def _client() -> vision.ImageAnnotatorClient:
    global _vision_client
    if _vision_client is None:
        sa_path = _service_account_path()
        if sa_path:
            _vision_client = vision.ImageAnnotatorClient.from_service_account_file(sa_path)
        else:
            _vision_client = vision.ImageAnnotatorClient()
    return _vision_client


def _set_client_for_tests(client: Optional[vision.ImageAnnotatorClient]) -> None:
    global _vision_client
    _vision_client = client


def _log_response(response: vision.AnnotateImageResponse, source: str) -> None:
    if not _LOG_RESPONSES:
        return
    try:
        payload = MessageToDict(response._pb, preserving_proto_field_name=True)  # type: ignore[attr-defined]
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        name = f"vision_{Path(source).stem}_{os.getpid()}"
        outfile = _LOG_DIR / f"{name}.json"
        outfile.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception as err:  # pragma: no cover
        logger.debug("Failed to log vision response: %s", err)


def _dominant_color(resp: vision.AnnotateImageResponse) -> Optional[str]:
    props = resp.image_properties_annotation
    if not props or not props.dominant_colors.colors:
        return None
    top = max(props.dominant_colors.colors, key=lambda c: c.score or 0.0)
    rgb = np.array([top.color.red, top.color.green, top.color.blue], dtype=float)
    return rgb_to_name(rgb)


def _extract_brand(resp: vision.AnnotateImageResponse) -> Optional[str]:
    if not resp.text_annotations:
        return None
    full_text = " ".join([a.description for a in resp.text_annotations])
    if not full_text:
        return None
    lower = full_text.lower()
    for raw, nice in BRANDS.items():
        if raw in lower:
            return nice
    return None


def _bbox_from_object(obj: vision.LocalizedObjectAnnotation, size: tuple[int, int]) -> Optional[BBox]:
    vertices = obj.bounding_poly.normalized_vertices
    if not vertices:
        return None
    width, height = size
    xs = [max(min(v.x, 1.0), 0.0) for v in vertices]
    ys = [max(min(v.y, 1.0), 0.0) for v in vertices]
    x1 = int(min(xs) * width)
    y1 = int(min(ys) * height)
    x2 = int(max(xs) * width)
    y2 = int(max(ys) * height)
    if x1 == x2 or y1 == y2:
        return None
    return BBox(x1=x1, y1=y1, x2=x2, y2=y2)


def _build_hypothesis(
    label: str,
    confidence: float,
    *,
    brand: Optional[str],
    bbox: Optional[BBox],
    color: Optional[str],
) -> ProductHypothesis:
    cfg = OBJECT_CONFIG.get(label, ObjectConfig(display_name=label, category=None))
    return ProductHypothesis(
        label=label,
        brand=brand,
        bbox=bbox,
        confidence=float(round(confidence, 4)),
        clip_vec=None,
        item_type=cfg.category,
        category=cfg.category,
        display_name=cfg.display_name,
        color=color,
    )


def _fallback_from_filename(filename: str) -> ProductHypothesis:
    base = os.path.basename(filename).lower()
    label = "object"
    brand = None
    for raw, nice in BRANDS.items():
        if raw in base:
            brand = nice
            break
    for key in ALLOW_LABELS:
        if key in base:
            label = key
            break
    if label == "object" and brand:
        label = BRAND_DEFAULT_LABEL.get(brand.lower(), label)
    return _build_hypothesis(label=label, confidence=0.5, brand=brand, bbox=None, color=None)


def _langchain_enabled() -> bool:
    flag = os.getenv("USE_LANGCHAIN_VISION", os.getenv("USE_LANGCHAIN", "0"))
    return flag is not None and flag.strip().lower() in {"1", "true", "yes"}


async def _finalize_with_llm(hypothesis: ProductHypothesis, evidence: Dict[str, Any]) -> ProductHypothesis:
    if not _langchain_enabled():
        return hypothesis
    try:
        return await refine_hypothesis_with_llm(hypothesis, evidence)
    except Exception as exc:
        logger.warning("vision_refine_failed: %s", exc, exc_info=True)
        return hypothesis


async def intake_image(filename: str) -> ProductHypothesis:
    evidence: dict[str, Any] = {"source": Path(filename).name}
    try:
        with open(filename, "rb") as f:
            content = f.read()
    except FileNotFoundError:
        evidence["fallback_reason"] = "file_not_found"
        return await _finalize_with_llm(_fallback_from_filename(filename), evidence)

    client = _client()
    image = vision.Image(content=content)
    features = [
        vision.Feature(type=vision.Feature.Type.OBJECT_LOCALIZATION, max_results=5),
        vision.Feature(type=vision.Feature.Type.LABEL_DETECTION, max_results=5),
        vision.Feature(type=vision.Feature.Type.TEXT_DETECTION, max_results=10),
        vision.Feature(type=vision.Feature.Type.IMAGE_PROPERTIES, max_results=1),
    ]

    try:
        response = client.annotate_image({"image": image, "features": features})
    except Exception:
        evidence["fallback_reason"] = "vision_api_error"
        return await _finalize_with_llm(_fallback_from_filename(filename), evidence)

    _log_response(response, filename)

    try:
        with Image.open(filename) as pil_img:
            width, height = pil_img.size
    except Exception:
        width = height = 0

    objects = sorted(
        [obj for obj in response.localized_object_annotations if obj.name.lower() in ALLOW_LABELS],
        key=lambda o: o.score,
        reverse=True,
    )

    brand = _extract_brand(response)
    color = _dominant_color(response)
    evidence.update(
        {
            "detected_brand": brand,
            "dominant_color": color,
        }
    )

    if objects and width and height:
        top = objects[0]
        label = top.name.lower()
        bbox = _bbox_from_object(top, (width, height))
        hypo = _build_hypothesis(
            label=label,
            confidence=top.score or 0.0,
            brand=brand,
            bbox=bbox,
            color=color,
        )
        logger.info(
            "vision_object_localized",
            extra={"label": hypo.label, "brand": hypo.brand, "confidence": hypo.confidence},
        )
        return await _finalize_with_llm(hypo, evidence)

    labels = [
        lab for lab in response.label_annotations if (lab.description or "").lower() in ALLOW_LABELS
    ]
    if labels:
        lab = max(labels, key=lambda l: l.score or 0.0)
        label = (lab.description or "object").lower()
        hypo = _build_hypothesis(
            label=label,
            confidence=lab.score or 0.0,
            brand=brand,
            bbox=None,
            color=color,
        )
        logger.info(
            "vision_label_match",
            extra={"label": hypo.label, "brand": hypo.brand, "confidence": hypo.confidence},
        )
        return await _finalize_with_llm(hypo, evidence)

    if response.localized_object_annotations:
        top = max(response.localized_object_annotations, key=lambda o: o.score or 0.0)
        label = top.name.lower()
        bbox = _bbox_from_object(top, (width, height)) if width and height else None
        hypo = _build_hypothesis(
            label=label,
            confidence=top.score or 0.0,
            brand=brand,
            bbox=bbox,
            color=color,
        )
        logger.info(
            "vision_fallback_object",
            extra={"label": hypo.label, "brand": hypo.brand, "confidence": hypo.confidence},
        )
        return await _finalize_with_llm(hypo, evidence)

    hypo = _build_hypothesis(label="object", confidence=0.0, brand=brand, bbox=None, color=color)
    if hypo.label == "object" and hypo.brand:
        hypo.label = BRAND_DEFAULT_LABEL.get(hypo.brand.lower(), hypo.label)
        cfg = OBJECT_CONFIG.get(hypo.label, ObjectConfig(display_name=hypo.label, category=None))
        hypo.display_name = cfg.display_name
        hypo.category = cfg.category
        hypo.item_type = cfg.category
    logger.info("vision_default_object", extra={"label": hypo.label, "brand": hypo.brand})
    return await _finalize_with_llm(hypo, evidence)


__all__ = ["intake_image", "_set_client_for_tests"]
