from __future__ import annotations

import csv
import json
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .agents import AGENTS, AgentSpec
from .config import AppConfig
from .llm import ContentLLM
from .models import PipelineMetadata, StageAttempt, StageResult, TopicRecord
from .prompting import load_prompt, load_style_guide, render_prompt
from .queue_store import QueueStore


@dataclass(frozen=True)
class TopicJob:
    job_key: str
    index: int
    topic: TopicRecord
    topic_dir: Path
    metadata_path: Path


class StageExecutionError(RuntimeError):
    def __init__(self, stage_result: StageResult) -> None:
        super().__init__(stage_result.error_message or f"{stage_result.stage_key} failed")
        self.stage_result = stage_result


def load_topics(topics_file: Path) -> list[TopicRecord]:
    with topics_file.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        topics = [
            TopicRecord(
                title=(row.get("title") or "").strip(),
                primary_keyword=(row.get("primary_keyword") or "").strip(),
                audience=(row.get("audience") or "").strip(),
                angle=(row.get("angle") or "").strip(),
                notes=(row.get("notes") or "").strip(),
            )
            for row in reader
            if (row.get("title") or "").strip()
        ]
    if not topics:
        raise RuntimeError(f"No valid topics found in {topics_file}")
    return topics


def run_pipeline(
    *,
    config: AppConfig,
    topics_file: Path,
    limit: int | None,
    resume: bool,
    topic_row: int | None,
) -> None:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    jobs = build_jobs(config=config, topics_file=topics_file, limit=limit, topic_row=topic_row)
    write_manifest(
        manifest_path=config.queue_manifest_path,
        topics_file=topics_file,
        config=config,
        jobs=jobs,
        resume=resume,
    )

    queue_store = QueueStore(config.queue_db_path)
    prep_stats = queue_store.prepare_run(
        [serialize_job_for_queue(job) for job in jobs],
        resume=resume,
    )
    style_guide = load_style_guide(config.style_guide_path)
    worker_count = max(1, min(config.worker_count, len(jobs)))
    log = make_logger()
    log(
        "[queue] "
        f"topics={len(jobs)} workers={worker_count} "
        f"stage_attempts={config.stage_max_attempts} backoff={config.retry_backoff_seconds}s"
    )
    log(
        "[queue] "
        f"db={config.queue_db_path} manifest={config.queue_manifest_path} "
        f"pending={prep_stats['pending']} recovered={prep_stats['recovered']} skipped={prep_stats['skipped']}"
    )

    threads = [
        threading.Thread(
            target=worker_loop,
            name=f"worker-{worker_id}",
            args=(worker_id, config, style_guide, queue_store, resume, log),
            daemon=False,
        )
        for worker_id in range(1, worker_count + 1)
    ]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    summarize_outcomes(queue_store=queue_store, log=log)


def build_jobs(
    *,
    config: AppConfig,
    topics_file: Path,
    limit: int | None,
    topic_row: int | None,
) -> list[TopicJob]:
    topics = load_topics(topics_file)
    if topic_row is not None:
        if topic_row < 1 or topic_row > len(topics):
            raise RuntimeError(
                f"--topic-row must be between 1 and {len(topics)} for {topics_file}"
            )
        indexed_topics = [(topic_row, topics[topic_row - 1])]
    else:
        indexed_topics = list(enumerate(topics, start=1))

    if limit is not None:
        indexed_topics = indexed_topics[:limit]

    jobs = []
    for index, topic in indexed_topics:
        topic_slug = slugify(topic.title)
        job_key = f"T{index:02d}-{topic_slug}"
        topic_dir = config.output_dir / job_key
        jobs.append(
            TopicJob(
                job_key=job_key,
                index=index,
                topic=topic,
                topic_dir=topic_dir,
                metadata_path=topic_dir / "metadata.json",
            )
        )
    if not jobs:
        raise RuntimeError("No topics selected for this run.")
    return jobs


def serialize_job_for_queue(job: TopicJob) -> dict[str, object]:
    return {
        "job_key": job.job_key,
        "topic_index": job.index,
        "topic_slug": slugify(job.topic.title),
        "title": job.topic.title,
        "topic_json": job.topic.model_dump_json(),
        "topic_dir": str(job.topic_dir),
        "metadata_path": str(job.metadata_path),
        "final_exists": (job.topic_dir / "04-final.md").exists(),
    }


def worker_loop(
    worker_id: int,
    config: AppConfig,
    style_guide: str,
    queue_store: QueueStore,
    resume: bool,
    log,
) -> None:
    llm = ContentLLM(config)
    worker_name = f"worker-{worker_id}"
    while True:
        claimed = queue_store.claim_next_job(worker_name)
        if claimed is None:
            return
        job = TopicJob(
            job_key=str(claimed["job_key"]),
            index=int(claimed["topic_index"]),
            topic=claimed["topic"],
            topic_dir=Path(str(claimed["topic_dir"])),
            metadata_path=Path(str(claimed["metadata_path"])),
        )
        process_topic(
            worker_name=worker_name,
            job=job,
            llm=llm,
            config=config,
            style_guide=style_guide,
            queue_store=queue_store,
            resume=resume,
            log=log,
        )


def process_topic(
    *,
    worker_name: str,
    job: TopicJob,
    llm: ContentLLM,
    config: AppConfig,
    style_guide: str,
    queue_store: QueueStore,
    resume: bool,
    log,
) -> None:
    topic = job.topic
    job.topic_dir.mkdir(parents=True, exist_ok=True)
    log(f"[{worker_name}] [start] T{job.index:02d}: {topic.title}")

    stage_outputs, stage_results = load_existing_stage_outputs(
        topic_dir=job.topic_dir,
        mock=config.mock,
        resume=resume,
    )
    metadata = PipelineMetadata(
        topic_index=job.index,
        topic_slug=slugify(topic.title),
        topic=topic,
        status="running",
        started_at=utc_now_iso(),
        active_stage=None,
        stage_results=stage_results,
        mock=config.mock,
    )
    write_metadata(job.metadata_path, metadata)
    queue_store.sync_metadata(job_key=job.job_key, worker_name=worker_name, metadata=metadata)

    for spec in AGENTS:
        if spec.key in stage_outputs:
            log(f"[{worker_name}] [resume] T{job.index:02d} {spec.label} -> reused existing artifact")
            continue

        metadata.active_stage = spec.key
        write_metadata(job.metadata_path, metadata)
        queue_store.sync_metadata(job_key=job.job_key, worker_name=worker_name, metadata=metadata)
        try:
            stage_result, content = run_stage_with_retry(
                spec=spec,
                llm=llm,
                config=config,
                topic=topic,
                topic_dir=job.topic_dir,
                style_guide=style_guide,
                stage_outputs=stage_outputs,
                log=log,
                worker_name=worker_name,
                topic_index=job.index,
            )
        except StageExecutionError as exc:
            metadata.stage_results.append(exc.stage_result)
            metadata.status = "failed"
            metadata.finished_at = utc_now_iso()
            metadata.error_message = exc.stage_result.error_message
            metadata.active_stage = spec.key
            write_metadata(job.metadata_path, metadata)
            queue_store.sync_metadata(job_key=job.job_key, worker_name=worker_name, metadata=metadata)
            log(
                f"[{worker_name}] [failed] T{job.index:02d} "
                f"{spec.label} -> {exc.stage_result.error_message}"
            )
            return

        stage_outputs[spec.key] = content
        metadata.stage_results.append(stage_result)
        metadata.error_message = None
        metadata.active_stage = None
        write_metadata(job.metadata_path, metadata)
        queue_store.sync_metadata(job_key=job.job_key, worker_name=worker_name, metadata=metadata)
        log(
            f"[{worker_name}] [done] T{job.index:02d} {spec.label:<20} "
            f"{stage_result.elapsed_seconds:>6.1f}s -> {stage_result.output_file}"
        )

    metadata.status = "completed"
    metadata.finished_at = utc_now_iso()
    metadata.active_stage = None
    write_metadata(job.metadata_path, metadata)
    queue_store.sync_metadata(job_key=job.job_key, worker_name=worker_name, metadata=metadata)
    log(f"[{worker_name}] [saved] T{job.index:02d} metadata -> {job.metadata_path}")


def load_existing_stage_outputs(
    *,
    topic_dir: Path,
    mock: bool,
    resume: bool,
) -> tuple[dict[str, str], list[StageResult]]:
    if not resume:
        return {}, []

    stage_outputs: dict[str, str] = {}
    stage_results: list[StageResult] = []
    for spec in AGENTS:
        output_path = topic_dir / spec.output_file
        if not output_path.exists():
            break
        content = output_path.read_text(encoding="utf-8")
        stage_outputs[spec.key] = content
        stage_results.append(
            StageResult(
                stage_key=spec.key,
                stage_label=spec.label,
                output_file=str(output_path),
                model="existing-artifact",
                status="reused",
                elapsed_seconds=0.0,
                request_id=None,
                usage={},
                attempts=[],
                error_message=None,
                mock=mock,
            )
        )
    return stage_outputs, stage_results


def run_stage_with_retry(
    *,
    spec: AgentSpec,
    llm: ContentLLM,
    config: AppConfig,
    topic: TopicRecord,
    topic_dir: Path,
    style_guide: str,
    stage_outputs: dict[str, str],
    log,
    worker_name: str,
    topic_index: int,
) -> tuple[StageResult, str]:
    prompt_template = load_prompt(config.prompts_dir, spec.prompt_file)
    prompt = render_prompt(
        prompt_template,
        {
            "title": topic.title,
            "primary_keyword": topic.primary_keyword,
            "audience": topic.audience,
            "angle": topic.angle,
            "notes": topic.notes,
            "style_guide": style_guide,
            "research_markdown": stage_outputs.get("research", "Research output not available yet."),
            "outline_markdown": stage_outputs.get("outline", "Outline output not available yet."),
            "draft_markdown": stage_outputs.get("writer", "Draft output not available yet."),
        },
    )
    output_path = topic_dir / spec.output_file
    attempts: list[StageAttempt] = []

    for attempt_number in range(1, config.stage_max_attempts + 1):
        attempt_started_at = utc_now_iso()
        started_at = time.perf_counter()
        try:
            generation = llm.generate(
                stage_key=spec.key,
                instructions=spec.instructions,
                prompt=prompt,
                topic=topic,
            )
            elapsed_seconds = round(time.perf_counter() - started_at, 2)
            output_path.write_text(generation.content.strip() + "\n", encoding="utf-8")
            attempts.append(
                StageAttempt(
                    attempt_number=attempt_number,
                    status="completed",
                    started_at=attempt_started_at,
                    finished_at=utc_now_iso(),
                    elapsed_seconds=elapsed_seconds,
                    model=generation.model,
                    request_id=generation.request_id,
                    usage=generation.usage,
                    error_message=None,
                )
            )
            return (
                StageResult(
                    stage_key=spec.key,
                    stage_label=spec.label,
                    output_file=str(output_path),
                    model=generation.model,
                    status="completed",
                    elapsed_seconds=round(sum(item.elapsed_seconds for item in attempts), 2),
                    request_id=generation.request_id,
                    usage=generation.usage,
                    attempts=attempts,
                    error_message=None,
                    mock=config.mock,
                ),
                generation.content,
            )
        except Exception as exc:
            elapsed_seconds = round(time.perf_counter() - started_at, 2)
            error_message = f"{type(exc).__name__}: {exc}"
            attempts.append(
                StageAttempt(
                    attempt_number=attempt_number,
                    status="failed",
                    started_at=attempt_started_at,
                    finished_at=utc_now_iso(),
                    elapsed_seconds=elapsed_seconds,
                    model=config.model_for_stage(spec.key),
                    request_id=None,
                    usage={},
                    error_message=error_message,
                )
            )
            if attempt_number < config.stage_max_attempts:
                backoff_seconds = round(
                    config.retry_backoff_seconds * (2 ** (attempt_number - 1)),
                    2,
                )
                log(
                    f"[{worker_name}] [retry] T{topic_index:02d} {spec.label} "
                    f"attempt {attempt_number}/{config.stage_max_attempts} failed: "
                    f"{error_message}. Waiting {backoff_seconds}s"
                )
                time.sleep(backoff_seconds)
                continue

            raise StageExecutionError(
                StageResult(
                    stage_key=spec.key,
                    stage_label=spec.label,
                    output_file=str(output_path),
                    model=config.model_for_stage(spec.key),
                    status="failed",
                    elapsed_seconds=round(sum(item.elapsed_seconds for item in attempts), 2),
                    request_id=None,
                    usage={},
                    attempts=attempts,
                    error_message=error_message,
                    mock=config.mock,
                )
            ) from exc

    raise RuntimeError(f"Unexpected retry loop exit for stage {spec.key}")


def write_manifest(
    *,
    manifest_path: Path,
    topics_file: Path,
    config: AppConfig,
    jobs: list[TopicJob],
    resume: bool,
) -> None:
    manifest = {
        "created_at": utc_now_iso(),
        "topics_file": str(topics_file),
        "output_dir": str(config.output_dir),
        "queue_db_path": str(config.queue_db_path),
        "resume": resume,
        "worker_count": config.worker_count,
        "stage_max_attempts": config.stage_max_attempts,
        "retry_backoff_seconds": config.retry_backoff_seconds,
        "jobs": [
            {
                "job_key": job.job_key,
                "topic_index": job.index,
                "title": job.topic.title,
                "topic_dir": str(job.topic_dir),
            }
            for job in jobs
        ],
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def summarize_outcomes(*, queue_store: QueueStore, log) -> None:
    summary = queue_store.summarize_selected_jobs()
    log(
        "[summary] "
        f"completed={summary['completed']} failed={summary['failed']} "
        f"skipped={summary['skipped']} pending={summary['pending']} running={summary['running']}"
    )


def write_metadata(metadata_path: Path, metadata: PipelineMetadata) -> None:
    metadata_path.write_text(
        json.dumps(metadata.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def make_logger():
    lock = threading.Lock()

    def _log(message: str) -> None:
        with lock:
            print(message, flush=True)

    return _log


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def slugify(value: str) -> str:
    lowered = value.strip().lower()
    cleaned = "".join(ch if ch.isalnum() else "-" for ch in lowered)
    compact = "-".join(part for part in cleaned.split("-") if part)
    return compact or "untitled"
