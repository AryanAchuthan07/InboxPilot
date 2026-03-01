from __future__ import annotations

from integrations.claude import build_draft_prompt, call_claude
from memory.models import DraftResult
from utils.logger import get_logger

logger = get_logger("inboxpilot.drafter")

DEFAULT_TONE_PROFILE = (
    "Professional, concise, and friendly. Avoid jargon. "
    "Use clear subject lines and short paragraphs."
)


def generate_draft(
    sender: str,
    subject: str,
    body: str,
    thread_history: list[str],
    tone_profile: str = DEFAULT_TONE_PROFILE,
) -> DraftResult:
    """
    Call Claude to generate a reply draft.
    Returns a validated DraftResult.
    """
    prompt = build_draft_prompt(
        sender=sender,
        subject=subject,
        body=body,
        thread_history=thread_history,
        tone_profile=tone_profile,
    )
    raw = call_claude(prompt)

    return DraftResult(
        draft_email=raw.get("draft_email", ""),
        tone_match_score=float(raw.get("tone_match_score", 0.5)),
        suggest_follow_up_date=raw.get("suggest_follow_up_date"),
    )
