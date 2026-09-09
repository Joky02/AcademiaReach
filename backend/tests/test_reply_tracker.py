from __future__ import annotations

import asyncio
import threading
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from backend.services import reply_tracker


class ReplyTrackerTests(unittest.IsolatedAsyncioTestCase):
    def test_base_subject_handles_common_reply_prefixes(self):
        self.assertEqual(
            reply_tracker._base_subject("Re: RE： 2027 PhD Application: Reliable Agents"),
            "2027 phd application: reliable agents",
        )
        self.assertEqual(
            reply_tracker._base_subject("回复：博士申请咨询：可靠智能体"),
            "博士申请咨询：可靠智能体",
        )

    def test_extracts_message_numbers_from_batched_fetch(self):
        payloads = reply_tracker._message_payloads([
            (b"41 (BODY[HEADER.FIELDS (SUBJECT)] {20}", b"Subject: Re: Hello\r\n\r\n"),
            b")",
            (b"42 (BODY[HEADER.FIELDS (SUBJECT)] {18}", b"Subject: Re: Hi\r\n\r\n"),
        ])
        self.assertEqual([number for number, _ in payloads], [b"41", b"42"])

    def test_imap_scan_starts_before_earliest_sent_draft(self):
        sent_at = (datetime.utcnow() - timedelta(days=20)).isoformat()
        since = datetime.strptime(
            reply_tracker._imap_since_date([{"sent_at": sent_at}]),
            "%d-%b-%Y",
        )
        self.assertGreaterEqual(since, datetime.utcnow() - timedelta(days=28))
        self.assertLessEqual(since, datetime.utcnow() - timedelta(days=26))

    async def test_check_replies_runs_outside_event_loop_thread(self):
        event_loop_thread = threading.get_ident()

        def fake_run_reply_check():
            return threading.get_ident()

        with patch.object(reply_tracker, "_run_reply_check", side_effect=fake_run_reply_check):
            worker_thread = await reply_tracker.check_replies()

        self.assertNotEqual(worker_thread, event_loop_thread)

    async def test_event_loop_remains_responsive_during_reply_check(self):
        started = threading.Event()
        release = threading.Event()

        def fake_run_reply_check():
            started.set()
            release.wait(timeout=1)
            return []

        with patch.object(reply_tracker, "_run_reply_check", side_effect=fake_run_reply_check):
            task = asyncio.create_task(reply_tracker.check_replies())
            await asyncio.to_thread(started.wait, 1)
            await asyncio.wait_for(asyncio.sleep(0), timeout=0.1)
            release.set()
            self.assertEqual(await task, [])


if __name__ == "__main__":
    unittest.main()
