from __future__ import annotations

import unittest

from backend.agents.compose_agent import (
    _ensure_explicit_paper_opening,
    _format_chinese_email_body,
    _render_english_email,
    _validate_chinese_email_body,
    _validate_english_email_body,
)


class ComposeRenderTests(unittest.TestCase):
    def test_normalizes_common_paper_openings_without_repeating_title(self):
        title = "Machine Behaviour"
        variants = [
            "Machine Behaviour provides a useful framing.",
            'Your 2019 paper, \u201cMachine Behaviour,\u201d provides a useful framing.',
            "The ACL 2019 paper Machine Behaviour provides a useful framing.",
            'In \u201cMachine Behaviour,\u201d the authors provide a useful framing.',
        ]

        for paragraph in variants:
            with self.subTest(paragraph=paragraph):
                result = _ensure_explicit_paper_opening(title, paragraph)
                self.assertTrue(
                    result.startswith('I recently read your paper, "Machine Behaviour."')
                )
                self.assertEqual(result.count(title), 1)

    def test_preserves_an_already_explicit_paper_opening(self):
        paragraph = (
            'I recently read your paper, "Machine Behaviour." '
            "The paper provides a useful framing."
        )
        self.assertEqual(
            _ensure_explicit_paper_opening("Machine Behaviour", paragraph),
            paragraph,
        )

    def test_renders_dynamic_subject_and_four_paragraph_body(self):
        template = """Subject: {{ subject }}

Dear Professor {{ professor_salutation }},

Fixed introduction.

{{ representative_work_paragraph }}

{{ background_bridge_paragraph }}

{{ fit_close_paragraph }}

Best regards,
Applicant"""
        subject, body = _render_english_email(
            template,
            {
                "subject": "2027 PhD Application: From Cooperation to Agent Organizations",
                "salutation": "Professor Rahwan,",
                "representative_work_title": "Machine Behaviour",
                "representative_work_paragraph": "Machine Behaviour provides a useful framing for studying intelligent systems.",
                "background_bridge_paragraph": "My optimization background supports this question.",
                "fit_close_paragraph": "My CV is attached. Thank you for considering whether I could fit your group.",
            },
            "Iyad Rahwan",
        )

        self.assertEqual(
            subject,
            "2027 PhD Application: From Cooperation to Agent Organizations",
        )
        self.assertIn("Dear Professor Rahwan,", body)
        self.assertEqual(len(body.split("\n\n")), 6)
        self.assertIn(
            'I recently read your paper, "Machine Behaviour." The paper provides',
            body,
        )
        self.assertNotIn("{{", body)

    def test_rejects_missing_dynamic_subject(self):
        with self.assertRaisesRegex(ValueError, "个性化主题"):
            _render_english_email(
                "Subject: {{ subject }}\n\nDear Professor {{ professor_salutation }},\n\n"
                "{{ representative_work_paragraph }}\n\n"
                "{{ background_bridge_paragraph }}\n\n{{ fit_close_paragraph }}",
                {
                    "subject": "",
                    "salutation": "Rahwan",
                    "representative_work_title": "Machine Behaviour",
                    "representative_work_paragraph": "Paper paragraph.",
                    "background_bridge_paragraph": "Background paragraph.",
                    "fit_close_paragraph": "Closing paragraph.",
                },
                "Iyad Rahwan",
            )

    def test_validates_traceable_english_paper_and_signature(self):
        body = """Dear Professor Rahwan,

Fixed introduction with a first-authored paper accepted at a major conference.

I recently read your paper, "Machine Behaviour." The paper provides a verified framing. I would like to explore a related question.

During an industry internship, I built an LLM-agent workflow.

My CV is attached. Thank you for considering whether I could fit your group.

Best regards,
Applicant"""
        professor = {"recommended_papers": [{"title": "Machine Behaviour"}]}
        _validate_english_email_body(body, professor)

        with self.assertRaisesRegex(ValueError, "邮箱"):
            _validate_english_email_body(
                body.replace("Applicant", "Applicant\nEmail: applicant@example.edu"),
                professor,
            )

    def test_validates_chinese_structure_and_recommendation_title(self):
        raw = """第一段。

第二段。

我最近读了您参与的《准确论文标题》，并关注其中经核验的问题。我想进一步探讨一个相关方向，希望能和老师交流。

随信附上我的简历，供您参考。申请人"""
        body = _format_chinese_email_body(raw, "黄民烈")
        professor = {
            "name": "黄民烈",
            "recommended_papers": [{"title": "准确论文标题"}],
        }
        _validate_chinese_email_body(body, professor)

        with self.assertRaisesRegex(ValueError, "推荐论文标题"):
            _validate_chinese_email_body(
                body.replace("准确论文标题", "被改写的标题"),
                professor,
            )


if __name__ == "__main__":
    unittest.main()
