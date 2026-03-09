import unittest
from unittest import mock

from events.bus import EventBus, GameEvent


class EventBusLoggingTests(unittest.TestCase):
    def test_publish_logs_and_continues_after_category_subscriber_exception(self):
        bus = EventBus()
        delivered = []

        def broken_handler(_event):
            raise RuntimeError("boom")

        def healthy_handler(event):
            delivered.append(event.summary)

        bus.subscribe("trade", broken_handler)
        bus.subscribe("trade", healthy_handler)

        with mock.patch("events.bus._logger") as logger_mock:
            bus.publish(GameEvent(category="trade", summary="Trade route opened"))

        self.assertEqual(delivered, ["Trade route opened"])
        logger_mock.warning.assert_called_once()
        log_message = logger_mock.warning.call_args.args[0]
        self.assertIn("Category subscriber failed", log_message)

    def test_publish_logs_wildcard_subscriber_exception(self):
        bus = EventBus()

        def broken_handler(_event):
            raise RuntimeError("boom")

        bus.subscribe("*", broken_handler)

        with mock.patch("events.bus._logger") as logger_mock:
            bus.publish(GameEvent(category="birth", summary="New praxan"))

        logger_mock.warning.assert_called_once()
        log_message = logger_mock.warning.call_args.args[0]
        self.assertIn("Wildcard subscriber failed", log_message)


if __name__ == "__main__":
    unittest.main()
