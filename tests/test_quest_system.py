"""Regression tests for the quest system."""
import time
import unittest
from systems.quests import (
    Quest, QuestNode, QuestManager,
    QUEST_HIDDEN, QUEST_AVAILABLE, QUEST_ACTIVE, QUEST_COMPLETED, QUEST_FAILED,
)


class StartQuestTests(unittest.TestCase):
    """Regression: start_quest must activate hidden quests (was silently no-op)."""

    def _make_manager_with_quest(self, quest_id="q_test"):
        qm = QuestManager()
        q = Quest(quest_id, "Test Quest")
        q.add_node(QuestNode("step1", "Do something", condition_fn=lambda gs: False), is_start=True)
        q.nodes["step1"].next_on_success = "__COMPLETE__"
        qm.register_quest(q)
        return qm, q

    def test_start_quest_activates_hidden_quest(self):
        """start_quest must succeed even when quest is QUEST_HIDDEN (the registered default)."""
        qm, q = self._make_manager_with_quest()
        self.assertEqual(q.state, QUEST_HIDDEN)
        qm.start_quest("q_test")
        self.assertEqual(q.state, QUEST_ACTIVE, "Quest should be ACTIVE after start_quest")
        self.assertEqual(q.current_node_id, "step1")

    def test_start_quest_on_available_quest(self):
        """start_quest also works when quest is already QUEST_AVAILABLE."""
        qm, q = self._make_manager_with_quest()
        qm.make_available("q_test")
        self.assertEqual(q.state, QUEST_AVAILABLE)
        qm.start_quest("q_test")
        self.assertEqual(q.state, QUEST_ACTIVE)

    def test_start_quest_does_not_restart_active_quest(self):
        """Calling start_quest a second time on an already-active quest is a no-op."""
        qm, q = self._make_manager_with_quest()
        qm.start_quest("q_test")
        first_node_started_at = q.nodes["step1"].started_at
        time.sleep(0.01)
        qm.start_quest("q_test")  # second call
        self.assertEqual(q.state, QUEST_ACTIVE)
        self.assertAlmostEqual(q.nodes["step1"].started_at, first_node_started_at, places=3,
                               msg="start time must not reset when quest already active")

    def test_default_quests_start_correctly(self):
        """The three auto-started default quests must become ACTIVE after build+start."""
        qm = QuestManager()
        qm.build_default_quests()
        qm.start_quest("first_settlement")
        qm.start_quest("feed_colony")
        qm.start_quest("growing_community")

        for qid in ("first_settlement", "feed_colony", "growing_community"):
            with self.subTest(quest=qid):
                self.assertEqual(qm.quests[qid].state, QUEST_ACTIVE,
                                 f"Quest '{qid}' must be ACTIVE after start_quest")


class TimerIsSuccessTests(unittest.TestCase):
    """QuestNode with timer_is_success=True should complete instead of fail on expiry."""

    def test_timer_is_success_completes_node(self):
        node = QuestNode("s", "Survive", timer_seconds=0.05, timer_is_success=True)
        node.next_on_success = "__COMPLETE__"
        node.start()
        time.sleep(0.06)
        result = node.check({})
        self.assertEqual(result, "__COMPLETE__")
        self.assertTrue(node.completed)
        self.assertFalse(node.failed)

    def test_timer_without_flag_fails_node(self):
        node = QuestNode("f", "Fail", timer_seconds=0.05, timer_is_success=False)
        node.next_on_failure = "__FAIL__"
        node.start()
        time.sleep(0.06)
        result = node.check({})
        self.assertEqual(result, "__FAIL__")
        self.assertTrue(node.failed)
        self.assertFalse(node.completed)


class QuestSerializationTests(unittest.TestCase):
    """to_dict / from_dict round-trip preserves quest state and timer progress."""

    def test_roundtrip_active_quest(self):
        qm = QuestManager()
        qm.build_default_quests()
        qm.start_quest("first_settlement")
        self.assertEqual(qm.quests["first_settlement"].state, QUEST_ACTIVE)

        snapshot = qm.to_dict()
        self.assertIn("first_settlement", snapshot["quest_states"])
        self.assertEqual(snapshot["quest_states"]["first_settlement"]["state"], QUEST_ACTIVE)

        # Restore into a fresh manager
        qm2 = QuestManager()
        qm2.build_default_quests()
        qm2.from_dict(snapshot)
        self.assertEqual(qm2.quests["first_settlement"].state, QUEST_ACTIVE)
        self.assertEqual(qm2.quests["first_settlement"].current_node_id, "build_house")

    def test_timer_elapsed_preserved_across_reload(self):
        """node_elapsed_seconds must be saved and restored so timed quests can't be reset."""
        qm = QuestManager()
        qm.build_default_quests()
        # Manually start the timed quest
        qm.make_available("survive_night")
        qm.start_quest("survive_night")
        time.sleep(0.05)

        snapshot = qm.to_dict()
        survive_state = snapshot["quest_states"].get("survive_night", {})
        elapsed = survive_state.get("node_elapsed_seconds", 0.0)
        self.assertGreater(elapsed, 0.0, "elapsed time must be persisted")

        qm2 = QuestManager()
        qm2.build_default_quests()
        qm2.from_dict(snapshot)
        node = qm2.quests["survive_night"].nodes.get("survive_5min")
        self.assertIsNotNone(node)
        restored_elapsed = time.time() - node.started_at
        self.assertAlmostEqual(restored_elapsed, elapsed, delta=0.1,
                               msg="restored timer should reflect saved elapsed time")


    def test_from_dict_ignores_malformed_quest_payloads(self):
        qm = QuestManager()
        qm.build_default_quests()
        qm.make_available("survive_night")
        qm.start_quest("survive_night")

        qm.from_dict({
            "completed": "bad-type",
            "quest_states": {
                "survive_night": {
                    "state": QUEST_ACTIVE,
                    "current_node": "survive_5min",
                    "node_elapsed_seconds": "not-a-number",
                },
                "first_settlement": ["bad-entry"],
            },
        })

        self.assertEqual(qm.completed_quest_ids, [])
        self.assertEqual(qm.quests["survive_night"].state, QUEST_ACTIVE)

        qm.from_dict({"quest_states": []})
        self.assertEqual(qm.quests["survive_night"].state, QUEST_ACTIVE)

if __name__ == "__main__":
    unittest.main()

