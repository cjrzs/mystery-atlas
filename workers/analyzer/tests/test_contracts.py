from mystery_atlas_analyzer.contracts import RelationFinding


def relation_with_kind(kind: str) -> RelationFinding:
    return RelationFinding(
        source="甲",
        target="乙",
        label="认识",
        kind=kind,
        first_chapter=1,
    )


def test_relation_kind_keeps_stable_category() -> None:
    assert relation_with_kind("investigation").kind == "investigation"


def test_relation_kind_normalizes_legacy_category() -> None:
    assert relation_with_kind("business").kind == "professional"


def test_relation_kind_shields_ui_from_arbitrary_model_category() -> None:
    assert relation_with_kind("unexpected English label").kind == "unknown"
