from __future__ import annotations

import json
import unittest

from backend.core.database import _merged_professor_update, _same_named_institution


class DatabaseDedupeTests(unittest.TestCase):
    def test_matches_chinese_name_with_same_institutional_email_domain(self) -> None:
        self.assertTrue(
            _same_named_institution(
                {"name": "示例教授", "email": "first@example.edu.cn"},
                {"name": "示例教授", "email": "second@example.edu.cn"},
            )
        )

    def test_does_not_match_public_email_or_romanized_name(self) -> None:
        self.assertFalse(
            _same_named_institution(
                {"name": "示例教授", "email": "first@gmail.com"},
                {"name": "示例教授", "email": "second@gmail.com"},
            )
        )
        self.assertFalse(
            _same_named_institution(
                {"name": "Wei Wang", "email": "first@example.edu"},
                {"name": "Wei Wang", "email": "second@example.edu"},
            )
        )

    def test_merge_keeps_personalized_recommendations_from_enrichment(self) -> None:
        recommendation = [{
            "title": "Verified Paper",
            "url": "https://example.edu/paper",
            "why_recommended": "Relevant to the applicant.",
        }]
        update = _merged_professor_update(
            {"recommended_papers": "[]", "tags": "[]"},
            {
                "recommended_papers": json.dumps(recommendation),
                "tags": "[]",
            },
        )

        self.assertEqual(
            json.loads(update["recommended_papers"]),
            recommendation,
        )


if __name__ == "__main__":
    unittest.main()
