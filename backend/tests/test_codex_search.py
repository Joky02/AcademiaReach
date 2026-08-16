from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from backend.agents.search_agent import _save_codex_candidate


class SaveCodexCandidateTests(unittest.IsolatedAsyncioTestCase):
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


if __name__ == "__main__":
    unittest.main()
