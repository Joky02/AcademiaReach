from __future__ import annotations

import asyncio
import threading
import unittest
from unittest.mock import patch

from backend.services import reply_tracker


class ReplyTrackerTests(unittest.IsolatedAsyncioTestCase):
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
