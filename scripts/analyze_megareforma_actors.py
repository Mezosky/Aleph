"""Audit every frozen source for substantive actors using the local Qwen model."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aleph.dossier.actor_census import (  # noqa: E402
    census_batch,
    merge_census,
    visible_article_text,
)
from aleph.llm.qwen import QwenProvider  # noqa: E402
from api.database import AnalysisRunRow, Database, utcnow  # noqa: E402

SOURCES = ROOT / "frontend/public/data/megareforma/sources.json"
DOSSIER = ROOT / "frontend/public/data/megareforma/dossier.json"
MUNICIPAL = ROOT / "frontend/public/data/megareforma/municipal-actors.json"
OUT = ROOT / "frontend/public/data/megareforma/actor-census.json"
CHECKPOINT = ROOT / "data/actor-census-checkpoint.json"
MODEL = "nvidia/Qwen3.5-122B-A10B-NVFP4"
REVISION = "98915d837c4e7c87ac8296d02e89de19b3207e6d"
CENSUS_VERSION = "actor-census-v5"


def _chunks(text: str, *, size: int = 12_000, overlap: int = 800) -> list[str]:
    if len(text) <= size:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap
    return chunks


def _snapshot_texts(
    database_path: Path, items: list[dict]
) -> tuple[list[tuple[str, str]], dict[str, str]]:
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    sources: list[tuple[str, str]] = []
    canonical_ids: dict[str, str] = {}
    for item in items:
        row = connection.execute(
            "SELECT content FROM retrieval_snapshots WHERE id = ?", (item["snapshot_id"],)
        ).fetchone()
        if row is None:
            raise SystemExit(f"captured source {item['id']} has no immutable snapshot")
        content = row["content"]
        if content.startswith(b"%PDF"):
            import pymupdf

            document = pymupdf.open(stream=content, filetype="pdf")
            text = " ".join(page.get_text() for page in document)
            document.close()
        else:
            text = visible_article_text(content, max_chars=1_000_000)
        if len(text) < 120:
            text = f"{item['title']}. {item['summary']}"
        # Comparative papers establish theory rather than positions on this bill.
        # Their opening section is enough to identify the publishing institution;
        # scanning hundreds of bibliography pages would turn cited authors into
        # false political actors. All bill/news/official text is scanned in full.
        parts = [text[:16_000]] if item["kind"] == "research" else _chunks(text)
        for part_number, part in enumerate(parts, 1):
            audit_id = (
                item["id"]
                if len(parts) == 1
                else f"{item['id']}::part-{part_number}-of-{len(parts)}"
            )
            sources.append((audit_id, part))
            canonical_ids[audit_id] = item["id"]
    connection.close()
    return sources, canonical_ids


def _canonicalize_mentions(result: dict, canonical_ids: dict[str, str]) -> dict:
    normalized = json.loads(json.dumps(result))
    for actor in normalized["actors"]:
        for mention in actor["mentions"]:
            mention["source_id"] = canonical_ids[mention["source_id"]]
    return normalized


def _profile_actor_type(role: str) -> str:
    normalized = role.casefold()
    if "alcald" in normalized:
        return "mayor"
    if any(value in normalized for value in ("diputad", "senador", "senadora", "senado")):
        return "legislator"
    if "presidente de la república" in normalized or "ministro" in normalized:
        return "government"
    return "other"


def _role_actor_type(role: str, current: str) -> str:
    normalized = role.casefold()
    if "alcald" in normalized:
        return "mayor"
    if any(value in normalized for value in ("diputad", "senador", "senadora", "senado")):
        return "legislator"
    if (
        any(
            value in normalized
            for value in ("ministro", "ministra", "subsecretario", "subsecretaria")
        )
        or "presidente de la república" in normalized
    ):
        return "government"
    if "presidenta del partido" in normalized or "secretario general" in normalized:
        return "political_party"
    return current


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8001/v1")
    parser.add_argument("--database-url", default="sqlite:///./data/aleph.db")
    parser.add_argument("--batch-size", type=int, default=3)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument(
        "--repair-batch-start",
        type=int,
        default=-1,
        help=(
            "Rebuild one dense batch from smaller source fragments, store it in the "
            "normal checkpoint, and exit. The value is the batch's starting chunk index."
        ),
    )
    args = parser.parse_args()

    source_payload = json.loads(SOURCES.read_text(encoding="utf-8"))
    dossier = json.loads(DOSSIER.read_text(encoding="utf-8"))
    municipal = json.loads(MUNICIPAL.read_text(encoding="utf-8"))
    database_path = ROOT / args.database_url.removeprefix("sqlite:///")
    source_texts, canonical_ids = _snapshot_texts(database_path, source_payload["items"])
    known_profiles = {
        actor["name"].casefold(): actor for actor in [*dossier["actors"], *municipal["actors"]]
    }
    detailed_names = {
        actor["name"].casefold(): actor["name"]
        for actor in [*dossier["actors"], *municipal["actors"]]
    }

    provider = QwenProvider(
        base_url=args.base_url,
        model=MODEL,
        temperature=0.0,
        timeout=900,
        enable_thinking=False,
    )
    checkpoint = (
        json.loads(CHECKPOINT.read_text(encoding="utf-8"))
        if CHECKPOINT.exists()
        else {"version": 1, "active_census_version": CENSUS_VERSION, "batches": {}}
    )
    if checkpoint.get("active_census_version") != CENSUS_VERSION:
        checkpoint = {
            "version": 1,
            "active_census_version": CENSUS_VERSION,
            "batches": {},
        }
        CHECKPOINT.write_text(
            json.dumps(checkpoint, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    batch_jobs = []
    for start in range(0, len(source_texts), args.batch_size):
        batch = source_texts[start : start + args.batch_size]
        batch_fingerprint = hashlib.sha256(
            json.dumps(
                {"version": CENSUS_VERSION, "batch": batch},
                ensure_ascii=False,
                sort_keys=True,
            ).encode()
        ).hexdigest()
        batch_jobs.append((start, batch_fingerprint, batch))
    checkpoint.update(
        {
            "sources_total": source_payload["capture_count"],
            "text_chunks_total": len(source_texts),
            "batches_total": len(batch_jobs),
        }
    )
    CHECKPOINT.write_text(
        json.dumps(checkpoint, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    if args.repair_batch_start >= 0:
        target = next(
            (job for job in batch_jobs if job[0] == args.repair_batch_start),
            None,
        )
        if target is None:
            provider.close()
            starts = ", ".join(str(start) for start, _, _ in batch_jobs)
            raise SystemExit(f"unknown batch start; valid values: {starts}")
        start, fingerprint, batch = target
        fragments: list[tuple[str, str, str]] = []
        for audit_id, source_text in batch:
            parts = _chunks(source_text, size=3_500, overlap=400)
            for number, part in enumerate(parts, 1):
                synthetic_id = f"{audit_id}::dense-{number}-of-{len(parts)}"
                fragments.append((synthetic_id, audit_id, part))

        repaired_parts: list[dict] = []
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
            futures = {
                executor.submit(census_batch, provider, [(synthetic_id, text)]): (
                    synthetic_id,
                    audit_id,
                )
                for synthetic_id, audit_id, text in fragments
            }
            completed = 0
            for future in as_completed(futures):
                synthetic_id, audit_id = futures[future]
                result = future.result()
                for actor in result["actors"]:
                    for mention in actor["mentions"]:
                        if mention["source_id"] != synthetic_id:
                            raise RuntimeError(
                                f"unexpected source id {mention['source_id']} in {synthetic_id}"
                            )
                        mention["source_id"] = audit_id
                repaired_parts.append(result)
                completed += 1
                print(
                    f"dense batch {start}: fragments {completed}/{len(fragments)}",
                    flush=True,
                )

        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        repaired = {
            "actors": [],
            "rejected": 0,
            "rejection_reasons": {},
            "rejected_examples": [],
            "usage": usage,
        }
        for part in repaired_parts:
            repaired["actors"].extend(part["actors"])
            repaired["rejected"] += int(part["rejected"])
            for reason, count in part["rejection_reasons"].items():
                repaired["rejection_reasons"][reason] = repaired["rejection_reasons"].get(
                    reason, 0
                ) + int(count)
            repaired["rejected_examples"].extend(part["rejected_examples"])
            for key in usage:
                usage[key] += int(part["usage"].get(key, 0) or 0)
        repaired["rejected_examples"] = repaired["rejected_examples"][:20]
        checkpoint["batches"][fingerprint] = repaired
        CHECKPOINT.write_text(
            json.dumps(checkpoint, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        provider.close()
        print(
            json.dumps(
                {
                    "batch_start": start,
                    "source_chunks": len(batch),
                    "dense_fragments": len(fragments),
                    "actors_returned": len(repaired["actors"]),
                    "rejected": repaired["rejected"],
                    "tokens": usage,
                }
            )
        )
        return 0

    batches_by_start: dict[int, dict] = {}
    pending = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        for start, fingerprint, batch in batch_jobs:
            result = checkpoint["batches"].get(fingerprint)
            if result is not None:
                batches_by_start[start] = _canonicalize_mentions(result, canonical_ids)
                print(
                    f"actor census chunks {min(start + len(batch), len(source_texts))}/"
                    f"{len(source_texts)} (cache)",
                    flush=True,
                )
            else:
                future = executor.submit(census_batch, provider, batch)
                pending.append((future, start, fingerprint, batch))
        future_metadata = {
            future: (start, fingerprint, batch) for future, start, fingerprint, batch in pending
        }
        for future in as_completed(future_metadata):
            start, fingerprint, batch = future_metadata[future]
            result = future.result()
            checkpoint["batches"][fingerprint] = result
            CHECKPOINT.write_text(
                json.dumps(checkpoint, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            batches_by_start[start] = _canonicalize_mentions(result, canonical_ids)
            print(
                f"actor census chunks {min(start + len(batch), len(source_texts))}/"
                f"{len(source_texts)} (model)",
                flush=True,
            )
    provider.close()
    batches = [batches_by_start[start] for start, _, _ in batch_jobs]
    merged = merge_census(batches, detailed_names=detailed_names)
    actors = merged["actors"]
    for actor in actors:
        profile = known_profiles.get(actor["name"].casefold())
        if profile is None:
            continue
        actor["role"] = profile["role"]
        actor["institution"] = profile.get("institution") or profile.get("municipality", "")
        actor["affiliation"] = profile.get("affiliation", "")
        actor["actor_type"] = _profile_actor_type(profile["role"])
        actor["public_record"] = profile.get("public_record", [])
        actor["record_caveat"] = profile.get("record_caveat", "")
        for field in (
            "image",
            "image_alt",
            "image_credit",
            "image_license",
            "image_source_url",
        ):
            if profile.get(field):
                actor[field] = profile[field]
    for actor in actors:
        if actor["entity_kind"] == "person":
            actor["actor_type"] = _role_actor_type(actor["role"], actor["actor_type"])
    generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    accepted_mentions = sum(len(actor["mentions"]) for actor in actors)
    people = sum(actor["entity_kind"] == "person" for actor in actors)
    institutions = len(actors) - people
    detailed = sum(actor["profile_depth"] == "detailed" for actor in actors)
    payload = {
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "execution": "local_gpu_offline",
        "runtime_calls": 0,
        "coverage": {
            "captured_sources_total": source_payload["capture_count"],
            "captured_sources_audited": source_payload["capture_count"],
            "text_chunks_audited": len(source_texts),
            "actors_indexed": len(actors),
            "people": people,
            "institutions": institutions,
            "detailed_profiles": detailed,
            "indexed_only": len(actors) - detailed,
            "accepted_mentions": accepted_mentions,
            "rejected_ungrounded_candidates": merged["rejected"],
            "universe": (
                "Toda persona o institución con una acción, posición, voto, evaluación técnica, "
                "negociación o responsabilidad de implementación atribuida en las capturas congeladas."
            ),
            "limitation": (
                "El censo es exhaustivo respecto de las fuentes capturadas al corte, no respecto de "
                "internet. Las fuentes inaccesibles permanecen como brechas y no pueden aportar "
                "actores hasta ser archivadas en otra corrida."
            ),
        },
        "actors": actors,
        "model": {
            "name": MODEL,
            "revision": REVISION,
            "batches": len(batches),
            "usage": merged["usage"],
        },
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    digest = hashlib.sha256(canonical).hexdigest()

    database = Database(args.database_url)
    with database.sessions.begin() as session:
        parent = session.scalar(
            select(AnalysisRunRow)
            .where(AnalysisRunRow.model_provider == "qwen")
            .order_by(AnalysisRunRow.completed_at.desc())
        )
        if parent is None:
            raise SystemExit("no canonical Qwen run exists")
        now = utcnow()
        session.add(
            AnalysisRunRow(
                id=uuid.uuid4().hex,
                document_id=parent.document_id,
                supersedes_run_id=parent.id,
                source_snapshot_id=parent.source_snapshot_id,
                state="complete",
                allow_network=False,
                model_provider="qwen",
                model_name=MODEL,
                model_revision=REVISION,
                pipeline_version="megareforma-actor-census-v2",
                prompt_version=CENSUS_VERSION,
                schema_version="1.0.0",
                config_fingerprint=hashlib.sha256(CENSUS_VERSION.encode()).hexdigest(),
                result_json={"actor_census": payload},
                result_sha256=digest,
                created_at=now,
                started_at=now,
                completed_at=now,
                updated_at=now,
            )
        )
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    database.dispose()
    print(
        json.dumps(
            {
                "sources": source_payload["capture_count"],
                "chunks": len(source_texts),
                "actors": len(actors),
                "people": people,
                "institutions": institutions,
                "mentions": accepted_mentions,
                "rejected": merged["rejected"],
                "tokens": merged["usage"],
                "sha256": digest,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
