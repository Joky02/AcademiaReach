from __future__ import annotations

import json
import unittest

from backend.services.draft_review import rank_drafts, score_draft


class DraftReviewTests(unittest.TestCase):
    def _row(self, **overrides):
        paper = {
            "title": "Machine behaviour",
            "venue": "Nature",
            "year": 2019,
            "citation_count": 1400,
            "url": "https://example.com/paper",
            "why_recommended": "Relevant to agent societies.",
        }
        row = {
            "id": 1,
            "subject": "2027 PhD Application: From Machine Behaviour to Agent Organizations",
            "body": (
                "Dear Professor Rahwan,\n\n"
                "I recently read your paper \"Machine behaviour.\" "
                "It led me to ask whether persistent roles could organize agents. "
                + "This is a concise sentence. " * 45
            ),
            "professor_email": "professor@example.edu",
            "professor_tags": json.dumps([
                "recruiting-explicit",
                "agent society",
                "multi-agent systems",
                "Associate Prof",
            ]),
            "recommended_papers": json.dumps([paper]),
            "research_summary": "LLM agents, collective intelligence, optimization",
            "recent_papers": "Current work on agent organizations",
            "is_starred": 0,
        }
        row.update(overrides)
        return row

    def test_influential_discussed_work_and_recruiting_raise_scores(self):
        scored = score_draft(self._row(), applicant_profile="multi-agent systems and optimization")
        self.assertEqual(scored["selected_paper"]["title"], "Machine behaviour")
        self.assertGreaterEqual(scored["relevance_score"], 80)
        self.assertGreaterEqual(scored["reply_likelihood_score"], 60)

    def test_generic_subject_and_unmatched_work_are_flagged(self):
        scored = score_draft(self._row(
            subject="2027 PhD Application - Applicant Name, Example University",
            body="Dear Professor Rahwan,\n\nI am interested in your research." * 8,
            professor_tags="[]",
        ))
        self.assertIsNone(scored["selected_paper"])
        self.assertIn("正文未匹配到推荐论文标题", scored["cautions"])
        self.assertIn("标题仍偏通用", scored["cautions"])

    def test_rank_drafts_uses_combined_priority(self):
        strong = self._row(id=1)
        weak = self._row(
            id=2,
            subject="PhD Application",
            body="Short generic note",
            professor_tags="[]",
        )
        ranked = rank_drafts(
            [weak, strong],
            applicant_profile="multi-agent systems and optimization",
        )
        self.assertEqual(ranked[0]["id"], 1)

    def test_chinese_drafts_use_character_length_and_chinese_signals(self):
        body = (
            "尊敬的李老师：\n\n"
            "　　我最近读了您参与的《Machine behaviour》，对其中的问题很感兴趣。"
            "我希望进一步探讨相关方向，并与您交流。" * 8
        )
        scored = score_draft(self._row(body=body), applicant_profile="多智能体系统")
        self.assertEqual(scored["length_unit"], "字")
        self.assertGreater(scored["content_length"], 100)


if __name__ == "__main__":
    unittest.main()
