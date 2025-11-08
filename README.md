# AgenticCommerce
Research framework demonstrating image-driven product procurement with agentic AI orchestration.
=======
﻿# Agentic Purchase Research System

This repository contains a research‑grade, multi‑agent purchase assistant that combines computer vision, language understanding, sourcing heuristics, trust analysis, and mock checkout. By default it runs in‑process using a LangGraph state machine behind a single FastAPI gateway. The legacy microservice mode (six FastAPI services: five workers + a coordinator) is still supported for distributed deployments. The project ships with an optional React chat UI, pluggable LLM support (OpenAI / Gemini / Ollama), token budgeting, and an evaluation harness that logs every saga and token event.

Note: The default runtime now uses an in-process LangGraph orchestration with a single FastAPI gateway. The legacy multi-service mode remains available, but most development and experiments run in one process for speed and reproducibility.

## Quickstart (Unified venv)

```
cd C:\Project
./scripts/setup_venv.ps1
./.venv/Scripts/Activate.ps1
python -m uvicorn Agentic_AI.apps.coordinator.main:app --reload
```

- Built‑in playground: http://127.0.0.1:8000/playground (per‑request overrides)
- React UI (optional): `cd agentic-purchase-chat-ui && npm install && npm run dev`

## Agentic Graph (In‑Process)

- Source: `Agentic_AI/agentic_graph/` (state, nodes, graph, orchestrator, utils)
- Endpoints (FastAPI coordinator): `/saga/preview` (S1–S4) and `/saga/start` (S1–S5)
- Optional LangServe host: `python -m uvicorn Agentic_AI.langserve_app:app --reload` exposing `/saga/*/invoke`

### S3 Parallel Branching
- Two sourcing strategies run in parallel and merge:
  - Strict branch: brand+category and item-name tokens required
  - Fuzzy branch: relaxed keyword/substring matching
- Merge: dedupe by URL, prefer higher score; optional LLM rerank (token‑budgeted) still applies.
- New events in response/log: `S3_BRANCH` (strict_count, fuzzy_count) and `S3_SOURCING` (offer_count, best_vendor, best_price)

### S4 Bounded Compensation
- If the chosen vendor is risky (medium/high), try up to K safer alternatives within a price window and extra latency cap.
- Defaults (env): `S4_COMP_TOPK=3`, `S4_COMP_PRICE_WINDOW_PCT=10`, `S4_COMP_EXTRA_LATENCY_MS=500`
- Per‑request overrides (form or headers) are supported and surfaced at `/playground`:
  - Form: `comp_topk`, `comp_price_pct`, `comp_latency_ms`, `token_policy`, `token_budgets_json`
  - Headers: `X-Comp-TopK`, `X-Comp-PriceWindowPct`, `X-Comp-LatencyMs`, `X-Token-Policy`, `X-Token-Budgets`
- Event per attempt: `S4_COMPENSATE` with `{candidate_vendor, candidate_risk, price_delta_pct, switched}`

## Evaluation Harness

- Dataset: `evaluation/dataset.yaml` (images live in `evaluation/images/`)
- Runner: `scripts/run_eval.py` (FastAPI legacy or `--langserve`)
  - Example: `python scripts/run_eval.py --dataset evaluation/dataset.yaml --mode preview --label deterministic`
- Reporter: `scripts/eval_report.py`
  - Outputs: `eval_summary.csv`, `stage_latency.csv`, `token_summary.csv`, `ranking_metrics.csv`
  - Options: `--compare LOG_A LOG_B` and `--bootstrap 1000`

## Unified Environment
- Use the root venv for everything: `scripts/setup_venv.ps1` → `./.venv/Scripts/Activate.ps1`
- Backend deps pinned in `Agentic_AI/requirements-agentic.txt`

---
## 1. Architecture

- Default (in‑process): React UI → FastAPI gateway → LangGraph saga (S1–S5 nodes) calling Python modules in `Agentic_AI/apps/agentX_*`.
  - Benefits: lower latency, simpler debugging, single venv, reproducible evaluation.
- Optional microservices: the same agent modules can be exposed as separate FastAPI services (ports 8101–8105) and called over HTTP by the gateway.
- The gateway owns saga orchestration, budgets, logging, and mock storefront pages. LangServe is provided for programmatic clients and playgrounds.

---
## 2. Repository Layout

```
C:\Project
├── Agentic_AI/
│   ├── agentic_graph/           # LangGraph saga (state, nodes, graph, orchestrator, utils)
│   ├── apps/
│   │   ├── coordinator/         # FastAPI gateway (/saga/*, /playground, /metrics, mock storefront)
│   │   ├── agent1_vision/       # Vision intake (Cloud Vision + optional LLM)
│   │   ├── agent2_intent/
│   │   ├── agent3_sourcing/
│   │   ├── agent4_trust/
│   │   └── agent5_checkout/
│   ├── libs/
│   │   ├── agents/              # LLM helpers (vision refinement, sourcing rerank, trust adjust)
│   │   └── schemas/models.py    # Pydantic data contracts
│   ├── data/mock_catalog.json   # Catalog used by S3 & mock storefront
│   ├── langserve_app.py         # Optional LangServe host (/saga/*/invoke)
│   ├── logs/                    # eval.log etc.
│   └── requirements-agentic.txt
├── evaluation/
│   ├── dataset.yaml             # Batch evaluation dataset
│   └── images/                  # Evaluation images
├── scripts/
│   ├── setup_venv.ps1           # Unified venv bootstrapper
│   ├── run_eval.py              # Batch runner → logs JSONL
│   └── eval_report.py           # Summarize logs → CSVs (incl. ranking_metrics.csv)
├── agentic-purchase-chat-ui/    # React + Vite frontend (optional)
└── README.md
```

---
## 3. Coordinator & Saga Details

### Saga States (S1–S5)
- S1 Capture: Vision intake (Google Cloud Vision + optional LLM refinement)
- S2 Intent: Extract item/color/qty/budget (rules + optional LLM)
- S3 Sourcing: Score catalog, run strict+fuzzy branches in parallel, merge, optional LLM rerank
- S4 Trust: Heuristics + bounded compensation to safer vendors (TopK, price window %, latency cap)
- S5 Checkout: Mock card validation + idempotent receipt

Key behaviors
- Timeouts/retries are enforced at the gateway, with additional S4 compensation latency caps.
- Idempotency: `/saga/start` accepts `Idempotency-Key` to avoid duplicate charges.
- Token budgets: `TokenBudgeter` enforces caps and writes TOKEN events; used by the S3 LLM reranker when enabled.

### Metrics & Logs
- `GET /metrics` (coordinator) returns:
  ```json
  {
    "uptime_s": 123.45,
    "states": {"S3_SOURCING": {"count_ok": 10, "avg_s": 1.23, ...}, ...},
    "config": {...timeouts...},
    "evaluation": {"recognition": {...}, "ranking": {...}, "events_logged": N},
    "tokens": {
      "aggregate": {"S3": {"prompt": 560, "completion": 210, "calls": 4}, ...},
      "local": {...coordinator-only...},
      "agents": {"sourcing": {...}, "trust": {...}, ...}
    }
  }
  ```
- `logs/eval.log` contains one JSON object per saga event (`type`: S1_CAPTURE…S5_CHECKOUT, SAGA_COMPLETE) plus TOKEN events. Each entry includes timestamps, run IDs, models, budgets, etc.
- `scripts/eval_report.py` parses `eval.log`, writes CSV summaries (`eval_summary.csv`, `token_summary.csv`), and prints quick tables (counts by state, token usage by state/role). Requires pandas for the optional tables.

---
## 4. Worker Agents

| Agent | FastAPI Module | Key Routes | Notes |
|-------|----------------|------------|-------|
| Vision (8101) | `apps/agent1_vision/service.py` | `GET /health`, `POST /intake` (multipart) | Uses Google Cloud Vision; optional LLM refinement. `/metrics` exposes token counters if running in-process. |
| Intent (8102) | `apps/agent2_intent/service.py` | `GET /health`, `POST /confirm` | Falls back to heuristics if LLM unavailable. `/metrics` provides token counts. |
| Sourcing (8103) | `apps/agent3_sourcing/service.py` | `GET /health`, `POST /offers` | Ranking heuristic + optional LLM rerank with `TokenBudgeter`. |
| Trust (8104) | `apps/agent4_trust/service.py` | `GET /health`, `POST /assess` | Determines risk level (low/medium/high) and returns trust snapshot. |
| Checkout (8105) | `apps/agent5_checkout/service.py` | `GET /health`, `POST /pay` | Validates card via Luhn, expiry, CVV presence; returns receipt. |

Every agent now also exposes `GET /metrics` returning `{ "tokens": {...} }` so the coordinator can aggregate usage.

---
## 5. LLM Integration & Configuration

- **Provider Selection**: `libs/agents/llm.py` reads `LANGCHAIN_PROVIDER` (`openai`, `google-genai`, `ollama`).
- **Model overrides**: `LANGCHAIN_MODEL` or per-feature `LANGCHAIN_{FEATURE}_MODEL`.
- **Feature flags**: set `USE_LANGCHAIN=1` or granular (`USE_LANGCHAIN_INTENT`, `USE_LANGCHAIN_SOURCING`, `USE_LANGCHAIN_TRUST`, `USE_LANGCHAIN_VISION`).
- **API Keys**:
  - OpenAI: `OPENAI_API_KEY`
  - Gemini: `GOOGLE_API_KEY`
  - Ollama: ensure server running and set `LANGCHAIN_BASE_URL` / `OLLAMA_BASE_URL` if needed.
- **Token Counting**: For OpenAI models, `tiktoken` gives precise usage; otherwise heuristic (chars/4).
- **Response Cache**: `TokenBudgeter` uses `prompt_cache_key` for optional caching (expansion point). Currently S3 reranker caches in-memory across calls to avoid double spending.

---
## 6. Running the System

### Default (single process)
```powershell
cd C:\Project
./scripts/setup_venv.ps1
./.venv/Scripts/Activate.ps1
python -m uvicorn Agentic_AI.apps.coordinator.main:app --reload
```
- Playground: http://127.0.0.1:8000/playground
- Swagger: http://127.0.0.1:8000/docs

### Optional: LangServe host
```powershell
python -m uvicorn Agentic_AI.langserve_app:app --reload
```
Playgrounds at `/saga/preview/playground/` and `/saga/start/playground/`; programmatic access via `/saga/*/invoke`.

### Legacy microservices (for distributed setups)
If you prefer 5 agents + coordinator as separate services, use `scripts/run-all.ps1` and the `AGENT_*_URL` env vars. The gateway will call agents over HTTP.

---
## 7. Logs & Evaluation Workflow

1. Run sample saga(s) via UI or `/saga/start`.
2. Inspect `Agentic_AI/logs/eval.log` for JSONL entries (SAGA & TOKEN events).
3. Generate CSV summaries:
   ```powershell
   (.venv) PS C:\Project> python scripts/eval_report.py
   ```
   Outputs CSVs in `Agentic_AI/logs/` and prints aggregated tables (if pandas present).
4. Publish metrics: include `/metrics` JSON snapshots in your paper’s appendix.

---
## 8. Directory/Module Reference

### Agentic_AI/apps/coordinator
- **main.py** – FastAPI routes (/health, /metrics, /intent/prompt, /saga/start, mock storefront, cascaded token aggregation).
- **saga.py** – Orchestrates S1–S5, handles timeouts/retries/compensation, logs events, records recognition/ranking accuracy.
- **config.py** – `TIMEOUTS`, `TOKEN_BUDGETS`, `TOKEN_POLICY`, `TOKEN_OUTPUT_SAFETY` (edit to match experimental budgets).
- **metrics.py** – Latency stats + evaluation counts; includes `TokenCounters` for live prompt/completion totals.
- **metrics_tokens.py** – TokenBudgeter, tokenizer utilities, JSONL logging, prompt cache key.
- **clients.py** – HTTP vs local function adapters (honors `AGENT_*_URL`).

### Agentic_AI/apps/agentX
Each agent has `service.py` (FastAPI routes) + `main.py` (core logic). All expose `GET /health`, main POST route, and now `GET /metrics` for token stats. Agents rely on shared models from `libs/schemas/models.py`.

### Agentic_AI/libs
- **agents/llm.py** – Provider selection (OpenAI/Gemini/Ollama) with environment overrides.
- **agents/sourcing_chain.py** – LLM-based reranker (budget-aware) with Pydantic output parser.
- **schemas/models.py** – Pydantic models for hypothesis/intent/offer/trust/receipt.

### Scripts
- **run-all.ps1** – Launch multi-agent stack; auto-loads `.env` into each window.
- **eval_report.py** – Summarize `logs/eval.log` into CSV; prints aggregated metrics when pandas available.

### Frontend (agentic-purchase-chat-ui)
- `src/App.jsx` – Chat UI: image upload preview, quick action buttons, voice input (Web Speech API), summarises saga output, opens mock storefront.
- `tailwind.config.js`, `vite.config.js` – build tooling; run `npm run dev` for local dev server.

---
## 9. Key Files & Their Purpose

| File | Purpose |
|------|---------|
| `Agentic_AI/apps/coordinator/main.py` | All API routes + metrics aggregation + mock storefront |
| `Agentic_AI/apps/coordinator/saga.py` | Saga orchestration, state logging, evaluation hooks |
| `Agentic_AI/apps/coordinator/config.py` | Timeouts + token budgets/policy |
| `Agentic_AI/apps/coordinator/metrics.py` | Latency/eval metrics + live token counters |
| `Agentic_AI/apps/coordinator/metrics_tokens.py` | Token counting/enforcement/logging |
| `Agentic_AI/libs/agents/sourcing_chain.py` | Prompt + parser + budget aware rerank |
| `Agentic_AI/libs/agents/llm.py` | Provider selection (OpenAI/Gemini/Ollama) |
| `Agentic_AI/apps/agent*_service.py` | Per-agent FastAPI entry points |
| `Agentic_AI/data/mock_catalog.json` | Mock e-commerce catalog |
| `scripts/run-all.ps1` | Launch all agents + coordinator |
| `scripts/eval_report.py` | Convert JSONL logs to CSV + tables |
| `agentic-purchase-chat-ui/src/App.jsx` | Chat front-end for demos |

---
## 10. Experimental Playbook

1. **Single Saga Run**: launch the stack → upload product image via chat → choose quick action → observe results & logs.
2. **Token Policy Tests**:
   - Set `TOKEN_POLICY="block"` and lower S3 cap to a tiny number to see the reranker raise `token_budget_block`.
   - Set `TOKEN_POLICY="fallback"` to force deterministic ranking when a rerank would exceed the cap.
3. **Provider Swap**: change `LANGCHAIN_PROVIDER` to `google-genai` or `ollama`; ensure dependencies exist; rerun sagas.
4. **Ablation**: toggle `USE_LANGCHAIN_*` to compare recognition/ranking metrics.
5. **Offline Analysis**: run `scripts/eval_report.py`, load the CSVs into pandas/Excel, plot histograms of per-state latency and token usage.

---
## 11. Known Limitations & Next Steps

- Recognition accuracy currently uses a simple heuristic (matching labels/brands/colors). For publishable results, build a labeled test set.
- Token counters aggregate by string state IDs (S1..S5). Extend budgets to sub-modules if you embed more LLM calls.
- Coordinator aggregates only agent metrics reachable via HTTP; offline logs remain per-process.
- Trust agent uses heuristic signals; extend to real TLS/HSTS/WHOIS/Safe-Browsing APIs if you need real security scoring.

Potential enhancements:
- Add per-agent `/metrics/latency` endpoints and coordinator fan-in for latency as well as tokens.
- Implement direct OpenAI/Gemini SDK calls instead of LangChain inside `llm.py` for greater control.
- Hook `scripts/eval_report.py` into a notebook/pipeline for automated report generation.

---
## 12. Support & Contribution

- **Bug reports**: open issues referencing the relevant agent or coordinator module.
- **Extending**: add new agents under `Agentic_AI/apps/agent6_xyz`, update `scripts/run-all.ps1`, and supply a new state in `coordinator/saga.py` and `config.py`.
- **Testing**: run `pytest` inside `Agentic_AI` (existing tests cover vision/intent/sourcing/trust/checkout components).

Happy experimenting with the Agentic Purchase research system!

---
## 13. Methodology (Implementation)

- Architecture Pattern
  - Multi-agent orchestration with a central FastAPI coordinator that executes a five-stage purchase saga (S1–S5).
  - Each agent is an independent FastAPI app that can run in-process (direct Python calls) or out-of-process (HTTP) selected via `AGENT_*_URL` env vars.
  - Shared Pydantic models in `Agentic_AI/libs/schemas/models.py` define strict contracts between stages.

- Core Components
  - Coordinator Orchestrator
    - Files: `Agentic_AI/apps/coordinator/saga.py`, `Agentic_AI/apps/coordinator/main.py`, `.../clients.py`.
    - Runs the saga, enforces per-state timeouts from `.../config.py:TIMEOUTS`, logs events/metrics, forwards correlation headers, and performs simple compensation if trust is risky.
  - Agent 1 – Vision
    - Files: `Agentic_AI/apps/agent1_vision/main.py`, `.../service.py`.
    - Tools: Google Cloud Vision (object localization, labels, text, image properties), PIL/NumPy; optional LLM refinement `libs.agents.vision_chain`.
    - Output: `ProductHypothesis` (label, display name, brand, color, bbox, confidence).
  - Agent 2 – Intent
    - File: `Agentic_AI/apps/agent2_intent/main.py`.
    - Tools: rule-based parsing for quantity, budget, color; optional LLM chain `libs.agents.intent_chain`.
    - Output: `PurchaseIntent` (item name, color, qty, budget, brand/category).
  - Agent 3 – Sourcing
    - File: `Agentic_AI/apps/agent3_sourcing/main.py`.
    - Tools: deterministic scoring over `data/mock_catalog.json` (price/ship/ETA + brand/color match bonuses); optional LLM rerank with token budgeting.
    - Output: ordered list of `Offer`s with images, price, ETA, vendor; URLs rewritten to a mock site via `MOCK_SITE_BASE`.
  - Agent 4 – Trust
    - File: `Agentic_AI/apps/agent4_trust/main.py`.
    - Tools: heuristic risk signals; optional LLM; returns `TrustAssessment` (risk, TLS, returns, refund time, etc.).
  - Agent 5 – Checkout
    - File: `Agentic_AI/apps/agent5_checkout/main.py`.
    - Tools: local validation (`libs.utils.payment`) — Luhn, CVV/expiry, brand detection, velocity checks — plus idempotency keying; returns `Receipt`.

- Data Flow & Contracts
  - Coordinator passes typed models: `ProductHypothesis → PurchaseIntent → [Offer] → TrustAssessment → Receipt`.
  - When using HTTP, requests are JSON with Pydantic schemas; for in-process mode, the same functions are invoked directly.
  - Headers (`X-Request-ID`, `X-Trace-ID`, `Idempotency-Key`) propagate through `apps/coordinator/clients.py`.
  - Checkout idempotency: caller may supply an idempotency key; otherwise it’s derived from offer+card payload to prevent duplicate charges.

- Frontend Chat Integration
  - App: `agentic-purchase-chat-ui` (React/Vite/Tailwind). Voice input and TTS optional via Web APIs.
  - Endpoints used by the UI:
    - `POST /intent/prompt` - builds a natural confirmation prompt and suggested option chips.
    - `POST /saga/preview` - runs S1-S4, returns hypothesis, intent, ranked offers, trust, and a saved checkout profile for display (no charge).
    - `POST /saga/start` - confirms a selected offer and posts saved payment fields; returns a `Receipt`.
    - `LangServe` host: launch via `python -m uvicorn Agentic_AI.langserve_app:app --reload` to expose the LangGraph saga as LangServe runnables (`/saga/preview` and `/saga/start` expect base64-encoded images + JSON payloads).
  - The UI renders offer cards and an inline checkout summary within the chat bubble to keep the flow in one place.

- Orchestration, Timeouts, and Metrics
  - Timeouts per state in `.../config.py:TIMEOUTS`; enforced via `asyncio.wait_for` wrappers in `saga.py`.
  - Metrics record per-state latency and optional token budgets (`metrics.py`, `metrics_tokens.py`). JSONL logs enable offline evaluation via `scripts/eval_report.py`.

- Tooling & Providers
  - Backend: FastAPI, httpx, Pydantic, PIL, NumPy, Google Cloud Vision; optional LangChain with OpenAI/Gemini/Ollama backends.
  - Frontend: React, Vite, Tailwind, Lucide icons; Web Speech API for STT/TTS.

- Deployment Modes
  - Single-process: coordinator imports agents as modules for development and low latency.
  - Microservices: set `AGENT_VISION_URL`, `AGENT_INTENT_URL`, `AGENT_SOURCING_URL`, `AGENT_TRUST_URL`, `AGENT_CHECKOUT_URL` to route via HTTP (Docker-friendly).

- Safety & Reliability
  - Rigorous input validation, idempotent checkout, and compensation when trust risk is high.
  - Deterministic fallbacks: if LangChain/LLM calls fail or exceed token caps, agents revert to heuristic logic so the saga completes.

- Configuration
  - `.env` drives provider/API keys, feature flags (`USE_LANGCHAIN_*`), and mock storefront base.
  - Vision credentials discovered from `GOOGLE_APPLICATION_CREDENTIALS`, `VISION_SERVICE_ACCOUNT_FILE`, or the project default path.

---
## 14. System Workings (Step‑By‑Step)

- S1 Capture (Vision)
  - UI uploads image; Agent 1 detects object/brand/color using Cloud Vision; optional LLM refines to a `ProductHypothesis`.
- S2 Intent (Disambiguation)
  - Agent 2 converts hypothesis + user text (e.g., "same item", "different color blue", budgets/quantities) into `PurchaseIntent`.
- S3 Sourcing (Offers)
  - Agent 3 scores catalog entries, may rerank with LLM under a token budget, and returns top offers with images/price/ETA.
- S4 Trust (Risk)
  - Agent 4 assigns `TrustAssessment`. If risk is medium/high and a safer runner‑up exists, the coordinator switches the winning offer.
- S5 Checkout (Payment)
  - UI confirms selection inline; coordinator validates payment (Luhn/CVV/expiry), ensures idempotency, and returns a `Receipt` which the UI renders in chat.
>>>>>>> 479ff97 (Initial Commit)
