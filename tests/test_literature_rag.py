from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.llm_client import build_general_chat_messages
from agent.rag import _database_candidates, _rank_candidates
from scripts.build_literature_chunks import (
    SourceDocument,
    _write_document,
    article_to_chunks,
    initialize_database,
)


class LiteratureIngestionTests(unittest.TestCase):
    def test_section_aware_chunks_keep_page_and_drop_references(self) -> None:
        document = SourceDocument(
            document_id="demo-paper",
            canonical_path=Path("demo.pdf"),
            source_files=("果胶/demo.pdf",),
            categories=("果胶",),
            fingerprint="fingerprint",
        )
        article = {
            "source_type": "pdf",
            "title": "Pectin extraction from citrus peel",
            "year": "2025",
            "doi": "10.1000/demo",
            "publication": "Demo Journal",
            "authors": [],
            "page_count": 2,
            "extracted_pages": 2,
            "extracted_chars": 1200,
            "text_quality": "good",
            "page_texts": [
                {
                    "page": 1,
                    "text": "Abstract\nCitrus peel pectin extraction increased galacturonic acid yield under the tested conditions. " * 8,
                },
                {
                    "page": 2,
                    "text": "Conclusion\nThe optimized extract had improved gel strength.\nReferences\nSmith et al. 2020. doi:10.1000/ref",
                },
            ],
        }
        chunks = article_to_chunks(document, article, chunk_chars=500, overlap_chars=80)
        self.assertGreaterEqual(len(chunks), 2)
        self.assertTrue(all(item["page_start"] in {1, 2} for item in chunks))
        self.assertTrue(any(item["section"] == "结论" for item in chunks))
        self.assertNotIn("Smith et al.", " ".join(item["chunk_text"] for item in chunks))

    def test_sqlite_fts_retrieves_and_reranks_a_relevant_chunk(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "literature.db"
            connection = initialize_database(db_path)
            document = SourceDocument(
                document_id="juice-paper",
                canonical_path=Path("juice.pdf"),
                source_files=("橙汁/juice.pdf",),
                categories=("橙汁",),
                fingerprint="fingerprint",
            )
            article = {
                "source_type": "pdf",
                "title": "Orange juice pasteurization and vitamin C retention",
                "year": "2024",
                "doi": "10.1000/juice",
                "publication": "Food Journal",
                "authors": [],
                "page_count": 1,
                "extracted_pages": 1,
                "extracted_chars": 900,
                "text_quality": "good",
                "page_texts": [
                    {
                        "page": 1,
                        "text": "Results\nOrange juice pasteurization temperature affected vitamin C retention and microbial stability. " * 8,
                    }
                ],
            }
            chunks = article_to_chunks(document, article, chunk_chars=600, overlap_chars=80)
            with connection:
                _write_document(connection, document, article, chunks)
            connection.close()

            candidates = _database_candidates("orange juice vitamin retention", None, 20, db_path)
            ranked = _rank_candidates("orange juice vitamin retention", candidates, None)
            self.assertTrue(ranked)
            self.assertEqual(ranked[0]["document_id"], "juice-paper")
            self.assertEqual(ranked[0]["page"], 1)


class LiteraturePromptTests(unittest.TestCase):
    @patch("agent.llm_client.comprehensive_search_knowledge")
    def test_domain_answer_receives_numbered_literature_context(self, search_mock) -> None:
        search_mock.return_value = [
            {
                "title": "Chenpi storage study",
                "year": "2025",
                "category": "陈皮",
                "section": "结论",
                "page": 9,
                "doi": "10.1000/chenpi",
                "chunk_text": "Storage conditions changed the measured flavonoid profile.",
            }
        ]
        messages = build_general_chat_messages([], "陈皮陈化时需要关注什么？")
        combined = "\n".join(item["content"] for item in messages)
        self.assertIn("[文献1]", combined)
        self.assertIn("第9页", combined)
        self.assertIn("体外、动物", messages[0]["content"])


if __name__ == "__main__":
    unittest.main()
