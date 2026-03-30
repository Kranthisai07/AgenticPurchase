"""
Trust evaluation — Precision, Recall, VVR, FVDR.

Ground-truth labeling (per offer):
  ground_truth = "SUSPICIOUS" if any of:
    - offer.title (lowercased) contains any keyword from suspicious_title_keywords
    - session1.price_anomaly AND session1.replica_flag  (both must fire)
    - session1.brand_mismatch AND session1.replica_flag
  Otherwise ground_truth = "AUTHENTIC"

Predicted label (from trust_results[i]["verdict"]):
  "AUTHENTIC"              → predicted AUTHENTIC
  "SUSPICIOUS" / "HIGH_RISK" → predicted SUSPICIOUS

Confusion matrix (SUSPICIOUS = positive class):
  TP = predicted SUSPICIOUS, ground truth SUSPICIOUS
  TN = predicted AUTHENTIC,  ground truth AUTHENTIC
  FP = predicted SUSPICIOUS, ground truth AUTHENTIC  (over-flagging)
  FN = predicted AUTHENTIC,  ground truth SUSPICIOUS (missed threat)

Metrics:
  precision = TP / (TP + FP)
  recall    = TP / (TP + FN)
  VVR       = TN / (TN + FN)   vendor verification rate (legitimate vendors cleared)
  FVDR      = FP / (FP + TN)   false vendor detection rate (legitimate vendors wrongly blocked)
"""
from __future__ import annotations

from dataclasses import dataclass

from backend.evaluation.dataset import EvalQuery


@dataclass
class TrustMetrics:
    precision: float
    recall: float
    vvr: float      # Vendor Verification Rate  = TN / (TN + FN)
    fvdr: float     # False Vendor Detection Rate = FP / (FP + TN)
    n_offers_evaluated: int
    n_authentic: int            # ground truth authentic
    n_suspicious: int           # ground truth suspicious
    tp: int
    tn: int
    fp: int
    fn: int


def evaluate_trust(saga_results: list) -> TrustMetrics:
    """
    Compute trust evaluation metrics across all saga eval results.

    Parameters
    ----------
    saga_results : list[SagaEvalResult]
        Each result must have:
          .query          EvalQuery
          .trust_results  list[dict] — each dict has:
                            title:          str
                            verdict:        "AUTHENTIC" | "SUSPICIOUS" | "HIGH_RISK"
                            price_anomaly:  bool
                            replica_flag:   bool
                            brand_mismatch: bool
          .success        bool

    Returns
    -------
    TrustMetrics
    """
    tp = tn = fp = fn = 0
    n_authentic = n_suspicious = 0

    for sr in saga_results:
        if not sr.success:
            continue

        query: EvalQuery = sr.query

        for tr in (sr.trust_results or []):
            gt  = _ground_truth(tr, query)
            pred = _predicted_label(tr.get("verdict", "AUTHENTIC"))

            if gt == "SUSPICIOUS":
                n_suspicious += 1
                if pred == "SUSPICIOUS":
                    tp += 1
                else:
                    fn += 1
            else:
                n_authentic += 1
                if pred == "SUSPICIOUS":
                    fp += 1
                else:
                    tn += 1

    n_total = tp + tn + fp + fn

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    vvr       = tn / (tn + fn) if (tn + fn) > 0 else 0.0
    fvdr      = fp / (fp + tn) if (fp + tn) > 0 else 0.0

    return TrustMetrics(
        precision=round(precision, 4),
        recall=round(recall, 4),
        vvr=round(vvr, 4),
        fvdr=round(fvdr, 4),
        n_offers_evaluated=n_total,
        n_authentic=n_authentic,
        n_suspicious=n_suspicious,
        tp=tp, tn=tn, fp=fp, fn=fn,
    )


# ── Private helpers ───────────────────────────────────────────────────────────

def _ground_truth(trust_record: dict, query: EvalQuery) -> str:
    """
    Derive ground-truth label for one offer.

    Returns "SUSPICIOUS" or "AUTHENTIC".
    """
    title = (trust_record.get("title") or "").lower()

    # Rule 1: suspicious keyword in title
    for kw in query.suspicious_title_keywords:
        if kw.lower() in title:
            return "SUSPICIOUS"

    # Rule 2: price anomaly + replica flag (both must fire)
    price_anomaly = bool(trust_record.get("price_anomaly", False))
    replica_flag  = bool(trust_record.get("replica_flag",  False))
    if price_anomaly and replica_flag:
        return "SUSPICIOUS"

    # Rule 3: brand mismatch + replica flag (both must fire)
    brand_mismatch = bool(trust_record.get("brand_mismatch", False))
    if brand_mismatch and replica_flag:
        return "SUSPICIOUS"

    return "AUTHENTIC"


def _predicted_label(verdict: str) -> str:
    """Map Session-2 verdict to binary label."""
    v = (verdict or "").upper()
    if v in ("SUSPICIOUS", "HIGH_RISK"):
        return "SUSPICIOUS"
    return "AUTHENTIC"
