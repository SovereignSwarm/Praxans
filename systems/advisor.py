import time
import math
from collections import Counter
import copy
from statistics import mean
from praxans_game import *
import llm.contracts as llm_contracts
import llm.memory as llm_memory
from llm.scheduler import LLMScheduler
import random
from events.bus import EventBus

class CivilizationAdvisor:
    """LLM-powered strategic advisor for civilization-level decisions"""
    def __init__(self):
        self.directives = []  # List of current directives
        self.last_query_time = time.time()  # Initialize to current time to prevent immediate query on first frame
        self.last_goal_assignment = time.time()  # Prevent immediate heavy LLM goal assignment on startup
        self.history = []  # Store last 5 queries with context
        self.strategic_goals = {'short': [], 'medium': [], 'long': []}
        self.events_history = []  # Major events (births, builds, shortages)
        
        # Enhanced directive system
        self.json_directives = {
            'individual': {},  # {praxan_id: instruction}
            'communal': '',    # Group task description
            'conditions': {}   # {condition: behavior}
        }
        self.group_tasks = []  # List of active GroupTask objects
        
        # Long-term goals tracking
        self.long_term_goals = {
            'survival': {'target_population': 10, 'progress': 0, 'priority': 10},
            'development': {'target_workshops': 1, 'progress': 0, 'priority': 8},
            'expansion': {'territories_explored': 0, 'target': 3, 'priority': 6},
            'social': {'target_happiness': 75, 'progress': 0, 'priority': 7}
        }
        self.civilization_age = 0  # In-game days survived
        self.total_deaths = 0
        self.achievements = []  # Milestones reached
        
        # Evolution system
        self.research_points = 0
        self.points_spent = 0
        self.game_modifiers = GameModifiers()
        
        # Challenge difficulty tracking
        self.challenge_difficulty = 1.0
        self.last_scaling_check = 0
        
        # Tech tree and abilities are content-driven so balancing stays centralized.
        self.tech_tree = clone_tech_tree()
        self.abilities = clone_abilities()
        
        # Challenge tracking
        self.active_challenges = []
        self.challenge_cooldown = 0
        
        # Legacy bonuses
        self.legacy_bonuses = clone_legacy_bonuses()
        
        # Meta learning
        self.session_stats = {
            'buildings_built': {},
            'deaths_by_cause': {},
            'avg_survival_time': 0,
            'successful_strategies': [],
            'births_total': 0,
            'highest_generation': 0,
            'peak_founder_lines': 0,
            'peak_factions': 0,
            'factions_formed': 0,
            'factions_dissolved': 0,
            'faction_schisms': 0,
            'faction_successions': 0,
            'migration_events': 0,
            'lineage_events': [],
            'evolution_history': [],
            'current_evolution_summary': {},
            'timeline_events': [],
            'faction_history': [],
            'current_run_summary': {},
        }
        
        # Smart LLM integration tracking
        self.query_count = 0
        self.focus_areas = ['resources', 'infrastructure', 'territory', 'population']
        self.current_focus = 'resources'
        self.stability_counter = 0  # Tracks consecutive stable assessments
        self.last_pop_count = INITIAL_POPULATION
        self.intervention_stats = {
            'total_queries': 0,
            'interventions': 0,
            'no_changes': 0,
            'crisis_interventions': 0
        }
        self.current_settlement_state = {}
        self.pending_strategy_job = None
        self.pending_goal_job = None
        self.last_model_used = None
        self.last_llm_error = None
        self.council_state = advisory_payload_defaults()
        self.advisory_history = []
        self.last_job_completed_at = 0.0
        self.last_evolution_sample_time = 0.0
        self.last_run_summary_refresh = 0.0

        # ── Multi-channel LLM subsystem (V2) ──────────────────────
        self.llm_scheduler: LLMScheduler | None = None
        self.llm_memory = LLMMemory()
        self._channel_last_fire: dict[str, float] = {
            CHANNEL_COUNCIL: 0.0,
            CHANNEL_FACTION: 0.0,
            CHANNEL_HISTORIAN: 0.0,
            CHANNEL_MEMORY: 0.0,
            CHANNEL_MUSE: 0.0,
        }
    
    def _generate_state_summary(self, praxans, resources, buildings, territory_manager, world_map):
        """Generate concise state summary with health indicators"""
        
        # Population metrics
        pop_status = "stable" if len(praxans) >= self.last_pop_count * 0.9 else "declining"
        pop_summary = f"Pop: {len(praxans)} ({pop_status})"
        
        # Resource availability (% metric)
        total_food = sum(t.inventory['food'] for t in praxans) + sum(b.stored_resources.get('food', 0) for b in buildings if b.building_type in ['storage', 'farm'])
        food_per_capita = total_food / max(1, len(praxans))
        food_status = "abundant" if food_per_capita > 3 else "adequate" if food_per_capita > 1.5 else "scarce"
        food_pct = min(100, int(food_per_capita / 3 * 100))
        resource_summary = f"Resources: Food {food_pct}% ({food_status})"
        
        # Need satisfaction
        avg_hunger = sum(t.needs['hunger'] for t in praxans) / max(1, len(praxans))
        avg_energy = sum(t.needs['energy'] for t in praxans) / max(1, len(praxans))
        needs_status = "healthy" if avg_hunger > 70 and avg_energy > 70 else "stressed"
        needs_summary = f"Needs: Hunger {avg_hunger:.0f}%, Energy {avg_energy:.0f}% ({needs_status})"
        
        # Territory control
        if territory_manager:
            territory_tiles = sum(1 for v in territory_manager.territory_grid.values() if v['claim_strength'] >= 50)
            territory_pct = min(100, territory_tiles // 2)  # Rough percentage
            territory_summary = f"Territory: {territory_pct}% claimed"
        else:
            territory_summary = "Territory: N/A"
            territory_pct = 0
        
        # Infrastructure
        houses = sum(1 for b in buildings if b.building_type == 'house')
        farms = sum(1 for b in buildings if b.building_type == 'farm')
        wells = sum(1 for b in buildings if b.building_type == 'well')
        shrines = sum(1 for b in buildings if b.building_type == 'shrine')
        workshops = sum(1 for b in buildings if b.building_type == 'workshop')
        avg_happiness = sum(t.happiness for t in praxans) / max(1, len(praxans))
        avg_morale = sum(getattr(t, 'morale', 65) for t in praxans) / max(1, len(praxans))
        infrastructure_status = "adequate" if houses >= len(praxans) // 2 and farms >= len(praxans) // 3 else "insufficient"
        infrastructure_summary = f"Infrastructure: {houses} houses, {farms} farms, {wells} wells, {workshops} workshops ({infrastructure_status})"
        culture_summary = f"Culture: Happiness {avg_happiness:.0f}%, Morale {avg_morale:.0f}%, Shrines {shrines}"
        
        # Crisis indicators
        crisis_flags = []
        if avg_hunger < 50:
            crisis_flags.append("HUNGER_CRISIS")
        if len(praxans) < 3:
            crisis_flags.append("POPULATION_CRITICAL")
        if food_pct < 30:
            crisis_flags.append("FOOD_SHORTAGE")
        if avg_happiness < 45:
            crisis_flags.append("MORALE_COLLAPSE")
        
        wealth_summary = f"Wealth: {self.session_stats.get('colony_wealth', 0):.0f}"
    
        return {
            'summary_text': f"{pop_summary} | {wealth_summary} | {resource_summary} | {needs_summary} | {territory_summary} | {infrastructure_summary} | {culture_summary}",
            'crisis_flags': crisis_flags,
            'metrics': {
                'colony_wealth': self.session_stats.get('colony_wealth', 0),
                'population': len(praxans),
                'food_pct': food_pct,
                'avg_hunger': avg_hunger,
                'avg_energy': avg_energy,
                'avg_happiness': avg_happiness,
                'avg_morale': avg_morale,
                'territory_pct': territory_pct,
                'houses': houses,
                'farms': farms,
                'wells': wells,
                'workshops': workshops,
                'shrines': shrines,
            }
        }
    
    def _check_milestones(self, metrics):
        """Check if any population milestones have been reached"""
        # Track milestones to avoid repeated triggers
        if not hasattr(self, 'achieved_milestones'):
            self.achieved_milestones = set()
        
        # Population milestones (every 5 praxans)
        if metrics['population'] > 0 and metrics['population'] % 5 == 0:
            pop_milestone = (metrics['population'] // 5) * 5
            pop_key = f"pop_{pop_milestone}"
            if pop_key not in self.achieved_milestones:
                self.achieved_milestones.add(pop_key)
                return True
        
        # First building of each type - only trigger once per type
        if metrics['houses'] == 1:
            milestone_key = "houses_1"
            if milestone_key not in self.achieved_milestones:
                self.achieved_milestones.add(milestone_key)
                return True
        if metrics['farms'] == 1:
            milestone_key = "farms_1"
            if milestone_key not in self.achieved_milestones:
                self.achieved_milestones.add(milestone_key)
                return True
        
        return False
    
    def _should_intervene(self, state_summary, current_time):
        """Decide if LLM should provide guidance or stay silent"""
        
        # Always intervene if crisis
        if state_summary['crisis_flags']:
            return True, "crisis", state_summary['crisis_flags']
        
        # Check milestone triggers (population milestones, first building, etc.)
        if self._check_milestones(state_summary['metrics']):
            return True, "milestone", []
        
        # Check if metrics below thresholds
        metrics = state_summary['metrics']
        if (metrics['food_pct'] < 50 or 
            metrics['avg_hunger'] < 60 or 
            metrics['avg_energy'] < 60 or
            metrics['avg_happiness'] < 55 or
            metrics['avg_morale'] < 55):
            return True, "imbalance", []
        
        # Variable interval - extend if stable
        time_since_last = current_time - self.last_query_time
        if self.stability_counter > 3:  # 3+ stable checks in a row
            required_interval = CIVILIZATION_ADVISOR_INTERVAL * 2  # Double interval when stable
        else:
            required_interval = CIVILIZATION_ADVISOR_INTERVAL
        
        if time_since_last < required_interval:
            return False, "stable", []
        
        # Rotate focus areas every 2 queries
        focus_rotation = ['resources', 'infrastructure', 'territory', 'population']
        current_focus = focus_rotation[self.query_count % len(focus_rotation)]
        
        # Only intervene if current focus area needs attention
        if current_focus == 'resources' and metrics['food_pct'] >= 70:
            return False, "focus_stable", []
        elif current_focus == 'infrastructure' and metrics['houses'] >= metrics['population'] // 2:
            return False, "focus_stable", []
        
        return True, "routine", []
    
    def query_llm(self, praxans, resources, buildings, narrative_panel=None, player_suggestion=None, territory_manager=None, city_planner=None, world_map=None, hazards=None, state_summary=None, intervention_reason=None, faction_manager=None):
        """Query LLM for strategic guidance"""
        # Calculate civilization statistics
        num_praxans = len(praxans)
        num_resources = sum(1 for r in resources if not r.collected)
        num_food = sum(1 for r in resources if r.resource_type == 'food' and not r.collected)
        num_wood = sum(1 for r in resources if r.resource_type == 'wood' and not r.collected)
        num_stone = sum(1 for r in resources if r.resource_type == 'stone' and not r.collected)
        total_food_inv = sum(t.inventory['food'] for t in praxans)
        total_wood_inv = sum(t.inventory['wood'] for t in praxans)
        total_stone_inv = sum(t.inventory['stone'] for t in praxans)
        avg_hunger = sum(t.needs['hunger'] for t in praxans) / len(praxans) if praxans else 0
        avg_energy = sum(t.needs['energy'] for t in praxans) / len(praxans) if praxans else 0
        
        # Count buildings by type and aggregate storage/production
        building_counts = {'house': 0, 'storage': 0, 'farm': 0, 'workshop': 0, 'shrine': 0, 'well': 0}
        total_food_in_storage = 0
        total_wood_in_storage = 0
        total_food_in_farms = 0
        total_carrying_food = 0
        total_carrying_wood = 0
        
        for building in buildings:
            building_counts[building.building_type] = building_counts.get(building.building_type, 0) + 1
            if building.building_type == 'storage':
                total_food_in_storage += building.stored_resources['food']
                total_wood_in_storage += building.stored_resources['wood']
            elif building.building_type == 'farm':
                total_food_in_farms += building.stored_resources['food']
        
        # Praxan behavioral analysis
        role_distribution = {'gatherer': 0, 'builder': 0, 'explorer': 0}
        hungry_count = sum(1 for t in praxans if t.needs['hunger'] < 50)
        energy_low_count = sum(1 for t in praxans if t.needs['energy'] < 50)
        can_reproduce_count = sum(1 for t in praxans if t.can_reproduce())
        
        # New metrics: Health, skills, social, disease
        avg_health = sum(t.health for t in praxans) / len(praxans) if praxans else 100
        avg_happiness = sum(t.happiness for t in praxans) / len(praxans) if praxans else 100
        diseased_count = sum(1 for t in praxans if t.diseased)
        
        # Faction analysis
        faction_info = ""
        num_factions = 0
        if faction_manager and faction_manager.factions:
            num_factions = len(faction_manager.factions)
            faction_details = []
            for faction_id, faction in faction_manager.factions.items():
                avg_bond = faction.get_bond_strength(praxans) if len(faction.member_ids) >= 2 else 0
                faction_details.append(f"Faction {faction_id}: {len(faction.member_ids)} members, avg bond {avg_bond:.0f}")
            faction_info = f"\n- Active Factions: {num_factions}\n" + "\n".join([f"  {fd}" for fd in faction_details[:5]])  # Limit to 5 for brevity
        
        # Social bonds analysis
        avg_bonds_per_praxan = sum(len(t.bonds) for t in praxans) / len(praxans) if praxans else 0
        strong_bonds = sum(1 for t in praxans for bond_val in t.bonds.values() if bond_val > 70)
        
        # AI Learning metrics (Q-learning success tracking)
        q_learning_stats = ""
        if praxans:
            total_q_entries = sum(len(t.q_table) for t in praxans)
            avg_q_entries = total_q_entries / len(praxans)
            if avg_q_entries > 0:
                # Calculate success rates
                successful_actions = sum(sum(t.success_memory.values()) for t in praxans if hasattr(t, 'success_memory'))
                failed_actions = sum(sum(t.failure_memory.values()) for t in praxans if hasattr(t, 'failure_memory'))
                total_actions = successful_actions + failed_actions
                success_rate = (successful_actions / total_actions * 100) if total_actions > 0 else 0
                q_learning_stats = f"\n- AI Learning: {avg_q_entries:.0f} learned actions per praxan, {success_rate:.0f}% success rate"
        
        # Skill distribution
        skill_levels = {'novice': 0, 'intermediate': 0, 'expert': 0}
        for t in praxans:
            skill_key = get_role_skill_key(t.role)
            if t.role and skill_key and skill_key in t.skills:
                # Count role
                if t.role in role_distribution:
                    role_distribution[t.role] += 1
                # Count skill level
                level = t.skills[skill_key]['level']
                if level >= 3:
                    skill_levels['expert'] += 1
                elif level >= 2:
                    skill_levels['intermediate'] += 1
                else:
                    skill_levels['novice'] += 1
        
        # Build context section
        recent_events_text = ""
        if self.events_history:
            recent_events = [e for e in self.events_history if time.time() - e['time'] < 60]
            if recent_events:
                recent_events_text = "\nRecent Events (last 60s):\n" + "\n".join([f"- {e['description']}" for e in recent_events[-5:]])
        
        # Previous strategy
        previous_strategy_text = ""
        if self.history:
            last_query = self.history[-1]
            previous_strategy_text = f"\nPrevious Strategy (30s ago):\n{last_query.get('summary', 'No previous strategy')}"
        
        # Build evolution system text
        active_mods_text = "\n".join([f"- {k}: {v:.2f}x" for k, v in self.game_modifiers.permanent.items()]) if self.game_modifiers.permanent else "- None"
        unlocked_techs_text = ', '.join([self.tech_tree[t]['name'] for t in self.game_modifiers.tech_unlocked]) if self.game_modifiers.tech_unlocked else 'None'
        
        # Available techs
        available_techs = []
        for tech_id, data in self.tech_tree.items():
            if tech_id not in self.game_modifiers.tech_unlocked:
                if all(req in self.game_modifiers.tech_unlocked for req in data.get('requires', [])):
                    available_techs.append(f"- {tech_id}: {data['name']} (cost: {data['cost']} points) - Effect: {data['effect']}")
        available_techs_text = "\n".join(available_techs[:8])
        
        # Meta insights
        buildings_built_text = ', '.join([f"{k}: {v}" for k, v in self.session_stats['buildings_built'].items()]) if self.session_stats['buildings_built'] else 'None yet'
        deaths_text = ', '.join([f"{k}: {v}" for k, v in self.session_stats['deaths_by_cause'].items()]) if self.session_stats['deaths_by_cause'] else 'No deaths yet'
        settlement = self.current_settlement_state or {}
        settlement_summary_text = f"""
Settlement Identity:
- Prosperity: {int(settlement.get('prosperity_score', 0.0) * 100)}%
- Culture: {int(settlement.get('culture_score', 0.0) * 100)}%
- District focus: {settlement.get('district_identity', 'homestead')}
- Dominant biome: {settlement.get('dominant_biome', 'plains')}
- Festival readiness: {int(settlement.get('festival_readiness', 0.0) * 100)}%
- Landmark tier: {settlement.get('landmark_level', 1)}
- Festival active: {'yes' if settlement.get('festival_active') else 'no'}"""
        
        prompt = f"""You are a strategic advisor for a civilization of {num_praxans} praxans.

=== RESPONSE CONTRACT ===
- Primary Ollama model target: {PREFERRED_OLLAMA_MODEL}
- You are running locally through Ollama with Qwen.
- Respond with either the exact text `No changes` OR one raw JSON object.
- Do not include markdown fences, prose preambles, or <think> tags.

=== GAME SCALE & LIMITS ===
- World Size: 2048x1536 pixels (64x48 tiles)
- Population Cap: {MAX_POPULATION} praxans (soft limit for performance)
- Initial Population: {INITIAL_POPULATION} praxans
- Territory System: Voronoi-based, expands dynamically from praxan/building positions
- Movement Speed: 0.75 px/frame (slow, deliberate expansion)
- Resource Spawn: Food respawns every 30s, wood/stone are finite (biome-specific)

=== GAME MECHANICS ===
Buildings:
{chr(10).join(format_building_prompt_lines())}
- Buildings level up automatically when clustered into stronger districts.

Praxan Behavior:
- Hunger decreases over time and increases when eating food
- Energy decreases over time, faster at night (0.042 vs 0.021)
- Thirst decreases over time, must drink from wells to survive
- Health decreases from unmet needs, age, and disease
- Praxans can die from old age (7 minute lifespan) or health failure
- Praxans gain skills and level up with experience
- Social bonds form between praxans working together (bonds >70 form factions)
- Disease outbreaks occur based on population density and hygiene
- Praxans automatically eat food when near resources/farms
- Praxans rest in houses when energy < 30
- Praxans can reproduce when needs met, with a 45s cooldown
- Morale, inspiration, favorite biome, and settlement prosperity all influence output

AI Decision Systems:
- Behavior Trees: Praxans use hierarchical decision trees that prioritize survival, then directives, then group tasks
- Q-Learning: Praxans learn from success/failure, adapting actions over time (30% exploration rate)
- Factions: Groups of 2-3+ praxans with bonds >70 can work together on coordinated tasks
- Boids Clustering: Praxans naturally cluster when working on same tasks (cohesion/separation forces)
- Territory: Voronoi-based dynamic territory expansion from praxan/building positions

Building Efficiency Guidelines:
- Build 1 storage per 5 praxans MAX (avoid overbuilding)
- Build houses to support population (1 house per 2 praxans)
- Farms should roughly match population for sustainable food
- Wells are CRITICAL for thirst needs and disease prevention (aim for 1 well per 10 population)

=== CURRENT CIVILIZATION STATUS ===
Population: {num_praxans} praxans
- Roles: {role_distribution['gatherer']} gatherers, {role_distribution['builder']} builders, {role_distribution['explorer']} explorers
- Skills: {skill_levels['novice']} novice, {skill_levels['intermediate']} intermediate, {skill_levels['expert']} expert
- Needs: {hungry_count} hungry (<50), {energy_low_count} low energy (<50), {can_reproduce_count} ready to reproduce
- Health: {diseased_count} diseased praxans, avg health: {avg_health:.1f}/100
- Wealth: {self.session_stats.get('colony_wealth', 0):.0f} total colony value (higher wealth draws stronger threats)
- Social Bonds: {avg_bonds_per_praxan:.1f} bonds per praxan, {strong_bonds} strong bonds (>70){faction_info}{q_learning_stats}

Resources:
- On map: {num_food} wild food, {num_wood} wild wood, {num_stone} stone
- Carried: {total_food_inv} food, {total_wood_inv} wood, {total_stone_inv} stone
- In storage: {total_food_in_storage} food, {total_wood_in_storage} wood
- In farms: {total_food_in_farms} ready-to-harvest food

Building Infrastructure:
- {building_counts['house']} houses (capacity: {building_counts['house'] * 2} praxans)
- {building_counts['storage']} storage (recommended: {max(1, num_praxans // 5)})
- {building_counts['farm']} farms (producing ~{building_counts['farm'] / 10:.1f} food/sec)
- {building_counts['workshop']} workshops, {building_counts['shrine']} shrines, {building_counts['well']} wells
{settlement_summary_text}"""
        
        # Calculate territory stats (Voronoi-based dynamic territory)
        territory_text = ""
        if territory_manager:
            territory_tiles = sum(1 for v in territory_manager.territory_grid.values() if v['claim_strength'] >= 50)
            if territory_tiles > 0:
                avg_claim_strength = sum(v['claim_strength'] for v in territory_manager.territory_grid.values()) / max(1, len(territory_manager.territory_grid))
                bounds = territory_manager.get_territory_bounds()
                voronoi_seeds = len(territory_manager.voronoi_seeds) if hasattr(territory_manager, 'voronoi_seeds') else 0
                if bounds:
                    territory_text = f"""
Territory Status (Voronoi-based dynamic expansion):
- Claimed tiles: {territory_tiles} (~{territory_tiles * 0.4:.1f} tiles²)
- Average claim strength: {avg_claim_strength:.1f}%
- Territory center: ({bounds['center_x']:.0f}, {bounds['center_y']:.0f})
- Active territory seeds: {voronoi_seeds} (praxans + buildings)"""
        
        # Get city plan summary
        city_plan_text = ""
        if city_planner and city_planner.current_plan:
            city_plan_text = f"""
Current City Plan:
{city_planner.get_plan_summary()}"""
        
        # Biome distribution
        biome_dist_text = ""
        if world_map and buildings:
            biome_counts = {}
            for building in buildings:
                biome_type = world_map.get_biome_at(building.x, building.y)
                biome_counts[biome_type] = biome_counts.get(biome_type, 0) + 1
            if biome_counts:
                biome_dist = ', '.join([f"{count} in {biome}" for biome, count in biome_counts.items()])
                biome_dist_text = f"\nBiomes: {biome_dist}"
        
        prompt += f"""
{territory_text}
{city_plan_text}
{biome_dist_text}

Civilization Health:
- Average hunger: {avg_hunger:.1f}/100 (target: >70)
- Average energy: {avg_energy:.1f}/100 (target: >70)
- Average health: {avg_health:.1f}/100
- Average happiness: {avg_happiness:.1f}/100
- Total deaths: {self.total_deaths}
- Population cap: {MAX_POPULATION} (current: {num_praxans}/{MAX_POPULATION})
{previous_strategy_text}
{recent_events_text}

=== EVOLUTION & RESEARCH SYSTEM ===
Available Research Points: {self.research_points} (spent: {self.points_spent})

Active Modifiers:
{active_mods_text}

Unlocked Technologies: {unlocked_techs_text}

Available Technologies to Unlock:
{available_techs_text}

You can issue EVOLUTION COMMANDS:
1. TECH|tech_id|reasoning - Unlock permanent technology
2. EVOLVE|mechanic|multiplier|reasoning - Temporary modifier (2 min, cost scales)
3. ABILITY|ability_name|reasoning - Trigger instant ability
4. CHALLENGE|type|reasoning - Spawn challenge for bonus points

Available mechanics to evolve temporarily:
- farm_production_rate, house_capacity, praxan_speed
- reproduction_cooldown, skill_xp_gain, happiness_modifier
- gather_efficiency, build_speed, disease_resistance

Available Abilities:
- speed_burst (50 pts, 30s, +100% speed)
- workers_focus (75 pts, 60s, +50% gather, +30% build)
- heal_wave (100 pts, instant, +50 health all)
- resource_blessing (80 pts, instant, spawn 5 resources)

Cost formula: base_cost * (1.5 ^ times_used), capped at 2.0x modifier range

=== META INSIGHTS (Historical Data) ===
Buildings Built This Session:
{buildings_built_text}

Death Analysis:
{deaths_text}

Average Survival Time: {self.session_stats['avg_survival_time']:.1f} seconds
"""
        
        # Add restraint and focus guidance if state_summary provided
        if state_summary:
            # Rotate focus every 2 queries
            if self.query_count % 2 == 0:
                focus_idx = (self.query_count // 2) % len(self.focus_areas)
                self.current_focus = self.focus_areas[focus_idx]
            
            crisis_flags_str = ', '.join(state_summary['crisis_flags']) if state_summary['crisis_flags'] else "None"
            intervention_reason_str = intervention_reason if intervention_reason else "routine"
            
            focus_guidance = {
                'resources': "Focus: Assess food/wood/stone availability. Intervene only if shortages detected.",
                'infrastructure': "Focus: Assess housing/farms/storage adequacy. Intervene only if capacity insufficient.",
                'territory': "Focus: Assess territorial expansion. Intervene only if stagnant or hazardous areas unclaimed.",
                'population': "Focus: Assess population health/growth. Intervene only if declining or overcrowded."
            }
            
            prompt += f"""

=== ASSESSMENT DIRECTIVE ===
Your PRIMARY role is to observe and assess. Intervene ONLY when necessary.

State Summary: {state_summary['summary_text']}
Crisis Flags: {crisis_flags_str}
Intervention Reason: {intervention_reason_str}
Current Focus: {self.current_focus}

RESTRAINT GUIDELINES:
1. If all metrics >60% and no crisis flags: Output 'No changes' or minimal observation
2. Propose changes ONLY if:
   - Any metric <50% (critical)
   - Crisis flags present
   - Major milestone reached (e.g., pop doubled, new territory)
3. When stable, acknowledge with: "Civilization progressing well. Monitoring." then NO directives
4. When intervening, be SPECIFIC and MINIMAL (1-3 directives max)

INTERVENTION SCALE:
- Stable (metrics >70%): "No changes needed"
- Mild concern (metrics 50-70%): 1 conditional directive
- Crisis (metrics <50%): 2-3 targeted directives

CURRENT FOCUS AREA: {focus_guidance.get(self.current_focus, '')}

EXAMPLE 1 - Stable Civilization:
State: Pop 12 (stable) | Food 85% (abundant) | Needs: Hunger 78%, Energy 82% (healthy) | Territory: 65% claimed
Assessment: "Civilization thriving. Praxans managing resources autonomously. No intervention required."
Output: 'No changes'

EXAMPLE 2 - Mild Concern:
State: Pop 15 (stable) | Food 55% (adequate) | Needs: Hunger 62%, Energy 71% (stressed) | Territory: 70% claimed
Assessment: "Food reserves declining but not critical. Preemptive farming recommended."
Output:
{{
  "individual": {{}},
  "communal": "If food drops below 50%, prioritize farm construction",
  "conditions": {{"hunger<60": "Focus 2 gatherers on food collection"}}
}}

EXAMPLE 3 - Crisis:
State: Pop 8 (declining) | Food 25% (scarce) | Needs: Hunger 42%, Energy 38% (stressed) | Territory: 45% claimed
Assessment: "FOOD CRISIS detected. Immediate action required."
Output:
{{
  "individual": {{"0": "Build farm immediately if 5 wood available", "1": "Gather food urgently"}},
  "communal": "All gatherers prioritize food - survival mode",
  "conditions": {{"hunger<50": "Drop all tasks, gather food from any source"}}
}}

=== YOUR STRATEGIC MISSION ===
Provide strategic directives in JSON format for autonomous praxan AI. You can issue both individual instructions (for specific praxans) and communal tasks (for groups).

**REQUIRED JSON FORMAT:**
{{
  "individual": {{
    "0": "Scout north, then gather if safe",
    "1": "Focus on farming skills - gather food from farms",
    "2": "Build farm when wood available"
  }},
  "communal": "Form party of 3 for building if pop>5",
  "team_task": {{
    "faction_id": 0,
    "task": "build workshop",
    "count": 3,
    "reasoning": "Faction 0 has strong bonds, assign coordinated building task"
  }},
  "conditions": {{
    "hunger<50": "Prioritize farm else explore in pairs",
    "population>5": "Assign 2 explorers to scout east"
  }}
}}

**Field Definitions:**
- "individual": Object mapping praxan IDs (as strings) to specific instructions. Use IDs 0-{num_praxans-1}.
- "communal": String describing group tasks (e.g., "Form party of 3 for building", "Coordinate gathering party of 2")
- "team_task": Object for faction-based coordinated tasks. Format: {{"faction_id": 0, "task": "build workshop", "count": 3, "reasoning": "reason"}}. Only use if factions exist ({num_factions} active). Faction IDs are 0-{num_factions-1}.
- "conditions": Object mapping game state conditions to adaptive behaviors. Conditions use format: "metric<value" or "metric>value" (e.g., "hunger<50", "population>5")

**Few-Shot Examples:**

Example 1 - Individual Focus:
{{
  "individual": {{
    "0": "Gather wood for upcoming construction",
    "1": "Explore north territory for new resources"
  }},
  "communal": "",
  "conditions": {{}}
}}

Example 2 - Communal Task:
{{
  "individual": {{}},
  "communal": "Form building party: assign 3 praxans to construct farm together",
  "conditions": {{
    "population>5": "If pop>5, form exploration party of 2"
  }}
}}

Example 2b - Faction Team Task (use when factions exist):
{{
  "individual": {{}},
  "communal": "",
  "team_task": {{
    "faction_id": 0,
    "task": "build workshop near houses",
    "count": 3,
    "reasoning": "Faction 0 members work well together, assign coordinated workshop construction"
  }},
  "conditions": {{}}
}}

Example 3 - Conditional Behavior:
{{
  "individual": {{
    "0": "Focus on gathering skills development"
  }},
  "communal": "",
  "conditions": {{
    "hunger<50": "All gatherers prioritize food collection",
    "energy<30": "Direct builders to rest in houses"
  }}
}}

**LEGACY FORMAT (still supported):**
Legacy fallback only if you absolutely cannot produce JSON:
priority|action|reasoning
Examples:
9|build 2 farms immediately|population hungry (avg {avg_hunger:.1f}/100), farms produce food automatically
7|gather wood|need 4 wood for 2 farms to sustain population

CRITICAL RULES:
- Avoid building excessive storage! Build only 1 per 5 population maximum.
- Wells are essential for survival - prioritize when population > {building_counts['well'] * 10}
- Build farms when average hunger < 70
- Workshops boost nearby gathering - consider strategic placement
- Individual directives override default behavior for specific praxans
- Communal tasks automatically form coordinated groups
- Team tasks assign to specific factions (factions form from bonds >70, {num_factions} active now)
- Conditions adapt behavior based on current game state
- Praxans learn from experience (Q-learning) - repeated failures indicate need for intervention
- Behavior trees prioritize survival over directives - don't issue directives during critical needs

STRATEGIC CITY PLANNING:
- Territory grows via Voronoi diagram from praxan/building positions. Dynamic expansion.
- Praxans cluster naturally via Boids algorithm when working together - leverage this
- Cluster related buildings: farms->storage, houses->wells, workshops->civic buildings
- Consider biomes: farms in plains/forest, houses avoid swamps/deserts
- Avoid hazards and difficult terrain (mountains, swamps)
- Factions work better together - use team_task for coordinated builds when factions exist
- If population > 10, you can provide city plan in JSON format:

CITY PLAN JSON FORMAT (optional, for major development):
{{
  "districts": [
    {{"type": "residential", "priority": 8, "location": "center", "buildings": ["house", "well"]}},
    {{"type": "production", "priority": 7, "location": "north", "buildings": ["farm", "storage"]}}
  ],
  "expansion_direction": "east|west|north|south",
  "rationale": "Brief reason for plan"
}}

{f'''
=== PLAYER SUGGESTION ===
The observer has suggested: "{player_suggestion}"

Evaluate this suggestion against current needs and resources:
1. Is it feasible given current resources/population?
2. Does it align with survival priorities?
3. Should it be accepted (add as directive), modified, or politely declined?

If accepting/modifying, include appropriate directives in your response.
If declining, return `No changes` or JSON with minimal cautionary directives only.
''' if player_suggestion else ''}
Your response MUST be either:
1. The exact text `No changes`
2. One raw JSON object following the schema above
3. Legacy directive lines only if JSON truly fails

Do not add prose before the JSON or directive lines.

Directives:"""
        
        try:
            print("\n[Civilization Advisor] Querying LLM for strategic guidance...")
            print(f"[Civilization Advisor] Population: {num_praxans}, Resources: {num_resources}, Buildings: {sum(building_counts.values())}")

            response_text, model_used = generate_ollama_text(prompt, purpose="advisor")
            print(f"[Civilization Advisor] Successfully queried {model_used}")
            
            print(f"[Civilization Advisor] LLM Response ({len(response_text)} chars):\n{response_text[:300]}...\n")
            
            # Try to parse JSON directives first, fall back to legacy format
            json_parsed = self.parse_json_directives(response_text)
            if json_parsed is None:
                # LLM returned "No changes" - already handled in parse_json_directives
                print("[Advisor] No intervention from LLM - civilization stable")
                # Clear all directives when no intervention needed
                self.directives = []
                # Calculate and report intervention rate
                intervention_rate = self.intervention_stats['interventions'] / max(1, self.intervention_stats['total_queries'])
                print(f"[Advisor Stats] Intervention Rate: {intervention_rate:.1%} (Target: <30%)")
            elif json_parsed and (json_parsed.get('individual') or json_parsed.get('communal') or json_parsed.get('conditions')):
                print(f"[Civilization Advisor] Parsed JSON directives: {len(json_parsed.get('individual', {}))} individual, communal: {bool(json_parsed.get('communal'))}, conditions: {len(json_parsed.get('conditions', {}))}")
                
                # Clear legacy directives when using JSON directives
                self.directives = []
                
                # Validate individual directives
                for praxan_id, instruction in list(json_parsed.get('individual', {}).items()):
                    directive = {'action': instruction, 'priority': 8}
                    is_valid, errors = self.validate_directive(directive, praxans, buildings, resources)
                    if not is_valid:
                        print(f"[Directive Validation] Invalid directive for praxan {praxan_id}: {', '.join(errors)}")
                        # Remove invalid directive
                        if praxan_id in self.json_directives['individual']:
                            del self.json_directives['individual'][praxan_id]
            else:
                # Fall back to legacy parse_directives
                parsed_data = self.parse_directives(response_text)
                print(f"[Civilization Advisor] Parsed {len(self.directives)} legacy directives")
                
                # Validate legacy directives
                validated_directives = []
                for directive in self.directives:
                    is_valid, errors = self.validate_directive(directive, praxans, buildings, resources)
                    if is_valid:
                        validated_directives.append(directive)
                    else:
                        print(f"[Directive Validation] Vetoed directive: {directive['action']} - {', '.join(errors)}")
                self.directives = validated_directives
            
            # Only warn if we have neither JSON directives nor legacy directives
            has_json_directives = (json_parsed and 
                                 (json_parsed.get('individual') or 
                                  json_parsed.get('communal') or 
                                  json_parsed.get('conditions')))
            has_legacy_directives = len(self.directives) > 0
            
            if not has_json_directives and not has_legacy_directives:
                print("[Civilization Advisor] WARNING: No directives parsed! LLM may not have followed format.")
                # Try to extract any actionable text as a single directive
                if 'build' in response_text.lower() or 'gather' in response_text.lower():
                    self.directives = [
                        {'priority': 5, 'action': response_text[:50], 'reasoning': 'LLM response (format may be incorrect)'}
                    ]
            
            # Parse evolution commands if narrative panel available
            if narrative_panel:
                self.parse_evolution_commands(response_text, narrative_panel, praxans, resources, buildings)
            
            # Store in history (keep last 5)
            history_entry = {
                'time': time.time(),
                'summary': response_text[:200],  # First 200 chars
                'directives': self.directives.copy(),
                'directive_count': len(self.directives)
            }
            self.history.append(history_entry)
            if len(self.history) > 5:
                self.history.pop(0)
        except Exception as e:
            print(f"[Civilization Advisor] ERROR: LLM query failed: {e}")
            print(f"[Civilization Advisor] Make sure Ollama is running: 'ollama serve'")
            print(f"[Civilization Advisor] Install a model: 'ollama pull {PREFERRED_OLLAMA_MODEL}'")
            # Fallback to smart directive based on game state
            if len(praxans) < 3:
                fallback_action = "gather food and wood to build first house"
            elif building_counts.get('well', 0) < len(praxans) // 10:
                fallback_action = "build 1 well immediately"
            elif building_counts.get('farm', 0) < len(praxans) / 2:
                fallback_action = "build farms for food production"
            else:
                fallback_action = "continue gathering resources"
            self.directives = [
                {'priority': 5, 'action': fallback_action, 'reasoning': f'LLM unavailable - {fallback_action}'}
            ]

    def has_pending_llm_jobs(self):
        if self.pending_strategy_job is not None or self.pending_goal_job is not None:
            return True
        if self.llm_scheduler and self.llm_scheduler.has_active_jobs():
            return True
        return False

    def get_llm_status_label(self, fallback_model=None):
        if self.llm_scheduler:
            active = self.llm_scheduler.get_active_channels()
            if active:
                return f"{'+'.join(active)}"
        if self.pending_strategy_job:
            elapsed = time.time() - self.pending_strategy_job.get("queued_at", time.time())
            return f"advisor {elapsed:.0f}s"
        if self.pending_goal_job:
            elapsed = time.time() - self.pending_goal_job.get("queued_at", time.time())
            return f"goals {elapsed:.0f}s"
        if self.last_llm_error and time.time() - self.last_job_completed_at < LLM_BACKOFF_SECONDS:
            return "cooldown"
        return self.last_model_used or fallback_model or PREFERRED_OLLAMA_MODEL

    # ── Multi-channel scheduling (V2) ─────────────────────────────

    def ensure_scheduler(self):
        """Create the LLM scheduler lazily (requires OllamaClient)."""
        if self.llm_scheduler is None and LLM_ENABLED:
            from praxans_game import _get_llm_client
            client = _get_llm_client()
            self.llm_scheduler = LLMScheduler(
                client, max_concurrent=2, default_backoff=LLM_BACKOFF_SECONDS
            )
        return self.llm_scheduler is not None

    def queue_channel_reviews(
        self,
        current_time,
        praxans,
        resources,
        buildings,
        state_summary,
        faction_manager=None,
    ):
        """Submit channel jobs when their cadence interval has elapsed."""
        if not self.ensure_scheduler():
            return

        sched = self.llm_scheduler
        settlement = self.current_settlement_state or {}

        # --- Council channel ---
        if current_time - self._channel_last_fire[CHANNEL_COUNCIL] >= COUNCIL_REVIEW_INTERVAL:
            should, reason, flags = self._should_intervene(state_summary, current_time)
            if should:
                view = build_council_view(
                    population=len(praxans),
                    buildings={b.building_type: sum(1 for x in buildings if x.building_type == b.building_type) for b in buildings},
                    resources_on_map={
                        "food": sum(1 for r in resources if r.resource_type == "food" and not r.collected),
                        "wood": sum(1 for r in resources if r.resource_type == "wood" and not r.collected),
                        "stone": sum(1 for r in resources if r.resource_type == "stone" and not r.collected),
                    },
                    resources_carried={
                        "food": sum(t.inventory["food"] for t in praxans),
                        "wood": sum(t.inventory["wood"] for t in praxans),
                        "stone": sum(t.inventory["stone"] for t in praxans),
                    },
                    avg_needs={
                        "hunger": sum(t.needs["hunger"] for t in praxans) / max(1, len(praxans)),
                        "energy": sum(t.needs["energy"] for t in praxans) / max(1, len(praxans)),
                        "health": sum(t.health for t in praxans) / max(1, len(praxans)),
                        "morale": sum(getattr(t, "morale", 65) for t in praxans) / max(1, len(praxans)),
                    },
                    diseased_count=sum(1 for t in praxans if t.diseased),
                    settlement=settlement,
                    faction_summaries=[
                        {
                            "id": f.id,
                            "doctrine": f.primary_doctrine,
                            "cohesion": f.cohesion,
                            "member_count": len(f.member_ids),
                            "rivals": list(f.rival_faction_ids),
                        }
                        for f in list((faction_manager.factions if faction_manager else {}).values())[:4]
                    ],
                    praxan_snapshot=[
                        {
                            "id": t.id,
                            "role": t.role or "unassigned",
                            "hunger": t.needs["hunger"],
                            "energy": t.needs["energy"],
                            "health": t.health,
                            "morale": getattr(t, "morale", 65),
                            "memory_personal": (
                                t.episodic_memory.most_significant_text(3)
                                if hasattr(t, "episodic_memory") and t.episodic_memory and t.episodic_memory.memory_count > 0
                                else ""
                            ),
                        }
                        for t in praxans[:8]
                    ],
                    crisis_flags=state_summary.get("crisis_flags", []),
                    summary_text=state_summary.get("summary_text", ""),
                    intervention_reason=reason,
                    current_focus=self.current_focus,
                    memory_civ_digest=self.llm_memory.civilization.digest_text(),
                    memory_faction_digest="\n".join(
                        self.llm_memory.factions.digest_text(fid)
                        for fid in self.llm_memory.factions.all_faction_ids()
                    ),
                    building_prompt_lines=format_building_prompt_lines(),
                )
                prompt = build_council_prompt(view, PREFERRED_OLLAMA_MODEL)
                if sched.submit(CHANNEL_COUNCIL, prompt, priority=10, stale_key=f"council_{int(current_time)}"):
                    self._channel_last_fire[CHANNEL_COUNCIL] = current_time

        # --- Faction channel ---
        if (
            faction_manager
            and faction_manager.factions
            and current_time - self._channel_last_fire[CHANNEL_FACTION] >= FACTION_REVIEW_INTERVAL
        ):
            for faction in list(faction_manager.factions.values())[:2]:
                view = build_faction_view(
                    faction_id=faction.id,
                    faction_name=getattr(faction, "name", f"Faction {faction.id}"),
                    doctrine=faction.primary_doctrine,
                    cohesion=faction.cohesion,
                    member_count=len(faction.member_ids),
                    rival_ids=list(faction.rival_faction_ids),
                    leader_id=getattr(faction, "leader_id", None),
                    schism_pressure=getattr(faction, "schism_pressure", 0),
                    migration_pressure=getattr(faction, "migration_pressure", 0),
                    preferred_biome=getattr(faction, "preferred_biome", "plains"),
                    recent_events=self.llm_memory.factions.recent_text(faction.id),
                    faction_digest=self.llm_memory.factions.digest_text(faction.id),
                    colony_population=len(praxans),
                    colony_prosperity=settlement.get("prosperity_score", 0),
                )
                prompt = build_faction_prompt(view, PREFERRED_OLLAMA_MODEL)
                sched.submit(
                    CHANNEL_FACTION, prompt, priority=7,
                    stale_key=f"faction_{faction.id}_{int(current_time)}",
                )
            self._channel_last_fire[CHANNEL_FACTION] = current_time

        # --- Historian channel ---
        if current_time - self._channel_last_fire[CHANNEL_HISTORIAN] >= HISTORIAN_REVIEW_INTERVAL:
            recent = self.llm_memory.civilization.entries[-8:]
            if recent:
                view = build_historian_view(
                    recent_events=recent,
                    population=len(praxans),
                    settlement_summary=settlement.get("district_identity", "homestead"),
                    faction_count=len(faction_manager.factions) if faction_manager else 0,
                    memory_civ_digest=self.llm_memory.civilization.digest_text(),
                    trigger_event=recent[-1].get("summary", "") if recent else "",
                )
                prompt = build_historian_prompt(view, PREFERRED_OLLAMA_MODEL)
                if sched.submit(CHANNEL_HISTORIAN, prompt, priority=4, stale_key=f"hist_{int(current_time)}"):
                    self._channel_last_fire[CHANNEL_HISTORIAN] = current_time

        # --- Memory summarizer channel ---
        if current_time - self._channel_last_fire[CHANNEL_MEMORY] >= MEMORY_SUMMARY_INTERVAL:
            view = build_memory_view(
                civ_recent=self.llm_memory.civilization.recent_text(),
                faction_recent={
                    fid: self.llm_memory.factions.recent_text(fid)
                    for fid in self.llm_memory.factions.all_faction_ids()
                },
                map_recent=self.llm_memory.map.recent_text(),
                current_civ_digest=self.llm_memory.civilization.digest_text(),
                current_map_digest=self.llm_memory.map.digest_text(),
            )
            prompt = build_memory_prompt(view, PREFERRED_OLLAMA_MODEL)
            if sched.submit(CHANNEL_MEMORY, prompt, priority=2, stale_key=f"mem_{int(current_time)}"):
                self._channel_last_fire[CHANNEL_MEMORY] = current_time

        # --- Muse channel ---
        MUSE_INTERVAL = 120.0
        if praxans and current_time - self._channel_last_fire[CHANNEL_MUSE] >= MUSE_INTERVAL:
            from llm.prompts import build_muse_prompt
            from llm.state_views import build_muse_view
            candidates = [p for p in praxans if (getattr(p, 'inspiration', 0) > 60 or p.personality.get('curiosity', 0) > 0.7) and getattr(p, 'alive', True)]
            if candidates:
                chosen = random.choice(candidates)
                recent_mem_text = chosen.episodic_memory.recent_text(5) if hasattr(chosen, 'episodic_memory') and chosen.episodic_memory else ""
                sig_mem_text = chosen.episodic_memory.most_significant_text(3) if hasattr(chosen, 'episodic_memory') and chosen.episodic_memory else ""
                
                view = build_muse_view(
                    id=chosen.id,
                    name=getattr(chosen, 'name', f'#{chosen.id}'),
                    role=chosen.role,
                    personality=chosen.personality,
                    traits=getattr(chosen, 'traits', []),
                    needs=chosen.needs,
                    health=chosen.health,
                    happiness=chosen.happiness,
                    current_action=chosen.current_action,
                    favorite_biome=chosen.favorite_biome,
                    recent_memories=recent_mem_text,
                    significant_memories=sig_mem_text,
                    nearby_buildings="",
                    nearby_praxans=""
                )
                prompt = build_muse_prompt(view, PREFERRED_OLLAMA_MODEL)
                if sched.submit(CHANNEL_MUSE, prompt, priority=3, stale_key=f"muse_{chosen.id}"):
                    self._channel_last_fire[CHANNEL_MUSE] = current_time
                    self._last_muse_praxan_id = chosen.id

    def poll_llm_channels(self, praxans, resources, buildings, narrative_panel=None, faction_manager=None):
        """Process completed multi-channel LLM jobs."""
        if not self.llm_scheduler:
            return

        completed = self.llm_scheduler.poll()
        for job in completed:
            self.last_job_completed_at = time.time()
            if job.error:
                self.last_llm_error = str(job.error)
                print(f"[LLM-V2] {job.channel} failed: {job.error}")
                continue

            self.last_model_used = job.model_used or self.last_model_used
            self.last_llm_error = None

            if job.channel == CHANNEL_COUNCIL:
                payload = parse_advisory_payload(job.response_text)
                if payload is None:
                    self.stability_counter += 1
                    self.intervention_stats["no_changes"] += 1
                else:
                    advisor_state = {
                        "council_state": self.council_state,
                        "current_focus": self.current_focus,
                        "json_directives": self.json_directives,
                        "directives": self.directives,
                        "advisory_history": self.advisory_history,
                        "session_stats": self.session_stats,
                    }
                    result = apply_council_payload(payload, advisor_state, faction_manager)
                    self.council_state = advisor_state["council_state"]
                    self.current_focus = advisor_state["current_focus"]
                    self.json_directives = advisor_state["json_directives"]
                    self.directives = advisor_state["directives"]
                    self.advisory_history = advisor_state["advisory_history"]
                    self.stability_counter = 0
                    self.intervention_stats["total_queries"] += 1
                    if result.get("intervened"):
                        self.intervention_stats["interventions"] += 1
                    self.process_communal_tasks(praxans, buildings, resources, faction_manager)
                    if payload.get("event_framing") and narrative_panel:
                        narrative_panel.add_message(payload["event_framing"], "Strategy")
                    # Record in memory
                    self.llm_memory.civilization.record(
                        "council",
                        payload.get("event_framing", "Council reviewed."),
                        time.time(),
                    )

            elif job.channel == CHANNEL_FACTION:
                from llm.contracts import parse_faction_intent_payload
                payload = parse_faction_intent_payload(job.response_text)
                if payload is not None and faction_manager:
                    fid = payload.get("faction_id", 0)
                    faction = faction_manager.get_faction(fid)
                    if faction:
                        result = apply_faction_intent(payload, faction, faction_manager)
                        self.llm_memory.factions.record(
                            fid, "intent", f"Intent: {result.get('intent', 'unknown')}", time.time()
                        )

            elif job.channel == CHANNEL_HISTORIAN:
                from llm.contracts import parse_historian_payload
                payload = parse_historian_payload(job.response_text)
                if payload is not None:
                    apply_historian(payload, narrative_panel=narrative_panel, memory=self.llm_memory)

            elif job.channel == CHANNEL_MEMORY:
                from llm.contracts import parse_memory_summary_payload
                payload = parse_memory_summary_payload(job.response_text)
                if payload is not None:
                    apply_memory_summary(payload, self.llm_memory)

            elif job.channel == CHANNEL_MUSE:
                from llm.contracts import parse_muse_payload
                payload = parse_muse_payload(job.response_text)
                if payload is not None:
                    # Extract target Praxan ID from the job's stale_key ("muse_<id>"),
                    # which is set immutably at submit time.  Using _last_muse_praxan_id
                    # would apply the result to the WRONG Praxan if a new muse job was
                    # submitted while this one was still executing (120s interval race).
                    pid = None
                    if job.stale_key.startswith("muse_"):
                        try:
                            pid = int(job.stale_key[len("muse_"):])
                        except ValueError:
                            pid = getattr(self, '_last_muse_praxan_id', None)
                    else:
                        pid = getattr(self, '_last_muse_praxan_id', None)
                    if pid is not None:
                        for p in praxans:
                            if p.id == pid:
                                p.inner_monologue = payload.get("inner_monologue")
                                p.spark_of_invention = payload.get("spark_of_invention")
                                p.personal_goal = payload.get("personal_goal")
                                mods = payload.get("behavior_modifier", {})
                                for k, v in mods.items():
                                    if k in p.work_priorities:
                                        p.work_priorities[k] = max(1, min(4, p.work_priorities[k] - v))
                                # Also grant a tiny inspiration boost
                                p.inspiration = min(100.0, p.inspiration + 10)
                                break

    def _format_environment_context(self) -> str:
        """Build a compact environment string for LLM prompts.

        Reads from ``self.environment_context`` which is synced each frame from
        the game loop.  Returns a short multi-line block like::

            - Season: Winter Y3 | Weather: Drought | Epoch: Ice Age
            - Land: avg fertility 52%, 2 Barren, 3 Stressed regions
        """
        env = getattr(self, "environment_context", None) or {}
        season = env.get("season", "unknown")
        year = env.get("year", "?")
        weather = env.get("weather", "clear")
        epoch = env.get("climate_epoch", "Holocene")
        eco = env.get("ecology", {})
        avg_f = eco.get("avg_fertility", 80)
        counts = eco.get("region_counts", {})
        distress_parts = []
        for status in ("Barren", "Degraded", "Stressed"):
            n = counts.get(status, 0)
            if n > 0:
                distress_parts.append(f"{n} {status}")
        land_detail = ", ".join(distress_parts) if distress_parts else "all healthy"
        return (
            f"- Season: {season.title()} Y{year} | Weather: {weather} | Epoch: {epoch}\n"
            f"- Land: avg fertility {avg_f:.0f}%, {land_detail}"
        )

    def _build_compact_strategy_request(
        self,
        praxans,
        resources,
        buildings,
        state_summary=None,
        intervention_reason=None,
        faction_manager=None,
    ):
        building_counts = {btype: 0 for btype in BUILDING_DEFINITIONS}
        for building in buildings:
            building_counts[building.building_type] = building_counts.get(building.building_type, 0) + 1

        settlement = self.current_settlement_state or {}
        avg_hunger = sum(t.needs["hunger"] for t in praxans) / max(1, len(praxans))
        avg_energy = sum(t.needs["energy"] for t in praxans) / max(1, len(praxans))
        avg_health = sum(t.health for t in praxans) / max(1, len(praxans)) if praxans else 100
        avg_happiness = sum(t.happiness for t in praxans) / max(1, len(praxans)) if praxans else 100
        avg_morale = sum(getattr(t, "morale", 65) for t in praxans) / max(1, len(praxans)) if praxans else 65
        diseased_count = sum(1 for t in praxans if t.diseased)
        total_food_inv = sum(t.inventory["food"] for t in praxans)
        total_wood_inv = sum(t.inventory["wood"] for t in praxans)
        total_stone_inv = sum(t.inventory["stone"] for t in praxans)
        map_food = sum(1 for r in resources if r.resource_type == "food" and not r.collected)
        map_wood = sum(1 for r in resources if r.resource_type == "wood" and not r.collected)
        map_stone = sum(1 for r in resources if r.resource_type == "stone" and not r.collected)
        faction_count = len(getattr(faction_manager, "factions", {})) if faction_manager else 0

        praxan_lines = "\n".join(
            [
                f"- {t.id}: role={t.role or 'unassigned'}, hunger={int(t.needs['hunger'])}, energy={int(t.needs['energy'])}, health={int(t.health)}, morale={int(getattr(t, 'morale', 65))}, carrying={t.inventory}"
                for t in praxans[:8]
            ]
        ) or "- none"
        crisis_flags = ", ".join(state_summary.get("crisis_flags", [])) if state_summary else "none"
        summary_text = state_summary.get("summary_text", "No state summary available.") if state_summary else "No state summary available."
        available_buildings = ", ".join(
            [
                f"{building_type}:{building_counts.get(building_type, 0)}"
                for building_type in ("house", "farm", "storage", "well", "workshop", "shrine")
            ]
        )
        faction_lines = []
        if faction_manager and getattr(faction_manager, "factions", {}):
            for faction in list(faction_manager.factions.values())[:4]:
                faction_lines.append(
                    f"- F{faction.id}: doctrine={faction.primary_doctrine}, cohesion={int(faction.cohesion)}, members={len(faction.member_ids)}, rivals={faction.rival_faction_ids}"
                )
        faction_text = "\n".join(faction_lines) or "- none"

        prompt = f"""You are the strategic council for a local autonomous colony sim.
Target model: {PREFERRED_OLLAMA_MODEL}
Return either the exact text No changes or one raw JSON object.
No markdown fences. No prose preamble. No <think> tags.

Mission:
- Co-govern the colony without changing rules directly.
- Suggest doctrine, priorities, faction goals, and a small set of directives.
- Never invent technologies, abilities, modifiers, or raw rule mutations.

Current review trigger: {intervention_reason or 'routine'}
State summary: {summary_text}
Crisis flags: {crisis_flags}
Current focus: {self.current_focus}

Colony:
- Population: {len(praxans)}
- Buildings: {available_buildings}
- Resources on map: food={map_food}, wood={map_wood}, stone={map_stone}
- Carrying: food={total_food_inv}, wood={total_wood_inv}, stone={total_stone_inv}
- Avg needs: hunger={avg_hunger:.0f}, energy={avg_energy:.0f}, health={avg_health:.0f}, happiness={avg_happiness:.0f}, morale={avg_morale:.0f}
- Colony Wealth: {self.session_stats.get('colony_wealth', 0):.0f} (higher wealth = deadlier threats)
- Diseased praxans: {diseased_count}
- District: {settlement.get('district_identity', 'homestead')}
- Prosperity: {int(settlement.get('prosperity_score', 0.0) * 100)}%
- Culture: {int(settlement.get('culture_score', 0.0) * 100)}%
- Festival readiness: {int(settlement.get('festival_readiness', 0.0) * 100)}%
- Factions: {faction_count}

Environment:
{self._format_environment_context()}

Faction snapshot:
{faction_text}

Praxan snapshot:
{praxan_lines}

Building rules:
{chr(10).join(format_building_prompt_lines())}

Constraints:
- Max 2 individual directives.
- Max 1 communal directive.
- Use team_task only if factions > 0.
- Keep event_framing to one sentence.
- If stable, return No changes.

JSON schema:
{{
  "doctrine": {{
    "focus": "survival|growth|industry|territory|culture|health|stability",
    "stance": "measured|urgent|expansive|defensive|restorative",
    "district_priority": "homestead|agrarian|industrial|frontier|civic|sanctuary",
    "crisis_posture": "stabilize|expand|recover|fortify|consolidate",
    "reasoning": "brief"
  }},
  "strategic_priorities": [
    {{"key": "food_security", "weight": 0.9, "reasoning": "brief"}}
  ],
  "individual": {{"0": "short instruction"}},
  "communal": "short group instruction",
  "team_task": {{"faction_id": 0, "task": "build workshop", "count": 3, "reasoning": "brief"}},
  "conditions": {{"hunger<50": "prioritize food"}},
  "faction_goals": [
    {{"faction_id": 0, "goal": "secure water access", "reasoning": "brief", "doctrine_key": "security"}}
  ],
  "event_framing": "One short council sentence for the observer log."
}}"""
        prompt += "\n\nDirectives:"
        return {
            "prompt": prompt,
            "reason": intervention_reason or "routine",
            "population": len(praxans),
            "resource_count": sum(1 for resource in resources if not resource.collected),
            "building_count": len(buildings),
        }

    def queue_strategy_query(
        self,
        praxans,
        resources,
        buildings,
        state_summary=None,
        intervention_reason=None,
        faction_manager=None,
    ):
        if not LLM_ENABLED or self.has_pending_llm_jobs():
            return False

        request = self._build_compact_strategy_request(
            praxans,
            resources,
            buildings,
            state_summary=state_summary,
            intervention_reason=intervention_reason,
            faction_manager=faction_manager,
        )
        self.pending_strategy_job = start_async_llm_job(request["prompt"], "advisor", request)
        self.last_query_time = time.time()
        self.last_pop_count = len(praxans)
        self.last_llm_error = None
        print(
            f"[Advisor] Queued async strategy review: pop={request['population']}, resources={request['resource_count']}, buildings={request['building_count']}"
        )
        return True

    def _apply_bounded_advisory_payload(self, advisory_payload, faction_manager=None):
        self.council_state = advisory_payload or advisory_payload_defaults()
        doctrine = dict(self.council_state.get("doctrine", {}))
        focus_mapping = {
            "survival": "population",
            "growth": "population",
            "industry": "infrastructure",
            "territory": "territory",
            "culture": "population",
            "health": "resources",
            "stability": "resources",
        }
        self.current_focus = focus_mapping.get(doctrine.get("focus"), self.current_focus)
        self.json_directives = {
            "individual": dict(self.council_state.get("individual", {})),
            "communal": str(self.council_state.get("communal", "")),
            "conditions": dict(self.council_state.get("conditions", {})),
        }
        if self.council_state.get("team_task"):
            self.json_directives["team_task"] = dict(self.council_state.get("team_task", {}))

        if faction_manager is not None:
            for faction in faction_manager.factions.values():
                faction.shared_goals = []
            for goal in self.council_state.get("faction_goals", []):
                faction = faction_manager.get_faction(goal.get("faction_id"))
                if faction is None:
                    continue
                doctrine_key = goal.get("doctrine_key") or faction.primary_doctrine
                faction.assign_shared_goal(goal.get("goal", ""), goal.get("reasoning", ""), doctrine_key)

        append_bounded_history(
            self.advisory_history,
            {
                "time": time.time(),
                "doctrine": doctrine,
                "strategic_priorities": list(self.council_state.get("strategic_priorities", [])),
                "event_framing": str(self.council_state.get("event_framing", "")),
            },
            10,
        )
        self.session_stats["current_doctrine"] = doctrine
        self.session_stats["current_advisory_priorities"] = list(self.council_state.get("strategic_priorities", []))

    def _apply_strategy_response(self, response_text, model_used, praxans, resources, buildings, narrative_panel=None, faction_manager=None):
        self.last_model_used = model_used or self.last_model_used
        self.last_llm_error = None

        print(f"[Civilization Advisor] Async response from {model_used}: {response_text[:300]}...")

        advisory_payload = parse_advisory_payload(response_text)
        if advisory_payload is None:
            print("[Advisor] No intervention from LLM - civilization stable")
            self.council_state = advisory_payload_defaults()
            self.json_directives = {"individual": {}, "communal": "", "conditions": {}}
            self.directives = []
            intervened = False
        else:
            self._apply_bounded_advisory_payload(advisory_payload, faction_manager=faction_manager)
            validated_individual = {}
            for praxan_id, instruction in list(self.json_directives.get("individual", {}).items()):
                directive = {"action": instruction, "priority": 8}
                is_valid, errors = self.validate_directive(directive, praxans, buildings, resources)
                if is_valid:
                    validated_individual[praxan_id] = instruction
                else:
                    print(f"[Directive Validation] Invalid directive for praxan {praxan_id}: {', '.join(errors)}")
            self.json_directives["individual"] = validated_individual
            self.directives = [
                {
                    "priority": max(1, min(10, int(round(priority.get("weight", 0.5) * 10)))),
                    "action": str(priority.get("key", "monitor")),
                    "reasoning": str(priority.get("reasoning", "Council priority")),
                }
                for priority in self.council_state.get("strategic_priorities", [])[:3]
                if isinstance(priority, dict)
            ]
            intervened = bool(
                self.json_directives.get("individual")
                or self.json_directives.get("communal")
                or self.json_directives.get("conditions")
                or self.json_directives.get("team_task")
                or self.council_state.get("faction_goals")
                or self.directives
            )

        if not intervened and response_text and ("build" in response_text.lower() or "gather" in response_text.lower()):
            self.directives = [
                {
                    "priority": 5,
                    "action": response_text[:50],
                    "reasoning": "LLM response (format may be incorrect)",
                }
            ]
            intervened = True

        if narrative_panel and self.council_state.get("event_framing"):
            narrative_panel.add_message(self.council_state["event_framing"], "Strategy")

        history_entry = {
            "time": time.time(),
            "summary": response_text[:200],
            "directives": self.directives.copy(),
            "directive_count": len(self.directives),
        }
        self.history.append(history_entry)
        if len(self.history) > 5:
            self.history.pop(0)

        return {"intervened": intervened}

    def _apply_strategy_failure(self, error, praxans, buildings):
        self.last_llm_error = str(error)
        print(f"[Civilization Advisor] Async query failed: {error}")
        print(f"[Civilization Advisor] Make sure Ollama is running: 'ollama serve'")
        print(f"[Civilization Advisor] Install a model: 'ollama pull {PREFERRED_OLLAMA_MODEL}'")

        building_counts = {btype: 0 for btype in BUILDING_DEFINITIONS}
        for building in buildings:
            building_counts[building.building_type] = building_counts.get(building.building_type, 0) + 1

        if len(praxans) < 3:
            fallback_action = "gather food and wood to build first house"
        elif building_counts.get("well", 0) < len(praxans) // 10:
            fallback_action = "build 1 well immediately"
        elif building_counts.get("farm", 0) < len(praxans) / 2:
            fallback_action = "build farms for food production"
        else:
            fallback_action = "continue gathering resources"

        self.council_state = advisory_payload_defaults()
        self.json_directives = {"individual": {}, "communal": "", "conditions": {}}
        self.directives = [
            {"priority": 5, "action": fallback_action, "reasoning": f"LLM unavailable - {fallback_action}"}
        ]
        return {"intervened": True}

    def _build_goal_assignment_request(self, praxans, buildings):
        settlement = self.current_settlement_state or {}
        avg_hunger = sum(t.needs["hunger"] for t in praxans) / max(1, len(praxans))
        praxan_snapshot = "\n".join(
            [
                f"- {t.id}: role={t.role or 'unassigned'}, hunger={int(t.needs['hunger'])}, energy={int(t.needs['energy'])}, morale={int(getattr(t, 'morale', 65))}, biome={t.favorite_biome}"
                for t in praxans[:8]
            ]
        ) or "- none"

        prompt = f"""Assign at most 3 personal goals to specific praxans.
Respond with plain lines only.
No markdown. No JSON. No <think> tags.

Colony:
- Population: {len(praxans)}
- Buildings: {len(buildings)}
- Avg hunger: {avg_hunger:.0f}
- Research points: {self.research_points}
- District: {settlement.get('district_identity', 'homestead')}
- Prosperity: {int(settlement.get('prosperity_score', 0.0) * 100)}%
- Culture: {int(settlement.get('culture_score', 0.0) * 100)}%

Praxans:
{praxan_snapshot}

Format:
praxan_id|goal_type|target|reasoning

Goal types:
{chr(10).join(format_goal_type_lines())}

Directives:"""
        return {"prompt": prompt, "assigned_at": time.time()}

    def _apply_goal_assignments(self, response_text, praxans, assigned_at):
        assignments = 0
        for line in sanitize_llm_response(response_text).split("\n"):
            line = line.strip()
            if "|" not in line:
                continue
            parts = line.split("|")
            if len(parts) < 3:
                continue
            try:
                praxan_id = int(parts[0].strip())
            except ValueError:
                continue

            goal_type = parts[1].strip()
            target = parts[2].strip() if len(parts) > 2 else "auto"
            reason = parts[3].strip() if len(parts) > 3 else "LLM assigned"
            for praxan in praxans:
                if praxan.id == praxan_id:
                    praxan.personal_goal = {"type": goal_type, "target": target, "reason": reason}
                    praxan.goal_assigned_time = assigned_at
                    assignments += 1
                    print(f"[Goal] Praxan {praxan_id} assigned: {goal_type}")
                    break
        return assignments

    def poll_async_jobs(self, praxans, resources, buildings, narrative_panel=None, faction_manager=None):
        if self.pending_strategy_job and self.pending_strategy_job["done"].is_set():
            job = self.pending_strategy_job
            self.pending_strategy_job = None
            self.last_job_completed_at = time.time()
            self.intervention_stats["total_queries"] += 1

            if job.get("error") is not None:
                result = self._apply_strategy_failure(job["error"], praxans, buildings)
            else:
                result = self._apply_strategy_response(
                    job.get("response_text", ""),
                    job.get("model_used"),
                    praxans,
                    resources,
                    buildings,
                    narrative_panel=narrative_panel,
                    faction_manager=faction_manager,
                )
                self.query_count += 1

            self.process_communal_tasks(praxans, buildings, resources, faction_manager)
            if result.get("intervened"):
                self.intervention_stats["interventions"] += 1
                if job.get("metadata", {}).get("reason") == "crisis":
                    self.intervention_stats["crisis_interventions"] += 1
                if self.directives and narrative_panel:
                    top_directive = max(self.directives, key=lambda directive: directive["priority"])
                    narrative_panel.add_message(f"The Advisor: {top_directive['reasoning']}", "Strategy")
            else:
                self.intervention_stats["no_changes"] += 1

        if self.pending_goal_job and self.pending_goal_job["done"].is_set():
            job = self.pending_goal_job
            self.pending_goal_job = None
            self.last_job_completed_at = time.time()
            if job.get("error") is not None:
                self.last_llm_error = str(job["error"])
                print(f"[Goal Assignment] Error: {job['error']}")
            else:
                self.last_model_used = job.get("model_used") or self.last_model_used
                self.last_llm_error = None
                self._apply_goal_assignments(
                    job.get("response_text", ""),
                    praxans,
                    job.get("metadata", {}).get("assigned_at", time.time()),
                )
    
    def parse_directives(self, response_text):
        """Parse LLM response into structured directives"""
        self.directives = []
        lines = sanitize_llm_response(response_text).split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            # Look for format: priority|action|reasoning
            if '|' in line:
                parts = line.split('|')
                if len(parts) >= 2:  # At least priority and action
                    try:
                        priority_str = parts[0].strip()
                        # Extract number from priority (handle "9" or "priority: 9" or "9.")
                        priority = int(''.join(filter(str.isdigit, priority_str))) if priority_str else 5
                        priority = max(1, min(10, priority))  # Clamp to 1-10
                        
                        action = parts[1].strip()
                        reasoning = parts[2].strip() if len(parts) >= 3 else "No reasoning provided"
                        
                        self.directives.append({
                            'priority': priority,
                            'action': action,
                            'reasoning': reasoning
                        })
                        print(f"[Directive] Priority {priority}: {action} - {reasoning}")
                    except (ValueError, IndexError) as e:
                        # Try alternative parsing - look for numbers followed by action words
                        if any(word in line.lower() for word in ['build', 'gather', 'explore', 'assign']):
                            # Extract a priority number if present
                            numbers = [int(s) for s in line.split() if s.isdigit() and 1 <= int(s) <= 10]
                            priority = numbers[0] if numbers else 5
                            action = line
                            self.directives.append({
                                'priority': priority,
                                'action': action,
                                'reasoning': 'Parsed from alternative format'
                            })
                            print(f"[Directive] Priority {priority} (alt format): {action}")
                        continue
        
        # Sort by priority (highest first)
        self.directives.sort(key=lambda d: d['priority'], reverse=True)
        
        return {'directives': self.directives}
    
    def parse_json_directives(self, response_text):
        """Parse LLM JSON response into structured directives"""
        import json
        import re
        response_text = sanitize_llm_response(response_text)
        
        # Check for explicit no-intervention responses
        if any(phrase in response_text.lower() for phrase in ['no changes', 'no intervention', 'monitoring', 'progressing well']):
            print("[Advisor] LLM Assessment: No intervention needed")
            self.stability_counter += 1
            # Reset JSON directives to empty
            self.json_directives = {
                'individual': {},
                'communal': '',
                'conditions': {}
            }
            return None  # Return None to skip directive processing
        
        # Reset stability counter if intervening
        self.stability_counter = 0
        
        # Reset JSON directives
        self.json_directives = {
            'individual': {},
            'communal': '',
            'conditions': {}
        }
        
        # Try to extract JSON from response
        # Look for JSON block (between ```json and ``` or between { and })
        json_pattern = r'```json\s*(\{.*?\})\s*```'
        match = re.search(json_pattern, response_text, re.DOTALL)
        if match:
            json_str = match.group(1)
        else:
            # Look for JSON object directly
            json_match = re.search(r'\{[^{}]*"individual"[^{}]*\{[^{}]*\}[^{}]*\}', response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
            else:
                # Try to find any JSON-like structure
                brace_start = response_text.find('{')
                if brace_start != -1:
                    brace_end = response_text.rfind('}')
                    if brace_end > brace_start:
                        json_str = response_text[brace_start:brace_end+1]
                    else:
                        return self.json_directives
                else:
                    return self.json_directives
        
        try:
            # Parse JSON
            parsed = json.loads(json_str)
            
            # Extract individual directives
            if 'individual' in parsed and isinstance(parsed['individual'], dict):
                for praxan_id_str, instruction in parsed['individual'].items():
                    try:
                        praxan_id = int(praxan_id_str)
                        self.json_directives['individual'][praxan_id] = str(instruction)
                        print(f"[JSON Directive] Assigned to praxan {praxan_id}: {instruction}")
                    except (ValueError, TypeError):
                        print(f"[JSON Directive] Warning: Invalid praxan ID: {praxan_id_str}")
            
            # Extract communal task
            if 'communal' in parsed and parsed['communal']:
                self.json_directives['communal'] = str(parsed['communal'])
                print(f"[JSON Directive] Communal task: {parsed['communal']}")
            
            # Extract conditions
            if 'conditions' in parsed and isinstance(parsed['conditions'], dict):
                for condition, behavior in parsed['conditions'].items():
                    self.json_directives['conditions'][condition] = str(behavior)
                    print(f"[JSON Directive] Condition: {condition} -> {behavior}")
            
            # Extract team_task (for faction-based team assignments)
            if 'team_task' in parsed and isinstance(parsed['team_task'], dict):
                team_task_data = parsed['team_task']
                self.json_directives['team_task'] = team_task_data
                print(f"[JSON Directive] Team task: {team_task_data}")
            
        except json.JSONDecodeError as e:
            print(f"[JSON Directive] Failed to parse JSON: {e}")
            print(f"[JSON Directive] Attempted to parse: {json_str[:200]}...")
            # Fall back to legacy parse_directives if JSON fails
            self.parse_directives(response_text)
        
        return self.json_directives
    
    def process_communal_tasks(self, praxans, buildings, resources, faction_manager=None):
        """Process communal task descriptions and create GroupTask objects"""
        import re
        
        # Clear old inactive tasks
        self.group_tasks = [task for task in self.group_tasks if task.active]
        
        # Process team_task (faction-based team assignments)
        if 'team_task' in self.json_directives and isinstance(self.json_directives['team_task'], dict):
            team_task_data = self.json_directives['team_task']
            faction_id = team_task_data.get('faction_id')
            task_description = team_task_data.get('task', '')
            required_count = team_task_data.get('count', 3)
            
            if faction_manager and faction_id is not None:
                faction = faction_manager.get_faction(faction_id)
                if faction:
                    # Determine task type from description
                    task_type = 'build'
                    target_building_type = None
                    if 'gather' in task_description.lower():
                        task_type = 'gather'
                    elif 'explore' in task_description.lower():
                        task_type = 'explore'
                    elif 'build' in task_description.lower():
                        task_type = 'build'
                        for btype in ['farm', 'house', 'storage', 'workshop', 'shrine', 'well']:
                            if btype in task_description.lower():
                                target_building_type = btype
                                break
                        if target_building_type is None:
                            preferred = faction.doctrine_profile.get("preferred_buildings", [])
                            target_building_type = preferred[0] if preferred else None
                    
                    # Create GroupTask with faction pre-assigned members
                    new_task = GroupTask(
                        task_type=task_type,
                        description=task_description,
                        required_count=required_count,
                        target_building_type=target_building_type
                    )
                    new_task.faction_id = faction_id
                    
                    # Pre-assign faction members to task
                    for member_id in faction.member_ids[:required_count]:  # Assign up to required_count
                        new_task.add_praxan(member_id)
                    
                    self.group_tasks.append(new_task)
                    print(f"[Group Task] Created faction task: {task_type} for faction {faction_id} ({len(new_task.assigned_praxans)}/{required_count} assigned)")

        if faction_manager:
            existing_signatures = {
                (task.faction_id, task.description.strip().lower())
                for task in self.group_tasks
                if getattr(task, "faction_id", None) is not None
            }
            for faction in faction_manager.factions.values():
                if not faction.shared_goals:
                    continue
                latest_goal = faction.shared_goals[-1]
                goal_text = str(latest_goal.get("goal", "")).strip()
                if not goal_text:
                    continue
                signature = (faction.id, goal_text.lower())
                if signature in existing_signatures:
                    continue
                task_type = "build"
                target_building_type = None
                lowered_goal = goal_text.lower()
                if "gather" in lowered_goal or "secure" in lowered_goal:
                    task_type = "gather"
                elif "explore" in lowered_goal or "scout" in lowered_goal:
                    task_type = "explore"
                elif "build" in lowered_goal or "raise" in lowered_goal:
                    task_type = "build"
                for btype in BUILDING_DEFINITIONS:
                    if btype in lowered_goal:
                        target_building_type = btype
                        break
                if task_type == "build" and target_building_type is None:
                    preferred = faction.doctrine_profile.get("preferred_buildings", [])
                    target_building_type = preferred[0] if preferred else None
                new_task = GroupTask(
                    task_type=task_type,
                    description=goal_text,
                    required_count=max(2, min(4, len(faction.member_ids))),
                    target_building_type=target_building_type,
                )
                new_task.faction_id = faction.id
                for member_id in faction.member_ids[: new_task.required_count]:
                    new_task.add_praxan(member_id)
                self.group_tasks.append(new_task)
                existing_signatures.add(signature)
                print(f"[Group Task] Doctrine task: {task_type} for faction {faction.id}")
        
        communal_str = self.json_directives.get('communal', '')
        if not communal_str:
            return
        
        # Parse communal task descriptions
        # Examples: "Form party of 3 for building", "Coordinate gathering party of 2"
        party_match = re.search(r'party of (\d+)', communal_str.lower())
        if party_match:
            required_count = int(party_match.group(1))
        else:
            required_count = 3  # Default
        
        # Determine task type
        task_type = 'build'
        target_building_type = None
        if 'gather' in communal_str.lower():
            task_type = 'gather'
        elif 'explore' in communal_str.lower():
            task_type = 'explore'
        elif 'build' in communal_str.lower():
            task_type = 'build'
            # Extract building type
            for btype in ['farm', 'house', 'storage', 'workshop', 'shrine', 'well']:
                if btype in communal_str.lower():
                    target_building_type = btype
                    break
        
        # Create or update group task
        existing_task = None
        for task in self.group_tasks:
            if task.task_type == task_type and task.target_building_type == target_building_type:
                existing_task = task
                break
        
        if not existing_task:
            new_task = GroupTask(
                task_type=task_type,
                description=communal_str,
                required_count=required_count,
                target_building_type=target_building_type
            )
            self.group_tasks.append(new_task)
            print(f"[Group Task] Created: {task_type} party of {required_count}")
        else:
            existing_task.required_count = max(existing_task.required_count, required_count)
    
    def evaluate_condition(self, condition_str, praxans, buildings, resources):
        """Evaluate a condition string (e.g., "hunger<50", "population>5")"""
        import re
        
        # Parse condition: metric<value or metric>value
        match = re.match(r'(\w+)([<>]=?)(\d+)', condition_str.strip())
        if not match:
            return False
        
        metric = match.group(1).lower()
        operator = match.group(2)
        value = int(match.group(3))
        
        num_praxans = len(praxans)
        
        # Evaluate metrics
        if metric == 'hunger':
            if praxans:
                avg_hunger = sum(t.needs['hunger'] for t in praxans) / len(praxans)
                if operator == '<':
                    return avg_hunger < value
                elif operator == '<=':
                    return avg_hunger <= value
                elif operator == '>':
                    return avg_hunger > value
                elif operator == '>=':
                    return avg_hunger >= value
        elif metric == 'population':
            if operator == '>':
                return num_praxans > value
            elif operator == '>=':
                return num_praxans >= value
            elif operator == '<':
                return num_praxans < value
            elif operator == '<=':
                return num_praxans <= value
        elif metric == 'energy':
            if praxans:
                avg_energy = sum(t.needs['energy'] for t in praxans) / len(praxans)
                if operator == '<':
                    return avg_energy < value
                elif operator == '<=':
                    return avg_energy <= value
                elif operator == '>':
                    return avg_energy > value
                elif operator == '>=':
                    return avg_energy >= value
        
        return False
    
    def get_individual_directive(self, praxan_id):
        """Get individual directive for a specific praxan"""
        return self.json_directives.get('individual', {}).get(praxan_id, None)
    
    def get_conditional_behaviors(self, praxans, buildings, resources):
        """Evaluate conditions and return active behaviors"""
        active_behaviors = []
        conditions = self.json_directives.get('conditions', {})
        
        for condition, behavior in conditions.items():
            if self.evaluate_condition(condition, praxans, buildings, resources):
                active_behaviors.append(behavior)
                print(f"[Conditional] Active: {condition} -> {behavior}")
                
                # Parse conditional behavior into directive format
                # Example: "All gatherers prioritize food" -> directive
                if 'prioritize' in behavior.lower():
                    if 'gatherer' in behavior.lower() or 'all' in behavior.lower():
                        # Add as high-priority directive
                        active_behaviors.append({
                            'priority': 7,
                            'action': behavior,
                            'reasoning': f'Conditional: {condition}'
                        })
        
        return active_behaviors
    
    def validate_directive(self, directive, praxans, buildings, resources):
        """Validate if a directive is feasible given current game state"""
        action = directive.get('action', '').lower()
        errors = []
        
        # Check building directives
        if 'build' in action:
            required_wood = 0
            required_stone = 0
            building_type = None
            
            if 'farm' in action:
                building_type = 'farm'
                required_wood = 5
            elif 'storage' in action:
                building_type = 'storage'
                required_wood = 3
            elif 'house' in action:
                building_type = 'house'
                required_wood = 4
            elif 'workshop' in action:
                building_type = 'workshop'
                required_wood = 6
                required_stone = 4
            elif 'shrine' in action:
                building_type = 'shrine'
                required_wood = 8
                required_stone = 5
            elif 'well' in action:
                building_type = 'well'
                required_stone = 3
            
            if building_type:
                # Check if directive is conditional (e.g., "when wood available")
                # Conditional directives are valid even if resources aren't available yet
                is_conditional = any(phrase in action for phrase in ['when', 'if available', 'once', 'after'])
                
                if not is_conditional:
                    # Only validate resource availability for non-conditional directives
                    # Check if any praxan has resources (using pooled resources)
                    total_wood = sum(t.inventory['wood'] for t in praxans)
                    total_stone = sum(t.inventory['stone'] for t in praxans)
                    
                    if total_wood < required_wood:
                        errors.append(f"Insufficient wood: need {required_wood}, have {total_wood}")
                    if total_stone < required_stone:
                        errors.append(f"Insufficient stone: need {required_stone}, have {total_stone}")
        
        # Check gathering directives
        elif 'gather' in action or 'collect' in action:
            resource_type = None
            if 'wood' in action:
                resource_type = 'wood'
            elif 'food' in action:
                resource_type = 'food'
            elif 'stone' in action:
                resource_type = 'stone'
            
            if resource_type:
                available = sum(1 for r in resources if r.resource_type == resource_type and not r.collected)
                if available == 0:
                    errors.append(f"No {resource_type} resources available on map")
        
        # Check population requirements for communal tasks
        if 'party' in action or 'group' in action:
            # Extract number from "party of 3" etc.
            import re
            party_match = re.search(r'(\d+)', action)
            if party_match:
                required_pop = int(party_match.group(1))
                if len(praxans) < required_pop:
                    errors.append(f"Insufficient population: need {required_pop}, have {len(praxans)}")
        
        return len(errors) == 0, errors
    
    def parse_evolution_commands(self, response_text, narrative_panel, praxans, resources, buildings):
        """Parse and execute evolution commands from LLM"""
        lines = sanitize_llm_response(response_text).split('\n')
        
        for line in lines:
            if line.startswith('TECH|'):
                parts = line.split('|')
                if len(parts) >= 2:
                    tech_id = parts[1].strip()
                    if tech_id in self.tech_tree and tech_id not in self.game_modifiers.tech_unlocked:
                        tech = self.tech_tree[tech_id]
                        if self.research_points >= tech['cost']:
                            # Check prerequisites
                            if all(req in self.game_modifiers.tech_unlocked for req in tech.get('requires', [])):
                                self.research_points -= tech['cost']
                                self.points_spent += tech['cost']
                                self.game_modifiers.tech_unlocked.add(tech_id)
                                # Apply permanent effects
                                for mechanic, value in tech['effect'].items():
                                    self.game_modifiers.permanent[mechanic] = value
                                narrative_panel.add_message(f"TECH UNLOCKED: {tech['name']}!", 'Achievement')
                                print(f"[Evolution] Unlocked tech: {tech['name']}")
            
            elif line.startswith('EVOLVE|'):
                parts = line.split('|')
                if len(parts) >= 3:
                    mechanic = parts[1].strip()
                    try:
                        multiplier = float(parts[2].strip())
                        multiplier = max(0.5, min(2.0, multiplier))  # Clamp to range
                        
                        # Calculate cost (scales with usage)
                        times_used = self.game_modifiers.temporary.get(mechanic + '_count', 0)
                        cost = int(50 * (1.5 ** times_used))
                        
                        if self.research_points >= cost:
                            self.research_points -= cost
                            self.points_spent += cost
                            end_time = time.time() + 120  # 2 minutes
                            self.game_modifiers.temporary[mechanic] = (multiplier, end_time)
                            self.game_modifiers.temporary[mechanic + '_count'] = times_used + 1
                            narrative_panel.add_message(f"EVOLVE: {mechanic} -> {multiplier:.1f}x for 2min", 'Strategy')
                            print(f"[Evolution] Applied modifier: {mechanic} = {multiplier}x")
                    except ValueError:
                        pass
            
            elif line.startswith('ABILITY|'):
                parts = line.split('|')
                if len(parts) >= 2:
                    ability_name = parts[1].strip()
                    if ability_name in self.abilities:
                        ability = self.abilities[ability_name]
                        if self.research_points >= ability['cost']:
                            self.research_points -= ability['cost']
                            self.points_spent += ability['cost']
                            
                            if ability.get('instant'):
                                if ability_name == 'heal_wave':
                                    for t in praxans:
                                        t.health = min(100, t.health + 50)
                                    narrative_panel.add_message("HEAL WAVE: All praxans +50 health!", 'Achievement')
                                elif ability_name == 'resource_blessing':
                                    for _ in range(5):
                                        x = random.randint(50, WINDOW_WIDTH - 50)
                                        y = random.randint(50, WINDOW_HEIGHT - 50)
                                        rtype = random.choice(['food', 'wood', 'stone'])
                                        resources.append(Resource(x, y, rtype))
                                    narrative_panel.add_message("RESOURCE BLESSING: 5 resources spawned!", 'Achievement')
                            else:
                                # Apply temporary modifier
                                end_time = time.time() + ability['duration']
                                for mechanic, value in ability['effect'].items():
                                    self.game_modifiers.temporary[mechanic] = (value, end_time)
                                narrative_panel.add_message(f"ABILITY: {ability_name} active!", 'Strategy')
            
            elif line.startswith('CHALLENGE|'):
                if time.time() > self.challenge_cooldown:
                    parts = line.split('|')
                    if len(parts) >= 2:
                        challenge_type = parts[1].strip().lower()
                        self.spawn_challenge(challenge_type, praxans, resources, buildings, narrative_panel)
                        self.challenge_cooldown = time.time() + 180  # 3 min cooldown
    
    def spawn_challenge(self, challenge_type, praxans, resources, buildings, narrative_panel):
        """Spawn emergent challenges"""
        if challenge_type == 'drought':
            challenge = {
                'type': 'drought',
                'start_time': time.time(),
                'duration': 90,
                'reward': 150,
                'active': True
            }
            self.active_challenges.append(challenge)
            narrative_panel.add_message("CHALLENGE: Drought! Wells disabled for 90s", 'Crisis')
        elif challenge_type == 'plague':
            challenge = {
                'type': 'plague',
                'start_time': time.time(),
                'duration': 60,
                'reward': 200,
                'active': True
            }
            self.active_challenges.append(challenge)
            narrative_panel.add_message("CHALLENGE: Plague outbreak! Disease risk 5x", 'Crisis')
        elif challenge_type == 'bounty':
            # Spawn bonus resources
            for _ in range(10):
                x = random.randint(50, WINDOW_WIDTH - 50)
                y = random.randint(50, WINDOW_HEIGHT - 50)
                resources.append(Resource(x, y, random.choice(['food', 'wood', 'stone'])))
            challenge = {
                'type': 'bounty',
                'start_time': time.time(),
                'duration': 60,
                'reward': 100,
                'collected': 0,
                'target': 10,
                'active': True
            }
            self.active_challenges.append(challenge)
            narrative_panel.add_message("CHALLENGE: Resource bounty! Collect 10 in 60s", 'Achievement')
    
    def assign_individual_goals(self, praxans, buildings, resources, world_map):
        """Queue personal goal generation without blocking the main loop."""
        current_time = time.time()

        # Only assign goals every 60 seconds to avoid spam
        if current_time - getattr(self, 'last_goal_assignment', current_time) < GOAL_ASSIGNMENT_INTERVAL:
            return

        # Avoid back-to-back advisor + goals LLM requests in the same moment.
        if current_time - getattr(self, 'last_query_time', 0) < POST_ADVISOR_GOAL_COOLDOWN:
            return
        
        self.last_goal_assignment = current_time
        
        # Skip if no praxans
        if not praxans:
            return
        
        # Skip quietly if LLM support is disabled or unavailable
        if not LLM_ENABLED:
            return

        if self.has_pending_llm_jobs():
            return

        request = self._build_goal_assignment_request(praxans, buildings)
        self.pending_goal_job = start_async_llm_job(request["prompt"], "goals", request)
        self.last_goal_assignment = current_time
        self.last_llm_error = None
        print(f"[Goal Assignment] Queued async personal goals for {len(praxans)} praxans")
    
    def calculate_colony_wealth(self, praxans, buildings, resources):
        """Calculate total colony wealth based on population, buildings, and stockpiles"""
        wealth = 0.0
        
        # 1. Population wealth (base value + skills)
        for t in praxans:
            wealth += 500  # Base value
            # Skills
            for skill_info in getattr(t, 'skills', {}).values():
                wealth += skill_info.get('level', 1) * 100
            # Health
            wealth += getattr(t, 'health', 100) * 2
            
        # 2. Building wealth (material costs value)
        for b in buildings:
            base_value = 200
            if getattr(b, 'building_type', '') in ['house', 'well']:
                base_value = 300
            elif getattr(b, 'building_type', '') in ['workshop', 'shrine']:
                base_value = 500
            elif getattr(b, 'building_type', '') in ['hospital', 'school', 'market']:
                base_value = 800
            wealth += base_value * getattr(b, 'level', 1)
            
        # 3. Resource Stockpiles
        for t in praxans:
            inv = getattr(t, 'inventory', {})
            wealth += inv.get('wood', 0) * 10
            wealth += inv.get('stone', 0) * 15
            wealth += inv.get('food', 0) * 20
            
        return wealth

    def calculate_difficulty(self, praxans, buildings, resources=None):
        """Calculate challenge difficulty based on dynamic colony wealth"""
        if resources is None:
            resources = []
            
        wealth = self.calculate_colony_wealth(praxans, buildings, resources)
        self.session_stats['colony_wealth'] = wealth
        
        # Scale: 
        # Base 1.0
        # +1.0 for every 10,000 wealth
        base_difficulty = 1.0 + (wealth / 10000.0)
        
        # Maximum difficulty cap of 5.0
        return min(5.0, base_difficulty)


