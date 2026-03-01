from __future__ import annotations

import json
import re
from pathlib import Path

import anthropic
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config import settings
from utils.logger import get_logger

logger = get_logger("inboxpilot.claude")

_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)


def _load_prompt(name: str) -> str:
    return (Path(__file__).parent.parent / "prompts" / f"{name}.txt").read_text()


def _extract_json(text: str) -> dict:
    """Try to parse JSON from Claude's response, stripping any markdown fences."""
    text = text.strip()
    # Remove markdown fences if present
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


class MalformedOutputError(ValueError):
    pass


@retry(
    retry=retry_if_exception_type((MalformedOutputError, json.JSONDecodeError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
def call_claude(prompt: str) -> dict:
    """Call Claude and return parsed JSON. Retries up to 3 times on bad output."""
    logger.debug("Calling Claude (model=%s)", settings.claude_model)
    response = _client.messages.create(
        model=settings.claude_model,
        max_tokens=settings.claude_max_tokens,
        temperature=settings.claude_temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text
    try:
        return _extract_json(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("Claude returned non-JSON output: %s", raw[:200])
        raise MalformedOutputError(f"Non-JSON response: {raw[:200]}") from exc


def build_classify_prompt(
    sender: str,
    subject: str,
    body: str,
    historical_score: float | None,
) -> str:
    template = _load_prompt("classify")
    return template.format(
        sender=sender,
        subject=subject,
        body=body[:2000],  # Truncate very long bodies
        historical_score=historical_score if historical_score is not None else "null",
    )


def build_draft_prompt(
    sender: str,
    subject: str,
    body: str,
    thread_history: list[str],
    tone_profile: str,
) -> str:
    template = _load_prompt("draft")
    history_text = "\n---\n".join(thread_history) if thread_history else "(no prior messages)"
    return template.format(
        sender=sender,
        subject=subject,
        body=body[:2000],
        thread_history=history_text[:3000],
        tone_profile=tone_profile,
    )


def build_reflect_prompt(
    total_emails: int,
    missed_high_priority: int,
    false_positives: int,
    avg_response_time: str,
    classification_accuracy: float,
    category_breakdown: str,
    failure_patterns: str,
) -> str:
    template = _load_prompt("reflect")
    return template.format(
        total_emails=total_emails,
        missed_high_priority=missed_high_priority,
        false_positives=false_positives,
        avg_response_time=avg_response_time,
        classification_accuracy=classification_accuracy,
        category_breakdown=category_breakdown,
        failure_patterns=failure_patterns,
    )
