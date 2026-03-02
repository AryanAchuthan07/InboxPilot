from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    anthropic_api_key: str
    google_credentials_file: str = "credentials.json"
    google_token_file: str = "token.json"
    poll_interval_minutes: int = 5
    follow_up_hours: int = 24
    unread_goal: int = 10
    database_path: str = "inboxpilot.db"

    # Claude
    claude_model: str = "claude-opus-4-5-20251101"
    claude_temperature: float = Field(default=0.3, le=0.3)
    claude_max_tokens: int = 1024

    # Priority thresholds
    priority_immediate_alert: int = 8
    priority_standard_label_min: int = 5
    priority_draft_min: int = 6
    priority_follow_up_min: int = 7

    # Priority decay / escalation
    escalation_enabled: bool = True
    escalation_min_priority: int = 7   # Only escalate emails originally classified at or above this
    escalation_hours: int = 12         # Hours of being unread before each escalation step
    escalation_step: int = 2           # Priority points added per escalation
    escalation_max_priority: int = 10  # Hard cap on escalated priority

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
