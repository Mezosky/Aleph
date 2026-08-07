from aleph.news.registry import default_registry


def test_official_actor_record_sources_are_registered_without_trust_scores() -> None:
    registry = default_registry()
    for source_id in ("src:cl-infoprobidad", "src:cl-poder-judicial", "src:cl-diario-oficial"):
        entry = registry.require(source_id)
        assert entry.kind.value == "government_body"
        assert "score" not in entry.model_dump()
        assert "credibility" not in entry.model_dump()
