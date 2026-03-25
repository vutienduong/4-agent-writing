from __future__ import annotations

import os
from openai import OpenAI

from .config import AppConfig
from .models import LLMGeneration, TokenUsage, TopicRecord


class ContentLLM:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.client = None if config.mock else self._build_client()

    def generate(
        self,
        *,
        stage_key: str,
        instructions: str,
        prompt: str,
        topic: TopicRecord,
    ) -> LLMGeneration:
        if self.config.mock:
            return self._mock_generation(stage_key=stage_key, prompt=prompt, topic=topic)

        assert self.client is not None
        model = self.config.model_for_stage(stage_key)
        response = self.client.responses.create(
            model=model,
            instructions=instructions,
            input=prompt,
        )
        usage = getattr(response, "usage", None)
        token_usage = TokenUsage(
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
            total_tokens=getattr(usage, "total_tokens", None),
        )
        return LLMGeneration(
            content=response.output_text.strip(),
            model=model,
            request_id=getattr(response, "_request_id", None),
            usage=token_usage,
            raw_response=response.model_dump() if hasattr(response, "model_dump") else None,
        )

    def _build_client(self) -> OpenAI:
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError(
                "OPENAI_API_KEY is missing. Create a .env from .env.example or use --mock."
            )

        return OpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            timeout=self.config.timeout_seconds,
            max_retries=self.config.max_retries,
        )

    def _mock_generation(
        self,
        *,
        stage_key: str,
        prompt: str,
        topic: TopicRecord,
    ) -> LLMGeneration:
        content = build_mock_markdown(stage_key=stage_key, topic=topic, prompt=prompt)
        return LLMGeneration(
            content=content,
            model=f"mock::{self.config.model_for_stage(stage_key)}",
            usage=TokenUsage(input_tokens=0, output_tokens=0, total_tokens=0),
            raw_response={"mock": True, "topic": topic.model_dump(mode="json")},
        )


def build_mock_markdown(stage_key: str, topic: TopicRecord, prompt: str) -> str:
    title = topic.title
    keyword = topic.primary_keyword or title.lower()
    if stage_key == "research":
        return f"""# Research Brief

## Search Intent
Readers searching for "{keyword}" likely want a practical explanation plus concrete steps they can apply immediately.

## Reader Problems
- Hard to decide where to start
- Too much vague advice
- Need examples that work for lean teams

## Core Claims To Cover
- Why the topic matters now
- Common implementation mistakes
- A practical operating model

## Important Terms And Entities
- {keyword}
- workflow
- automation
- quality control

## Suggested Examples
- A small team shipping weekly content
- A pipeline with review gates

## Risks, Caveats, Or Assumptions
- Examples should be adapted to the reader's team size and budget.

## Internal Link Ideas
- Beginner's guide
- Tool comparison
- Implementation checklist

## Call To Action Direction
Invite the reader to audit their current workflow and start with one small pilot.
"""
    if stage_key == "outline":
        return f"""# Article Outline

## Positioning
Make the topic practical, not theoretical.

## Working Title Options
- {title}: A Practical Guide
- How To Execute {keyword} Without Chaos

## Meta Description Drafts
- Learn how to approach {keyword} with a simple and repeatable workflow.

## Recommended H1
# {title}

## Heading Structure
## Introduction
## Why This Matters
## Common Mistakes
## A Practical Framework
## Example Workflow
## Metrics To Track
## Conclusion

## Section-by-Section Brief
- Introduction: Set the promise and context.
- Why This Matters: Explain business value.
- Common Mistakes: Show what to avoid.
- A Practical Framework: Give the reader an operating model.
- Example Workflow: Make it concrete.
- Metrics To Track: Show how to evaluate results.
- Conclusion: Summarize and add CTA.

## FAQ Ideas
- How long does implementation take?
- Which tasks should be automated first?

## CTA Placement
Add a CTA near the end with a practical next step.
"""
    if stage_key == "writer":
        return f"""# {title}

{title} is easiest to understand when we stop treating it like a vague trend and start treating it like an operating system. Most teams do not fail because the idea is bad. They fail because the workflow is loose, ownership is unclear, and quality control happens too late.

## Why This Matters

For a lean team, the real value of {keyword} is leverage. The goal is not to publish more for the sake of volume. The goal is to create a repeatable system that converts inputs into useful outputs with less coordination overhead.

## Common Mistakes

One common mistake is asking one model to do everything. Another is skipping explicit handoffs. A third is leaving quality checks to the very end, when fixing structural issues becomes expensive.

## A Practical Framework

A better approach is to break the work into stages. Start with research so the system knows what readers care about. Then design an outline that locks the narrative arc. After that, let the writer expand the outline into a full draft. Finish with a strict editorial pass focused on SEO, readability, and calls to action.

Each stage should produce a concrete artifact. This makes the system observable. When an output is weak, you can inspect the exact stage that caused the weakness instead of blaming the whole pipeline.

## Example Workflow

Imagine a team managing a backlog of fifty content ideas. The operator feeds a CSV file into the pipeline. The research agent turns each topic into a brief. The outline agent converts that brief into a structured article plan. The writer generates a long-form draft. The SEO editor tightens the piece and formats the final deliverable.

Because each step is separate, the team can retry only the failed stage, swap models per stage, and compare performance over time. That is much more reliable than a monolithic prompt.

## Metrics To Track

Track lead time per article, token cost per stage, pass rate without manual edits, and downstream performance metrics such as impressions, click-through rate, and assisted conversions. These numbers help you decide where automation is adding value and where human review still matters most.

## Conclusion

The strongest systems do not rely on magic. They rely on explicit roles, clear contracts, and observable artifacts. If you want better outcomes from {keyword}, start by making the pipeline legible and measurable.

## CTA

Map your current process into four stages, then automate one stage at a time and measure the quality delta.
"""
    return f"""---
meta_title: {title} | Practical Guide
meta_description: Learn a practical framework for {keyword} with clear steps, examples, and metrics.
---

# {title}

{title} works best when the workflow is explicit. Rather than pushing one prompt to do everything, strong teams separate research, structure, drafting, and SEO refinement into distinct stages.

## Why This Matters

The advantage of this approach is consistency. Each stage has one job, one output, and one quality bar. That makes it easier to scale content production without losing control over clarity or relevance.

## Common Mistakes To Avoid

Teams often over-automate too early, skip editorial gates, or rely on vague prompts. Those mistakes create shallow articles that are hard to trust and hard to rank.

## A Practical Framework

Start with a research brief that captures search intent, reader pain points, and supporting examples. Use that brief to create an outline with a clear narrative arc. Turn the outline into a full draft with concrete examples and useful explanations. Finish with an SEO-focused editorial pass that improves scanability, keyword placement, and conversion elements.

## Example Workflow

For example, a lean content team can process a CSV of topics through four agents. Each agent saves a markdown artifact, which makes the pipeline easy to inspect, retry, and improve over time.

## Metrics To Track

Measure cycle time, token cost, publish rate, and post-publication performance. These signals reveal whether the workflow is actually creating leverage.

## Conclusion

The best automation systems are not mysterious. They are disciplined. When you define clear agent roles and handoffs, {keyword} becomes far easier to scale without losing quality.

## CTA

Choose one high-value topic, run it through a four-stage pipeline, and review the outputs before expanding volume.
"""
