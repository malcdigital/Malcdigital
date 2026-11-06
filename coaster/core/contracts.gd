class_name Contracts
extends RefCounted
## Challenge contracts: a client brief with a site, a coaster type, a budget
## and targets. One star for meeting the brief, two more for bonus goals.
## Completing contracts unlocks coaster types and the next contracts.
##
## Goals are {"kind": String, "value": float, "bonus": bool}. Kinds:
##   complete, budget, max_height, min_thrill, max_intensity, max_nausea,
##   min_speed_kmh, min_inversions, min_splashes, min_tunnel_m,
##   min_near_misses, no_lift, needs_launch, zones_clear, no_red, max_cost_frac

const LIST := [
	{
		"id": "first_steps", "title": "First Steps",
		"brief": "The park wants its first proper coaster. Something fun, nothing that makes the guests ill.",
		"type": CoasterTypes.Id.STEEL, "terrain": TerrainData.Preset.FLAT, "budget": 2200000.0,
		"goals": [
			{"kind": "complete"}, {"kind": "min_thrill", "value": 4.0}, {"kind": "max_nausea", "value": 5.0},
			{"kind": "min_thrill", "value": 6.0, "bonus": true}, {"kind": "max_cost_frac", "value": 0.75, "bonus": true},
		],
	},
	{
		"id": "family_woodie", "title": "Family Woodie",
		"brief": "A classic wooden coaster through the hills for families. Keep it gentle and under 30 m.",
		"type": CoasterTypes.Id.WOODEN, "terrain": TerrainData.Preset.HILLS, "budget": 1800000.0,
		"goals": [
			{"kind": "complete"}, {"kind": "max_height", "value": 30.0}, {"kind": "min_thrill", "value": 3.5},
			{"kind": "max_intensity", "value": 5.0}, {"kind": "no_red"},
			{"kind": "min_near_misses", "value": 2.0, "bonus": true}, {"kind": "max_nausea", "value": 3.0, "bonus": true},
		],
		"unlocks": CoasterTypes.Id.LAUNCHED,
	},
	{
		"id": "lakeside_splash", "title": "Lakeside Splash",
		"brief": "Guests on the lake shore want to get wet. Dip the train into the lake at speed.",
		"type": CoasterTypes.Id.STEEL, "terrain": TerrainData.Preset.LAKE, "budget": 2600000.0,
		"goals": [
			{"kind": "complete"}, {"kind": "min_splashes", "value": 1.0}, {"kind": "min_thrill", "value": 5.0}, {"kind": "no_red"},
			{"kind": "min_splashes", "value": 2.0, "bonus": true}, {"kind": "max_nausea", "value": 4.0, "bonus": true},
		],
	},
	{
		"id": "zero_to_ninety", "title": "Zero to Ninety",
		"brief": "No chain lift on this one. Launch the train past 90 km/h and keep it under control.",
		"type": CoasterTypes.Id.LAUNCHED, "terrain": TerrainData.Preset.FLAT, "budget": 3200000.0,
		"goals": [
			{"kind": "complete"}, {"kind": "no_lift"}, {"kind": "needs_launch"}, {"kind": "min_speed_kmh", "value": 90.0},
			{"kind": "max_intensity", "value": 7.0}, {"kind": "no_red"},
			{"kind": "min_inversions", "value": 2.0, "bonus": true}, {"kind": "min_thrill", "value": 7.0, "bonus": true},
		],
	},
	{
		"id": "into_the_hill", "title": "Into the Hill",
		"brief": "The hills are protected scenery, so go through them. Tunnels and close calls wanted, and keep the path clear.",
		"type": CoasterTypes.Id.STEEL, "terrain": TerrainData.Preset.HILLS, "budget": 3000000.0,
		"zones": [{"rect": Rect2(-60, -12, 34, 8), "clear": 4.0, "name": "park path"}],
		"goals": [
			{"kind": "complete"}, {"kind": "min_tunnel_m", "value": 60.0}, {"kind": "min_near_misses", "value": 2.0},
			{"kind": "zones_clear"}, {"kind": "no_red"},
			{"kind": "min_near_misses", "value": 5.0, "bonus": true}, {"kind": "min_thrill", "value": 6.5, "bonus": true},
		],
		"unlocks": CoasterTypes.Id.WING,
	},
	{
		"id": "height_limit", "title": "Height Restriction",
		"brief": "The planning office capped the ride at 25 m. Make it thrilling anyway.",
		"type": CoasterTypes.Id.STEEL, "terrain": TerrainData.Preset.FLAT, "budget": 2400000.0,
		"goals": [
			{"kind": "complete"}, {"kind": "max_height", "value": 25.0}, {"kind": "min_thrill", "value": 6.0}, {"kind": "no_red"},
			{"kind": "min_thrill", "value": 7.5, "bonus": true}, {"kind": "max_cost_frac", "value": 0.8, "bonus": true},
		],
	},
	{
		"id": "wings_over_water", "title": "Wings Over Water",
		"brief": "A wing coaster skimming the lake, with plenty of close passes and two inversions.",
		"type": CoasterTypes.Id.WING, "terrain": TerrainData.Preset.LAKE, "budget": 4200000.0,
		"goals": [
			{"kind": "complete"}, {"kind": "min_inversions", "value": 2.0}, {"kind": "min_near_misses", "value": 4.0},
			{"kind": "max_nausea", "value": 6.0}, {"kind": "no_red"},
			{"kind": "min_thrill", "value": 7.5, "bonus": true}, {"kind": "min_near_misses", "value": 8.0, "bonus": true},
		],
		"unlocks": CoasterTypes.Id.FLYING,
	},
	{
		"id": "canyon_flyer", "title": "Canyon Flyer",
		"brief": "Riders fly face-down through the canyon. Flying riders take less G, so design gently.",
		"type": CoasterTypes.Id.FLYING, "terrain": TerrainData.Preset.CANYON, "budget": 5000000.0,
		"goals": [
			{"kind": "complete"}, {"kind": "min_thrill", "value": 6.5}, {"kind": "max_intensity", "value": 7.5}, {"kind": "no_red"},
			{"kind": "min_near_misses", "value": 4.0, "bonus": true}, {"kind": "max_nausea", "value": 5.0, "bonus": true},
		],
	},
]


static func find(id: String) -> Dictionary:
	for c in LIST:
		if c["id"] == id:
			return c
	return {}


static func index_of(id: String) -> int:
	for i in LIST.size():
		if LIST[i]["id"] == id:
			return i
	return -1


static func zones(id: String) -> Array:
	return find(id).get("zones", [])


static func goal_text(g: Dictionary) -> String:
	var v: float = g.get("value", 0.0)
	match g["kind"]:
		"complete": return "Train completes the circuit"
		"budget": return "Within budget"
		"max_height": return "Height at most %.0f m" % v
		"min_thrill": return "Thrill at least %.1f" % v
		"max_intensity": return "Intensity at most %.1f" % v
		"max_nausea": return "Nausea at most %.1f" % v
		"min_speed_kmh": return "Top speed at least %.0f km/h" % v
		"min_inversions": return "At least %d inversions" % int(v)
		"min_splashes": return "At least %d splashdown%s" % [int(v), "" if int(v) == 1 else "s"]
		"min_tunnel_m": return "At least %.0f m of tunnel" % v
		"min_near_misses": return "At least %d near misses" % int(v)
		"no_lift": return "No chain lift"
		"needs_launch": return "Uses a launch"
		"zones_clear": return "Keep the marked area clear"
		"no_red": return "No dangerous (red) spots"
		"max_cost_frac": return "Costs under %.0f%% of the budget" % (v * 100.0)
	return str(g["kind"])
