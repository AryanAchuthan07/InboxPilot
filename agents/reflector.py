from __future__ import annotations

from integrations.claude import build_reflect_prompt, call_claude
from memory.models import ReflectionResult
from utils.logger import get_logger

logger = get_logger("inboxpilot.reflector")


def run_reflection(
    total_emails: int,
    missed_high_priority: int,
    false_positives: int,
    avg_response_time: str,
    classification_accuracy: float,
    category_breakdown: dict[str, int],
    failure_patterns: list[str],
) -> ReflectionResult:
    """
    Run the weekly reflection Claude task.
    Returns a ReflectionResult with actionable rule adjustments.
    """
    category_text = "\n".join(
        f"  {cat}: {count} emails" for cat, count in category_breakdown.items()
    ) or "  (no data)"

    patterns_text = "\n".join(
        f"  - {p}" for p in failure_patterns
    ) or "  (none detected)"

    prompt = build_reflect_prompt(
        total_emails=total_emails,
        missed_high_priority=missed_high_priority,
        false_positives=false_positives,
        avg_response_time=avg_response_time,
        classification_accuracy=classification_accuracy,
        category_breakdown=category_text,
        failure_patterns=patterns_text,
    )
    raw = call_claude(prompt)

    return ReflectionResult(
        adjust_priority_rules=raw.get("adjust_priority_rules", ""),
        suggest_threshold_changes=raw.get("suggest_threshold_changes", ""),
        detected_failure_patterns=raw.get("detected_failure_patterns", []),
    )
