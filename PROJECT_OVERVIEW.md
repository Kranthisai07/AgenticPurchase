# Agentic Purchase System – Comprehensive Reference

This document captures the full context of the Agentic Purchase research project you are publishing, including architecture, tech stack, workflow, data, and reproducibility guidance. It mirrors the description shared with reviewers and can be linked from your IEEE paper or GitHub repository.

---

## 1. Purpose

Deliver a multimodal, agentic shopping assistant that ingests a user photo, understands intent, recommends similar products, and performs mock checkout through a single conversational UI. The project demonstrates autonomous multi-agent orchestration, optional LLM reasoning, and seamless voice-guided UX suitable for research-grade evaluation.

---

## 2. Tech Stack

| Layer | Technology | Role |
|-------|------------|------|
| **Runtime / Orchestration** | **LangGraph** (`Agentic_AI/agentic_graph`) | Governs the S1–S5 purchase saga (capture, intent, sourcing, trust, checkout). Each stage is a node with shared `SagaState`, retries, compensation, and logging. |
| **Agents** | Python modules under `Agentic_AI/apps/agent{1..5}` | Vision (Google Cloud Vision), Intent, Sourcing, Trust, Checkout. Optional LangChain hooks refine intent & rerank offers. |
| **Gateways** | FastAPI (`Agentic_AI/apps/coordinator/main.py`) + LangServe (`Agentic_AI/langserve_app.py`) | FastAPI serves legacy `/intent/prompt`, `/saga/preview`, `/saga/start` for the React UI. LangServe exposes the same LangGraph runners as JSON/base64 APIs with playgrounds. |
| **Contracts** | Pydantic models (`Agentic_AI/libs/schemas/models.py`) | Define `ProductHypothesis`, `PurchaseIntent`, `Offer`, `TrustAssessment`, `Receipt`, `CheckoutProfile`, etc. |
| **Vision API** | Google Cloud Vision | Object localization, OCR, label detection, color extraction. |
| **LLM Integration** | LangChain with OpenAI/Gemini/Ollama | Optional intent refinement and sourcing rerankers. Controlled by `USE_LANGCHAIN_*` env flags. |
| **Catalog Data** | JSON catalog (`Agentic_AI/data/mock_catalog.json`) | Rich per-product metadata (phones, pens, shoes, bottles, laptops). Multiple variants per brand enable “three similar products” suggestions. |
| **Logging & Eval** | JSONL saga logs + `scripts/eval_report.py` | Capture per-stage latency, trust swaps, receipts, token usage for benchmarking. |
| **Frontend** | React + Vite + Tailwind + Web Speech API | Chat UI with image upload, voice prompts, inline checkout summary, and receipt rendering. |

---

## 3. Architecture & Data Flow

1. **React Frontend** – Users upload photos, respond via text/voice, and see the assistant summarize detection, offers, trust, and payment confirmation inline.
2. **FastAPI or LangServe Gateway** – Saves uploaded images to temp files, forwards requests to LangGraph, and returns saga results plus the default checkout profile (Ada Lovelace address/card/shipping).
3. **LangGraph Saga** – Executes the five agents in-process:
   - **S1 Capture**: Vision agent calls Google Cloud Vision, extracts brand/color, optional LangChain refinement.
   - **S2 Intent**: Parses user text/voice to build `PurchaseIntent`; can fallback to LangChain if deterministic parsing fails.
   - **S3 Sourcing**: Matches intent vs. JSON catalog, scores offers, optionally reranks top-K via LangChain under token budgets.
   - **S4 Trust**: Produces `TrustAssessment`; compensates by switching to a safer offer if risk is medium/high.
   - **S5 Checkout**: Validates mock payment (Luhn, CVV, expiry, velocity), enforces idempotency, returns `Receipt`.
4. **Response** – The saga payload (hypothesis, intent, offers, trust, receipt, event log) is serialized to the UI or API client. The React UI displays offer cards, updated profile, trust snippet, and receipts; LangServe responds with JSON for programmable access.

---

## 4. Front-End Experience

- **Image Upload**: Drag-and-drop or camera capture feeds `/intent/prompt` to produce a conversational prompt plus option chips.
- **Offer Preview**: `/saga/preview` runs S1–S4 and returns multiple similar offers (e.g., three iPhone variants) thanks to the expanded catalog.
- **Voice-Guided Flow**:
  - After offers render, the assistant speaks the top matches, then starts SpeechRecognition. Saying “option two” or “Pixel” selects the corresponding offer; typing the option also works.
  - The assistant then asks which card to use. Users can say “Visa”, “Amex”, etc., or select from the on-screen chips (three saved cards with unique CVVs).
  - Status indicators show when the assistant is listening and whether it needs an offer or card.
- **Checkout**: The inline summary shows shipping, selected card, trust score, and totals (subtotal + shipping + estimated tax at 8.75%). Tapping “Pay” posts `/saga/start`, and the assistant reads back the mock receipt (order ID, vendor, masked card, idempotency key).

---

## 5. Data & Catalog

`Agentic_AI/data/mock_catalog.json` contains dozens of entries per category with consistent structure:

- **Phones**: Multiple iPhone (Pro Max, Plus, 14 Pro refurb) and Pixel (8 Pro, 8, Fold) variants, each with brand, model, price, shipping, keywords, descriptions, image URLs.
- **Pens**: Pilot G2 black/color packs, Sharpie S-Gel, BIC Intensity.
- **Shoes**: Nike Pegasus, Nike InfinityRN, Adidas Ultraboost, New Balance 1080.
- **Bottles**: Hydro Flask 32oz & 24oz, Contigo Autoseal, original Nike/Adidas/Puma bottles.
- **Laptops**: Dell XPS 15/13, MacBook Pro/Air M3, Lenovo Yoga 9i.

The Sourcing agent filters by category + brand keywords, so Vision detections like “iPhone” or “Pixel” reliably produce several similar offers.

---

## 6. Reproducibility

1. **Backend Setup (Unified venv at repo root)**
   ```powershell
   cd C:\Project
   # Create or reuse a unified venv at .venv
   .\scripts\setup_venv.ps1
   # Activate it for this session
   .\.venv\Scripts\Activate.ps1
   ```
   - Installs from `Agentic_AI\requirements-agentic.txt`.
   - Place Google Cloud Vision credentials in `Agentic_AI\.env` (point `GOOGLE_APPLICATION_CREDENTIALS` to your service-account JSON).
   - Start the FastAPI gateway: `python -m uvicorn Agentic_AI.apps.coordinator.main:app --reload`
   - Optionally, start the LangServe host: `python -m uvicorn Agentic_AI.langserve_app:app --reload`

2. **Frontend Setup**
   ```bash
   cd agentic-purchase-chat-ui
   npm install
   npm run dev     # VITE_API_BASE defaults to http://127.0.0.1:8000
   ```

3. **Evaluation & Logs**
   - Saga logs (JSONL) capture S1–S5 events, trust swaps, receipts. Use `scripts/eval_report.py` to convert logs into latency/token CSVs for the IEEE manuscript.
   - Unit tests (`pytest`) cover agent logic; front-end builds are validated via `npm run build`.

---

## 7. Key Outputs

- **Hypothesis & Intent**: Detected label/brand/color and parsed purchase intent are shown to the user for transparency.
- **Offer Recommendations**: At least three similar products per detected brand/category (thanks to catalog expansion). Ranked by price, shipping speed, and LLM reranker (if enabled).
- **Trust & Safety**: Trust agent labels each vendor as low/medium/high risk, with simple heuristics (TLS, domain age, policy) and optional LLM adjustments. The saga swaps to a safer offer when needed.
- **Receipt & Idempotency**: Mock checkout returns an order ID, masked card number, brand, and idempotency key. The assistant reads the result aloud and logs the event.
- **Voice Interaction**: Microphone activates sequentially after prompts (offers, cards). Spoken commands like “option two” or “Visa” trigger the respective actions; typed commands are also interpreted.

---

## 8. Evaluation and Metrics

- Dataset
  - Format: YAML list at `evaluation/dataset.yaml` (example provided).
  - Fields per item: `image` (path), optional `user_text`, optional `preferred_offer_url`, and `expect` with `brand`/`family`/`category` for scoring.
  - Add your own images under `evaluation/images/` and update paths.

- What is measured (implemented)
  - Recognition/Intent Alignment: binary hit if hypothesis/intent aligns with expectation (brand equality, or family/category substring).
  - Sourcing Accuracy: Top‑1 and Top‑3 brand hit (by vendor) from returned offers.
  - Latency: per‑stage durations (S1–S5) from the saga event log and client wall‑clock time.
  - Token Usage: prompt/completion counts by stage when LLM features are enabled.

- How to run
  - Start backend (FastAPI or LangServe) as in Section 6.
  - Preview (S1–S4): `python scripts/run_eval.py --dataset evaluation/dataset.yaml --mode preview`
  - Full (S1–S5 + checkout): `python scripts/run_eval.py --dataset evaluation/dataset.yaml --mode start --card-number 4242424242424242 --expiry 12/29 --cvv 123`
  - Summarize: `python scripts/eval_report.py --log Agentic_AI/logs/eval.log`

- Outputs
  - `Agentic_AI/logs/eval_summary.csv` — per‑run metrics (recognition hit, Top‑K, wall‑clock, lat_*)
  - `Agentic_AI/logs/stage_latency.csv` — per‑run per‑stage latencies
  - `Agentic_AI/logs/token_summary.csv` — per‑stage token usage (if logged)

Note: Advanced IR metrics (e.g., NDCG/MRR), trust calibration (AUC/ECE/Brier), statistical confidence intervals, human evaluation, and voice/STT timing are not computed by the current scripts and are listed as future work below.

---

## 9. Suggested Future Enhancements (Optional)

- Ranking metrics: add graded relevance in the dataset and compute NDCG@K/MRR.
- Trust calibration: expose numeric risk scores and report AUC/ECE/Brier.
- Statistical analysis: bootstrap or other CIs; significance tests for deterministic vs LLM runs.
- Voice/STT metrics: log TTS→STT timing and voice selection accuracy end‑to‑end.
- Automated evaluation CI and artifact publishing (CSV/plots) for reviewers.
- LangServe cURL examples and a pre‑release tag (e.g., `v1.0`) with `LICENSE` and `CITATION.cff`.

---

With this document and the repository, reviewers and readers have everything needed to understand, reproduce, and validate the Agentic Purchase System—from the multimodal UI through the LangGraph-controlled agent pipeline and mock checkout flow.
