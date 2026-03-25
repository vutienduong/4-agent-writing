from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TopicRecord(BaseModel):
    title: str
    primary_keyword: str = ""
    audience: str = ""
    angle: str = ""
    notes: str = ""


class TokenUsage(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class LLMGeneration(BaseModel):
    content: str
    model: str
    request_id: str | None = None
    usage: TokenUsage = Field(default_factory=TokenUsage)
    raw_response: dict[str, Any] | None = None


class StageAttempt(BaseModel):
    attempt_number: int
    status: str
    started_at: str
    finished_at: str
    elapsed_seconds: float
    model: str
    request_id: str | None = None
    usage: TokenUsage = Field(default_factory=TokenUsage)
    error_message: str | None = None


class StageResult(BaseModel):
    stage_key: str
    stage_label: str
    output_file: str
    model: str
    status: str
    elapsed_seconds: float
    request_id: str | None = None
    usage: TokenUsage = Field(default_factory=TokenUsage)
    attempts: list[StageAttempt] = Field(default_factory=list)
    error_message: str | None = None
    mock: bool = False


class PipelineMetadata(BaseModel):
    topic_index: int
    topic_slug: str
    topic: TopicRecord
    status: str
    started_at: str
    finished_at: str | None = None
    active_stage: str | None = None
    stage_results: list[StageResult] = Field(default_factory=list)
    error_message: str | None = None
    mock: bool
