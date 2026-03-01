from __future__ import annotations

from integrations.claude import build_classify_prompt, call_claude
from memory.models import ClassificationResult
from utils.logger import get_logger

logger = get_logger("inboxpilot.classifier")

# Hard rules from PRD
_CATEGORY_FLOOR: dict[str, int] = {
    "internship": 7,
    "recruiter": 7,
}
_CATEGORY_CEILING: dict[str, int] = {
    "promotional": 4,
}


def _enforce_priority_rules(result: ClassificationResult) -> ClassificationResult:
    """Apply hard PRD constraints on priority scores."""
    cat = result.category.lower()

    floor = _CATEGORY_FLOOR.get(cat)
    if floor is not None and result.priority_score < floor:
        logger.info(
            "Bumping priority for category '%s' from %d to %d",
            cat,
            result.priority_score,
            floor,
        )
        result = result.model_copy(update={"priority_score": floor})

    ceiling = _CATEGORY_CEILING.get(cat)
    if ceiling is not None and result.priority_score > ceiling:
        logger.info(
            "Capping priority for category '%s' from %d to %d",
            cat,
            result.priority_score,
            ceiling,
        )
        result = result.model_copy(update={"priority_score": ceiling})

    return result


def classify_email(
    sender: str,
    subject: str,
    body: str,
    historical_score: float | None = None,
) -> ClassificationResult:
    """
    Call Claude to classify an email.
    Applies hard priority rules and returns a validated ClassificationResult.
    """
    prompt = build_classify_prompt(sender, subject, body, historical_score)
    raw = call_claude(prompt)

    result = ClassificationResult(
        category=raw.get("category", "informational"),
        priority_score=int(raw.get("priority_score", 5)),
        requires_response=bool(raw.get("requires_response", False)),
        confidence=float(raw.get("confidence", 0.5)),
    )
    return _enforce_priority_rules(result)
