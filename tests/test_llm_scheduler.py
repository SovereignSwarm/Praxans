"""Tests for the multi-channel LLM scheduler."""

import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from llm.scheduler import LLMScheduler, LLMJob, ChannelStatus


class _FakeClient:
    """Minimal OllamaClient stand-in for testing."""

    available = True
    seed = None

    def __init__(self, delay: float = 0.0, fail: bool = False):
        self._delay = delay
        self._fail = fail
        self.call_count = 0

    def detect_model(self):
        return "test-model"

    def generate(self, prompt, channel="council", options=None):
        self.call_count += 1
        if self._delay:
            time.sleep(self._delay)
        if self._fail:
            raise RuntimeError("fake error")
        return f"response-{self.call_count}", "test-model"


class SchedulerBasicTests(unittest.TestCase):
    def test_submit_and_poll_success(self):
        client = _FakeClient()
        sched = LLMScheduler(client, max_concurrent=2)

        ok = sched.submit("council", "test prompt", priority=5, stale_key="c1")
        self.assertTrue(ok)

        # Wait for completion
        time.sleep(0.2)
        completed = sched.poll()
        self.assertEqual(len(completed), 1)
        self.assertTrue(completed[0].succeeded)
        self.assertIn("response", completed[0].response_text)

    def test_submit_unavailable_client(self):
        client = _FakeClient()
        client.available = False
        sched = LLMScheduler(client)
        self.assertFalse(sched.submit("council", "test"))

    def test_unknown_channel_rejected(self):
        client = _FakeClient()
        sched = LLMScheduler(client)
        self.assertFalse(sched.submit("invalid_channel", "test"))

    def test_max_concurrent_enforced(self):
        client = _FakeClient(delay=0.5)
        sched = LLMScheduler(client, max_concurrent=2)

        # Submit 3 jobs on different channels
        sched.submit("council", "p1", priority=5, stale_key="c1")
        sched.submit("faction_leaders", "p2", priority=5, stale_key="f1")
        sched.submit("historian", "p3", priority=5, stale_key="h1")

        time.sleep(0.05)
        # Only 2 should be active
        active = sched.get_active_channels()
        self.assertLessEqual(len(active), 2)

        # Wait for all to finish
        time.sleep(1.0)
        completed = sched.poll()
        self.assertGreaterEqual(len(completed), 2)

    def test_stale_collapse(self):
        client = _FakeClient(delay=0.3)
        sched = LLMScheduler(client, max_concurrent=1)

        # First job starts
        sched.submit("council", "old", priority=5, stale_key="council_v1")
        time.sleep(0.05)

        # Queue replacement while first is running
        sched.submit("council", "new", priority=5, stale_key="council_v2")

        # Wait for first to finish
        time.sleep(0.5)
        completed = sched.poll()
        self.assertEqual(len(completed), 1)

        # Wait for queued (replacement) to finish
        time.sleep(0.5)
        completed2 = sched.poll()
        self.assertEqual(len(completed2), 1)

    def test_per_channel_cooldown_on_failure(self):
        client = _FakeClient(fail=True)
        sched = LLMScheduler(client, max_concurrent=2, default_backoff=1.0)

        sched.submit("council", "test", priority=5, stale_key="c1")
        time.sleep(0.2)
        sched.poll()

        # Should be in cooldown now
        status = sched.get_channel_status("council")
        self.assertTrue(status.in_cooldown)
        self.assertFalse(sched.submit("council", "retry"))

        # But other channels should work
        self.assertTrue(sched.submit("historian", "test2"))

    def test_channel_status_tracking(self):
        client = _FakeClient()
        sched = LLMScheduler(client)

        sched.submit("council", "test", priority=5, stale_key="c1")
        time.sleep(0.2)
        sched.poll()

        status = sched.get_channel_status("council")
        self.assertEqual(status.total_requests, 1)
        self.assertEqual(status.total_successes, 1)
        self.assertEqual(status.total_errors, 0)

    def test_get_stats(self):
        client = _FakeClient()
        sched = LLMScheduler(client)

        sched.submit("council", "test")
        time.sleep(0.2)
        sched.poll()

        stats = sched.get_stats()
        self.assertIn("council", stats)
        self.assertEqual(stats["council"]["total_requests"], 1)

    def test_priority_ordering(self):
        client = _FakeClient(delay=0.3)
        sched = LLMScheduler(client, max_concurrent=1)

        # Start one job to fill the slot
        sched.submit("council", "blocking", priority=1, stale_key="block")
        time.sleep(0.05)

        # Queue low and high priority on different channels
        sched.submit("historian", "low-pri", priority=1, stale_key="h1")
        sched.submit("faction_leaders", "high-pri", priority=10, stale_key="f1")

        # Wait for blocking to finish
        time.sleep(0.5)
        sched.poll()

        # High-priority should start first
        active = sched.get_active_channels()
        if active:
            self.assertIn("faction_leaders", active)


if __name__ == "__main__":
    unittest.main()
