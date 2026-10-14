"""Evaluation only: one-to-one semantic matching; no extraction imports."""
import math


def metrics(tp, n_predictions, n_reference):
    if not 0 <= tp <= min(n_predictions, n_reference):
        raise ValueError("Invalid matched count")
    precision = tp / n_predictions if n_predictions else 0.0
    recall = tp / n_reference if n_reference else 0.0
    return {"predictions": n_predictions, "reference": n_reference, "tp": tp,
            "fp": n_predictions - tp, "fn": n_reference - tp,
            "precision": precision, "recall": recall,
            "f1_content": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
            "coverage": recall}


def match_matrix(similarities, n_reference, threshold=0.6):
    """Hungarian maximum total cosine assignment, then threshold the assigned pairs.

    No class/document/identifier gates: classification and source agreement are
    reported separately. A below-threshold assigned pair is not a true positive.
    """
    import numpy as np
    from scipy.optimize import linear_sum_assignment
    if not math.isfinite(threshold) or not -1 <= threshold <= 1:
        raise ValueError("Invalid threshold")
    a = np.asarray(similarities, dtype=float)
    n_predictions = len(similarities)
    if not n_predictions or not n_reference:
        return [], metrics(0, n_predictions, n_reference)
    if a.shape != (n_predictions, n_reference) or not np.isfinite(a).all():
        raise ValueError("Invalid similarity matrix")
    rows, cols = linear_sum_assignment(a, maximize=True)
    pairs = [{"prediction_index": int(i), "reference_index": int(j), "cosine": float(a[i, j]),
              "matched": bool(a[i, j] >= threshold)} for i, j in zip(rows, cols)]
    return pairs, metrics(sum(p["matched"] for p in pairs), n_predictions, n_reference)


def content_text(rule):
    """Identifiers and class labels are deliberately excluded from embeddings."""
    return " ".join((str(rule.get("condition", "")) + " " + str(rule.get("response", ""))).split())
