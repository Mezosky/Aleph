from aleph.dossier.theory import TOPICS, synthesize_theory_analysis
from aleph.llm.base import LLMResponse, StructuredOutputMode


class _Provider:
    def __init__(self, *, bad_source: bool = False) -> None:
        self.bad_source = bad_source

    def complete(self, *_args, **_kwargs) -> LLMResponse:
        topics = []
        for index, (topic_id, spec) in enumerate(TOPICS.items()):
            source_ids = [spec["source_ids"][0]]
            if self.bad_source and index == 0:
                source_ids = ["invented-source"]
            topics.append(
                {
                    "id": topic_id,
                    "bottom_line": "La evidencia permite una conclusión condicional, no una predicción automática para Chile.",
                    "findings": [
                        "El efecto observado depende del diseño institucional y del contexto económico.",
                        "La evidencia comparada no identifica por sí sola el efecto causal del proyecto chileno.",
                    ],
                    "application_to_reform": "La reforma necesita indicadores chilenos posteriores y una comparación pública contra un contrafactual.",
                    "limits": "No existe todavía una serie posterior que permita atribuir resultados a esta ley.",
                    "source_ids": source_ids,
                }
            )
        return LLMResponse(
            text="{}",
            model="test-qwen",
            provider="qwen",
            parsed={"topics": topics},
            schema_valid=True,
            structured_output_mode=StructuredOutputMode.JSON_SCHEMA,
        )


def test_theory_analysis_accepts_only_the_bounded_source_packet() -> None:
    result = synthesize_theory_analysis(_Provider())
    assert len(result["topics"]) == 6
    assert {item["id"] for item in result["topics"]} == set(TOPICS)


def test_theory_analysis_rejects_an_invented_reference() -> None:
    try:
        synthesize_theory_analysis(_Provider(bad_source=True))
    except ValueError as exc:
        assert "outside its evidence packet" in str(exc)
    else:
        raise AssertionError("an invented comparative source must fail closed")
