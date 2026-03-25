from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentSpec:
    key: str
    label: str
    prompt_file: str
    output_file: str
    instructions: str


AGENTS: tuple[AgentSpec, ...] = (
    AgentSpec(
        key="research",
        label="Agent 1: Research",
        prompt_file="research.md",
        output_file="01-research.md",
        instructions=(
            "You are a senior content researcher. Return polished markdown only and "
            "optimize for accurate handoff to the next agent."
        ),
    ),
    AgentSpec(
        key="outline",
        label="Agent 2: Outline",
        prompt_file="outline.md",
        output_file="02-outline.md",
        instructions=(
            "You design high-quality blog outlines. Return markdown only and create "
            "a structure that a writer can follow directly."
        ),
    ),
    AgentSpec(
        key="writer",
        label="Agent 3: Writer",
        prompt_file="writer.md",
        output_file="03-draft.md",
        instructions=(
            "You write clear, expert long-form blog posts. Return markdown only and "
            "optimize for usefulness, clarity, and flow."
        ),
    ),
    AgentSpec(
        key="seo",
        label="Agent 4: SEO Audit",
        prompt_file="seo.md",
        output_file="04-final.md",
        instructions=(
            "You are a careful SEO editor. Return markdown only and improve search "
            "clarity, readability, and conversion while preserving substance."
        ),
    ),
)
