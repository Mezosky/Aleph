#!/usr/bin/env python3
"""Build the shipped English catalog with the local GPU model.

Only explanatory prose is translated. Headlines, names, citations, URLs,
identifiers and schema-control values remain in their original language so an
English reader never mistakes a translation for primary evidence.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "frontend" / "public" / "data" / "megareforma"
OUTPUT = DATA / "translations-en.json"
CHECKPOINT = DATA / "translations-en.partial.json"
FILES = (
    "dossier.json",
    "deep-analysis.json",
    "theory.json",
    "municipal-actors.json",
    "actor-census.json",
    "sources.json",
)
SKIP_KEYS = {
    "id",
    "name",
    "publisher",
    "author",
    "affiliation",
    "institution",
    "model",
    "model_id",
    "sha256",
    "url",
    "pdf_url",
    "image_url",
    "screenshot_path",
    "source_quote",
    "evidence_quote",
    "quote",
    "verbatim_quote",
}
PROTECTED_KEYS = {
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
CONTROL_VALUE = re.compile(r"^[a-z0-9][a-z0-9_./:@-]*$")


def collect(value: Any, *, path: tuple[str, ...] = ()) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            next_path = (*path, key)
            if (
                key in SKIP_KEYS
                or key.endswith("_id")
                or key.endswith("_ids")
                or key.endswith("_at")
                or ("items" in path and path[0] == "sources.json" and key == "title")
            ):
                continue
            found.update(collect(item, path=next_path))
    elif isinstance(value, list):
        for item in value:
            found.update(collect(item, path=path))
    elif isinstance(value, str):
        text = value.strip()
        if (
            len(text) >= 3
            and not CONTROL_VALUE.fullmatch(text)
            and not text.startswith(("http://", "https://"))
        ):
            found.add(text)
    return found


def collect_protected(value: Any, *, path: tuple[str, ...] = ()) -> set[str]:
    protected: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            source_headline = (
                key == "title" and path and path[0] == "sources.json" and "items" in path
            )
            if (key in PROTECTED_KEYS or source_headline) and isinstance(item, str):
                protected.add(item.strip())
            else:
                protected.update(collect_protected(item, path=(*path, key)))
    elif isinstance(value, list):
        for item in value:
            protected.update(collect_protected(item, path=path))
    return protected


def normalize_english(source: str, target: str) -> str:
    """Apply Chile-specific terminology and remove gender guesses deterministically."""

    def matching_case(match: re.Match[str], replacement: str) -> str:
        return replacement.capitalize() if match.group(0)[0].isupper() else replacement

    normalized = re.sub(
        r"\b(?:he/she|she/he)\b",
        lambda match: matching_case(match, "they"),
        target,
        flags=re.IGNORECASE,
    )
    source_folded = source.casefold()
    property_tax_context = "contribuciones" in source_folded and any(
        marker in source_folded
        for marker in (
            "exención",
            "vivienda",
            "municip",
            "comuna",
            "adultos mayores",
            "personas mayores",
            "propietari",
            "fondo común",
            "avalúo",
            "pagar contribuciones",
            "baja de contribuciones",
        )
    )
    if property_tax_context:
        normalized = re.sub(
            r"\bcontribution exemption\b",
            "property tax exemption",
            normalized,
            flags=re.IGNORECASE,
        )
        normalized = re.sub(
            r"(?<!property )\bcontributions\b",
            lambda match: matching_case(match, "property taxes"),
            normalized,
            flags=re.IGNORECASE,
        )
        normalized = re.sub(
            r"\bproperty property taxes\b", "property taxes", normalized, flags=re.IGNORECASE
        )
    elif "contribuciones" in source_folded:
        normalized = re.sub(r"\bproperty taxes\b", "contributions", normalized, flags=re.IGNORECASE)
    if "permiso de circulación" in source.casefold():
        normalized = re.sub(
            r"\bcirculation permits?\b",
            "vehicle registration fees",
            normalized,
            flags=re.IGNORECASE,
        )
    if "avalúo fiscal" in source.casefold():
        normalized = re.sub(
            r"\bfiscal appraisal\b", "tax-assessed value", normalized, flags=re.IGNORECASE
        )
    if "mesa del senado" in source.casefold():
        normalized = normalized.replace("Senate table", "Senate leadership")
    return normalized


async def translate_batch(
    client: httpx.AsyncClient,
    endpoint: str,
    model: str,
    batch: list[tuple[str, str]],
) -> dict[str, str]:
    payload = dict(batch)
    response = await client.post(
        f"{endpoint.rstrip('/')}/chat/completions",
        json={
            "model": model,
            "temperature": 0.0,
            "max_tokens": 12000,
            "chat_template_kwargs": {"enable_thinking": False},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a precise professional translator of Chilean public-policy analysis. "
                        "Translate every Spanish value into natural English. Preserve numbers, names, acronyms, "
                        "legal nuance and epistemic caution. Never add claims. Return exactly one JSON object with "
                        "the same keys and translated string values; no commentary."
                    ),
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "aleph_translation_batch",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {key: {"type": "string"} for key in payload},
                        "required": list(payload),
                        "additionalProperties": False,
                    },
                },
            },
        },
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    translated = json.loads(content)
    if set(translated) != set(payload) or not all(
        isinstance(item, str) for item in translated.values()
    ):
        raise RuntimeError("Translation batch returned different keys or non-string values")
    return translated


async def run(args: argparse.Namespace) -> None:
    texts: set[str] = set()
    protected: set[str] = set()
    for filename in FILES:
        payload = json.loads((DATA / filename).read_text())
        texts.update(collect(payload, path=(filename,)))
        protected.update(collect_protected(payload, path=(filename,)))
    texts.difference_update(protected)
    checkpoint_catalog: dict[str, Any] = {}
    completed_translations: dict[str, str] = {}
    if CHECKPOINT.exists():
        checkpoint_catalog = json.loads(CHECKPOINT.read_text())
        completed_translations = checkpoint_catalog.get("translations", {})
    ordered = sorted(texts.difference(completed_translations))
    batches = [
        [
            (f"t{index + offset:04d}", text)
            for offset, text in enumerate(ordered[index : index + args.batch_size])
        ]
        for index in range(0, len(ordered), args.batch_size)
    ]
    by_key = {key: text for batch in batches for key, text in batch}
    semaphore = asyncio.Semaphore(args.concurrency)

    async with httpx.AsyncClient(timeout=args.timeout) as client:

        async def guarded(batch: list[tuple[str, str]]) -> dict[str, str]:
            async with semaphore:
                try:
                    return await translate_batch(client, args.endpoint, args.model, batch)
                except (RuntimeError, json.JSONDecodeError):
                    if len(batch) == 1:
                        raise
                    middle = len(batch) // 2
                    left = await translate_batch(client, args.endpoint, args.model, batch[:middle])
                    right = await translate_batch(client, args.endpoint, args.model, batch[middle:])
                    return {**left, **right}

        tasks = [asyncio.create_task(guarded(batch)) for batch in batches]
        results: list[dict[str, str]] = []
        translated_count = 0
        for completed_count, task in enumerate(asyncio.as_completed(tasks), start=1):
            result = await task
            results.append(result)
            translated_count += len(result)
            checkpoint_catalog = {
                "source_language": "es",
                "target_language": "en",
                "generated_by": args.model,
                "translation_policy": (
                    "Analysis prose translated; original headlines, names and evidence "
                    "quotations retained."
                ),
                "translations": {
                    **completed_translations,
                    **{
                        by_key[key]: normalize_english(by_key[key], value)
                        for key, value in result.items()
                    },
                },
            }
            completed_translations = checkpoint_catalog["translations"]
            CHECKPOINT.write_text(
                json.dumps(checkpoint_catalog, ensure_ascii=False, indent=2) + "\n"
            )
            print(
                f"translation {completed_count}/{len(tasks)} batches · "
                f"{translated_count}/{len(ordered)} strings",
                flush=True,
            )

    translations = {
        **completed_translations,
        **{
            by_key[key]: normalize_english(by_key[key], english)
            for result in results
            for key, english in result.items()
        },
    }
    catalog = {
        "source_language": "es",
        "target_language": "en",
        "generated_by": args.model,
        "translation_policy": "Analysis prose translated; original headlines, names and evidence quotations retained.",
        "translations": translations,
    }
    OUTPUT.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n")
    CHECKPOINT.unlink(missing_ok=True)
    print(f"translated {len(translations)} strings in {len(batches)} batches -> {OUTPUT}")


def clean_existing() -> None:
    catalog = json.loads(OUTPUT.read_text())
    protected: set[str] = set()
    for filename in FILES:
        protected.update(
            collect_protected(json.loads((DATA / filename).read_text()), path=(filename,))
        )
    before = len(catalog["translations"])
    catalog["translations"] = {
        source: normalize_english(source, target)
        for source, target in catalog["translations"].items()
        if source not in protected
    }
    OUTPUT.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n")
    print(f"removed {before - len(catalog['translations'])} protected strings -> {OUTPUT}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", default="http://127.0.0.1:8001/v1")
    parser.add_argument("--model", default="nvidia/Qwen3.5-122B-A10B-NVFP4")
    parser.add_argument("--batch-size", type=int, default=35)
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument(
        "--clean-existing",
        action="store_true",
        help="remove protected names, headlines and quotations without invoking the model",
    )
    args = parser.parse_args()
    if args.clean_existing:
        clean_existing()
    else:
        asyncio.run(run(args))


if __name__ == "__main__":
    main()
