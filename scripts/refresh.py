"""Refresh deterministic curated outputs; live retrieval remains explicit."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--fetch", action="store_true", help="explicitly poll verified live feeds")
    parser.add_argument(
        "--query",
        default="18216-05 megarreforma reconstrucción desarrollo económico social",
    )
    parser.add_argument("--max-articles", type=int, default=20)
    args = parser.parse_args()
    if args.fetch:
        return subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "scrape_news.py"),
                "--allow-network",
                "--query",
                args.query,
                "--max-articles",
                str(max(0, args.max_articles)),
            ],
            cwd=ROOT,
            check=False,
        )
    command = [sys.executable, str(ROOT / "scripts" / "generate_sample_data.py")]
    if args.check:
        command.append("--check")
    return subprocess.run(command, cwd=ROOT, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
