from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from backend.services import send_service


class FakeSMTP:
    refused: dict = {}
    last_recipients: list[str] = []
    last_message = ""

    def __init__(self, *args, **kwargs):
        pass

    def login(self, username: str, password: str):
        return None

    def sendmail(self, sender: str, recipients: list[str], message: str):
        type(self).last_recipients = recipients
        type(self).last_message = message
        return type(self).refused

    def quit(self):
        return None


class SendEmailTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        FakeSMTP.refused = {}
        FakeSMTP.last_recipients = []
        FakeSMTP.last_message = ""

    async def _send(self, include_cc: bool = False):
        draft = {
            "id": 7,
            "status": "pending",
            "professor_email": "professor@example.edu",
            "subject": "PhD application",
            "body": "Hello",
            "language": "en",
        }
        smtp = {
            "host": "smtp.gmail.com",
            "port": 465,
            "username": "sender@gmail.com",
            "password": "app-password",
            "use_tls": False,
            "from_name": "Applicant Name",
            "cc": "archive@example.edu",
        }
        with (
            patch.object(send_service.db, "get_draft", AsyncMock(return_value=draft)),
            patch.object(send_service.db, "update_draft", AsyncMock()) as update_draft,
            patch.object(send_service, "_get_smtp_config", return_value=smtp),
            patch.object(send_service, "_get_cv_path", return_value=None),
            patch.object(send_service, "_get_transcript_path", return_value=None),
            patch.object(send_service, "_get_papers", return_value=[]),
            patch.object(send_service, "create_smtp_client", return_value=FakeSMTP()),
        ):
            result = await send_service.send_email(7, include_cc=include_cc)
        return result, update_draft

    async def test_sends_to_professor_and_default_cc(self):
        result, update_draft = await self._send(include_cc=True)

        self.assertTrue(result["success"])
        self.assertEqual(
            FakeSMTP.last_recipients,
            ["professor@example.edu", "archive@example.edu"],
        )
        self.assertIn("Cc: archive@example.edu", FakeSMTP.last_message)
        self.assertIn("From: Applicant Name <sender@gmail.com>", FakeSMTP.last_message)
        update_draft.assert_awaited_once()

    async def test_does_not_cc_unless_requested(self):
        result, update_draft = await self._send()

        self.assertTrue(result["success"])
        self.assertEqual(FakeSMTP.last_recipients, ["professor@example.edu"])
        self.assertNotIn("Cc:", FakeSMTP.last_message)
        update_draft.assert_awaited_once()

    async def test_does_not_mark_sent_when_professor_is_refused(self):
        FakeSMTP.refused = {"professor@example.edu": (550, b"rejected")}

        result, update_draft = await self._send()

        self.assertFalse(result["success"])
        update_draft.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
