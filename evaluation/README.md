Evaluation dataset format

- File: `evaluation/dataset.yaml`
- Each item describes one input image and optional expectations used for scoring.

Fields per item
- `image`: Path to a local image file (relative to repo root or absolute).
- `user_text` (optional): Text prompt to seed intent (e.g., "black, qty 1").
- `preferred_offer_url` (optional): If you want to bias selection to a known URL.
- `expect` (optional): Ground-truth hints used for metrics.
  - `brand`: e.g., Apple, Google, Pilot, Nike
  - `family`: e.g., iPhone, Pixel (helps recognition alignment)
  - `category`: e.g., phone, pen, shoe

Example
  - image: evaluation/images/iphone_14.jpg
    user_text: "black, qty 1"
    expect:
      brand: Apple
      family: iPhone
      category: phone
  - image: evaluation/images/pixel_7.png
    expect:
      brand: Google
      family: Pixel
      category: phone

Running evaluation
- Start the backend (choose one):
  - Legacy FastAPI coordinator: `python -m uvicorn Agentic_AI.apps.coordinator.main:app --reload`
  - LangServe host: `python -m uvicorn Agentic_AI.langserve_app:app --reload`

- Preview mode (S1–S4):
  `python scripts/run_eval.py --dataset evaluation/dataset.yaml --mode preview`

- Full mode with checkout (S1–S5):
  `python scripts/run_eval.py --dataset evaluation/dataset.yaml --mode start --card-number 4242424242424242 --expiry 12/29 --cvv 123`

- Using LangServe endpoints instead of legacy FastAPI:
  add `--langserve` (the script will switch to /invoke routes automatically).

Reports
- Generate CSV summaries after a run:
  `python scripts/eval_report.py --log Agentic_AI/logs/eval.log`

This produces:
- `Agentic_AI/logs/eval_summary.csv` (per-run metrics)
- `Agentic_AI/logs/stage_latency.csv` (per-run stage latencies)
- `Agentic_AI/logs/token_summary.csv` (if LLM/token logging is enabled)
 - `Agentic_AI/logs/ranking_metrics.csv` (NDCG@3 and MRR derived from expectations)

Images directory
- Put your image files under `evaluation/images/` (this folder is included in the repo with a README placeholder).
- Either keep the filenames used in `evaluation/dataset.yaml` or edit the YAML to match your file names.
- If an image is missing, `scripts/run_eval.py` will print a warning and skip that row.

Optional:
- Compare two logs (e.g., deterministic vs LLM):
  `python scripts/eval_report.py --log Agentic_AI/logs/eval.log --compare path/to/log_A path/to/log_B`
- Print bootstrap CIs for ranking metrics:
  `python scripts/eval_report.py --log Agentic_AI/logs/eval.log --bootstrap 1000`
