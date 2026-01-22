# Agentic Purchase Research System – Project Summary

This document is a single reference for the current shape of the project: what we set out to build, how the architecture evolved, the technology in play, and how each folder fits into the overall research system. Use it when presenting the work or onboarding collaborators.

---

## 1. Vision & Evolution

| Phase | Goal | Key Outcomes |
|-------|------|--------------|
| **Initial (legacy repo)** | Demonstrate a “multi-agent” purchase assistant using five FastAPI microservices plus a coordinator (Saga pattern). | Deterministic services (vision → intent → sourcing → trust → checkout) orchestrated sequentially via HTTP. |
| **Current (LLM‑first)** | Replace deterministic agents with LLM-driven reasoning, integrate a real(istic) product corpus, and focus on trust/authenticity (the novelty of the paper). | LangGraph orchestrates S1–S5 nodes. Each node calls a hosted LLM (OpenAI or Gemini) for its reasoning step. Retrieval currently uses the mock catalog while we migrate to richer datasets (e.g., Amazon Berkeley Objects). Trust adds price Z-scores (and is being extended for richer authenticity). |

### What “Agentic” Means Now
- Every stage (capture, intent, sourcing, trust) makes at least one LLM call and produces structured JSON validated with Pydantic.
- Shared `SagaState` carries hypothesis, intent, offers, trust, etc., and now also a `messages` channel so stages can leave “notes” to one another (e.g., intent → sourcing, trust → checkout).
- Compensation logic lives in the LangGraph nodes (S4 can veto an offer and instruct S3 to switch). This is logged as events/messages so you can trace the reasoning chain.

---

## 2. Technology Stack

| Layer | Technology | Notes |
|-------|------------|-------|
| **Runtime** | Python 3.11, FastAPI, LangGraph | LangGraph drives S1–S5 nodes. FastAPI exposes `/intent/prompt`, `/saga/preview`, `/saga/start` for the UI. |
| **LLM** | LangChain + OpenAI (GPT‑4o mini) or Google Gemini | Set via env: `LANGCHAIN_PROVIDER`, `LANGCHAIN_MODEL`, `OPENAI_API_KEY` / `GOOGLE_API_KEY`. All `USE_LANGCHAIN_*` flags are enabled so the system fails fast if keys are missing. |
| **Vision tool** | Google Cloud Vision API | Provides object labels/text; LLM refines the result. Credentials: `GOOGLE_APPLICATION_CREDENTIALS`. |
| **Data retrieval** | Local mock catalog (`Agentic_AI/data/mock_catalog.json`) + external product dataset (Amazon Berkeley Objects planned) | Retrieval hooks live in `Agentic_AI/apps/agent3_sourcing` and `Agentic_AI/libs/providers/`. Replacement dataset prep scripts will live under `scripts/` as we onboard ABO. |
| **Trust/Authenticity** | LLM analysis + price Z-score (`Agentic_AI/data/price_refs.json`) + vendor heuristics | S4 raises risk when price is far below reference or when LLM flags authenticity issues. |
| **Frontend** | React/Vite chat UI (`agentic-purchase-chat-ui`) | Talks to the FastAPI coordinator; unchanged API contract. |

---

## 3. How the System Works (Lifecycle of a Saga)

1. **S1 Capture** (`agent1_vision`)
   - Input: uploaded image path.
   - Flow: Google Vision → evidence → LLM (`vision_chain`) refines into `ProductHypothesis` JSON.
   - Output: hypothesis + a message (“vision → intent: Detected Adidas bottle…”).

2. **S2 Intent** (`agent2_intent`)
   - Input: hypothesis + optional user text.
   - Flow: LLM parses structured `PurchaseIntent` (item, color, quantity, budget).
   - Output: intent + message (“intent → sourcing: Need 2x iPhone, max $1000”).

3. **S3 Sourcing** (`agent3_sourcing`)
   - Retrieves top candidates from the local mock catalog (strict + fuzzy filters). External datasets (ABO) will plug in here next.
   - Scores candidates deterministically, then optionally LLM reranks the shortlist.
   - Writes `offers` + `best_offer` + message (“sourcing → trust: Top candidate Vendor X $799”).

4. **S4 Trust & Authenticity** (`agent4_trust`)
   - Computes vendor risk (TLS, domain age, returns), price/weight/dimension z-scores via `libs/providers/price_refs.py`, cross-checks vision brand/color vs. listing metadata, flags suspicious domains, and scans bullet points for replica cues before handing evidence to the LLM.
   - If risk is medium/high, re-checks other offers (compensation). Messages capture approvals or vetoes.

5. **S5 Checkout** (`agent5_checkout`)
   - Validates payment (Luhn, expiry, CVV). No LLM here; deterministic for safety.
   - Returns `Receipt` and a final message to the user.

Throughout the run, `SagaState.events` keeps timing logs (S1_CAPTURE etc.), and `SagaState.messages` tracks inter-agent messages (vision→intent, trust→checkout, etc.). API responses now include both lists.

---

## 4. Folder-by-Folder Guide

| Path | What’s inside | Why it matters |
|------|---------------|----------------|
| `Agentic_AI/apps/agent1_vision` | FastAPI service + Google Vision wrapper | Handles image intake and LLM refinement. Entry: `intake_image`. |
| `Agentic_AI/apps/agent2_intent` | Intent confirmation logic | LLM-only parser producing `PurchaseIntent`. |
| `Agentic_AI/apps/agent3_sourcing` | Catalog retrieval + scoring | Combines strict/fuzzy mock catalog filters with the ABO dataset adapter; optional LLM rerank. |
| `Agentic_AI/apps/agent4_trust` | Trust & authenticity | Vendor heuristics + price Z-scores + LLM authenticity adjustments. |
| `Agentic_AI/apps/agent5_checkout` | Mock payment | Card validation, idempotent receipts. |
| `Agentic_AI/apps/coordinator` | FastAPI gateway | Routes `/intent/prompt`, `/saga/preview`, `/saga/start`; loads LangGraph saga. |
| `Agentic_AI/agentic_graph` | LangGraph definitions | `state.py` (SagaState), `nodes.py` (S1–S5 coroutines), `graph.py` (connects nodes), `utils.py` (state→payload). Messages feature lives here. |
| `Agentic_AI/libs/agents` | LangChain prompt logic | `vision_chain.py`, `intent_chain.py`, `sourcing_chain.py`, `trust_chain.py`, etc. Each enforces JSON outputs. |
| `Agentic_AI/libs/providers` | External data helpers | `price_refs.py` (price stats) + future dataset adapters (e.g., ABO). |
| `Agentic_AI/data/` | Static datasets | `mock_catalog.json`, `abo_offers.jsonl`, `price_refs.json`. |
| `scripts/` | Utilities | `prepare_abo_offers.py`, `build_price_refs_from_offers.py`, evaluation scripts (`eval_report.py`). |
| `agentic-purchase-chat-ui/` | React UI | Talks to coordinator, displays hypothesis/offers/trust/checkout. |

---

## 5. Setup & Run

1. **Install dependencies** (one time):
   ```powershell
   cd C:\Project
   .\scripts\setup_venv.ps1
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r Agentic_AI/requirements-agentic.txt
   ```

2. **Environment variables** (per session or in `.env`):
   ```powershell
   $Env:USE_LANGCHAIN = "1"            # and USE_LANGCHAIN_VISION / INTENT / SOURCING / TRUST
   $Env:LANGCHAIN_PROVIDER = "openai"  # or google-genai
   $Env:LANGCHAIN_MODEL = "gpt-4o-mini"
   $Env:OPENAI_API_KEY = "sk-..."
   $Env:GOOGLE_APPLICATION_CREDENTIALS = "C:\Project\Agentic_AI\service-account.json"
   ```

3. **Prepare Amazon Berkeley Objects data (once per update)**:
   ```powershell
   python scripts/prepare_abo_offers.py --metadata-dir dataset/listings/metadata --out Agentic_AI/data/abo_offers.jsonl
   python scripts/build_price_refs_from_offers.py Agentic_AI/data/abo_offers.jsonl
   ```

4. **Run backend**:
   ```powershell
   python -m uvicorn Agentic_AI.apps.coordinator.main:app --host 127.0.0.1 --port 8000 --reload
   ```

5. **Run UI** (optional):
   ```powershell
   cd agentic-purchase-chat-ui
   npm install
   npm run dev   # visit http://localhost:5174
   ```

---

## 6. Current “Agents” & Communication

Messages emitted at each stage (visible in API response under `messages`):

| Stage | Example message |
|-------|-----------------|
| S1 (Vision) | `{sender: "vision", recipient: "intent", content: "Detected Adidas bottle", confidence: 0.87}` |
| S2 (Intent) | `{sender: "intent", recipient: "sourcing", content: "Need 1x water bottle in blue", budget: 40}` + `{sender: "intent", recipient: "user", content: "Understood your preference."}` |
| S3 (Sourcing) | `{sender: "sourcing", recipient: "trust", content: "Top candidate VendorX at $29.99", offer_count: 20}` |
| S4 (Trust) | `{sender: "trust", recipient: "checkout", content: "VendorX evaluated as medium", price_z: -2.3}` plus `{sender: "trust", recipient: "sourcing", content: "Switched to Mockazon due to lower risk"}` when compensating. |
| S5 (Checkout) | `{sender: "checkout", recipient: "user", content: "Order confirmed with Mockazon", amount: 29.99, order_id: ...}` |

This gives you traceability for discussions with reviewers/professors: each agent leaves a structured “note” as it hands off to the next stage.

---

## 7. Evaluation & Next Steps

- **Evaluation pipeline**: `scripts/eval_report.py` parses `Agentic_AI/logs/eval.log` to summarise events, latency, and token usage. Extend it to include authenticity metrics (price_z distributions, veto rates, etc.).
- **Planned improvements**:
  - Integrate Amazon Berkeley Objects (ABO) with TF-IDF/FAISS retrieval to replace the Kaggle CSV pipeline entirely.
  - Authenticity badge in the UI using `trust.auth_label` / `price_zscore`.
  - Train a dedicated authenticity classifier (logistic regression or cross-encoder) to augment S4.
  - Optional: add looping edges in LangGraph (e.g., Intent asks for clarification when confidence is low).

---

## 8. Key Talking Points for the Professor

1. **LLM-first agents**: each stage is now driven by the chosen LLM; deterministic logic is only used for tooling and validation.
2. **Dataset roadmap**: we are migrating from Kaggle CSVs to the Amazon Berkeley Objects corpus for higher-quality images and attributes, plugged into the sourcing/trust stages.
3. **Trust/authenticity focus**: price z-scores + LLM reasoning allow us to flag fake/too-cheap listings and automatically switch to safer vendors.
4. **Traceability**: LangGraph events + messages show exactly how agents communicate, making the system explainable.
5. **UI compatibility**: The React chat UI works unchanged—so demos and user studies reuse the original front-end.

With this summary you can explain where the project started, where it is now, what technology it uses, and how each folder contributes to your research goals.
