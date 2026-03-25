from __future__ import annotations

import argparse
from pathlib import Path

from .config import load_config
from .orchestrator import run_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a local 4-agent content pipeline.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run the pipeline.")
    run_parser.add_argument(
        "--topics-file",
        default="topics.csv",
        help="CSV file containing content topics.",
    )
    run_parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory for generated article artifacts. Defaults to ./output.",
    )
    run_parser.add_argument(
        "--style-guide",
        default=None,
        help="Optional path to a markdown style guide injected into prompts.",
    )
    run_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only process the first N topics.",
    )
    run_parser.add_argument(
        "--topic-row",
        type=int,
        default=None,
        help="Process a single 1-based row from the CSV.",
    )
    run_parser.add_argument(
        "--mock",
        action="store_true",
        help="Run without calling the API and generate deterministic placeholder outputs.",
    )
    run_parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip topics that already have 04-final.md.",
    )
    run_parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Number of topic workers to run in parallel.",
    )
    run_parser.add_argument(
        "--stage-max-attempts",
        type=int,
        default=None,
        help="Maximum attempts per stage before a topic is marked failed.",
    )
    run_parser.add_argument(
        "--retry-backoff-seconds",
        type=float,
        default=None,
        help="Base backoff in seconds between stage retries.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "run":
        config = load_config(
            mock=args.mock,
            output_dir=args.output_dir,
            style_guide=args.style_guide,
            worker_count=args.workers,
            stage_max_attempts=args.stage_max_attempts,
            retry_backoff_seconds=args.retry_backoff_seconds,
        )
        run_pipeline(
            config=config,
            topics_file=Path(args.topics_file).expanduser().resolve(),
            limit=args.limit,
            resume=args.resume,
            topic_row=args.topic_row,
        )


if __name__ == "__main__":
    main()
