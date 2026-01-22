from typing import TypedDict

class StateCfg(TypedDict):
    timeout_s: int
    retries: int
    tokens_est_k: float
    tokens_cap_k: float

TIMEOUTS: dict[str, StateCfg] = {
    "S1_CAPTURE": {"timeout_s": 12, "retries": 2, "tokens_est_k": 0.2, "tokens_cap_k": 0.8},
    "S2_CONFIRM": {"timeout_s": 10, "retries": 2, "tokens_est_k": 0.3, "tokens_cap_k": 1.0},
    "S3_SOURCING": {"timeout_s": 18, "retries": 2, "tokens_est_k": 0.5, "tokens_cap_k": 1.5},
    "S4_TRUST": {"timeout_s": 12, "retries": 1, "tokens_est_k": 0.3, "tokens_cap_k": 1.2},
    "S5_CHECKOUT": {"timeout_s": 16, "retries": 2, "tokens_est_k": 0.2, "tokens_cap_k": 0.8},
}
# ---- Token Budgets & Policy ----
TOKEN_BUDGETS = {
    "S1": {"est": 400,  "cap": 800},   # Capture / Vision prompting (if any)
    "S2": {"est": 700,  "cap": 1000},  # Intent
    "S3": {"est": 1100, "cap": 1500},  # Sourcing (reranker)
    "S4": {"est": 900,  "cap": 1200},  # Trust
    "S5": {"est": 400,  "cap": 800},   # Checkout explanation
}
# Policy when a call would exceed the cap: "warn" | "truncate" | "fallback" | "block"
TOKEN_POLICY = "truncate"
# Safety margin for completion tokens when truncating
TOKEN_OUTPUT_SAFETY = 32
