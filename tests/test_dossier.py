from types import SimpleNamespace

import pytest

from aleph.dossier.synthesize import _ANCHORS, synthesize_document_brief
from aleph.llm.base import LLMResponse, StructuredOutputMode


def _objective(category: str) -> dict:
    return {
        "category": category,
        "title": f"Objetivo {category}",
        "plain_language": "Explicación concreta y suficientemente extensa para una persona lectora.",
        "mechanism": "Mecanismo legal explicado de manera verificable y sin atribuir resultados futuros.",
        "affected_groups": ["grupo afectado"],
        "caveat": "El resultado depende de condiciones que todavía deben observarse.",
    }


class _Provider:
    def __init__(self, objectives: list[dict]) -> None:
        self.objectives = objectives

    def complete(self, *_args, **_kwargs) -> LLMResponse:
        return LLMResponse(
            text="{}",
            model="test-qwen",
            provider="qwen",
            parsed={
                "document_summary": "Resumen suficientemente largo del documento financiero y de sus mecanismos principales.",
                "scope_note": "El informe es inicial y no equivale al texto finalmente modificado por el Congreso.",
                "objectives": self.objectives,
            },
            schema_valid=True,
            structured_output_mode=StructuredOutputMode.JSON_SCHEMA,
        )


def _document():
    by_page: dict[int, list[str]] = {}
    for _category, (page, quote) in _ANCHORS.items():
        by_page.setdefault(page, []).append(quote)
    pages = tuple(
        SimpleNamespace(page_number=page, text="\n".join(quotes))
        for page, quotes in by_page.items()
    )
    return SimpleNamespace(pages=pages)


def test_dossier_attaches_only_literal_deterministic_anchors() -> None:
    result = synthesize_document_brief(
        _document(),
        _Provider([_objective(category) for category in _ANCHORS]),
    )

    assert result["grounding"]["accepted"] == 6
    assert result["grounding"]["rejected"] == 0
    assert all(item["quote_verified"] for item in result["objectives"])
    assert all(
        item["quote_grounding_method"] == "deterministic_exact_anchor"
        for item in result["objectives"]
    )


def test_dossier_rejects_duplicate_categories() -> None:
    duplicated = [_objective("reconstruction") for _ in range(6)]
    with pytest.raises(ValueError, match="only 1 objectives"):
        synthesize_document_brief(_document(), _Provider(duplicated))
