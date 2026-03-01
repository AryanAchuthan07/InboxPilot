from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class EmailObject(BaseModel):
    id: str
    sender: str
    subject: str
    body: str
    timestamp: str
    thread_history: list[str] = Field(default_factory=list)
    unread_count: int = 0


class ClassificationResult(BaseModel):
    category: str
    priority_score: int = Field(ge=1, le=10)
    requires_response: bool
    confidence: float = Field(ge=0.0, le=1.0)


class DraftResult(BaseModel):
    draft_email: str
    tone_match_score: float = Field(ge=0.0, le=1.0)
    suggest_follow_up_date: Optional[str] = None


class ReflectionResult(BaseModel):
    adjust_priority_rules: str
    suggest_threshold_changes: str
    detected_failure_patterns: list[str]


class SenderMemory(BaseModel):
    sender_email: str
    importance_score: float = Field(default=5.0, ge=1.0, le=10.0)
    last_response_time_avg: Optional[str] = None
    category_frequency: dict[str, int] = Field(default_factory=dict)

    def category_frequency_json(self) -> str:
        return json.dumps(self.category_frequency)


class PerformanceMemory(BaseModel):
    week_start: str = Field(
        default_factory=lambda: datetime.utcnow().strftime("%Y-%m-%d")
    )
    weekly_missed_high_priority: int = 0
    classification_accuracy: float = 0.0
    avg_response_time: str = "N/A"


class ActionLog(BaseModel):
    timestamp: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat()
    )
    email_id: str
    action: str
    detail: str
