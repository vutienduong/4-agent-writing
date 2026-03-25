from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class AppConfig:
    repo_root: Path
    prompts_dir: Path
    output_dir: Path
    queue_db_path: Path
    queue_manifest_path: Path
    default_model: str
    research_model: str | None
    outline_model: str | None
    writer_model: str | None
    seo_model: str | None
    timeout_seconds: float
    max_retries: int
    worker_count: int
    stage_max_attempts: int
    retry_backoff_seconds: float
    mock: bool = False
    style_guide_path: Path | None = None

    def model_for_stage(self, stage_key: str) -> str:
        model_map = {
            "research": self.research_model,
            "outline": self.outline_model,
            "writer": self.writer_model,
            "seo": self.seo_model,
        }
        return model_map.get(stage_key) or self.default_model


def load_config(
    *,
    mock: bool,
    output_dir: str | None,
    style_guide: str | None,
    worker_count: int | None,
    stage_max_attempts: int | None,
    retry_backoff_seconds: float | None,
) -> AppConfig:
    load_dotenv(REPO_ROOT / ".env")
    selected_output_dir = Path(output_dir) if output_dir else REPO_ROOT / "output"
    style_guide_path = Path(style_guide).expanduser().resolve() if style_guide else None

    return AppConfig(
        repo_root=REPO_ROOT,
        prompts_dir=REPO_ROOT / "prompts",
        output_dir=selected_output_dir,
        queue_db_path=selected_output_dir / "pipeline_state.sqlite",
        queue_manifest_path=selected_output_dir / "queue_manifest.json",
        default_model=os.getenv("OPENAI_MODEL", "gpt-5.2"),
        research_model=_blank_to_none(os.getenv("RESEARCH_MODEL")),
        outline_model=_blank_to_none(os.getenv("OUTLINE_MODEL")),
        writer_model=_blank_to_none(os.getenv("WRITER_MODEL")),
        seo_model=_blank_to_none(os.getenv("SEO_MODEL")),
        timeout_seconds=float(os.getenv("OPENAI_TIMEOUT_SECONDS", "120")),
        max_retries=int(os.getenv("OPENAI_MAX_RETRIES", "2")),
        worker_count=worker_count or int(os.getenv("PIPELINE_WORKERS", "2")),
        stage_max_attempts=stage_max_attempts or int(os.getenv("STAGE_MAX_ATTEMPTS", "3")),
        retry_backoff_seconds=retry_backoff_seconds
        or float(os.getenv("STAGE_RETRY_BACKOFF_SECONDS", "2")),
        mock=mock,
        style_guide_path=style_guide_path,
    )


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
