"""Explicit live news acquisition; never called by import or CI."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from aleph.core.config import get_config
    from aleph.news.registry import load_registry
    from aleph.retrieval.acquisition import NewsAcquirer
    from api.database import Database

    parser = argparse.ArgumentParser(description="Poll verified Aleph news feeds")
    parser.add_argument("--allow-network", action="store_true", required=True)
    parser.add_argument(
        "--query",
        default="18216-05 megarreforma reconstrucción desarrollo económico social",
    )
    parser.add_argument("--max-articles", type=int, default=20)
    args = parser.parse_args()
    config = get_config()
    database = Database(config.database_url.reveal(), auto_create=config.database_auto_create)
    try:
        summary = NewsAcquirer(
            database,
            registry=load_registry(config.source_registry_path),
        ).run(
            args.query,
            allow_network=args.allow_network,
            max_articles=max(0, args.max_articles),
        )
        print(json.dumps(asdict(summary), ensure_ascii=False, indent=2))
    finally:
        database.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
