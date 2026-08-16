from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock, patch

from backend.agents.search_agent import (
    _codex_search_batch_specs,
    _new_professor_tags,
    _normalize_recommended_papers,
    _save_codex_candidate,
    _search_professors_codex,
)


class SaveCodexCandidateTests(unittest.IsolatedAsyncioTestCase):
    def test_new_professor_tag_is_persistent_and_preserves_other_tags(self) -> None:
        tags = json.loads(_new_professor_tags('["Fellow", "新"]'))

        self.assertEqual(tags, ["新", "Fellow"])

    def test_batch_specs_split_large_search_into_narrow_lanes(self) -> None:
        specs = _codex_search_batch_specs(
            ["LLM", "AI4Science"],
            ["Hong Kong", "Singapore"],
            max_results=8,
            batch_size=3,
        )

        self.assertEqual([spec["target"] for spec in specs], [3, 3, 2])
        self.assertIn("Hong Kong", specs[0]["focus"])
        self.assertIn("Singapore", specs[1]["focus"])
        self.assertNotEqual(specs[0]["focus"], specs[2]["focus"])

    def test_recommended_papers_require_verified_links_and_are_deduplicated(self) -> None:
        papers = _normalize_recommended_papers([
            {
                "title": "A Relevant Paper",
                "venue": "KDD",
                "year": "2024",
                "citation_count": "1,234 citations",
                "url": "https://example.edu/paper",
                "why_recommended": "与申请者的优化研究方向直接相关。",
            },
            {
                "title": "A Relevant Paper",
                "url": "https://example.edu/duplicate",
                "why_recommended": "duplicate",
            },
            {
                "title": "Unverified Paper",
                "url": "",
                "why_recommended": "missing source",
            },
        ])

        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0]["year"], 2024)
        self.assertEqual(papers[0]["citation_count"], 1234)

    async def test_rejects_candidate_without_public_source(self) -> None:
        candidate = {
            "name": "Example Professor",
            "university": "Example University",
            "region": "Singapore",
            "sources": [],
        }

        with patch(
            "backend.agents.search_agent.db.is_blacklisted",
            new=AsyncMock(return_value=False),
        ), patch(
            "backend.agents.search_agent.db.create_professor",
            new=AsyncMock(),
        ) as create_professor:
            message, saved = await _save_codex_candidate(candidate)

        self.assertIn("缺少可核验的公开来源", message)
        self.assertIsNone(saved)
        create_professor.assert_not_awaited()

    async def test_normalizes_obfuscated_email_before_saving(self) -> None:
        candidate = {
            "name": "Example Professor",
            "university": "Example University",
            "region": "Singapore",
            "email": "person {at} example {dot} edu",
            "homepage": "https://example.edu/person",
            "google_scholar": "",
            "department": "Computer Science",
            "research_summary": "Machine learning.",
            "recent_papers": "A verified paper.",
            "recommended_papers": [{
                "title": "A Relevant Paper",
                "venue": "KDD",
                "year": 2024,
                "citation_count": 123,
                "url": "https://example.edu/paper",
                "why_recommended": "Relevant to the applicant profile.",
            }],
            "tags": ["machine learning"],
            "sources": ["https://example.edu/person"],
        }

        async def create(data: dict) -> dict:
            return {**data, "id": 1}

        with patch(
            "backend.agents.search_agent.db.is_blacklisted",
            new=AsyncMock(return_value=False),
        ), patch(
            "backend.agents.search_agent.db.find_existing_professor_match",
            new=AsyncMock(return_value=None),
        ), patch(
            "backend.agents.search_agent.db.create_professor",
            new=AsyncMock(side_effect=create),
        ) as create_professor:
            _, saved = await _save_codex_candidate(candidate)

        self.assertIsNotNone(saved)
        self.assertEqual(saved["email"], "person@example.edu")
        self.assertEqual(
            create_professor.await_args.args[0]["email"],
            "person@example.edu",
        )
        self.assertEqual(
            json.loads(create_professor.await_args.args[0]["tags"]),
            ["新", "machine learning"],
        )
        self.assertEqual(
            json.loads(
                create_professor.await_args.args[0]["recommended_papers"]
            )[0]["title"],
            "A Relevant Paper",
        )

    async def test_codex_search_saves_each_completed_batch(self) -> None:
        stream_calls: list[dict] = []

        async def stream(**kwargs):
            stream_calls.append(kwargs)
            batch_number = len(stream_calls)
            yield {
                "type": "result",
                "data": {
                    "candidates": [
                        {
                            "name": f"Professor {batch_number}",
                            "university": "Example University",
                        }
                    ],
                    "summary": f"batch {batch_number} done",
                },
            }

        async def save(candidate: dict):
            return (
                f"saved {candidate['name']}",
                {"id": len(candidate["name"]), **candidate},
            )

        with (
            patch(
                "backend.agents.search_agent.load_yaml_config",
                return_value={
                    "llm": {"codex": {"model": ""}},
                    "search": {
                        "codex": {
                            "batch_size": 2,
                            "parallel_batches": 2,
                            "timeout_seconds": 900,
                        }
                    },
                },
            ),
            patch(
                "backend.agents.search_agent._build_codex_search_prompt",
                new=AsyncMock(return_value="prompt"),
            ),
            patch(
                "backend.agents.search_agent.stream_agent_task",
                new=stream,
            ),
            patch(
                "backend.agents.search_agent._save_codex_candidate",
                new=AsyncMock(side_effect=save),
            ),
            patch(
                "backend.agents.search_agent.db.get_professors",
                new=AsyncMock(return_value=[]),
            ),
        ):
            messages = [
                message
                async for message in _search_professors_codex(max_results=4)
            ]

        professor_messages = [
            message for message in messages if message["type"] == "professor"
        ]
        self.assertEqual(len(professor_messages), 2)
        self.assertEqual(len(stream_calls), 2)
        self.assertTrue(all(call["backend"] == "codex" for call in stream_calls))
        self.assertTrue(
            all(call["timeout_seconds"] == 180 for call in stream_calls)
        )
        self.assertEqual(messages[-1]["type"], "done")


if __name__ == "__main__":
    unittest.main()
