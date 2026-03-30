"""
VisionAgent — analyzes images to produce structured product descriptions.

Self-evaluation: rejects results with confidence < 0.6.
"""
import base64
import json
from typing import Any

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from backend.agents.base import BaseAgent
from backend.agents.vision.prompts import (
    VISION_SYSTEM_PROMPT,
    VISION_USER_PROMPT_IMAGE,
    VISION_USER_PROMPT_TEXT_ONLY,
)
from backend.core.config import get_settings
from backend.models.agent_messages import AgentType
from backend.models.agent_results import VisionFailure, VisionSuccess
from backend.models.agent_tasks import VisionTask

CONFIDENCE_THRESHOLD = 0.6


class VisionAgent(BaseAgent):
    agent_type = AgentType.VISION
    timeout = 15

    def __init__(self) -> None:
        settings = get_settings()
        llm = ChatOpenAI(
            model=settings.openai_model_orchestrator,
            api_key=settings.openai_api_key,
            temperature=0,
        )
        super().__init__(llm=llm)

    async def _execute(self, task: VisionTask) -> VisionSuccess | VisionFailure:
        if task.image_bytes:
            return await self._analyze_image(task.image_bytes, task.user_text)
        elif task.user_text:
            return await self._analyze_text(task.user_text)
        else:
            return VisionFailure(
                error="no_product_detected",
                suggestion="Please describe the product you're looking for or upload a photo.",
            )

    async def _analyze_image(
        self, image_bytes: bytes, user_text: str | None
    ) -> VisionSuccess | VisionFailure:
        try:
            b64 = base64.b64encode(image_bytes).decode()
            content: list[Any] = [
                {"type": "text", "text": VISION_USER_PROMPT_IMAGE},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "high"},
                },
            ]
            if user_text:
                content.append(
                    {"type": "text", "text": f"Additional context from user: {user_text}"}
                )

            messages = [
                SystemMessage(content=VISION_SYSTEM_PROMPT),
                HumanMessage(content=content),
            ]
            response = await self._invoke_llm(messages)
            return self._parse_llm_response(response.content)

        except Exception as exc:
            if "timeout" in str(exc).lower():
                return VisionFailure(
                    error="api_timeout",
                    suggestion="Image analysis timed out. Please try again.",
                )
            return VisionFailure(
                error="image_unclear",
                suggestion="I couldn't analyze the image. Please try a clearer photo or describe the product.",
            )

    async def _analyze_text(self, user_text: str) -> VisionSuccess | VisionFailure:
        prompt = VISION_USER_PROMPT_TEXT_ONLY.format(user_text=user_text)
        messages = [
            SystemMessage(content=VISION_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]
        try:
            response = await self._invoke_llm(messages)
            return self._parse_llm_response(response.content)
        except Exception:
            return VisionFailure(
                error="no_product_detected",
                suggestion="I couldn't understand the product description. Could you rephrase?",
            )

    def _parse_llm_response(self, content: str) -> VisionSuccess | VisionFailure:
        try:
            # Strip markdown code fences if present
            cleaned = content.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("```")[1]
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:]
            data = json.loads(cleaned.strip())
            return VisionSuccess(
                product_description=data["product_description"],
                detected_attributes=data.get("detected_attributes", {}),
                confidence=float(data.get("confidence", 0.0)),
            )
        except (json.JSONDecodeError, KeyError, ValueError):
            return VisionFailure(
                error="no_product_detected",
                suggestion="I couldn't identify a product. Please try again with a clearer image or description.",
            )

    async def _self_evaluate(self, result: Any) -> tuple[bool, str]:
        if isinstance(result, VisionFailure):
            return True, ""  # Failures are valid results — let orchestrator handle them

        if isinstance(result, VisionSuccess):
            if result.confidence < CONFIDENCE_THRESHOLD:
                return False, (
                    f"confidence {result.confidence:.2f} is below threshold {CONFIDENCE_THRESHOLD}"
                )
            if not result.product_description.strip():
                return False, "product_description is empty"

        return True, ""
