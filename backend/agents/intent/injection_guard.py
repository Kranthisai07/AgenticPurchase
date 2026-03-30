"""
Prompt injection detection for IntentAgent.
Scores user input for injection risk using heuristic + LLM patterns.
"""
import re

# High-risk patterns that indicate prompt injection attempts
_INJECTION_PATTERNS = [
    r"ignore (previous|all|prior|above) (instructions?|prompt|context)",
    r"disregard (your|the) (system|previous|original) (prompt|instructions?)",
    r"you are now",
    r"act as (a|an|the)\s+\w+",
    r"your (new|real|true) (instructions?|role|purpose|goal|objective) (is|are)",
    r"forget (everything|all) (you|i|we)",
    r"override (your|the) (instructions?|system|prompt)",
    r"jailbreak",
    r"DAN mode",
    r"do anything now",
    r"system:\s*(prompt|message|instruction)",
    r"<\s*system\s*>",
    r"\[INST\]",
    r"###\s*instruction",
    r"<\|im_start\|>",
]

_COMPILED = [re.compile(p, re.IGNORECASE) for p in _INJECTION_PATTERNS]


def detect_prompt_injection(text: str) -> dict:
    """
    Heuristic injection detector.
    Returns {is_injection: bool, risk_score: float, matched_pattern: str | None}
    """
    if not text:
        return {"is_injection": False, "risk_score": 0.0, "matched_pattern": None}

    matches = []
    for pattern in _COMPILED:
        m = pattern.search(text)
        if m:
            matches.append(m.group(0))

    risk_score = min(1.0, len(matches) * 0.4)
    is_injection = risk_score >= 0.4

    return {
        "is_injection": is_injection,
        "risk_score": risk_score,
        "matched_pattern": matches[0] if matches else None,
    }


def sanitize_input(text: str) -> str:
    """
    Remove detected injection fragments from user input.
    Preserves the product-related content.
    """
    for pattern in _COMPILED:
        text = pattern.sub("[REDACTED]", text)
    return text.strip()
