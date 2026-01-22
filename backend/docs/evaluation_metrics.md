Evaluation & Metrics

Overview
- Goal: quantify end-to-end quality and efficiency of the agentic purchase pipeline (S1–S5) under the current LangGraph orchestration with a FastAPI/LangServe gateway.
- Scope: image-to-offer ranking (S1–S3), trust selection (S4), and checkout (S5) latency; intent/recognition alignment; sourcing accuracy; optional token usage when LLMs are enabled.

Test Harness
- Runner: `scripts/run_eval.py` executes batch jobs over a YAML dataset, calling `/saga/preview` (S1–S4) or `/saga/start` (S1–S5) and writing JSONL to `backend/logs/eval.log`.
- Report: `scripts/eval_report.py` summarizes logs into CSVs and prints aggregates (means, p95 latencies). It supports both legacy TOKEN events and new RUN_RESULT entries.
- Dataset: `evaluation/dataset.yaml` lists images and expected attributes (brand, family, category). Add your own images in `evaluation/images/`.

Metrics
- Recognition/Intent Alignment (binary):
  - Hit if hypothesis/intent matches any of the expectations (brand equality, family substring in label/item_name, or category substring).
- Sourcing Accuracy:
  - Top-1 Brand Hit: vendor of the first offer equals the expected brand.
  - Top-3 Brand Hit: any of the top-3 vendors equals the expected brand.
  - Ranking (added): NDCG@3 and MRR computed from graded relevance derived from expectations (brand+family = 2, brand-only = 1, else = 0).
- Latency:
  - Per-stage dt_s from saga events: S1_CAPTURE, S2_CONFIRM, S3_SOURCING, S4_TRUST, S5_CHECKOUT.
  - Wall-clock for request (client-observed), reported as `dt_wall_s`.
- Token Usage (optional):
  - If LLM providers are used with `TokenBudgeter`, TOKEN events capture `state`, `role`, `n_tokens`, enabling per-stage prompt/completion totals.

Ablations (recommended)
- No-LLM vs LLM-rerank: Measure changes in Top-1/Top-3 and latency; record token costs.
- Trust compensation on/off: Measure rate of vendor switching and effect on risk distribution.
- Catalog matching strategies: strict brand+category vs fuzzy title/keyword matching.

Statistical Reporting
- Report means and p95 across the dataset for accuracy and latency. For token usage, report prompt/completion totals by stage when available.

Reproducibility
- Start server: `python -m uvicorn backend.apps.coordinator.main:app --reload` (or `backend.langserve_app:app`).
- Run: `python scripts/run_eval.py --dataset evaluation/dataset.yaml --mode preview`.
- Summarize: `python scripts/eval_report.py --log backend/logs/eval.log`.

Output Artifacts
- `backend/logs/eval_summary.csv` — per-run metrics (recognition_hit, top1_brand_hit, top3_brand_hit, dt_wall_s, lat_*).
- `backend/logs/stage_latency.csv` — per-run per-stage dt_s.
- `backend/logs/token_summary.csv` — TOKEN events (if present) for prompt/completion usage by stage.

Notes
- Browser mic permission and UI voice flow do not affect backend evaluation; dataset-driven runs are non-interactive.
- Legacy `apps/coordinator/saga.py` still logs to `logs/eval.log` when used; the new harness writes RUN_* lines compatible with the updated report script.
