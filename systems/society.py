import time
import logging
import copy
from collections import defaultdict, deque
from thronglets_game import *
from society_dynamics import compute_faction_metrics
import random

class Faction:
    """Represents a group of thronglets with strong bonds"""
    _next_id = 0
    
    def __init__(self, member_ids):
        self.id = Faction._next_id
        Faction._next_id += 1
        self.member_ids = list(member_ids)  # List of thronglet IDs
        self.leader_id = None  # Will be set to highest skill thronglet
        self.shared_goals = []  # Goals assigned by LLM
        self.formed_time = time.time()
        self.ideology = {axis: 0.0 for axis in FACTION_IDEOLOGY_AXES}
        self.cohesion = 50.0
        self.stability = 50.0
        self.primary_doctrine = "growth"
        self.doctrine_profile = dict(FACTION_DOCTRINE_PROFILES[self.primary_doctrine])
        self.rival_faction_ids = []
        self.schism_pressure = 0.0
        self.migration_pressure = 0.0
        self.migration_target = None
        self.preferred_biome = "plains"
        self.succession_count = 0
        self.last_succession_time = 0.0
        self.last_schism_time = 0.0
        self.last_migration_time = 0.0
        self.last_doctrine_goal_time = 0.0
        self.golden_age = False
    
    def add_member(self, thronglet_id):
        """Add a member to this faction"""
        if thronglet_id not in self.member_ids:
            self.member_ids.append(thronglet_id)
    
    def remove_member(self, thronglet_id):
        """Remove a member from this faction"""
        if thronglet_id in self.member_ids:
            self.member_ids.remove(thronglet_id)
    
    def update_leader(self, thronglets):
        """Update leader to highest skill thronglet"""
        best_skill = -1.0
        best_id = None
        
        for thronglet_id in self.member_ids:
            thronglet = next((t for t in thronglets if t.id == thronglet_id), None)
            if thronglet:
                total_skill = 0.0
                skill_key = get_role_skill_key(thronglet.role)
                if skill_key and skill_key in thronglet.skills:
                    total_skill = float(thronglet.skills[skill_key]['level']) * 12.0
                total_skill += float(getattr(thronglet, "health", 100.0)) * 0.08
                total_skill += float(getattr(thronglet, "happiness", 70.0)) * 0.06
                total_skill += float(getattr(thronglet, "morale", 65.0)) * 0.07
                total_skill += float(getattr(thronglet, "genetics", {}).get("social_cohesion", 1.0)) * 7.5
                if thronglet.id == self.leader_id:
                    total_skill += 5.0
                
                if total_skill > best_skill:
                    best_skill = total_skill
                    best_id = thronglet_id
        
        self.leader_id = best_id if best_id else (self.member_ids[0] if self.member_ids else None)
    
    def get_bond_strength(self, thronglets):
        """Get average bond strength within faction"""
        if len(self.member_ids) < 2:
            return 0.0
        
        total_bonds = 0.0
        bond_count = 0
        
        for thronglet in thronglets:
            if thronglet.id in self.member_ids:
                for other_id in self.member_ids:
                    if other_id != thronglet.id and other_id in thronglet.bonds:
                        total_bonds += thronglet.bonds[other_id]
                        bond_count += 1
        
        return total_bonds / bond_count if bond_count > 0 else 0.0

    def get_members(self, thronglets):
        return [thronglet for thronglet in thronglets if thronglet.id in self.member_ids]

    def get_centroid(self, thronglets):
        members = self.get_members(thronglets)
        if not members:
            return None
        avg_x = sum(member.x for member in members) / len(members)
        avg_y = sum(member.y for member in members) / len(members)
        return (avg_x, avg_y)

    def refresh_identity(self, thronglets):
        members = self.get_members(thronglets)
        if not members:
            return

        avg_bond = self.get_bond_strength(thronglets)
        member_snapshots = []
        for member in members:
            member_snapshots.append(
                {
                    "id": member.id,
                    "health": member.health,
                    "happiness": member.happiness,
                    "morale": getattr(member, "morale", 65),
                    "curiosity": member.personality.get("curiosity", 0.5),
                    "sociability": member.personality.get("sociability", 0.5),
                    "learning_affinity": member.genetics.get("learning_affinity", 1.0),
                    "immune_strength": member.genetics.get("immune_strength", 1.0),
                    "fertility_drive": member.genetics.get("fertility_drive", 1.0),
                    "social_cohesion": member.genetics.get("social_cohesion", 1.0),
                    "adaptability": member.genetics.get("adaptability", 1.0),
                    "favorite_biome": getattr(member, "favorite_biome", "plains"),
                    "role": member.role,
                    "diseased": bool(member.diseased),
                    "known_resources_count": len(getattr(member, "known_resources", [])),
                    "known_resources": list(getattr(member, "known_resources", [])),
                    "leader_bond": member.bonds.get(self.leader_id, 50.0) if self.leader_id is not None else 50.0,
                }
            )

        metrics = compute_faction_metrics(member_snapshots, avg_bond=avg_bond)
        self.ideology = dict(metrics["ideology"])
        self.primary_doctrine = str(metrics["primary_doctrine"])
        self.doctrine_profile = dict(FACTION_DOCTRINE_PROFILES.get(self.primary_doctrine, FACTION_DOCTRINE_PROFILES["growth"]))
        self.cohesion = clamp(float(metrics["cohesion"]), 0.0, 100.0)
        self.stability = clamp(float(metrics["stability"]), 0.0, 100.0)
        self.schism_pressure = clamp(float(metrics["schism_pressure"]), 0.0, 100.0)
        self.migration_pressure = clamp(float(metrics["migration_pressure"]), 0.0, 100.0)
        self.preferred_biome = str(metrics.get("preferred_biome", "plains"))

        if getattr(self, "golden_age", False):
            for member in members:
                member.inspiration = min(100.0, member.inspiration + 0.25)
                member.morale = min(100.0, getattr(member, "morale", 65.0) + 0.25)
                member.add_moodlet("Golden Age", 15.0, 30.0, time.time())

    def assign_shared_goal(self, goal_text, reasoning="", doctrine_key=""):
        goal_text = str(goal_text or "").strip()
        if not goal_text:
            return
        goal_entry = {
            "goal": goal_text[:120],
            "reasoning": str(reasoning or "").strip()[:180],
            "doctrine_key": doctrine_key or self.primary_doctrine,
            "assigned_at": round(time.time(), 3),
        }
        append_bounded_history(self.shared_goals, goal_entry, 4)


class FactionManager:
    """Manages faction formation and updates"""
    def __init__(self):
        self.factions = {}  # {faction_id: Faction}
        self.last_update = 0
        self.update_interval = 10.0  # Update every 10 seconds
    
    def update_factions(self, thronglets, advisor=None):
        """Auto-form and update factions based on bonds > 70"""
        current_time = time.time()
        
        # Only update periodically for performance
        if current_time - self.last_update < self.update_interval:
            return
        
        self.last_update = current_time
        
        # Find groups of thronglets with mutual bonds > 70
        bond_groups = []
        processed = set()
        
        for thronglet in thronglets:
            if thronglet.id in processed:
                continue
            
            # Find all thronglets with bonds > 70 to this one
            group = {thronglet.id}
            queue = [thronglet]
            
            while queue:
                current = queue.pop(0)
                if current.id in processed:
                    continue
                processed.add(current.id)
                
                for other in thronglets:
                    if other.id in processed or other.id == current.id:
                        continue
                    
                    # Check mutual bond > 70
                    bond_1 = current.bonds.get(other.id, 0)
                    bond_2 = other.bonds.get(current.id, 0)
                    
                    if bond_1 > 70 and bond_2 > 70:
                        group.add(other.id)
                        queue.append(other)
            
            # Only create faction if min(3, population/4) members (scales with population)
            min_faction_size = min(3, max(2, len(thronglets) // 4))
            if len(group) >= min_faction_size:
                bond_groups.append(group)
        
        # Create or update factions
        used_groups = set()
        
        # Try to match existing factions to groups
        for faction_id, faction in list(self.factions.items()):
            best_match = None
            best_overlap = 0
            
            for group in bond_groups:
                overlap = len(set(faction.member_ids) & group)
                if overlap >= 2 and overlap > best_overlap:  # Need at least 2 members overlap
                    best_match = group
                    best_overlap = overlap
            
            if best_match:
                # Update existing faction
                previous_leader_id = faction.leader_id
                faction.member_ids = list(best_match)
                faction.update_leader(thronglets)
                faction.refresh_identity(thronglets)
                self._register_leadership_change(faction, previous_leader_id, advisor, current_time)
                used_groups.add(id(best_match))
            else:
                # Faction dissolved (not enough bonds), remove it
                dissolved_size = len(faction.member_ids)
                del self.factions[faction_id]
                for thronglet in thronglets:
                    if thronglet.faction_id == faction_id:
                        thronglet.faction_id = None
                if advisor is not None:
                    advisor.session_stats["factions_dissolved"] = advisor.session_stats.get("factions_dissolved", 0) + 1
                    self._record_faction_history(
                        advisor,
                        current_time,
                        "dissolved",
                        faction_id=faction_id,
                        members=dissolved_size,
                    )
                    record_observer_timeline_event(advisor, current_time, "faction", f"Faction {faction_id} dissolved", f"{dissolved_size} members lost cohesion.")
        
        # Create new factions for unmatched groups
        for group in bond_groups:
            if id(group) not in used_groups:
                new_faction = Faction(group)
                new_faction.update_leader(thronglets)
                new_faction.refresh_identity(thronglets)
                self.factions[new_faction.id] = new_faction
                
                # Assign faction_id to members
                for thronglet in thronglets:
                    if thronglet.id in group:
                        thronglet.faction_id = new_faction.id
                if advisor is not None:
                    advisor.session_stats["factions_formed"] = advisor.session_stats.get("factions_formed", 0) + 1
                    self._record_faction_history(
                        advisor,
                        current_time,
                        "formed",
                        faction_id=new_faction.id,
                        members=len(group),
                        leader_id=new_faction.leader_id,
                        doctrine=new_faction.primary_doctrine,
                    )
                    record_observer_timeline_event(
                        advisor,
                        current_time,
                        "faction",
                        f"Faction {new_faction.id} formed",
                        f"{len(group)} members around leader #{new_faction.leader_id}.",
                    )

        if advisor is not None:
            advisor.session_stats["peak_factions"] = max(
                advisor.session_stats.get("peak_factions", 0),
                len(self.factions),
            )

        for faction in self.factions.values():
            faction.refresh_identity(thronglets)
            
            if faction.cohesion >= 95.0 and faction.stability >= 90.0 and not getattr(faction, "golden_age", False):
                faction.golden_age = True
                if advisor is not None:
                    record_observer_timeline_event(
                        advisor,
                        current_time,
                        "cultural_shift",
                        f"Faction {faction.id} entered a Golden Age",
                        f"Unprecedented cohesion under {faction.primary_doctrine} triggers incredible inspiration across all members."
                    )
                    advisor.session_stats["golden_ages"] = advisor.session_stats.get("golden_ages", 0) + 1

        self._update_rivalries()
        self._evaluate_schisms(thronglets, advisor, current_time)
        self._update_rivalries()

    def _update_rivalries(self):
        factions = list(self.factions.values())
        for faction in factions:
            faction.rival_faction_ids = []

        for faction in factions:
            best_rival_id = None
            best_rival_score = 0.0
            for other in factions:
                if other.id == faction.id:
                    continue
                ideology_gap = sum(abs(faction.ideology.get(axis, 0.0) - other.ideology.get(axis, 0.0)) for axis in FACTION_IDEOLOGY_AXES)
                cohesion_pressure = abs(faction.cohesion - other.cohesion) / 100.0
                rivalry_score = ideology_gap + cohesion_pressure
                if rivalry_score > best_rival_score:
                    best_rival_score = rivalry_score
                    best_rival_id = other.id
            if best_rival_id is not None and best_rival_score >= 0.45:
                faction.rival_faction_ids = [best_rival_id]

    def _record_faction_history(self, advisor, current_time, action, **payload):
        if advisor is None:
            return
        event_payload = {"time": current_time, "action": str(action)}
        event_payload.update(payload)
        append_bounded_history(advisor.session_stats.setdefault("faction_history", []), event_payload, 24)

    def _register_leadership_change(self, faction, previous_leader_id, advisor, current_time):
        if previous_leader_id in (None, faction.leader_id):
            return
        if current_time - getattr(faction, "last_succession_time", 0.0) < FACTION_DYNAMICS["succession_grace_seconds"]:
            return
        faction.succession_count += 1
        faction.last_succession_time = current_time
        if advisor is None:
            return
        advisor.session_stats["faction_successions"] = advisor.session_stats.get("faction_successions", 0) + 1
        self._record_faction_history(
            advisor,
            current_time,
            "succession",
            faction_id=faction.id,
            previous_leader_id=previous_leader_id,
            leader_id=faction.leader_id,
            members=len(faction.member_ids),
            doctrine=faction.primary_doctrine,
        )
        record_observer_timeline_event(
            advisor,
            current_time,
            "faction",
            f"Faction {faction.id} leadership changed",
            f"Leader #{previous_leader_id} replaced by #{faction.leader_id}.",
        )

    def _soften_cross_faction_bonds(self, split_members, remaining_members):
        for member in split_members:
            for other in remaining_members:
                if other.id in member.bonds:
                    member.bonds[other.id] = min(member.bonds[other.id], 42.0)
                if member.id in other.bonds:
                    other.bonds[member.id] = min(other.bonds[member.id], 42.0)

    def _evaluate_schisms(self, thronglets, advisor, current_time):
        for faction in list(self.factions.values()):
            if len(faction.member_ids) < max(4, FACTION_DYNAMICS["minimum_schism_size"] * 2):
                continue
            if faction.schism_pressure < FACTION_DYNAMICS["schism_pressure_threshold"]:
                continue
            if current_time - faction.formed_time < FACTION_DYNAMICS["schism_cooldown_seconds"]:
                continue
            if current_time - getattr(faction, "last_schism_time", 0.0) < FACTION_DYNAMICS["schism_cooldown_seconds"]:
                continue

            members = faction.get_members(thronglets)
            if len(members) < 4:
                continue
            member_snapshots = [
                {
                    "id": member.id,
                    "leader_bond": member.bonds.get(faction.leader_id, 50.0) if faction.leader_id is not None else 50.0,
                    "happiness": member.happiness,
                    "curiosity": member.personality.get("curiosity", 0.5),
                    "social_cohesion": member.genetics.get("social_cohesion", 1.0),
                    "favorite_biome": getattr(member, "favorite_biome", "plains"),
                    "role": member.role,
                }
                for member in members
            ]
            split_ids = choose_schism_members(
                member_snapshots,
                leader_id=faction.leader_id,
                preferred_biome=faction.preferred_biome,
                minimum_size=FACTION_DYNAMICS["minimum_schism_size"],
            )
            if not split_ids:
                continue

            split_members = [member for member in members if member.id in split_ids]
            remaining_members = [member for member in members if member.id not in split_ids]
            if len(split_members) < FACTION_DYNAMICS["minimum_schism_size"] or len(remaining_members) < FACTION_DYNAMICS["minimum_schism_size"]:
                continue

            faction.member_ids = [member.id for member in remaining_members]
            new_faction = Faction(split_ids)
            new_faction.formed_time = current_time
            new_faction.last_schism_time = current_time
            faction.last_schism_time = current_time

            for member in split_members:
                member.faction_id = new_faction.id
            for member in remaining_members:
                member.faction_id = faction.id

            self._soften_cross_faction_bonds(split_members, remaining_members)
            faction.update_leader(thronglets)
            faction.refresh_identity(thronglets)
            new_faction.update_leader(thronglets)
            new_faction.refresh_identity(thronglets)
            new_goal = AUTONOMOUS_DOCTRINE_GOALS.get(new_faction.primary_doctrine)
            if new_goal:
                new_faction.assign_shared_goal(new_goal, "Emergent post-schism doctrine", new_faction.primary_doctrine)
            self.factions[new_faction.id] = new_faction

            if advisor is not None:
                advisor.session_stats["faction_schisms"] = advisor.session_stats.get("faction_schisms", 0) + 1
                advisor.session_stats["peak_factions"] = max(advisor.session_stats.get("peak_factions", 0), len(self.factions))
                self._record_faction_history(
                    advisor,
                    current_time,
                    "schism",
                    faction_id=faction.id,
                    new_faction_id=new_faction.id,
                    members=len(split_members),
                    leader_id=new_faction.leader_id,
                    doctrine=new_faction.primary_doctrine,
                )
                record_observer_timeline_event(
                    advisor,
                    current_time,
                    "faction",
                    f"Faction {faction.id} split into F{new_faction.id}",
                    f"{len(split_members)} members broke away under doctrine {new_faction.primary_doctrine}.",
                )

    def apply_autonomous_pressure(self, thronglets, advisor, world_map, world_width, world_height, current_time):
        for faction in self.factions.values():
            members = faction.get_members(thronglets)
            if len(members) < 2:
                continue

            if (
                not faction.shared_goals
                or current_time - getattr(faction, "last_doctrine_goal_time", 0.0) >= 32.0
            ):
                doctrine_goal = AUTONOMOUS_DOCTRINE_GOALS.get(faction.primary_doctrine)
                if doctrine_goal:
                    faction.assign_shared_goal(doctrine_goal, "Autonomous doctrine pressure", faction.primary_doctrine)
                    faction.last_doctrine_goal_time = current_time

            if faction.migration_pressure < FACTION_DYNAMICS["migration_pressure_threshold"]:
                continue
            if current_time - getattr(faction, "last_migration_time", 0.0) < FACTION_DYNAMICS["migration_cooldown_seconds"]:
                continue

            member_snapshots = [
                {
                    "known_resources": list(getattr(member, "known_resources", [])),
                }
                for member in members
            ]
            target = choose_migration_target(
                faction.get_centroid(thronglets),
                member_snapshots,
                faction.primary_doctrine,
                world_width,
                world_height,
                faction.migration_pressure,
                world_map=world_map,
            )
            if not target:
                continue

            faction.migration_target = target
            faction.last_migration_time = current_time
            eligible_members = [
                member
                for member in members
                if member.needs["hunger"] > 50 and member.needs["energy"] > 50 and not member.diseased
            ]
            eligible_members.sort(
                key=lambda member: (
                    0 if member.role == "explorer" else 1,
                    distance_between(member.x, member.y, target[0], target[1]),
                    member.id,
                )
            )
            assigned = 0
            for member in eligible_members:
                existing_reason = str((member.personal_goal or {}).get("reason", ""))
                if member.personal_goal and "Faction migration" not in existing_reason and current_time - getattr(member, "goal_assigned_time", 0.0) < 18.0:
                    continue
                member.personal_goal = {
                    "type": "migrate",
                    "target": {"x": round(target[0], 2), "y": round(target[1], 2)},
                    "reason": f"Faction migration toward {faction.primary_doctrine} frontier",
                }
                member.goal_assigned_time = current_time
                assigned += 1
                if assigned >= min(3, len(eligible_members)):
                    break

            if assigned and advisor is not None:
                advisor.session_stats["migration_events"] = advisor.session_stats.get("migration_events", 0) + 1
                self._record_faction_history(
                    advisor,
                    current_time,
                    "migration",
                    faction_id=faction.id,
                    members=assigned,
                    doctrine=faction.primary_doctrine,
                    target={"x": round(target[0], 1), "y": round(target[1], 1)},
                )
                record_observer_timeline_event(
                    advisor,
                    current_time,
                    "migration",
                    f"Faction {faction.id} shifted toward a new frontier",
                    f"{assigned} members moving toward ({int(target[0])}, {int(target[1])}).",
                )
    
    def get_faction(self, faction_id):
        """Get faction by ID"""
        return self.factions.get(faction_id)
    
    def get_faction_for_thronglet(self, thronglet_id):
        """Get faction containing this thronglet"""
        for faction in self.factions.values():
            if thronglet_id in faction.member_ids:
                return faction
        return None


class TradeSystem:
    """Inter-faction trade: factions exchange surplus resources when not rivals."""

    TRADE_INTERVAL = 30.0  # seconds between trade rounds
    SURPLUS_THRESHOLD = 3   # Must have > 3 of a resource to offer it
    DEFICIT_THRESHOLD = 1   # Will accept if they have <= 1

    def __init__(self):
        self.last_trade_time = 0.0
        self.trade_log = []  # [{time, from_faction, to_faction, resource, amount}]
        self.max_log = 20

    def update(self, faction_manager, thronglets, current_time):
        """Run a trade round if enough time has passed."""
        if current_time - self.last_trade_time < self.TRADE_INTERVAL:
            return
        self.last_trade_time = current_time
        if faction_manager is None:
            return

        # Build per-faction aggregate inventory
        faction_inventories = {}
        for faction_id, faction in faction_manager.factions.items():
            members = faction.get_members(thronglets)
            agg = {}
            for m in members:
                for res, qty in getattr(m, 'inventory', {}).items():
                    agg[res] = agg.get(res, 0) + qty
            faction_inventories[faction_id] = agg

        # Attempt trades between non-rival factions
        faction_ids = list(faction_manager.factions.keys())
        for i, fid_a in enumerate(faction_ids):
            fa = faction_manager.factions[fid_a]
            rival_ids = set(getattr(fa, 'rival_faction_ids', []) or [])
            inv_a = faction_inventories.get(fid_a, {})
            for fid_b in faction_ids[i + 1:]:
                if fid_b in rival_ids:
                    continue
                fb = faction_manager.factions[fid_b]
                if fid_a in set(getattr(fb, 'rival_faction_ids', []) or []):
                    continue
                inv_b = faction_inventories.get(fid_b, {})
                self._try_trade(fa, fb, inv_a, inv_b, thronglets, current_time)

    def _try_trade(self, fa, fb, inv_a, inv_b, thronglets, current_time):
        """Attempt a single resource exchange between two factions."""
        # A has surplus, B has deficit
        for res, qty_a in inv_a.items():
            if qty_a <= self.SURPLUS_THRESHOLD:
                continue
            qty_b = inv_b.get(res, 0)
            if qty_b > self.DEFICIT_THRESHOLD:
                continue
            # Transfer 1 unit: take from a random member of A, give to random member of B
            amount = 1
            donors = [m for m in fa.get_members(thronglets) if getattr(m, 'inventory', {}).get(res, 0) > 0]
            recipients = fb.get_members(thronglets)
            if donors and recipients:
                donor = random.choice(donors)
                recipient = random.choice(recipients)
                donor.inventory[res] = max(0, donor.inventory.get(res, 0) - amount)
                recipient.inventory[res] = recipient.inventory.get(res, 0) + amount
                self.trade_log.append({
                    'time': current_time,
                    'from_faction': fa.id,
                    'to_faction': fb.id,
                    'resource': res,
                    'amount': amount,
                })
                if len(self.trade_log) > self.max_log:
                    del self.trade_log[:-self.max_log]
                return  # One trade per pair per round

    def get_trade_opportunities(self, faction_manager, thronglets):
        """Return human-readable trade opportunity descriptions for LLM state view."""
        if faction_manager is None:
            return []
        opportunities = []
        faction_ids = list(faction_manager.factions.keys())
        for i, fid_a in enumerate(faction_ids):
            fa = faction_manager.factions[fid_a]
            members_a = fa.get_members(thronglets)
            inv_a = {}
            for m in members_a:
                for res, qty in getattr(m, 'inventory', {}).items():
                    inv_a[res] = inv_a.get(res, 0) + qty
            surplus = [f"{r}={q}" for r, q in inv_a.items() if q > self.SURPLUS_THRESHOLD]
            if surplus:
                rival_ids = set(getattr(fa, 'rival_faction_ids', []) or [])
                for fid_b in faction_ids[i + 1:]:
                    if fid_b not in rival_ids:
                        opportunities.append(
                            f"F{fid_a} surplus ({', '.join(surplus)}) can trade with F{fid_b}"
                        )
        return opportunities[:4]

    def get_territory_overlaps(self, faction_manager, thronglets, territory_manager=None):
        """Return descriptions of territory overlaps between factions."""
        if faction_manager is None:
            return []
        overlaps = []
        faction_ids = list(faction_manager.factions.keys())
        for i, fid_a in enumerate(faction_ids):
            fa = faction_manager.factions[fid_a]
            centroid_a = fa.get_centroid(thronglets)
            if centroid_a is None:
                continue
            for fid_b in faction_ids[i + 1:]:
                fb = faction_manager.factions[fid_b]
                centroid_b = fb.get_centroid(thronglets)
                if centroid_b is None:
                    continue
                dist = math.sqrt(
                    (centroid_a[0] - centroid_b[0]) ** 2 + (centroid_a[1] - centroid_b[1]) ** 2
                )
                if dist < 200:
                    overlaps.append(f"F{fid_a} and F{fid_b} territory overlap (dist={int(dist)}px)")
        return overlaps[:4]

    def serialize(self):
        return {'trade_log': list(self.trade_log[-10:])}


