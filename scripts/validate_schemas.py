"""Compile every published schema as Draft 2020-12."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"
ID_PREFIX = "https://mezosky.github.io/Aleph/schemas/"


def main() -> int:
    failures: list[str] = []
    paths = sorted(SCHEMAS.glob("*.json"))
    if not paths:
        print("no schemas found", file=sys.stderr)
        return 1
    for path in paths:
        try:
            schema = json.loads(path.read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
            if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
                failures.append(f"{path.name}: wrong or missing $schema")
            if not str(schema.get("$id", "")).startswith(ID_PREFIX):
                failures.append(f"{path.name}: $id is outside the published schema namespace")
        except Exception as exc:
            failures.append(f"{path.name}: {exc}")
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(f"{len(paths)} schemas compile as Draft 2020-12")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
