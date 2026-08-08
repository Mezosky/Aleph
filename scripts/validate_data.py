"""Validate committed static payloads and their referential invariants."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]


def _validate_megareforma() -> list[str]:
    failures: list[str] = []
    try:
        analytics_schema = json.loads(
            (ROOT / "schemas" / "site_analytics.json").read_text(encoding="utf-8")
        )
        analytics = json.loads(
            (ROOT / "frontend" / "public" / "data" / "site-analytics.json").read_text(
                encoding="utf-8"
            )
        )
        for error in Draft202012Validator(
            analytics_schema, format_checker=FormatChecker()
        ).iter_errors(analytics):
            location = "/".join(str(part) for part in error.absolute_path) or "<root>"
            failures.append(f"site-analytics.json:{location}: {error.message}")
    except Exception as exc:
        failures.append(f"site-analytics.json: {exc}")
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
    translation_path = (
        ROOT / "frontend" / "public" / "data" / "megareforma" / "translations-en.json"
    )
    try:
        translation_catalog = json.loads(translation_path.read_text(encoding="utf-8"))
        translations = translation_catalog.get("translations", {})
        if translation_catalog.get("source_language") != "es":
            failures.append("translations-en.json: source_language must be es")
        if translation_catalog.get("target_language") != "en":
            failures.append("translations-en.json: target_language must be en")
        if not isinstance(translations, dict) or len(translations) < 500:
            failures.append("translations-en.json: expected at least 500 translated prose strings")
        elif any(
            not isinstance(source, str) or not isinstance(target, str) or not target.strip()
            for source, target in translations.items()
        ):
            failures.append(
                "translations-en.json: translations must map strings to non-empty strings"
            )
        else:
            protected_keys = {
                "name",
                "publisher",
                "author",
                "affiliation",
                "institution",
                "municipality",
                "source_quote",
                "evidence_quote",
                "quote",
                "verbatim_quote",
            }

            def protected_values(value: object) -> set[str]:
                values: set[str] = set()
                if isinstance(value, dict):
                    for key, item in value.items():
                        if key in protected_keys and isinstance(item, str):
                            values.add(item.strip())
                        else:
                            values.update(protected_values(item))
                elif isinstance(value, list):
                    for item in value:
                        values.update(protected_values(item))
                return values

            protected = set().union(*(protected_values(payload) for payload in payloads.values()))
            protected.update(
                item.get("title", "").strip()
                for item in sources.get("items", [])
                if isinstance(item.get("title"), str)
            )
            overlap = protected.intersection(translations)
            if overlap:
                failures.append(
                    "translations-en.json: primary evidence or identity strings were translated: "
                    + ", ".join(sorted(overlap)[:3])
                )
    except Exception as exc:
        failures.append(f"translations-en.json: {exc}")
    source_ids = {item.get("id") for item in sources.get("items", [])}
    source_by_id = {item.get("id"): item for item in sources.get("items", [])}
    all_news_ids = {
        source_id for source_id, source in source_by_id.items() if source.get("kind") == "news"
    }
    known_source_ids = source_ids | {item.get("id") for item in sources.get("gaps", [])}
    actor_ids = {item.get("id") for item in dossier.get("actors", [])}
    official_legal_hosts = {
        "fiscaliadechile.cl",
        "pjud.cl",
        "contraloria.cl",
        "diariooficial.interior.gob.cl",
        "tribunalconstitucional.cl",
        "tribunalcalificador.cl",
        "fne.gob.cl",
        "tdlc.cl",
    }
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
        for record in actor.get("legal_record", []):
            source = record.get("source", {})
            hostname = (urlparse(str(source.get("url", ""))).hostname or "").removeprefix("www.")
            if hostname not in official_legal_hosts:
                failures.append(
                    f"dossier.json:{actor.get('id')}: legal record lacks an approved official source"
                )
            if source.get("tier") not in {
                "primary_document",
                "legislative_record",
                "official_technical_report",
            }:
                failures.append(
                    f"dossier.json:{actor.get('id')}: legal record source is not primary"
                )
            if not record.get("resolved") and len(str(record.get("presumption_note") or "")) < 30:
                failures.append(
                    f"dossier.json:{actor.get('id')}: unresolved legal record lacks presumption note"
                )
        for record in actor.get("official_case_context", []):
            source = record.get("source", {})
            hostname = (urlparse(str(source.get("url", ""))).hostname or "").removeprefix("www.")
            if hostname not in official_legal_hosts:
                failures.append(
                    f"dossier.json:{actor.get('id')}: official case context lacks an approved official source"
                )
            if source.get("tier") != "primary_document":
                failures.append(
                    f"dossier.json:{actor.get('id')}: official case context source is not primary"
                )
            if record.get("personal_status") != "named_professional_not_sanctioned":
                failures.append(
                    f"dossier.json:{actor.get('id')}: professional context misstates personal status"
                )
        has_legal = bool(actor.get("legal_record"))
        has_context = bool(actor.get("official_case_context"))
        expected_audit_status = (
            "personal_record_and_professional_context_attached"
            if has_legal and has_context
            else "personal_record_attached"
            if has_legal
            else "professional_context_attached"
            if has_context
            else "no_qualifying_record_documented"
        )
        if actor.get("official_record_audit", {}).get("status") != expected_audit_status:
            failures.append(
                f"dossier.json:{actor.get('id')}: official audit status does not match attached evidence"
            )
    for meter in dossier.get("meters", []):
        for actor_id in meter.get("actor_ids", []):
            if actor_id not in actor_ids:
                failures.append(f"dossier.json:{meter.get('id')}: unknown actor {actor_id}")
        poles = meter.get("pole_actor_ids", {})
        left_pole_ids = poles.get("left", [])
        right_pole_ids = poles.get("right", [])
        if not left_pole_ids or not right_pole_ids:
            failures.append(f"dossier.json:{meter.get('id')}: both actor poles must be populated")
        if set(left_pole_ids) & set(right_pole_ids):
            failures.append(f"dossier.json:{meter.get('id')}: actor poles must not overlap")
        if not {*left_pole_ids, *right_pole_ids}.issubset(set(meter.get("actor_ids", []))):
            failures.append(
                f"dossier.json:{meter.get('id')}: pole actors must also appear in actor_ids"
            )
        for actor_id in [*left_pole_ids, *right_pole_ids]:
            if actor_id not in actor_ids:
                failures.append(f"dossier.json:{meter.get('id')}: unknown actor {actor_id}")
        for evidence in meter.get("evidence", []):
            for source_id in evidence.get("source_ids", []):
                if source_id not in source_ids:
                    failures.append(f"dossier.json:{meter.get('id')}: unknown source {source_id}")
        if meter.get("id") == "coverage-position":
            meter_news_ids = {
                source_id
                for evidence in meter.get("evidence", [])
                for source_id in evidence.get("source_ids", [])
            }
            if meter_news_ids != all_news_ids:
                failures.append(
                    "dossier.json: coverage meter must classify every captured news item"
                )
    evaluated_news_ids: set[str] = set()
    for question in dossier.get("debate", []):
        for source_id in question.get("news_source_ids", []):
            source = source_by_id.get(source_id)
            if source is None:
                failures.append(
                    f"dossier.json:{question.get('id')}: unknown debate-news source {source_id}"
                )
            elif source.get("kind") != "news":
                failures.append(
                    f"dossier.json:{question.get('id')}: debate-news source is not press {source_id}"
                )
            evaluated_news_ids.add(source_id)
    other_angle_news_ids: list[str] = []
    for angle in dossier.get("other_angles", []):
        for actor_id in angle.get("actor_ids", []):
            if actor_id not in actor_ids:
                failures.append(f"dossier.json:{angle.get('id')}: unknown actor {actor_id}")
        for source_id in angle.get("source_ids", []):
            source = source_by_id.get(source_id)
            if source is None:
                failures.append(f"dossier.json:{angle.get('id')}: unknown source {source_id}")
            elif source.get("kind") == "news":
                other_angle_news_ids.append(source_id)
    if len(other_angle_news_ids) != len(set(other_angle_news_ids)):
        failures.append("dossier.json: a news item appears in more than one other angle")
    overlap = evaluated_news_ids.intersection(other_angle_news_ids)
    if overlap:
        failures.append(
            "dossier.json: evaluated news must not be duplicated in other angles: "
            + ", ".join(sorted(overlap)[:3])
        )
    assigned_news_ids = evaluated_news_ids | set(other_angle_news_ids)
    if assigned_news_ids != all_news_ids:
        missing = all_news_ids - assigned_news_ids
        unexpected = assigned_news_ids - all_news_ids
        failures.append(
            "dossier.json: every captured news item must belong to an evaluated question or "
            f"other angle (missing={sorted(missing)}, unexpected={sorted(unexpected)})"
        )
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
    census_ids = [actor.get("id") for actor in census_actors]
    if len(census_ids) != len(set(census_ids)):
        failures.append("actor-census.json: actor ids must be unique after identity reconciliation")
    census_people = [actor for actor in census_actors if actor.get("entity_kind") == "person"]
    documented_affiliations = sum(
        actor.get("affiliation_status") != "not_documented" for actor in census_people
    )
    if documented_affiliations * 2 <= len(census_people):
        failures.append(
            "actor-census.json: most people must have a sourced affiliation or independent status"
        )
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
