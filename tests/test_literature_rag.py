from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.llm_client import build_general_chat_messages, retrieve_general_literature
from agent.rag import (
    _database_candidates,
    _build_fts_match_query,
    _rank_candidates,
    comprehensive_search_knowledge,
    fetch_adjacent_method_result_chunks,
)
from scripts.build_literature_chunks import (
    SourceDocument,
    _write_document,
    article_to_chunks,
    initialize_database,
)


class LiteratureIngestionTests(unittest.TestCase):
    @staticmethod
    def _write_test_chunks(connection, document_id: str, chunks: list[dict], *, title: str) -> None:
        document = SourceDocument(
            document_id=document_id,
            canonical_path=Path(f"{document_id}.pdf"),
            source_files=(f"橙汁/{document_id}.pdf",),
            categories=("橙汁",),
            fingerprint=f"fingerprint-{document_id}",
        )
        article = {
            "source_type": "pdf",
            "title": title,
            "year": "2025",
            "doi": "",
            "publication": "Test Journal",
            "authors": [],
            "page_count": max(len(chunks), 1),
            "extracted_pages": len(chunks),
            "extracted_chars": sum(len(item["chunk_text"]) for item in chunks),
            "text_quality": "good",
        }
        rows = []
        for index, item in enumerate(chunks, 1):
            rows.append(
                {
                    "chunk_id": item.get("chunk_id") or f"{document_id}-c{index}",
                    "document_id": document_id,
                    "chunk_index": item.get("chunk_index", index),
                    "source_type": "pdf",
                    "source_file": document.source_files[0],
                    "source_files": "[]",
                    "category": "橙汁",
                    "title": title,
                    "year": "2025",
                    "doi": "",
                    "publication": "Test Journal",
                    "page_start": index,
                    "page_end": index,
                    "section": item["section"],
                    "product": "橙汁",
                    "topic": "杀菌",
                    "keywords": "橙汁、杀菌",
                    "chunk_text": item["chunk_text"],
                    "search_terms": "concept_juice concept_citrus orange juice pasteurization citrus",
                    "char_count": len(item["chunk_text"]),
                }
            )
        with connection:
            _write_document(connection, document, article, rows)

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

    def test_deep_candidates_filter_pending_ocr_before_limit_and_backfill(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "literature.db"
            connection = initialize_database(db_path)
            for index in range(4):
                self._write_test_chunks(
                    connection,
                    f"ocr-{index}",
                    [
                        {
                            "section": "题录（待OCR）",
                            "chunk_text": "题名：Orange juice pasteurization。该 PDF 暂未提取到可用正文，不能据此推断研究结果。",
                        }
                    ],
                    title=f"Orange juice pasteurization catalog {index}",
                )
            for index in range(2):
                self._write_test_chunks(
                    connection,
                    f"full-{index}",
                    [
                        {
                            "section": "材料与方法" if index == 0 else "结果",
                            "chunk_text": "Orange juice pasteurization used a documented thermal method and reported microbial results.",
                        }
                    ],
                    title=f"Orange juice thermal processing {index}",
                )
            connection.close()
            stats: dict = {}
            candidates = _database_candidates(
                "orange juice pasteurization",
                None,
                2,
                db_path,
                category_filter="橙汁",
                retrieval_mode="deep",
                stats=stats,
            )

        self.assertEqual(len(candidates), 2)
        self.assertTrue(all(item["section"] != "题录（待OCR）" for item in candidates))
        self.assertEqual({item["document_id"] for item in candidates}, {"full-0", "full-1"})
        self.assertEqual(stats["fts_rows_returned"], 2)

    def test_deep_search_expands_candidates_but_preserves_public_top_k(self) -> None:
        calls: list[tuple[str, int]] = []

        def fake_single(query, product_filter, limit, category_filter=None, *, retrieval_mode="quick", stats=None):
            calls.append((retrieval_mode, limit))
            return [
                {
                    "chunk_id": f"chunk-{index}",
                    "document_id": f"document-{index}",
                    "title": "Citrus juice processing",
                    "chunk_text": "Orange juice method and results.",
                    "match_score": 90 - index,
                }
                for index in range(10)
            ]

        with patch("agent.rag._single_query_search", side_effect=fake_single):
            quick = comprehensive_search_knowledge("orange juice", top_k=5)
            deep = comprehensive_search_knowledge(
                "orange juice",
                top_k=5,
                retrieval_mode="deep",
                return_metadata=True,
            )

        self.assertIsInstance(quick, list)
        self.assertEqual(len(quick), 5)
        self.assertEqual(len(deep["evidence"]), 5)
        self.assertGreater(calls[1][1], calls[0][1])
        self.assertEqual(deep["deep_retrieval_stats"]["retrieval_mode"], "deep")
        self.assertEqual(deep["deep_retrieval_stats"]["selected_count"], 5)
        self.assertGreater(deep["deep_retrieval_stats"]["library_document_count"], 0)
        self.assertGreater(deep["deep_retrieval_stats"]["library_chunk_count"], 0)

    def test_deep_search_does_not_fall_back_when_full_index_is_unavailable(self) -> None:
        fallback = {
            "chunk_id": "legacy-1",
            "document_id": "legacy-document",
            "title": "Legacy orange juice note",
            "chunk_text": "Orange juice pasteurization at 80 C.",
            "match_score": 99,
        }

        def unavailable_database(*args, stats=None, **kwargs):
            if stats is not None:
                stats["database_available"] = False
                stats["retrieval_complete"] = False
                stats["retrieval_error"] = "全库文献索引未能加载，本轮未执行全库深度检索。"
            return []

        with (
            patch("agent.rag._database_candidates", side_effect=unavailable_database),
            patch("agent.rag._legacy_candidates", return_value=[fallback]) as legacy_search,
        ):
            result = comprehensive_search_knowledge(
                "orange juice pasteurization",
                top_k=5,
                retrieval_mode="deep",
                return_metadata=True,
            )

        self.assertEqual(result["evidence"], [])
        self.assertFalse(result["deep_retrieval_stats"]["database_available"])
        self.assertFalse(result["deep_retrieval_stats"]["retrieval_complete"])
        self.assertIn("未能加载", result["deep_retrieval_stats"]["retrieval_error"])
        legacy_search.assert_not_called()

    def test_deep_match_query_uses_product_anchor_and_specific_focus_not_generic_or_pool(self) -> None:
        query = (
            "orange juice materials methods results quality temperature time "
            "washing juicing deaeration filling pasteurization"
        )
        quick_match = _build_fts_match_query(query, "quick").lower()
        deep_match = _build_fts_match_query(query, "deep").lower()

        self.assertIn(" or ", quick_match)
        self.assertIn(" and ", deep_match)
        self.assertIn("concept_juice", deep_match)
        self.assertIn("pasteurization", deep_match)
        self.assertIn("filling", deep_match)
        self.assertIn(
            "deaeration",
            _build_fts_match_query("orange juice materials methods deaeration", "deep").lower(),
        )
        operation_match = _build_fts_match_query(
            "orange juice deaeration pressure flow temperature time",
            "deep",
        ).lower()
        self.assertIn("deaeration", operation_match)
        self.assertNotIn('"pressure"', operation_match)
        self.assertNotIn('"flow"', operation_match)
        for generic in ("materials", "methods", "results", "quality", "temperature", "time"):
            self.assertNotIn(f'"{generic}"', deep_match)

    def test_adjacent_context_stays_in_document_and_method_result_sections(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "literature.db"
            connection = initialize_database(db_path)
            self._write_test_chunks(
                connection,
                "target",
                [
                    {"chunk_id": "target-c1", "section": "材料与方法", "chunk_text": "Orange juice was homogenized before filling."},
                    {"chunk_id": "target-c2", "section": "引言", "chunk_text": "Orange juice background."},
                    {"chunk_id": "target-c3", "section": "结果", "chunk_text": "The treatment improved orange juice stability."},
                    {"chunk_id": "target-c4", "section": "结论", "chunk_text": "Far conclusion."},
                ],
                title="Orange juice homogenization",
            )
            self._write_test_chunks(
                connection,
                "other",
                [{"chunk_id": "other-c1", "section": "结果", "chunk_text": "Other orange juice result."}],
                title="Other orange juice paper",
            )
            connection.close()
            payload = fetch_adjacent_method_result_chunks(
                [{"chunk_id": "target-c2", "document_id": "target", "chunk_index": 2}],
                db_path=db_path,
                radius=1,
                per_hit=3,
                limit=3,
                return_metadata=True,
            )

        neighbors = payload["adjacent_chunks"]["target-c2"]
        self.assertEqual({item["chunk_id"] for item in neighbors}, {"target-c1", "target-c3"})
        self.assertTrue(all(item["document_id"] == "target" for item in neighbors))
        self.assertEqual(payload["deep_retrieval_stats"]["adjacent_added_count"], 2)


class LiteraturePromptTests(unittest.TestCase):
    @patch("agent.llm_client.comprehensive_search_knowledge")
    def test_deep_follow_up_reuses_previous_domain_question(self, search_mock) -> None:
        search_mock.return_value = {"evidence": [], "deep_retrieval_stats": {}}

        retrieve_general_literature(
            "有证据吗？",
            history=[{"role": "user", "content": "橙汁脱气需要控制哪些参数？"}],
            retrieval_mode="deep",
            return_metadata=True,
        )

        self.assertEqual(search_mock.call_count, 1)
        query = search_mock.call_args.args[0]
        self.assertIn("橙汁脱气", query)
        self.assertIn("有证据吗", query)

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
