"""
Quest System — Multi-step, branching quest engine.

Quests are graphs of QuestNodes. Each node has:
  - conditions to activate (trigger)
  - a description/label for the player
  - success/failure outcomes that link to other nodes or end
  - optional rewards and timers

Quests can be defined in JSON (defs/core/quests.json) or created programmatically.
"""
from __future__ import annotations

import time
import logging
from typing import Any, Callable, Optional

logger = logging.getLogger("Quests")


# ---- Quest States ----
QUEST_AVAILABLE = "available"      # Can be started
QUEST_ACTIVE = "active"            # Currently in progress
QUEST_COMPLETED = "completed"      # Successfully finished
QUEST_FAILED = "failed"            # Failed / expired
QUEST_HIDDEN = "hidden"            # Not yet discovered


class QuestNode:
    """A single step/milestone in a quest."""

    def __init__(self, node_id: str, label: str, description: str = "",
                 condition_fn: Optional[Callable] = None,
                 on_complete_fn: Optional[Callable] = None,
                 timer_seconds: float = 0.0):
        self.node_id = node_id
        self.label = label
        self.description = description
        self.condition_fn = condition_fn     # (game_state) -> bool
        self.on_complete_fn = on_complete_fn # (game_state) -> None
        self.timer_seconds = timer_seconds   # 0 = no time limit
        self.next_on_success: Optional[str] = None  # node_id
        self.next_on_failure: Optional[str] = None   # node_id
        self.completed = False
        self.failed = False
        self.started_at: float = 0.0

    def check(self, game_state: dict) -> Optional[str]:
        """
        Check if this node's condition is met.
        Returns the next node_id to advance to, or None if still in progress.
        """
        if self.completed or self.failed:
            return None

        # Check timer expiry
        if self.timer_seconds > 0 and self.started_at > 0:
            elapsed = time.time() - self.started_at
            if elapsed >= self.timer_seconds:
                self.failed = True
                logger.info(f"Quest node '{self.node_id}' timed out")
                return self.next_on_failure

        # Check success condition
        if self.condition_fn and self.condition_fn(game_state):
            self.completed = True
            if self.on_complete_fn:
                self.on_complete_fn(game_state)
            logger.info(f"Quest node '{self.node_id}' completed")
            return self.next_on_success

        return None

    def start(self):
        self.started_at = time.time()


class Quest:
    """A complete quest composed of QuestNodes."""

    def __init__(self, quest_id: str, name: str, description: str = "",
                 category: str = "main"):
        self.quest_id = quest_id
        self.name = name
        self.description = description
        self.category = category
        self.state = QUEST_HIDDEN
        self.nodes: dict[str, QuestNode] = {}
        self.start_node_id: Optional[str] = None
        self.current_node_id: Optional[str] = None
        self.rewards: dict[str, Any] = {}

    def add_node(self, node: QuestNode, is_start: bool = False):
        self.nodes[node.node_id] = node
        if is_start:
            self.start_node_id = node.node_id

    def start(self):
        if self.state != QUEST_AVAILABLE:
            return
        self.state = QUEST_ACTIVE
        self.current_node_id = self.start_node_id
        if self.current_node_id in self.nodes:
            self.nodes[self.current_node_id].start()
        logger.info(f"Quest '{self.name}' started")

    def update(self, game_state: dict) -> bool:
        """
        Update the quest. Returns True if the quest state changed.
        """
        if self.state != QUEST_ACTIVE:
            return False

        if self.current_node_id is None:
            return False

        current_node = self.nodes.get(self.current_node_id)
        if current_node is None:
            return False

        next_id = current_node.check(game_state)
        if next_id is None:
            return False

        if next_id == "__COMPLETE__":
            self.state = QUEST_COMPLETED
            logger.info(f"Quest '{self.name}' COMPLETED!")
            return True
        elif next_id == "__FAIL__":
            self.state = QUEST_FAILED
            logger.info(f"Quest '{self.name}' FAILED")
            return True
        elif next_id in self.nodes:
            self.current_node_id = next_id
            self.nodes[next_id].start()
            return True

        return False

    def get_current_objective(self) -> Optional[str]:
        if self.current_node_id and self.current_node_id in self.nodes:
            return self.nodes[self.current_node_id].label
        return None


class QuestManager:
    """Manages all active and available quests."""

    def __init__(self):
        self.quests: dict[str, Quest] = {}
        self.completed_quest_ids: list[str] = []

    def register_quest(self, quest: Quest):
        self.quests[quest.quest_id] = quest

    def make_available(self, quest_id: str):
        quest = self.quests.get(quest_id)
        if quest and quest.state == QUEST_HIDDEN:
            quest.state = QUEST_AVAILABLE
            logger.info(f"Quest '{quest.name}' is now available")

    def start_quest(self, quest_id: str):
        quest = self.quests.get(quest_id)
        if quest:
            quest.start()

    def update(self, game_state: dict):
        """Update all active quests."""
        for quest in self.quests.values():
            if quest.state == QUEST_ACTIVE:
                changed = quest.update(game_state)
                if changed and quest.state == QUEST_COMPLETED:
                    self.completed_quest_ids.append(quest.quest_id)
                    # Apply rewards
                    self._apply_rewards(quest, game_state)

    def _apply_rewards(self, quest: Quest, game_state: dict):
        """Apply quest completion rewards."""
        advisor = game_state.get('advisor')
        narrative = game_state.get('narrative_panel')

        for reward_type, amount in quest.rewards.items():
            if reward_type == "research_points" and advisor:
                advisor.research_points = getattr(advisor, 'research_points', 0) + amount
            elif reward_type == "food":
                # Add to nearest storage building
                buildings = game_state.get('buildings', [])
                for b in buildings:
                    if getattr(b, 'building_type', '') == 'storage':
                        stored = getattr(b, 'stored_resources', {})
                        stored['food'] = stored.get('food', 0) + amount
                        break

        if narrative:
            narrative.add_message(f"Quest completed: {quest.name}!", 'Achievement')

    def get_active_quests(self) -> list[Quest]:
        return [q for q in self.quests.values() if q.state == QUEST_ACTIVE]

    def get_available_quests(self) -> list[Quest]:
        return [q for q in self.quests.values() if q.state == QUEST_AVAILABLE]

    def build_default_quests(self):
        """Create the built-in starter quests using programmatic conditions."""

        # Quest 1: First Settlement
        q1 = Quest("first_settlement", "First Settlement",
                    "Build your first house to shelter your praxans.", "tutorial")
        q1.add_node(QuestNode(
            "build_house",
            "Build a house",
            "Construct a house to provide shelter for your praxans.",
            condition_fn=lambda gs: any(
                getattr(b, 'building_type', '') == 'house'
                for b in gs.get('buildings', [])
            ),
        ), is_start=True)
        q1.nodes["build_house"].next_on_success = "__COMPLETE__"
        q1.rewards = {"research_points": 50}
        self.register_quest(q1)

        # Quest 2: Feed the Colony
        q2 = Quest("feed_colony", "Feed the Colony",
                    "Build a farm to ensure sustainable food production.", "tutorial")
        q2.add_node(QuestNode(
            "build_farm",
            "Build a farm",
            "Construct a farm to grow food.",
            condition_fn=lambda gs: any(
                getattr(b, 'building_type', '') == 'farm'
                for b in gs.get('buildings', [])
            ),
        ), is_start=True)
        q2.nodes["build_farm"].next_on_success = "__COMPLETE__"
        q2.rewards = {"research_points": 50, "food": 10}
        self.register_quest(q2)

        # Quest 3: Growing Community
        q3 = Quest("growing_community", "Growing Community",
                    "Grow your colony to 5 praxans.", "milestone")
        q3.add_node(QuestNode(
            "reach_5_pop",
            "Reach population of 5",
            "Have at least 5 living praxans in your colony.",
            condition_fn=lambda gs: len([
                p for p in gs.get('praxans', [])
                if getattr(p, 'alive', True)
            ]) >= 5,
        ), is_start=True)
        q3.nodes["reach_5_pop"].next_on_success = "__COMPLETE__"
        q3.rewards = {"research_points": 100}
        self.register_quest(q3)

        # Quest 4: Survive the Night (timed)
        q4 = Quest("survive_night", "Survive the Storm",
                    "Keep all praxans alive for 5 minutes during a climax phase.", "challenge")
        q4.add_node(QuestNode(
            "survive_5min",
            "Survive for 5 minutes",
            "Keep your colony alive through adversity.",
            condition_fn=lambda gs: True,  # Auto-completes if timer doesn't expire
            timer_seconds=300.0,
        ), is_start=True)
        q4.nodes["survive_5min"].next_on_success = "__COMPLETE__"
        q4.nodes["survive_5min"].next_on_failure = "__FAIL__"
        q4.rewards = {"research_points": 150}
        self.register_quest(q4)

        # Make tutorial quests available immediately
        self.make_available("first_settlement")
        self.make_available("feed_colony")
        self.make_available("growing_community")

    def to_dict(self) -> dict:
        """Serialize quest state for save files."""
        return {
            "completed": self.completed_quest_ids,
            "quest_states": {
                qid: {
                    "state": q.state,
                    "current_node": q.current_node_id,
                }
                for qid, q in self.quests.items()
            }
        }
