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
    parser.add_argument("--fetch", action="store_true", help="reserved for explicit live retrieval")
    args = parser.parse_args()
    if args.fetch:
        print(
            "live refresh providers are not configured; no network request was made",
            file=sys.stderr,
        )
        return 2
    command = [sys.executable, str(ROOT / "scripts" / "generate_sample_data.py")]
    if args.check:
        command.append("--check")
    return subprocess.run(command, cwd=ROOT, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
