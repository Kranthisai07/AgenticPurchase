# Agentic Purchase Research System

Research sandbox for an **LLM-first purchase assistant** built on LangGraph, OpenAI/Gemini models, and the Amazon Berkeley Objects (ABO) dataset. A single FastAPI coordinator now runs the entire saga (capture -> intent -> sourcing -> trust -> checkout), emits structured traces/messages between agents, and serves static ABO thumbnails so the React chat UI can display the exact listing candidates.

- **LLM everywhere:** every stage except checkout uses an LLM chain with Pydantic validation, token budgeting, and JSON logging.
- **Authenticity signals:** price/weight/dimension Z-scores, brand/domain mismatches, replica keyword sweeps, and trust LLM adjustments gate risky offers.
- **Real corpus:** Kaggle CSVs are gone. Retrieve from `abo_offers.jsonl`, keep images locally under `/dataset/abo-images/small`, and mount them at `/abo-images`.
- **Traceability:** `SagaState.events` + `SagaState.messages` + `/metrics` show how hypotheses evolve, which heuristics fired, and why the system vetoed an offer.

---

## 1. Architecture

```
+--------------------------------------------------------------------------+
| React / Vite UI (frontend)                                               |
|  - image upload  - chips/prompts  - trust badge  - inline checkout       |
+--------------+-----------------------------------------------------------+
               | HTTP (image + metadata)
+--------------v-----------------------------------------------------------+
| FastAPI Coordinator (backend/apps/coordinator)                        |
|  - LangGraph saga S1..S5  - SagaState messages/events                    |
|  - Mock storefront + ABO image mount (/abo-images)                       |
|  - /intent/prompt, /saga/preview, /saga/start, /metrics                  |
+-----+---------------+---------------+---------------+---------------+----+
      |S1             |S2             |S3             |S4             |S5
+-----v----+   +------v----+   +------v----+   +------v----+   +------v----+
|Vision    |->->|Intent      |->->|Sourcing    |->->|Trust       |->->|Checkout    |
|(LLM+GCV) |   |(LLM)       |   |(ABO + LLM) |   |(signals+LLM)|   |(deterministic)|
+----------+   +-----------+   +-----------+   +-----------+   +-----------+
```

- **LangGraph nodes** live in `backend/agentic_graph/`. `state.py` defines `SagaState`, `nodes.py` wires S1-S5, and `graph.py` registers compensating edges (e.g., Trust -> Sourcing when a vendor is vetoed).
- **Messaging channel:** each node appends JSON messages (sender/recipient/content) so you can explain why intent nudged sourcing or why trust escalated.
- **Single process by default:** Agents are imported directly for fast iteration. `scripts/run-all.ps1` still spins up legacy HTTP microservices if you need strict isolation.

---

## 2. Data & Authenticity Pipeline

1. **Download ABO metadata and thumbnails (static images are fine).**
   ```powershell
   aws s3 sync s3://amazon-berkeley-objects/listings/metadata/ `
       dataset/listings/metadata --no-sign-request

   aws s3 sync s3://amazon-berkeley-objects/images/small/ `
       dataset/abo-images/small --no-sign-request
   ```
   > Ensure the AWS CLI is on your `PATH` (`aws --version`). No account is required when using `--no-sign-request`.

2. **Generate structured offers from metadata.**
   ```powershell
   python scripts/prepare_abo_offers.py `
       --metadata-dir dataset/listings/metadata `
       --out backend/data/abo_offers.jsonl `
       --image-prefix http://127.0.0.1:8000/abo-images
   ```
   - Synthesizes deterministic USD prices (ABO lacks prices).
   - Captures bullet points, keywords, dimensions, and derived attributes needed for authenticity checks.

3. **Build price & dimension references for Z-scores.**
   ```powershell
   python scripts/build_price_refs_from_offers.py `
       backend/data/abo_offers.jsonl `
       --out backend/data/price_refs.json
   ```
   - Produces per-(vendor,category) medians + robust spreads for price, weight, and dimensions.

4. **Trust & authenticity features use these artifacts to:**
   - Flag price/weight/dimension anomalies (`compute_price_z`, `compute_weight_z`, `compute_dimension_zscores`).
   - Compare vision-detected brand/color vs. listing metadata.
   - Run regex/lexical checks for replica cues (e.g., "1:1 replicas", "mirror copy").
   - Surface suspicious domains, TLS gaps, policy misses, or vendor blacklist hits.
   - Pass structured evidence into an LLM adjustment step for final `trust.note`.

---

## 3. Repository Layout (excerpt)

```
C:\Project
+-- backend/
|   +-- agentic_graph/          # LangGraph nodes, state, orchestration helpers
|   +-- apps/
|   |   +-- coordinator/        # FastAPI app, sagas, metrics, ABO image mount
|   |   +-- agent1_vision/      # Google Vision wrapper + vision_chain
|   |   +-- agent2_intent/      # Prompt generator + intent_chain
|   |   +-- agent3_sourcing/    # ABO retrieval + reranker + heuristics
|   |   +-- agent4_trust/       # Authenticity heuristics + trust_chain
|   |   +-- agent5_checkout/    # Deterministic payment validation
|   +-- data/
|   |   +-- abo_offers.jsonl    # Generated listings corpus (ABO)
|   |   +-- price_refs.json     # Z-score references built from ABO
|   |   +-- mock_catalog.json   # Legacy mock catalog (fallback/demo)
|   +-- libs/
|   |   +-- agents/             # LangChain helpers (vision/intents/sourcing/trust)
|   |   +-- providers/          # abo_catalog search + price ref utilities
|   +-- logs/                   # JSONL saga + token events (eval.log)
|   +-- tests/                  # Unit tests for agents and graph
|   +-- requirements-agentic.txt
+-- frontend/                   # React/Vite chat client with trust badges
|   +-- src/                    # React components and app logic
|   +-- dist/                   # Production build output
|   +-- package.json
+-- evaluation/                 # Test dataset and evaluation images
|   +-- dataset.yaml            # Labeled test cases with expected outcomes
|   +-- images/                 # Test images for evaluation runs
+-- scripts/
|   +-- prepare_abo_offers.py   # Generate structured offers from ABO metadata
|   +-- build_price_refs_from_offers.py  # Build Z-score references
|   +-- eval_report.py          # Generate evaluation metrics and reports
|   +-- run_eval.py             # Batch evaluation driver
|   +-- run-all.ps1             # Launch all microservices (legacy mode)
|   +-- setup_venv.ps1          # Virtual environment setup helper
+-- docs/
|   +-- PROJECT_SUMMARY.md      # Detailed project documentation
```

---

## 4. Setup & Run

### Prerequisites

- Python 3.11+, PowerShell (on Windows), Node 18+ for the UI.
- AWS CLI v2 (for the public `amazon-berkeley-objects` bucket).
- LLM provider credentials (OpenAI `OPENAI_API_KEY` or Google `GOOGLE_API_KEY`).
- Google Cloud Vision service account JSON for S1 (set `GOOGLE_APPLICATION_CREDENTIALS`).

### 1. Install dependencies

```powershell
cd C:\Project
python -m venv .venv
. .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r backend/requirements-agentic.txt
```

### 2. Prepare the ABO dataset

Follow the steps in Section 2 to download metadata/images, run `prepare_abo_offers.py`, and build `price_refs.json`. The FastAPI coordinator automatically mounts `dataset/abo-images/small` at `/abo-images` when the folder exists.

### 3. Configure environment variables

Create `backend/.env` or export in the shell:

```powershell
$Env:USE_LANGCHAIN = "1"
$Env:USE_LANGCHAIN_VISION = "1"
$Env:USE_LANGCHAIN_INTENT = "1"
$Env:USE_LANGCHAIN_SOURCING = "1"
$Env:USE_LANGCHAIN_TRUST = "1"
$Env:LANGCHAIN_PROVIDER = "openai"      # or google-genai
$Env:LANGCHAIN_MODEL    = "gpt-4o-mini" # override per-stage via LANGCHAIN_*_MODEL
$Env:OPENAI_API_KEY = "sk-..."
$Env:GOOGLE_APPLICATION_CREDENTIALS = "C:\Project\backend\service-account.json"
# Optional overrides:
# $Env:ABO_OFFERS_JSONL = "C:\Project\backend\data\abo_offers.jsonl"
# $Env:PRICE_REFS_JSON  = "C:\Project\backend\data\price_refs.json"
```

### 4. Run the backend (single process)

```powershell
(.venv) PS C:\Project> python -m uvicorn backend.apps.coordinator.main:app `
    --host 127.0.0.1 --port 8000 --reload
```

- Swagger docs: http://127.0.0.1:8000/docs
- Static images: http://127.0.0.1:8000/abo-images/<image_id>.jpg
- Metrics: http://127.0.0.1:8000/metrics (aggregated tokens, latency, event counts)

### 5. Run the chat UI (optional but recommended)

```powershell
cd frontend
npm install
npm run dev   # http://127.0.0.1:5174
```

### 6. Optional multi-service mode

If you prefer the legacy six-process layout:

```powershell
cd C:\Project
Set-ExecutionPolicy -Scope Process RemoteSigned
.\scripts\run-all.ps1   # launches coordinator + S1..S5 on ports 8000 & 8101-8105
```

Set `AGENT_*_URL` variables to force the coordinator to call agents over HTTP.

---

## 5. APIs, Messages, and UI Hooks

- `POST /intent/prompt`: returns the capture hypothesis plus a natural-language confirmation prompt and suggested chips for the UI.
- `POST /saga/preview`: runs S1-S4, returns hypothesis, intent, ranked offers, trust verdict, and message/event logs (no checkout).
- `POST /saga/start`: executes the full saga with payment info, returning a `Receipt`.
- Every saga response includes:
  - `messages`: `[{"sender": "trust", "recipient": "sourcing", "content": "..."}]`
  - `events`: timestamped S1..S5 markers for latency debugging.
  - Offers referencing `/abo-images/...` URLs so the UI can render the actual catalog photo.
- React UI surfaces:
  - Vision hypothesis, reranked offers, trust badge (risk + authenticity label), and `replica_terms` warnings.
  - Inline checkout summary that reuses `/saga/preview` output until the user confirms payment.

---

## 6. Authenticity & Trust Signals

| Signal | Source | Effect |
|--------|--------|--------|
| **Price Z-score** | `price_refs.json` | Low Z (< -2) escalates risk to high; also shown as a badge. |
| **Weight/Dimension anomalies** | `price_refs.json` stats | |z| >= 3 marks medium/high risk and is logged in `trust.dimension_zscores`. |
| **Vision vs. metadata mismatch** | `SagaState.hypothesis` vs `Offer` | Brand/color mismatches add notes and can trigger compensating sourcing runs. |
| **Replica keyword sweep** | Bullet points + keywords (`nodes.py`) | Hits (e.g., "AAA replica", "1:1 copy") populate `trust.replica_terms` for the UI. |
| **Domain heuristics** | Vendor profile table + URL scan | Young domains, missing TLS, lack of policy pages, or suspicious hostnames elevate risk. |
| **LLM trust adjustment** | `trust_chain.py` | Final pass that reasons over structured evidence; writes `trust.note`. |

All evidence is fed into LangGraph messages so you can trace "why this offer was rejected" end-to-end.

---

## 7. Evaluation & Logging

- **Labeled dataset:** `evaluation/dataset.yaml` now encodes `expect.authenticity` (genuine/fake) and `expect.intent` slots (item/color/qty/budget) so we can score trust precision/recall and intent F1. Update/add rows to expand coverage.
- **Batch driver:** With the backend running, execute `python scripts/run_eval.py --dataset evaluation/dataset.yaml --mode preview --base http://127.0.0.1:8000` (add `--label deterministic`, toggle `USE_LANGCHAIN_*`, etc.). Start-mode runs also take mock card data to exercise checkout.
- **JSONL log:** Each run appends `RUN_START`, `RUN_RESULT`, and `TOKEN` rows to `backend/logs/eval.log`, including stage events, offers, trust verdicts, and per-call token budgets.
- **Offline reports:** `python scripts/eval_report.py --log backend/logs/eval.log` now emits:
  - `eval_summary.csv` (per-run metrics, token totals, USD cost estimates),
  - `stage_latency.csv`,
  - `token_summary.csv`,
  - `ranking_metrics.csv` (NDCG@3/MRR),
  - `aggregate_metrics.csv` with trust precision/recall/F1, intent precision/recall/F1, per-stage latency p95/mean, wall-clock p95, and average token/cost numbers.
  Optional pandas output prints means/quantiles inline; add `--bootstrap 500` for CI on ranking metrics.
- **Reproducibility:** Token budgeting is deterministic; rerunning the same dataset with identical flags yields matching `RUN_RESULT`/`TOKEN` rows, which makes before/after comparisons (e.g., ablations, baselines) straightforward via `eval_report.py --compare LOG_A LOG_B`.

---

## 8. Troubleshooting Tips

- **Still seeing mock catalog images?** Confirm `backend/data/abo_offers.jsonl` exists and that `prepare_abo_offers.py` used `--image-prefix http://127.0.0.1:8000/abo-images`. Restart the backend after downloading images so FastAPI remounts `/abo-images`.
- **Irrelevant offers?** Ensure the ABO metadata download completed (all `listings_*.json.gz`). You can cap exports with `--limit` while testing, but production runs should include the full set for better recall. Double-check that the intent payload contains the right brand/color text.
- **AWS CLI "not recognized"?** Add `C:\Program Files\Amazon\AWSCLIV2\` to your PATH or relaunch PowerShell after installation. Use `aws --version` to verify before syncing the datasets.
- **LLM failures:** If any `USE_LANGCHAIN_*` flag is unset or keys are missing, the system falls back to deterministic heuristics. Check the warnings in the Uvicorn console and `/metrics`' `token_policy` section.

---

## 9. Roadmap & Contribution Ideas

1. **Vision vs. listing comparison UI:** visualize price/weight/brand deltas next to each offer card.
2. **Authenticity classifier:** train a logistic regression/cross-encoder using ABO metadata to score replica likelihood.
3. **ABO retrieval enhancements:** plug TF-IDF/FAISS into `backend/libs/providers/abo_catalog.py` so sourcing scales beyond keyword overlap.
4. **Looping edges:** allow Intent to re-ask clarifying questions when LLM confidence drops below a threshold.
5. **Observability:** push `/metrics` snapshots to dashboards or extend `eval_report.py` with authenticity histograms for papers.

Pull requests are welcome--add new agents under `backend/apps/agent*_xyz`, extend LangGraph edges in `agentic_graph`, and document new authenticity signals in both this README and `docs/PROJECT_SUMMARY.md`.
