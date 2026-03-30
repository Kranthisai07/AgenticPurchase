# Agentic Purchase System

A true multi-agent autonomous purchase system. The user describes or photographs a product; a multi-agent system sources it from Etsy, eBay, and Google Shopping, evaluates vendor trust, ranks offers, and completes checkout — entirely inside the chat interface.

## Architecture

```
User → Chat UI (React + SSE)
         ↓
    Orchestrator (LangGraph)
         ↓
 ┌───────────────────────┐
 │  AgentBus (async)     │
 └───────────────────────┘
    ↓         ↓        ↓
 Vision    Intent   Sourcing×3
               ↓        ↓
           Trust×3  (parallel)
               ↓
           Ranking
               ↓
           Checkout (Stripe)
```

**Agents:** VisionAgent · IntentAgent · SourcingAgent (×3) · TrustAgent (×3) · RankingAgent · CheckoutAgent

**Stack:** FastAPI · LangGraph · PostgreSQL · Redis · Stripe · React 18 · Zustand · SSE

## Quick Start (Development)

### Prerequisites
- Docker + Docker Compose
- Node.js 20+
- Python 3.12+

### 1. Configure environment

```bash
cp .env.example .env
# Fill in: OPENAI_API_KEY, STRIPE_SECRET_KEY, ETSY_API_KEY, EBAY_APP_ID, SERPAPI_KEY
cp frontend/.env.example frontend/.env
# Fill in: VITE_STRIPE_PUBLISHABLE_KEY
```

### 2. Start services

```bash
docker-compose -f docker-compose.dev.yml up --build
```

### 3. Run database migrations

```bash
docker-compose -f docker-compose.dev.yml exec backend alembic upgrade head
```

### 4. Access

- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- API Docs: http://localhost:8000/docs
- Metrics: http://localhost:8000/metrics

## Local Development (without Docker)

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
cp .env.example .env           # configure values
alembic upgrade head
uvicorn backend.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
cp .env.example .env           # configure values
npm run dev
```

## Running Tests

```bash
cd backend
pytest tests/ -v
```

Run specific test suites:

```bash
pytest tests/unit/agents/ -v                    # agent unit tests
pytest tests/unit/core/test_trust_scorer.py -v  # trust formula
pytest tests/integration/ -v                    # integration tests
```

## API Reference

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/sessions` | Create user session |
| `POST` | `/saga` | Start purchase saga |
| `GET`  | `/saga/{id}/stream` | SSE stream for agent progress |
| `POST` | `/saga/{id}/resume` | Resume paused saga (clarification, offer selection, checkout) |
| `GET`  | `/checkout/{id}/status` | Checkout status |
| `POST` | `/webhooks/stripe` | Stripe webhook handler |
| `GET`  | `/health` | Liveness probe |
| `GET`  | `/metrics` | Prometheus metrics |

## SSE Event Reference

| Event | When |
|-------|------|
| `session_ready` | Saga created |
| `agent_started` | Agent begins |
| `agent_complete` | Agent succeeds |
| `agent_failed` | Agent fails (stream continues) |
| `clarification_needed` | Intent needs more info |
| `offers_ready` | Ranking complete — top 5 shown |
| `trust_scored` | Per-offer trust score (streaming) |
| `checkout_ready` | PaymentIntent created — confirm with Stripe.js |
| `saga_complete` | Purchase initiated |
| `saga_failed` | Unrecoverable failure + retry guidance |

## Agent Contracts

| Agent | LLM | Timeout | Self-Evaluation |
|-------|-----|---------|-----------------|
| Vision | GPT-4o | 15s | Rejects confidence < 0.6 |
| Intent | GPT-4o | 10s | Rejects empty query, inverted price range |
| Sourcing ×3 | GPT-4o-mini | 20s | Retries once with relaxed query |
| Trust ×3 | None (scorer) | 15s | Detects score/signal inconsistency |
| Ranking | GPT-4o-mini | 10s | Validates composite score range |
| Checkout | None | 30s | Idempotency + velocity limits |

## Security

- Stripe.js tokenizes card data on the frontend — raw card numbers never reach the backend
- Checkout idempotency: `SHA256(saga_id + offer_id + user_id)` prevents double-charges
- Velocity limiting: max 3 checkout attempts per user per hour
- Prompt injection detection in IntentAgent before LLM processing
- Stripe webhook HMAC-SHA256 verification

## Production Deployment

```bash
cp .env.example .env
# Set APP_ENV=production, strong passwords, real API keys
docker-compose up --build -d
docker-compose exec backend alembic upgrade head
```
