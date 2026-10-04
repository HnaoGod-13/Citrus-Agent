from agent.evidence import (
    clean_source_text,
    clean_source_title,
    source_text_for_display,
)
from agent.rag import format_evidence_context


def test_source_title_drops_appended_chinese_filename_translation():
    title = (
        "The residual behavior and processing factors of abamectin and fluazinam "
        "in citrus juice processing.【中文 阿维菌素和氟啶胺在"
    )
    assert clean_source_title(title) == (
        "The residual behavior and processing factors of abamectin and fluazinam "
        "in citrus juice processing"
    )


def test_source_text_removes_metadata_and_repairs_display_boundaries():
    raw = "serial JL 272552 articleinfo contenttype FULL-TEXT 1.5.2 10mL柑橘juice"
    assert clean_source_text(raw) == ""
    assert clean_source_text("采用 10mL柑橘juice。") == "采用 10 mL 柑橘 juice。"


def test_source_text_merges_same_document_adjacent_chunks_without_cross_document_leakage():
    item = {
        "document_id": "paper-1",
        "chunk_index": 3,
        "chunk_text": "The method used 60 °C for 30 min",
        "adjacent_chunks": [
            {
                "document_id": "paper-1",
                "chunk_index": 2,
                "chunk_text": "Materials were washed before treatment. ",
            },
            {
                "document_id": "paper-2",
                "chunk_index": 4,
                "chunk_text": "This unrelated text must not be shown.",
            },
            {
                "document_id": "paper-1",
                "chunk_index": 4,
                "chunk_text": " and cooled immediately.",
            },
        ],
    }
    display = source_text_for_display(item)
    assert display.startswith("Materials were washed before treatment.")
    assert "cooled immediately" in display
    assert "unrelated text" not in display


def test_source_text_drops_a_cut_off_leading_clause_when_no_context_exists():
    display = source_text_for_display(
        {
            "document_id": "paper-1",
            "chunk_text": "00 g magnesium sulfate was added. The extract was filtered.",
        }
    )
    assert display == "The extract was filtered."


def test_source_text_focuses_a_complete_sentence_for_retrieved_terms():
    display = source_text_for_display(
        {
            "document_id": "paper-1",
            "chunk_text": "Citation metadata. The treatment reduced residue by 30%. Further context follows.",
            "matched_terms": ["residue"],
        },
        focus_terms=["residue"],
    )
    assert display == "The treatment reduced residue by 30%. Further context follows."


def test_llm_evidence_context_uses_clean_bibliographic_display_fields():
    rendered = format_evidence_context(
        [
            {
                "title": "Paper title.【中文 中文翻译",
                "year": "2024",
                "section": "Results",
                "chunk_text": "The result improved at 1. 5 mg.",
            }
        ]
    )
    assert "Paper title" in rendered
    assert "【中文" not in rendered
    assert "1.5 mg" in rendered
