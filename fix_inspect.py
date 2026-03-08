import sys

with open('ui/inspect.py', 'r') as f:
    lines = f.readlines()

new_lines = []

for line in lines[:27]:
    new_lines.append(line)

helpers = '''def _build_settlement_model(settlement_state: dict, advisor, active_tab: str) -> InspectViewModel:
    tabs = [("overview", "Overview"), ("evolution", "Evolution"), ("risks", "Risks")]
    sections = [
        _section(
            "Settlement",
            f"District  {str(settlement_state.get('district_identity', 'homestead')).replace('_', ' ').title()}",
            f"Prosperity  {int(float(settlement_state.get('prosperity_score', 0.0) or 0.0) * 100)}%",
            f"Culture  {int(float(settlement_state.get('culture_score', 0.0) or 0.0) * 100)}%",
            f"Festival Readiness  {int(float(settlement_state.get('festival_readiness', 0.0) or 0.0) * 100)}%",
            f"Stores  F{int(settlement_state.get('stored_food', 0) or 0)}  W{int(settlement_state.get('stored_wood', 0) or 0)}  S{int(settlement_state.get('stored_stone', 0) or 0)}",
        )
    ]
    if active_tab == "evolution":
        evo = dict((getattr(advisor, "session_stats", {}) or {}).get("current_evolution_summary", {}) or {})
        sections = [
            _section(
                "Evolution",
                f"Average Generation  {float(evo.get('avg_generation', 0.0) or 0.0):.1f}",
                f"Max Generation  {int(evo.get('max_generation', 0) or 0)}",
                f"Founder Lines  {int(evo.get('founder_lines', 0) or 0)}",
                f"Dominant Lineage  L{evo.get('dominant_lineage', '?')}",
            )
        ]
    elif active_tab == "risks":
        sections = [
            _section(
                "Risks",
                f"Challenges Active  {len(getattr(advisor, 'active_challenges', []) or [])}",
                f"Deaths Recorded  {int(getattr(advisor, 'total_deaths', 0) or 0)}",
                f"Research Points  {int(getattr(advisor, 'research_points', 0) or 0)}",
            )
        ]
    return InspectViewModel(
        title="Settlement",
        subtitle="Colony state and observer context",
        entity_type="settlement",
        accent=(153, 194, 196),
        tabs=tabs,
        active_tab=active_tab if active_tab in {tab_id for tab_id, _ in tabs} else "overview",
        sections=sections,
    )

def _build_building_model(building, active_tab: str) -> InspectViewModel:
    tabs = [("overview", "Overview"), ("economy", "Stores")]
    
    if getattr(building, 'building_type', '') in ['farm', 'workshop']:
        tabs.append(("production", "Production"))
        
    active_tab = active_tab if active_tab in {tab_id for tab_id, _ in tabs} else "overview"
    stored_resources = dict(getattr(building, "stored_resources", {}) or {})
    commands = [
        InspectCommand(id="deconstruct", label="Deconstruct", action="deconstruct_building", payload=building),
    ]
    
    if active_tab == "economy":
        sections = [_section("Stores", *[f"{name.title()}  {int(value)}" for name, value in stored_resources.items()])]
    elif active_tab == "production":
        bills = getattr(building, 'bills', [])
        bill_lines = []
        if bills:
            for idx, bill_id in enumerate(bills):
                from game_content import JOB_DEFS
                job = JOB_DEFS.get(bill_id, {})
                label = bill_id.replace('Craft', '').replace('Smith', '').replace('Cook', '')
                bill_lines.append(f"{idx+1}. {label} ({job.get('skill_factor', 'unknown').title()})")
        else:
            bill_lines.append("No active bills")
            
        sections = [_section("Bills Queue", *bill_lines)]
    else:
        sections = [
            _section(
                "Building",
                f"Type  {str(getattr(building, 'building_type', 'structure')).title()}",
                f"Level  {int(getattr(building, 'level', 1) or 1)}",
                f"Built By  #{getattr(building, 'built_by', 'Unknown')}",
                f"Occupants  {len(getattr(building, 'occupants', []))}",
            )
        ]
    return InspectViewModel(
        title=str(getattr(building, "building_type", "Building")).title(),
        subtitle="Structure and operational status",
        entity_type="building",
        accent=(166, 181, 116),
        tabs=tabs,
        active_tab=active_tab,
        sections=sections,
        commands=commands,
    )

def _build_resource_model(resource) -> InspectViewModel:
    sections = [
        _section(
            "Resource",
            f"Type  {str(getattr(resource, 'resource_type', 'resource')).title()}",
            f"Status  {'Respawning' if getattr(resource, 'collected', False) else 'Available'}",
        )
    ]
    return InspectViewModel(
        title=f"{str(getattr(resource, 'resource_type', 'resource')).title()} Resource",
        subtitle="Map resource node",
        entity_type="resource",
        accent=(153, 194, 196),
        tabs=[("overview", "Overview")],
        active_tab="overview",
        sections=sections,
    )

def _build_generic_model(selected_entity, selected_type: str) -> InspectViewModel:
    subject_name = selected_type.replace("_", " ").title()
    sections = [
        _section(
            subject_name,
            f"Type  {subject_name}",
            f"X  {round(float(getattr(selected_entity, 'x', 0.0)), 1)}",
            f"Y  {round(float(getattr(selected_entity, 'y', 0.0)), 1)}",
        )
    ]
    return InspectViewModel(
        title=subject_name,
        subtitle="Observed world entity",
        entity_type=selected_type,
        accent=(171, 110, 79),
        tabs=[("overview", "Overview")],
        active_tab="overview",
        sections=sections,
    )
'''
new_lines.append(helpers)

prax_sig = '''
def _build_praxan_model(praxan, active_tab: str, current_time: float, praxans, faction_manager, diplomacy_manager) -> InspectViewModel:
'''
new_lines.append(prax_sig)

# lines[81] is '        praxan = selected_entity'
# lines[331] is '            )'
# This corresponds to indices 81 to 331 (we slice up to index 332 to include line 331)
for line in lines[81:332]:
    if line.startswith('    '):
        new_lines.append(line[4:])
    elif line == '\n':
        new_lines.append(line)
    else:
        new_lines.append(line)

new_lines.append("\n\n")
new_lines.append('''def build_inspect_view_model(
    selected_entity,
    selected_type: str | None,
    advisor,
    current_time: float,
    settlement_state: dict,
    faction_manager=None,
    active_tab: str = "overview",
    praxans=None,
    diplomacy_manager=None,
) -> InspectViewModel:
    if not selected_entity or not selected_type:
        return _build_settlement_model(settlement_state, advisor, active_tab)

    if selected_type == "building":
        return _build_building_model(selected_entity, active_tab)

    if selected_type == "resource":
        return _build_resource_model(selected_entity)

    if selected_type == "praxan":
        return _build_praxan_model(selected_entity, active_tab, current_time, praxans, faction_manager, diplomacy_manager)

    return _build_generic_model(selected_entity, selected_type)
''')

# Now add everything from line 420 onwards (which is def _draw_need_bar)
# lines[420] is def _draw_need_bar
for line in lines[420:]:
    new_lines.append(line)

with open('ui/inspect.py', 'w') as f:
    f.writelines(new_lines)

print('Success')
