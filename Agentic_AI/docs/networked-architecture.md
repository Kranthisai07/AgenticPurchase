## Networked Agent Architecture Overview

This document summarizes the target shape for running the purchase saga with discrete agents communicating over the network.

### Service Boundaries
- **Coordinator (`apps/coordinator_service.py`)** — orchestrates the saga. Talks to other agents over HTTP, manages retries, timeouts, metrics, and persistence.
- **Vision Agent (`apps/agent1_vision/service.py`)** — accepts an image upload, returns a `ProductHypothesis`.
- **Intent Agent (`apps/agent2_intent/service.py`)** — accepts the hypothesis plus optional free-form user text, returns a structured `PurchaseIntent`.
- **Sourcing Agent (`apps/agent3_sourcing/service.py`)** — accepts a `PurchaseIntent`, returns ranked `Offer` objects.
- **Trust Agent (`apps/agent4_trust/service.py`)** — accepts an `Offer`, returns a `TrustAssessment`.
- **Checkout Agent (`apps/agent5_checkout/service.py`)** — accepts an `Offer`, payment payload, and idempotency key, returns a `Receipt`.

Each service exposes a minimal FastAPI app so it can run in its own process or container. Shared Pydantic models live in `libs/schemas`, which remains importable by every service via a shared install (editable install during development).

### Transport & Discovery
- Primary transport: HTTP+JSON (FastAPI + httpx). gRPC or async messaging can be added later.
- Base URLs are configured with environment variables (`AGENT_VISION_URL`, `AGENT_INTENT_URL`, etc.). The coordinator falls back to in-process calls when an env var is absent, which keeps tests lightweight.

### Request Flow
1. Coordinator receives `/saga/start`.
2. Calls Vision service (`POST /intake` with multipart file upload) and receives `ProductHypothesis`.
3. Calls Intent service (`POST /confirm`) with hypothesis JSON and optional user text to get `PurchaseIntent`.
4. Calls Sourcing service (`POST /offers`) with intent JSON to get ranked offers.
5. Calls Trust service (`POST /assess`) with offer JSON to get `TrustAssessment`; may call again for fallback vendors.
6. Calls Checkout service (`POST /pay`) with offer JSON, payment inputs, and idempotency key; gets back `Receipt`.

### Observability & Metadata
- Every request carries `X-Request-ID` and optionally `X-Trace-ID`, forwarded by the coordinator.
- Services log structured events and expose `/health` endpoints for probes.
- Coordinator metrics already present (p95, counts); additional Prometheus exporters can be added per service later.

### Local Development (multi-process)
1. Create a Python virtual environment, `pip install -r requirements-agentic.txt`.
2. Install the project in editable mode (`pip install -e .`) or add the repo root to `PYTHONPATH`.
3. Start each agent service with uvicorn:
   - `uvicorn apps.agent1_vision.service:app --port 8101 --reload`
   - `uvicorn apps.agent2_intent.service:app --port 8102 --reload`
   - `uvicorn apps.agent3_sourcing.service:app --port 8103 --reload`
   - `uvicorn apps.agent4_trust.service:app --port 8104 --reload`
   - `uvicorn apps.agent5_checkout.service:app --port 8105 --reload`
4. Export the matching coordinator env vars, e.g.:
   ```
   set AGENT_VISION_URL=http://127.0.0.1:8101
   set AGENT_INTENT_URL=http://127.0.0.1:8102
   set AGENT_SOURCING_URL=http://127.0.0.1:8103
   set AGENT_TRUST_URL=http://127.0.0.1:8104
   set AGENT_CHECKOUT_URL=http://127.0.0.1:8105
   ```
5. Start the coordinator (`uvicorn apps.coordinator.main:app --reload`).
6. Use the chat UI or Swagger docs against the coordinator; it now orchestrates remote calls.

### Next Steps
- Containerize each service (`docker/agents/` + docker-compose).
- Introduce centralized tracing (OpenTelemetry) and metrics (Prometheus).
- Optionally replace the HTTP transport with message queues for async orchestration.

