import unittest

from systems.diplomacy import DiplomacyManager
from systems.society import Faction, TradeSystem


class _Member:
    def __init__(self, member_id, inventory, x=0.0, y=0.0):
        self.id = member_id
        self.inventory = dict(inventory)
        self.x = x
        self.y = y


class _FactionManager:
    def __init__(self, factions):
        self.factions = {f.id: f for f in factions}


class _Advisor:
    def __init__(self):
        self.events_history = []
        self.session_stats = {"timeline_events": []}


class TradeSystemTests(unittest.TestCase):
    def test_crisis_relief_prioritizes_needy_faction_and_records_timeline(self):
        donor_member = _Member(1, {"food": 6})
        needy_member = _Member(2, {"food": 0})

        donor_faction = Faction([donor_member.id])
        needy_faction = Faction([needy_member.id])

        donor_faction.resource_stress = 20.0
        donor_faction.food_security = 80.0
        donor_faction.material_security = 75.0

        needy_faction.resource_stress = 88.0
        needy_faction.food_security = 18.0
        needy_faction.material_security = 42.0

        manager = _FactionManager([donor_faction, needy_faction])
        advisor = _Advisor()
        trade = TradeSystem()

        trade.update(manager, [donor_member, needy_member], current_time=100.0, advisor=advisor)

        self.assertEqual(donor_member.inventory.get("food", 0), 5)
        self.assertEqual(needy_member.inventory.get("food", 0), 1)
        self.assertEqual(advisor.session_stats.get("relief_transfers", 0), 1)

        self.assertEqual(len(trade.trade_log), 1)
        entry = trade.trade_log[0]
        self.assertEqual(entry["kind"], "relief")
        self.assertEqual(entry["from_faction"], donor_faction.id)
        self.assertEqual(entry["to_faction"], needy_faction.id)

        timeline = advisor.session_stats.get("timeline_events", [])
        self.assertTrue(any("sent relief" in str(event.get("summary", "")).lower() for event in timeline))

    def test_normal_trade_registers_with_diplomacy(self):
        sender = _Member(3, {"wood": 5})
        receiver = _Member(4, {"wood": 0})

        faction_a = Faction([sender.id])
        faction_b = Faction([receiver.id])
        faction_a.resource_stress = 45.0
        faction_b.resource_stress = 40.0

        manager = _FactionManager([faction_a, faction_b])
        diplomacy = DiplomacyManager()
        trade = TradeSystem()

        trade.update(manager, [sender, receiver], current_time=200.0, diplomacy_manager=diplomacy)

        self.assertEqual(sender.inventory.get("wood", 0), 4)
        self.assertEqual(receiver.inventory.get("wood", 0), 1)

        relation = diplomacy.get_relation(faction_a.id, faction_b.id)
        self.assertEqual(relation.trade_count, 1)
        self.assertGreater(relation.standing, 0.0)

        self.assertEqual(len(trade.trade_log), 1)
        self.assertEqual(trade.trade_log[0]["kind"], "trade")


if __name__ == "__main__":
    unittest.main()
