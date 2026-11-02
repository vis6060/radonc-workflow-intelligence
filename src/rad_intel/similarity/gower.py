"""Missing-aware weighted Gower-style similarity."""

from __future__ import annotations

from typing import Any

DEFAULT_WEIGHTS = {
    "age": 1.0,
    "disease_site": 2.0,
    "subsite": 1.5,
    "t": 1.0,
    "n": 1.0,
    "m": 1.0,
    "stage": 1.5,
    "hpv_status": 1.0,
    "workflow_stage": 2.0,
    "completed_prerequisites": 1.5,
    "outstanding_tasks": 1.5,
    "elapsed_days": 1.0,
}


def rank_similar(
    query: dict[str, Any],
    candidates: list[dict[str, Any]],
    k: int,
    weights: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Rank candidates deterministically; missing pairs contribute no weight."""
    active_weights = {**DEFAULT_WEIGHTS, **(weights or {})}
    scored = [_score(query, candidate, active_weights) for candidate in candidates]
    scored.sort(key=lambda item: (-item["score"], item["patient_id"]))
    return scored[:k]


def _score(
    query: dict[str, Any], candidate: dict[str, Any], weights: dict[str, float]
) -> dict[str, Any]:
    comparisons: dict[str, Any] = {}
    reasons: list[str] = []
    weighted_distance = 0.0
    used_weight = 0.0
    numeric_ranges = {"age": 100.0, "elapsed_days": 30.0}
    set_features = {"completed_prerequisites", "outstanding_tasks"}
    for feature, weight in weights.items():
        left, right = query.get(feature), candidate.get(feature)
        if left is None or right is None or left == "" or right == "":
            continue
        if feature in numeric_ranges:
            distance = min(
                abs(float(left) - float(right)) / numeric_ranges[feature], 1.0
            )
        elif feature in set_features:
            left_set, right_set = set(left), set(right)
            union = left_set | right_set
            distance = (
                0.0 if not union else 1.0 - len(left_set & right_set) / len(union)
            )
        else:
            distance = 0.0 if left == right else 1.0
        comparisons[feature] = {
            "query": left,
            "candidate": right,
            "similarity": round(1.0 - distance, 6),
        }
        weighted_distance += weight * distance
        used_weight += weight
        if distance == 0:
            reasons.append(f"same {feature.replace('_', ' ')}")
        elif feature == "age" and distance <= 0.05:
            reasons.append("age within 5 years")
    score = 0.0 if used_weight == 0 else 1.0 - weighted_distance / used_weight
    return {
        "patient_id": candidate["patient_id"],
        "score": round(max(0.0, min(1.0, score)), 6),
        "feature_comparisons": comparisons,
        "similarity_reasons": reasons,
    }
