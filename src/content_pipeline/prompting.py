from __future__ import annotations

from pathlib import Path


def load_prompt(prompts_dir: Path, prompt_file: str) -> str:
    return (prompts_dir / prompt_file).read_text(encoding="utf-8")


def load_style_guide(style_guide_path: Path | None) -> str:
    if style_guide_path is None:
        return "No dedicated style guide provided. Use a clear, practical, professional tone."
    return style_guide_path.read_text(encoding="utf-8").strip()


def render_prompt(template: str, values: dict[str, str]) -> str:
    return template.format(**values)
