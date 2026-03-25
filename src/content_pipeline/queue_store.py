from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import PipelineMetadata, TopicRecord


class QueueStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def prepare_run(self, jobs: list[dict[str, object]], *, resume: bool) -> dict[str, int]:
        stats = {"pending": 0, "recovered": 0, "skipped": 0}
        now = utc_now_iso()
        with self._connect() as conn:
            conn.execute("UPDATE jobs SET selected_for_run = 0")
            for job in jobs:
                row = conn.execute(
                    "SELECT status, finished_at FROM jobs WHERE job_key = ?",
                    (job["job_key"],),
                ).fetchone()
                final_exists = int(job["final_exists"])
                existing_status = row["status"] if row else None
                status = decide_prepared_status(
                    existing_status=existing_status,
                    final_exists=bool(final_exists),
                    resume=resume,
                )
                if existing_status == "running" and status == "pending":
                    stats["recovered"] += 1
                if status == "pending":
                    stats["pending"] += 1
                if status == "skipped":
                    stats["skipped"] += 1

                if row is None:
                    conn.execute(
                        """
                        INSERT INTO jobs (
                          job_key,
                          topic_index,
                          topic_slug,
                          title,
                          topic_json,
                          topic_dir,
                          metadata_path,
                          status,
                          active_stage,
                          error_message,
                          worker_id,
                          selected_for_run,
                          created_at,
                          updated_at,
                          started_at,
                          finished_at,
                          last_heartbeat_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            job["job_key"],
                            job["topic_index"],
                            job["topic_slug"],
                            job["title"],
                            job["topic_json"],
                            job["topic_dir"],
                            job["metadata_path"],
                            status,
                            None,
                            None,
                            None,
                            1,
                            now,
                            now,
                            None if status == "pending" else now,
                            now if status == "skipped" else None,
                            None,
                        ),
                    )
                    continue

                finished_at = row["finished_at"]
                if status == "pending":
                    finished_at = None
                elif status == "skipped":
                    finished_at = finished_at or now

                conn.execute(
                    """
                    UPDATE jobs
                    SET topic_index = ?,
                        topic_slug = ?,
                        title = ?,
                        topic_json = ?,
                        topic_dir = ?,
                        metadata_path = ?,
                        status = ?,
                        active_stage = NULL,
                        error_message = NULL,
                        worker_id = NULL,
                        selected_for_run = 1,
                        updated_at = ?,
                        started_at = CASE WHEN ? = 'pending' THEN NULL ELSE started_at END,
                        finished_at = ?,
                        last_heartbeat_at = NULL
                    WHERE job_key = ?
                    """,
                    (
                        job["topic_index"],
                        job["topic_slug"],
                        job["title"],
                        job["topic_json"],
                        job["topic_dir"],
                        job["metadata_path"],
                        status,
                        now,
                        status,
                        finished_at,
                        job["job_key"],
                    ),
                )
        return stats

    def claim_next_job(self, worker_name: str) -> dict[str, object] | None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT job_key, topic_index, topic_json, topic_dir, metadata_path
                FROM jobs
                WHERE selected_for_run = 1 AND status = 'pending'
                ORDER BY topic_index ASC
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                conn.execute("COMMIT")
                return None

            now = utc_now_iso()
            conn.execute(
                """
                UPDATE jobs
                SET status = 'running',
                    worker_id = ?,
                    updated_at = ?,
                    started_at = COALESCE(started_at, ?),
                    last_heartbeat_at = ?,
                    error_message = NULL
                WHERE job_key = ?
                """,
                (worker_name, now, now, now, row["job_key"]),
            )
            conn.execute("COMMIT")
            return {
                "job_key": row["job_key"],
                "topic_index": row["topic_index"],
                "topic": TopicRecord.model_validate_json(row["topic_json"]),
                "topic_dir": row["topic_dir"],
                "metadata_path": row["metadata_path"],
            }

    def sync_metadata(
        self,
        *,
        job_key: str,
        worker_name: str,
        metadata: PipelineMetadata,
    ) -> None:
        now = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status = ?,
                    active_stage = ?,
                    error_message = ?,
                    worker_id = ?,
                    updated_at = ?,
                    finished_at = ?,
                    last_heartbeat_at = ?,
                    metadata_json = ?
                WHERE job_key = ?
                """,
                (
                    metadata.status,
                    metadata.active_stage,
                    metadata.error_message,
                    worker_name,
                    now,
                    metadata.finished_at,
                    now,
                    json.dumps(metadata.model_dump(mode="json"), ensure_ascii=False),
                    job_key,
                ),
            )

    def summarize_selected_jobs(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM jobs
                WHERE selected_for_run = 1
                GROUP BY status
                """
            ).fetchall()
        summary = {row["status"]: row["count"] for row in rows}
        return {
            "completed": summary.get("completed", 0),
            "failed": summary.get("failed", 0),
            "skipped": summary.get("skipped", 0),
            "pending": summary.get("pending", 0),
            "running": summary.get("running", 0),
        }

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                  job_key TEXT PRIMARY KEY,
                  topic_index INTEGER NOT NULL,
                  topic_slug TEXT NOT NULL,
                  title TEXT NOT NULL,
                  topic_json TEXT NOT NULL,
                  topic_dir TEXT NOT NULL,
                  metadata_path TEXT NOT NULL,
                  status TEXT NOT NULL,
                  active_stage TEXT,
                  error_message TEXT,
                  worker_id TEXT,
                  selected_for_run INTEGER NOT NULL DEFAULT 0,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  started_at TEXT,
                  finished_at TEXT,
                  last_heartbeat_at TEXT,
                  metadata_json TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_jobs_selected_status
                ON jobs (selected_for_run, status, topic_index)
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection


def decide_prepared_status(
    *,
    existing_status: str | None,
    final_exists: bool,
    resume: bool,
) -> str:
    if not resume:
        return "pending"
    if final_exists:
        return "skipped"
    if existing_status == "running":
        return "pending"
    if existing_status in {"pending", "failed", None, "completed", "skipped"}:
        return "pending"
    return "pending"


def utc_now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).replace(microsecond=0).isoformat()
