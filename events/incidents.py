import math
import random
import time
from systems.storyteller import INCIDENT_GOOD, INCIDENT_NEUTRAL, INCIDENT_BAD


def _clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def _compute_colony_anchor(praxans, buildings, world_width, world_height):
    anchors = []
    for praxan in praxans:
        if hasattr(praxan, "x") and hasattr(praxan, "y") and getattr(praxan, "alive", True):
            anchors.append((float(praxan.x), float(praxan.y)))
    for building in buildings:
        if hasattr(building, "x") and hasattr(building, "y"):
            anchors.append((float(building.x), float(building.y)))

    if anchors:
        center_x = sum(anchor[0] for anchor in anchors) / len(anchors)
        center_y = sum(anchor[1] for anchor in anchors) / len(anchors)
    else:
        center_x = world_width / 2.0
        center_y = world_height / 2.0

    return (
        _clamp(center_x, 120.0, max(120.0, world_width - 120.0)),
        _clamp(center_y, 120.0, max(120.0, world_height - 120.0)),
    )

def incident_crop_blight(game_state: dict):
    buildings = game_state.get('buildings', [])
    farms = [b for b in buildings if getattr(b, 'building_type', '') == 'farm']
    blighted = 0
    for farm in farms:
        if random.random() < 0.5:
            resources = getattr(farm, 'stored_resources', None)
            if not isinstance(resources, dict):
                resources = {}
                setattr(farm, 'stored_resources', resources)
            resources['food'] = 0
            blighted += 1
            
    narrative_panel = game_state.get('narrative_panel')
    if narrative_panel and blighted > 0:
        narrative_panel.add_message(f"Blight destroyed food in {blighted} farms!", "Extinction")

def incident_migrant_wave(game_state: dict):
    praxans = game_state.get('praxans', [])
    buildings = game_state.get('buildings', [])
    world_width = game_state.get('world_width', 800)
    world_height = game_state.get('world_height', 600)
    PraxanClass = game_state.get('praxan_class')
    
    if not PraxanClass: return
    
    count = random.randint(1, 3)
    center_x, center_y = _compute_colony_anchor(praxans, buildings, world_width, world_height)
    for _ in range(count):
        angle = random.uniform(0.0, math.tau)
        distance = random.uniform(70.0, 150.0)
        x = _clamp(center_x + math.cos(angle) * distance, 80.0, max(80.0, world_width - 80.0))
        y = _clamp(center_y + math.sin(angle) * distance, 80.0, max(80.0, world_height - 80.0))
        new_praxan = PraxanClass(x, y)
        new_praxan.inventory['food'] = 2
        new_praxan.personal_goal = {
            'type': 'migrate',
            'target': {'x': center_x, 'y': center_y},
            'reason': 'migrant_wave',
            'assigned_at': time.time(),
        }
        praxans.append(new_praxan)
        
    narrative_panel = game_state.get('narrative_panel')
    if narrative_panel:
        narrative_panel.add_message(f"A group of {count} migrants joined the settlement.", "Migration")

def incident_animal_attack(game_state: dict):
    # For now, just a direct hit to a random praxan's health since we don't have a hostile mob system yet
    praxans = game_state.get('praxans', [])
    if not praxans: return
    
    target = random.choice(praxans)
    target.health -= random.uniform(20, 50)
    
    narrative_panel = game_state.get('narrative_panel')
    if narrative_panel:
        narrative_panel.add_message(f"Praxan #{target.id} was attacked by a wild beast!", "Crisis")

def incident_resource_pod(game_state: dict):
    resources = game_state.get('resources', [])
    world_width = game_state.get('world_width', 800)
    world_height = game_state.get('world_height', 600)
    ResourceClass = game_state.get('resource_class')
    
    if not ResourceClass: return
    
    x = random.uniform(100, world_width - 100)
    y = random.uniform(100, world_height - 100)
    
    for _ in range(5):
        r = ResourceClass(x + random.uniform(-30, 30), y + random.uniform(-30, 30))
        r.resource_type = random.choice(['food', 'wood', 'stone'])
        resources.append(r)
        
    narrative_panel = game_state.get('narrative_panel')
    if narrative_panel:
        narrative_panel.add_message("A pod of resources crashed nearby.", "Discovery")

def incident_disease_outbreak(game_state: dict):
    praxans = game_state.get('praxans', [])
    if not praxans: return

    # Use the typed disease system — pick a disease weighted by severity
    try:
        from systems.disease import DiseaseManager, get_all_disease_ids, get_disease_def
        disease_ids = get_all_disease_ids()
        if disease_ids:
            # Prefer non-rare diseases for ambient outbreaks; rare for high-drama
            weights = []
            for did in disease_ids:
                ddef = get_disease_def(did)
                w = 1.0
                if ddef and "rare" in ddef.get("tags", []):
                    w = 0.15
                if ddef and "common" in ddef.get("tags", []):
                    w = 2.0
                weights.append(w)
            disease_id = random.choices(disease_ids, weights=weights, k=1)[0]
        else:
            disease_id = None
    except Exception:
        disease_id = None

    infected_count = max(1, len(praxans) // 4)
    targets = random.sample(praxans, min(infected_count, len(praxans)))
    event_bus = game_state.get('event_bus')
    narrative_panel = game_state.get('narrative_panel')

    actually_infected = 0
    disease_label = "unknown illness"
    for t in targets:
        if disease_id:
            try:
                mgr = DiseaseManager()
                if mgr.infect(t, disease_id, event_bus=event_bus, narrative_panel=narrative_panel):
                    actually_infected += 1
                    ddef = get_disease_def(disease_id)
                    disease_label = ddef.get("label", disease_id) if ddef else disease_id
            except Exception:
                t.diseased = True
                actually_infected += 1
        else:
            t.diseased = True
            actually_infected += 1

    if narrative_panel and actually_infected > 0:
        narrative_panel.add_message(
            f"Outbreak of {disease_label}! {actually_infected} praxans infected.", "Crisis"
        )

def incident_natural_disaster(game_state: dict):
    """Storyteller-triggered natural disaster — delegates to DisasterManager."""
    disaster_manager = game_state.get('disaster_manager')
    if disaster_manager is None:
        return

    import time as _time
    praxans = game_state.get('praxans', [])
    buildings = game_state.get('buildings', [])
    world_map = game_state.get('world_map')
    event_bus = game_state.get('event_bus')
    narrative_panel = game_state.get('narrative_panel')
    season = game_state.get('season')
    weather_system = game_state.get('weather_system')
    season_name = getattr(season, 'current', 'summer') if season else 'summer'
    weather_name = getattr(weather_system, 'current_weather', 'clear') if weather_system else 'clear'

    now = _time.time()
    # Force selection and firing (bypass the random chance check)
    disaster_id = disaster_manager._select_disaster(
        now, praxans, buildings, world_map, season_name, weather_name,
    )
    if disaster_id:
        disaster_manager._fire_disaster(
            disaster_id, now, praxans, buildings,
            world_map, event_bus, narrative_panel,
        )
        # Apply immediately
        for ad in disaster_manager.active_disasters:
            if not ad.applied:
                ad.applied = True
                disaster_manager._apply_effects(
                    ad, praxans, buildings, world_map,
                    event_bus, narrative_panel,
                )


def register_all_incidents(storyteller):
    storyteller.add_incident("crop_blight", INCIDENT_BAD, 40.0, incident_crop_blight)
    storyteller.add_incident("animal_attack", INCIDENT_BAD, 60.0, incident_animal_attack)
    storyteller.add_incident("disease_outbreak", INCIDENT_BAD, 80.0, incident_disease_outbreak)
    storyteller.add_incident("natural_disaster", INCIDENT_BAD, 90.0, incident_natural_disaster)
    storyteller.add_incident("migrant_wave", INCIDENT_GOOD, 0.0, incident_migrant_wave)
    storyteller.add_incident("resource_pod", INCIDENT_NEUTRAL, 0.0, incident_resource_pod)
