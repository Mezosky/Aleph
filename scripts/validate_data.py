"""Validate committed static payloads and their referential invariants."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]


def _validate_megareforma() -> list[str]:
    failures: list[str] = []
    pairs = [
        ("megareforma_dossier.json", "dossier.json"),
        ("megareforma_sources.json", "sources.json"),
        ("megareforma_theory.json", "theory.json"),
    ]
    payloads: dict[str, dict] = {}
    for schema_name, data_name in pairs:
        schema_path = ROOT / "schemas" / schema_name
        data_path = ROOT / "frontend" / "public" / "data" / "megareforma" / data_name
        try:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            payload = json.loads(data_path.read_text(encoding="utf-8"))
            payloads[data_name] = payload
            errors = sorted(
                Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(payload),
                key=lambda error: list(error.absolute_path),
            )
            for error in errors:
                location = "/".join(str(part) for part in error.absolute_path) or "<root>"
                failures.append(f"{data_name}:{location}: {error.message}")
        except Exception as exc:
            failures.append(f"{data_name}: {exc}")

    dossier = payloads.get("dossier.json", {})
    sources = payloads.get("sources.json", {})
    theory = payloads.get("theory.json", {})
    source_ids = {item.get("id") for item in sources.get("items", [])}
    known_source_ids = source_ids | {item.get("id") for item in sources.get("gaps", [])}
    actor_ids = {item.get("id") for item in dossier.get("actors", [])}
    screenshots = ROOT / "frontend" / "public" / "data"
    for item in sources.get("items", []):
        if not (screenshots / str(item.get("screenshot", ""))).is_file():
            failures.append(f"sources.json:{item.get('id')}: screenshot is missing")
    for actor in dossier.get("actors", []):
        if not (screenshots / str(actor.get("image", ""))).is_file():
            failures.append(f"dossier.json:{actor.get('id')}: actor image is missing")
        for record in actor.get("public_record", []):
            for source_id in record.get("source_ids", []):
                if source_id not in known_source_ids:
                    failures.append(
                        f"dossier.json:{actor.get('id')}: unknown record source {source_id}"
                    )
    for meter in dossier.get("meters", []):
        poles = meter.get("pole_actor_ids", {})
        for actor_id in [*poles.get("left", []), *poles.get("right", [])]:
            if actor_id not in actor_ids:
                failures.append(f"dossier.json:{meter.get('id')}: unknown actor {actor_id}")
        for evidence in meter.get("evidence", []):
            for source_id in evidence.get("source_ids", []):
                if source_id not in source_ids:
                    failures.append(f"dossier.json:{meter.get('id')}: unknown source {source_id}")
    for topic in theory.get("topics", []):
        for source_id in topic.get("source_ids", []):
            if source_id not in known_source_ids:
                failures.append(f"theory.json:{topic.get('id')}: unknown source {source_id}")
    return failures


def main() -> int:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "generate_sample_data.py"), "--check"],
        cwd=ROOT,
        check=False,
    )
    failures = _validate_megareforma()
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print("megareforma dossier and captured-source registry validate")
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
