# Agentic Purchase — Week‑1 MVP Scaffold

End-to-end demo: upload/take a product image → Vision hypothesis → Intent confirm → Sourcing/ranking from mock catalog → Trust check → Test checkout → Receipt.

## Quickstart (Unified venv)

```powershell
cd C:\Project
./scripts/setup_venv.ps1
./.venv/Scripts/Activate.ps1
python -m uvicorn backend.apps.coordinator.main:app --reload
```

- Playground with per‑request overrides: http://127.0.0.1:8000/playground
- Swagger: http://127.0.0.1:8000/docs

> The vision agent uses Google Cloud Vision. Provide credentials via `GOOGLE_APPLICATION_CREDENTIALS=C:\path\to\service-account.json` (or supply `VISION_SERVICE_ACCOUNT_FILE`). If you drop a `service-account.json` alongside the code it will be picked up automatically.

To experiment with standalone networked agents, see `docs/networked-architecture.md` for the port layout and environment variables the coordinator expects.

### Multi-service (Docker Compose)

Run every agent as its own FastAPI service (plus the chat UI) with a single command:

1. Copy `.env.example` to `.env` and populate `GOOGLE_API_KEY` with your Gemini key. Make sure `service-account.json` lives in the project root (or update the volume mount).
2. Ensure Docker Desktop is running, then execute:
   ```bash
   docker compose up --build
   ```
3. The coordinator will be available at http://127.0.0.1:8000 (Swagger) and the chat UI at http://127.0.0.1:5173 while services talk over the internal network.
4. Stop everything with `docker compose down` when you are finished.

### Optional: LangChain-backed Agents (Intent / Sourcing / Trust)
- Choose a provider: set `OPENAI_API_KEY` for OpenAI-compatible endpoints, or install [Ollama](https://ollama.com), run `ollama pull llama3`, and export `LANGCHAIN_PROVIDER=ollama`. Override with `LANGCHAIN_MODEL` or feature-specific variables such as `LANGCHAIN_INTENT_MODEL`; set `OLLAMA_BASE_URL` or `LANGCHAIN_BASE_URL` if the endpoint differs from the default.
- Enable features via flags: `USE_LANGCHAIN_VISION=1`, `USE_LANGCHAIN_INTENT=1`, `USE_LANGCHAIN_SOURCING=1`, `USE_LANGCHAIN_TRUST=1` (or set `USE_LANGCHAIN=1` to enable all). Optional knobs per feature: `LANGCHAIN_{FEATURE}_MODEL`, `LANGCHAIN_{FEATURE}_TEMPERATURE`, `LANGCHAIN_{FEATURE}_BASE_URL`.
- Agents always fall back to deterministic logic if the LangChain call fails, so you can toggle these flags without breaking the saga.


## Project Layout
```
backend/
  apps/
    coordinator/         # FastAPI app with saga state machine
    agent1_vision/       # Google Cloud Vision integration
    agent2_intent/
    agent3_sourcing/
    agent4_trust/
    agent5_checkout/
    webapp/              # minimal HTML demo
  libs/
    schemas/             # shared Pydantic models
    utils/               # logging, retry, payment, idempotency
  data/
    mock_catalog.json    # offers
  tests/
    unit/
frontend/   # React/Vite frontend
Dockerfile
docker-compose.yml
.dockerignore
.env.example
```
## Notes
- Default runtime is *in‑process* via LangGraph (one FastAPI service). Agents are importable modules.
- S3 Parallel Branching: strict (brand+category+tokens) and fuzzy keyword branches run in parallel and merge. See `S3_BRANCH` and `S3_SOURCING` events in responses.
- S4 Bounded Compensation: tries up to K safer vendors within a price window and extra latency cap. Env defaults: `S4_COMP_TOPK=3`, `S4_COMP_PRICE_WINDOW_PCT=10`, `S4_COMP_EXTRA_LATENCY_MS=500`. Per‑request overrides at `/playground`:
  - Form: `comp_topk`, `comp_price_pct`, `comp_latency_ms`, `token_policy`, `token_budgets_json`
  - Headers: `X-Comp-TopK`, `X-Comp-PriceWindowPct`, `X-Comp-LatencyMs`, `X-Token-Policy`, `X-Token-Budgets`
- Idempotent checkout via `Idempotency-Key` header.
- Evaluation harness writes JSONL to `backend/logs/eval.log`. Use `scripts/eval_report.py` for CSVs (`eval_summary.csv`, `stage_latency.csv`, `token_summary.csv`, `ranking_metrics.csv`) and options `--compare` / `--bootstrap`.
