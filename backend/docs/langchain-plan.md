## LangChain Integration Plan

### Goals
1. Replace deterministic agent logic with LangChain-powered reasoning where it adds value (e.g., richer intent understanding, offer synthesis, risk analysis).
2. Preserve existing FastAPI service boundaries so each agent remains deployable as an independent service.
3. Keep coordinator contract stable (same Pydantic schemas) to avoid breaking the chat UI or downstream consumers.

### High-Level Approach
- Introduce a shared module `libs/agents` containing reusable LangChain components (prompt templates, tool definitions, chain factories).
- Each agent service wraps its LangChain chain in the FastAPI route handler. If an env var `USE_LANGCHAIN=0` is set, the service falls back to the current deterministic logic for easy toggling and regression testing.
- Use LangChain Expression Language (LCEL) or `Runnable` interface to build composable chains with guardrails and retries.
- Leverage structured output validators (`JsonOutputParser`) to guarantee responses conform to Pydantic models before sending them back to the coordinator.

### Agent-by-Agent Design
#### Vision Agent
- Tools: Google Cloud Vision API (existing code), optional CLIP embeddings or captioning model.
- Chain: `req_image -> vision_tool -> parse -> ProductHypothesis`.
- Prompt: if raw Vision results are ambiguous, call an LLM to reconcile labels/brands/colors with fallback heuristics.
- Output parser: Pydantic `ProductHypothesis`.

#### Intent Agent
- Inputs: hypothesis JSON, user free-form text, chat history (optional).
- Chain: Prompt that interprets user request, extracts structured fields (item, color, size, qty, budget) using OpenAI or local model with `StructuredOutputParser`.
- Tools: synonyms dictionary, color list, budgeting heuristics.
- Fallback: deterministic `_extract_qty/_extract_budget` functions for validation.

#### Sourcing Agent
- Tools: catalog search function, optional external APIs (Amazon, eBay) mocked behind interface.
- Chain: 
  1. Generator prompt to decide search query keywords.
  2. Call catalog tool to fetch candidates (top N).
  3. Rerank using an LLM (LangChain `LLMRerankChain`) based on price, shipping, match quality.
- Output: top offers as structured list (converted to `Offer` models).

#### Trust Agent
- Tools: vendor knowledge base (JSON, vector store), simple heuristics.
- Chain: LLM analyzes vendor profile, CIS benchmarks, and heuristics to assign risk level, linking explanations.
- Output: `TrustAssessment` validated via Pydantic.

#### Checkout Agent
- Keep deterministic validations (Luhn, expiry). LangChain optional for generating human-readable explanations or for future fraud scoring (LLM summarizing risk signals). No change required for MVP.

### Coordinator Enhancements
- Add optional “explain” mode where coordinator requests verbose reasoning traces from agents (e.g., `X-Agent-Explain=true` header). Agents can return additional fields (`analysis_text`) when LangChain is active.
- Introduce circuit breakers and tracing to observe LLM latency.

### Dependencies & Configuration
- Add LangChain packages to `requirements-agentic.txt`:
  - `langchain`, `langchain-openai`, `langchain-community` (for providers such as Ollama), `langsmith` for tracing.
  - `openai` or other provider SDKs as needed; configure credentials or local endpoints (`OPENAI_API_KEY`, `LANGCHAIN_PROVIDER=ollama`, `OLLAMA_BASE_URL`, etc.).
  - Optional: `faiss-cpu` or `chromadb` for vector stores.
- Feature flags via env vars per service:
  - `USE_LANGCHAIN=1` (default staged rollout).
  - `LANGCHAIN_PROVIDER` to choose back ends (`openai`, `ollama`, etc.).
  - `LANGCHAIN_MODEL=...` to pick provider/model.
  - `LANGCHAIN_TRACING_V2=1` to enable LangSmith.

### Testing Strategy
- Unit tests for chain factories with mocked LLMs (LangChain allows `FakeListLLM`).
- Contract tests verifying endpoints still return valid Pydantic payloads under LangChain mode.
- Integration tests running small local models (e.g., `gpt4all` or `ollama`) to avoid external dependencies in CI.
- Fallback tests ensuring deterministic mode works when `USE_LANGCHAIN=0`.

### Rollout Plan
1. **Phase 1**: instrument Intent Agent with LangChain (highest impact, minimal risk). Provide fallback. **Status:** implemented (`USE_LANGCHAIN_INTENT` flag).
2. **Phase 2**: add LangChain reranking to Sourcing Agent; optional explanation text. **Status:** implemented (`USE_LANGCHAIN_SOURCING` flag).
3. **Phase 3**: add reasoning to Trust Agent (LLM analyzing vendor policies). **Status:** implemented (`USE_LANGCHAIN_TRUST` flag).
4. **Phase 4**: optional Vision agent prompt-based refinement (depends on GPU/API cost). **Status:** implemented (`USE_LANGCHAIN_VISION` flag).
5. Monitor latency/cost metrics, optimize prompts/tokens, then consider CrewAI or multi-agent negotiation if needed.
