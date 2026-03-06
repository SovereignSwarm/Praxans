"""Smoke test for ALL remaining pillar systems."""
# Pillar 7: Mod Support
from systems.mod_loader import ModLoader
ml = ModLoader("mods")
mods = ml.discover()
print(f"ModLoader: discovered {len(mods)} mods")

# Pillar 8: Quest Scripting
from systems.quests import QuestManager
qm = QuestManager()
qm.build_default_quests()
print(f"QuestManager: {len(qm.quests)} quests registered")
print(f"  Available: {[q.name for q in qm.get_available_quests()]}")

# Pillar 12: Search Overlay
from ui.search_overlay import SearchOverlay
so = SearchOverlay()
so.toggle()
print(f"SearchOverlay: active={so.active}")

# Pillar 5: ExposeData
from systems.expose_data import Exposable, safe_get
class TestEntity(Exposable):
    __schema_version__ = 2
    def __init__(self):
        self.health = 100.0
        self.name = "test"
        self.new_field = "default_val"
    def expose_fields(self):
        return {"health": 100.0, "name": "test", "new_field": "default_val"}

entity = TestEntity()
# Simulate loading an old save missing "new_field"
entity.expose_from_dict({"health": 75, "name": "old_save", "__version__": 1})
print(f"ExposeData: health={entity.health}, name={entity.name}, new_field={entity.new_field}")
print(f"  safe_get test: {safe_get({'a': 42}, 'a', cast_type=float)}")

# Pillar 3: POI Generation
from map.poi import POIGenerator
gen = POIGenerator(seed=12345)
pois = gen.generate(15360, 6144, count=10)
print(f"POI Generator: {len(pois)} POIs created")
for p in pois[:3]:
    print(f"  {p.name} ({p.category}) at ({int(p.world_x)},{int(p.world_y)}) [{p.biome}] danger={p.danger_level}")

print("\nALL PILLAR SYSTEMS OK")
