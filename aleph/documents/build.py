"""Turn located extracted text into a conservative phase-one document model."""

from __future__ import annotations

import re
from collections.abc import Iterable

from aleph.core.enums import (
    DataStatus,
    DocumentStatus,
    JurisdictionLevel,
    ProvisionType,
    SectionType,
)
from aleph.core.models import (
    DocumentIdentity,
    DocumentModel,
    DocumentSource,
    DocumentStructure,
    Jurisdiction,
    Provision,
    Section,
    Span,
)
from aleph.ingestion.fetch import FetchedDocument
from aleph.ingestion.pdf import ExtractedDocument


def _paragraphs(text: str) -> Iterable[tuple[int, str]]:
    for match in re.finditer(r"\S(?:.*?\S)?(?=\n\s*\n|\Z)", text, re.DOTALL):
        value = " ".join(match.group(0).split())
        if len(value) >= 20:
            yield match.start(), value


def build_document_model(
    fetched: FetchedDocument,
    extracted: ExtractedDocument,
    *,
    title: str | None = None,
    language: str = "und",
) -> DocumentModel:
    """Build only what the source establishes; unknown metadata stays unknown."""
    slug = fetched.sha256[:12]
    document_id = f"doc:{slug}"
    provisions: list[Provision] = []
    for index, (start, text) in enumerate(_paragraphs(extracted.text), start=1):
        page = extracted.page_at(start)
        provisions.append(
            Provision(
                id=f"prov:{slug}:{index}",
                title=None,
                text=text,
                provision_type=ProvisionType.OTHER,
                section_id="sec:body",
                span=Span(
                    page=page.page_number if page else None,
                    section_id="sec:body",
                    char_start=start,
                    char_end=start + len(text),
                    text=text,
                ),
            )
        )

    section = Section(
        id="sec:body",
        heading="Document body",
        level=0,
        section_type=SectionType.OTHER,
        char_start=0,
        char_end=len(extracted.text),
        provision_ids=[item.id for item in provisions],
        is_heuristic=True,
    )
    resolved_title = (
        title or extracted.metadata.get("title") or fetched.file_name or "Untitled document"
    )
    return DocumentModel(
        schema_version="1.0.0",
        data_status=DataStatus.DERIVED,
        id=document_id,
        identity=DocumentIdentity(
            slug=slug,
            title=resolved_title,
            jurisdiction=Jurisdiction(code=None, name=None, level=JurisdictionLevel.UNKNOWN),
            document_type="other",
            language=language,
            status=DocumentStatus.UNKNOWN,
        ),
        source=DocumentSource(
            url=fetched.final_url or fetched.url,
            file_name=fetched.file_name,
            media_type=fetched.media_type,
            file_hash=fetched.sha256,
            hash_algorithm="sha256",
            file_size_bytes=fetched.size_bytes,
            page_count=extracted.page_count,
            retrieved_at=fetched.retrieved_at,
            retrieval_method=fetched.retrieval_method,
            extraction_method=extracted.extraction_method,
            extractor_version=extracted.extractor_version,
            extraction_quality=extracted.quality,
        ),
        structure=DocumentStructure(
            sections=[section],
            numbering_scheme=None,
            max_depth=0,
            has_table_of_contents=False,
        ),
        provisions=provisions,
        extraction_warnings=list(extracted.warnings),
        notes=(
            "Paragraph boundaries are a conservative fallback; provision structure is heuristic "
            "until a document-specific outline can be established from the source."
        ),
    )
