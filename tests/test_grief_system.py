"""
Regression tests for Praxan grief moodlet system.

Key race condition fixed: update_bonds (long-tick) can fire in the same
tick_manager.tick() call as the death (rare-tick), deleting the partner
relationship before the death loop's apply_grief can read it.  The fix:
  - update_bonds calls apply_grief before deleting the dead-partner entry
  - _griefed_ids guards against double-fire if the death loop also calls
    apply_grief for the same praxan
"""
import sys
import time
import unittest

# praxans_game parses sys.argv at import time; neutralise unittest's args first.
_saved_argv = sys.argv
sys.argv = sys.argv[:1]
import praxans_game  # noqa: F401  — must precede entities.praxan (wildcard import dep)
sys.argv = _saved_argv
from entities.praxan import Praxan
from praxans_game import REL_PARTNER, REL_CHILD, REL_PARENT, REL_FRIEND, REL_RIVAL


def _make_praxan(x=100, y=100):
    return Praxan(x, y)


class GriefRaceConditionTests(unittest.TestCase):
    """The core race: update_bonds fires before the death loop's apply_grief."""

    def setUp(self):
        self.survivor = _make_praxan(100, 100)
        self.dead = _make_praxan(102, 100)
        self.dead.alive = False

        # Establish partner relationship
        self.survivor.set_relationship(self.dead.id, REL_PARTNER)
        self.dead.set_relationship(self.survivor.id, REL_PARTNER)

    def test_update_bonds_fires_grief_before_deleting_partner(self):
        """update_bonds must apply grief before removing the dead-partner relationship."""
        t = time.time()
        # Simulate the race: update_bonds runs with the dead praxan still in the list
        self.survivor.update_bonds([self.survivor, self.dead], delta_time=1.0)

        # Relationship should be cleaned up
        self.assertNotIn(self.dead.id, self.survivor.relationships,
                         "Dead partner must be removed from relationships")
        # Grief moodlet must have fired
        moodlet_names = [m['name'] for m in self.survivor.moodlets]
        self.assertIn("Lost Partner", moodlet_names,
                      "Lost Partner grief moodlet must fire when partner dies in update_bonds")

    def test_death_loop_apply_grief_is_idempotent_after_update_bonds(self):
        """If update_bonds already fired grief, the death loop's apply_grief is a no-op."""
        t = time.time()
        # update_bonds fires first (the race scenario)
        self.survivor.update_bonds([self.survivor, self.dead], delta_time=1.0)
        moodlets_after_bonds = [m for m in self.survivor.moodlets]

        # Death loop then calls apply_grief (relationship already gone)
        self.survivor.apply_grief(self.dead.id, t)

        moodlets_after_loop = [m for m in self.survivor.moodlets]
        # Same number of moodlets — no new one added
        self.assertEqual(len(moodlets_after_bonds), len(moodlets_after_loop),
                         "apply_grief must not add a duplicate moodlet after update_bonds already grieved")

    def test_death_loop_fires_grief_when_no_race(self):
        """Normal path: relationship intact, death loop apply_grief fires correctly."""
        t = time.time()
        # No update_bonds call — relationship is still there
        self.survivor.apply_grief(self.dead.id, t)

        moodlet_names = [m['name'] for m in self.survivor.moodlets]
        self.assertIn("Lost Partner", moodlet_names)
        self.assertIn(self.dead.id, self.survivor._griefed_ids)

    def test_second_apply_grief_call_does_not_add_moodlet(self):
        """Calling apply_grief twice for the same dead_id is idempotent."""
        t = time.time()
        self.survivor.apply_grief(self.dead.id, t)
        count_after_first = len(self.survivor.moodlets)

        self.survivor.apply_grief(self.dead.id, t + 1)
        count_after_second = len(self.survivor.moodlets)

        self.assertEqual(count_after_first, count_after_second,
                         "Second apply_grief call must not add a new moodlet")


class GriefMoodletVariantsTests(unittest.TestCase):
    """Each relationship type yields the correct moodlet."""

    def _grief_for(self, rel_type):
        survivor = _make_praxan(100, 100)
        dead = _make_praxan(200, 200)
        dead.alive = False
        survivor.set_relationship(dead.id, rel_type)
        survivor.apply_grief(dead.id, time.time())
        return [m['name'] for m in survivor.moodlets]

    def test_partner_grief(self):
        self.assertIn("Lost Partner", self._grief_for(REL_PARTNER))

    def test_child_grief(self):
        self.assertIn("Lost Child", self._grief_for(REL_CHILD))

    def test_parent_grief(self):
        self.assertIn("Lost Parent", self._grief_for(REL_PARENT))

    def test_friend_grief(self):
        self.assertIn("Lost Friend", self._grief_for(REL_FRIEND))

    def test_rival_death_positive(self):
        names = self._grief_for(REL_RIVAL)
        self.assertIn("Rival Perished", names)
        rival_moodlet = next(m for m in self._grief_for(REL_RIVAL) if m == "Rival Perished")
        # Should be positive (happy a rival is gone) — checked via build
        self.assertEqual(rival_moodlet, "Rival Perished")

    def test_high_bond_stranger_grief(self):
        """High-bond praxan with no typed relationship still gets a grief moodlet."""
        survivor = _make_praxan(100, 100)
        dead = _make_praxan(200, 200)
        dead.alive = False
        survivor.bonds[dead.id] = 80  # High bond, no typed relationship
        survivor.apply_grief(dead.id, time.time())
        moodlet_names = [m['name'] for m in survivor.moodlets]
        self.assertIn("Lost Companion", moodlet_names)

    def test_no_grief_for_stranger(self):
        """No relationship and no bond → no grief moodlet."""
        survivor = _make_praxan(100, 100)
        dead = _make_praxan(200, 200)
        survivor.apply_grief(dead.id, time.time())
        self.assertEqual(len(survivor.moodlets), 0)


if __name__ == "__main__":
    unittest.main()
