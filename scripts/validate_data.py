"""Validate committed static payloads and their referential invariants."""

from __future__ import annotations

import hashlib
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
        ("megareforma_municipal_actors.json", "municipal-actors.json"),
        ("megareforma_deep_analysis.json", "deep-analysis.json"),
        ("megareforma_actor_census.json", "actor-census.json"),
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
    municipal = payloads.get("municipal-actors.json", {})
    deep = payloads.get("deep-analysis.json", {})
    census = payloads.get("actor-census.json", {})
    source_ids = {item.get("id") for item in sources.get("items", [])}
    known_source_ids = source_ids | {item.get("id") for item in sources.get("gaps", [])}
    actor_ids = {item.get("id") for item in dossier.get("actors", [])}
    screenshots = ROOT / "frontend" / "public" / "data"
    for item in sources.get("items", []):
        screenshot = screenshots / str(item.get("screenshot", ""))
        if not screenshot.is_file():
            failures.append(f"sources.json:{item.get('id')}: screenshot is missing")
        elif hashlib.sha256(screenshot.read_bytes()).hexdigest() != item.get("screenshot_sha256"):
            failures.append(f"sources.json:{item.get('id')}: screenshot hash does not match")
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
    municipal_actors = municipal.get("actors", [])
    if municipal.get("coverage", {}).get("actors_indexed") != len(municipal_actors):
        failures.append("municipal-actors.json: coverage actors_indexed does not match actors")
    for actor in municipal_actors:
        image_value = actor.get("image")
        if image_value:
            image = screenshots / str(image_value)
            if not image.is_file():
                failures.append(f"municipal-actors.json:{actor.get('id')}: image is missing")
            elif hashlib.sha256(image.read_bytes()).hexdigest() != actor.get("image_sha256"):
                failures.append(
                    f"municipal-actors.json:{actor.get('id')}: image hash does not match"
                )
        references = list(actor.get("source_ids", []))
        references.extend(
            source_id
            for record in actor.get("public_record", [])
            for source_id in record.get("source_ids", [])
        )
        for source_id in references:
            if source_id not in known_source_ids:
                failures.append(
                    f"municipal-actors.json:{actor.get('id')}: unknown source {source_id}"
                )
    if deep.get("document", {}).get("last_structured_page") != 46:
        failures.append("deep-analysis.json: structured reading does not reach page 46")
    if deep.get("coverage", {}).get("topics_grounded") != len(deep.get("topics", [])):
        failures.append("deep-analysis.json: grounded topic count does not match topics")
    for topic in deep.get("topics", []):
        if topic.get("source_page") not in topic.get("pages", []):
            failures.append(
                f"deep-analysis.json:{topic.get('id')}: source page is outside declared pages"
            )
        for source_id in topic.get("news_source_ids", []):
            if source_id not in source_ids:
                failures.append(
                    f"deep-analysis.json:{topic.get('id')}: unknown news source {source_id}"
                )
    census_actors = census.get("actors", [])
    if census.get("coverage", {}).get("actors_indexed") != len(census_actors):
        failures.append("actor-census.json: actor count does not match actors")
    for actor in census_actors:
        for source_id in actor.get("source_ids", []):
            if source_id not in source_ids:
                failures.append(f"actor-census.json:{actor.get('id')}: unknown source {source_id}")
        for mention in actor.get("mentions", []):
            if mention.get("source_id") not in source_ids:
                failures.append(
                    f"actor-census.json:{actor.get('id')}: unknown mention source "
                    f"{mention.get('source_id')}"
                )
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
