class_name CoasterTypes
extends RefCounted
## The coaster types the player can build. Each changes the physics feel, the
## comfort limits, what ride systems are allowed, the cost, and the look.
##
##   Steel     the baseline sit-down coaster
##   Wooden    more friction, a rattling ride, no inversions, cheap to build
##   Launched  linear-motor launches instead of (or as well as) a chain lift
##   Wing      seats hang off both sides of the track: rolls throw riders
##             around and close passes feel much closer
##   Flying    riders lie face-down under the track; positive G pushes them
##             into the harness, so comfort limits are lower

enum Id { STEEL, WOODEN, LAUNCHED, WING, FLYING }

const ORDER := [Id.STEEL, Id.WOODEN, Id.LAUNCHED, Id.WING, Id.FLYING]

const TYPES := {
	Id.STEEL: {
		"name": "Steel", "blurb": "The all-rounder: smooth, fast, and happy upside down.",
		"friction": 0.012, "drag": 0.0003, "rattle": 0.0, "g_scale": 1.0,
		"seat_offset": 0.0, "prone": false, "launch": false, "inversions": true,
		"cost_per_m": 1200.0, "support_cost_per_m": 350.0,
		"rail": Color(0.72, 0.74, 0.78), "spine": Color(0.9, 0.35, 0.12), "tie": Color(0.72, 0.74, 0.78),
		"support": Color(0.55, 0.58, 0.62), "car": Color(0.95, 0.75, 0.1), "style": "steel",
	},
	Id.WOODEN: {
		"name": "Wooden", "blurb": "Rattly, rowdy airtime machine. Can't go upside down.",
		"friction": 0.022, "drag": 0.00035, "rattle": 0.35, "g_scale": 1.0,
		"seat_offset": 0.0, "prone": false, "launch": false, "inversions": false,
		"cost_per_m": 850.0, "support_cost_per_m": 260.0,
		"rail": Color(0.35, 0.33, 0.32), "spine": Color(0.55, 0.38, 0.22), "tie": Color(0.58, 0.42, 0.26),
		"support": Color(0.62, 0.47, 0.3), "car": Color(0.75, 0.15, 0.15), "style": "wood",
	},
	Id.LAUNCHED: {
		"name": "Launched", "blurb": "Linear motors fire the train from standstill to full speed.",
		"friction": 0.01, "drag": 0.0003, "rattle": 0.0, "g_scale": 1.0,
		"seat_offset": 0.0, "prone": false, "launch": true, "inversions": true,
		"cost_per_m": 1450.0, "support_cost_per_m": 380.0,
		"rail": Color(0.75, 0.78, 0.82), "spine": Color(0.45, 0.25, 0.85), "tie": Color(0.75, 0.78, 0.82),
		"support": Color(0.3, 0.32, 0.36), "car": Color(0.15, 0.75, 0.9), "style": "steel",
	},
	Id.WING: {
		"name": "Wing", "blurb": "Seats sit beside the track with nothing above or below you.",
		"friction": 0.012, "drag": 0.00045, "rattle": 0.0, "g_scale": 1.0,
		"seat_offset": 1.6, "prone": false, "launch": false, "inversions": true,
		"cost_per_m": 1800.0, "support_cost_per_m": 420.0,
		"rail": Color(0.78, 0.8, 0.84), "spine": Color(0.12, 0.55, 0.35), "tie": Color(0.78, 0.8, 0.84),
		"support": Color(0.85, 0.85, 0.88), "car": Color(0.95, 0.95, 0.98), "style": "steel",
	},
	Id.FLYING: {
		"name": "Flying", "blurb": "Ride face-down under the rails like a superhero.",
		"friction": 0.013, "drag": 0.0005, "rattle": 0.0, "g_scale": 0.82,
		"seat_offset": 0.0, "prone": true, "launch": false, "inversions": true,
		"cost_per_m": 2000.0, "support_cost_per_m": 450.0,
		"rail": Color(0.8, 0.82, 0.86), "spine": Color(0.15, 0.3, 0.8), "tie": Color(0.8, 0.82, 0.86),
		"support": Color(0.2, 0.25, 0.4), "car": Color(0.9, 0.2, 0.25), "style": "flying",
	},
}


static func get_type(id: int) -> Dictionary:
	return TYPES.get(id, TYPES[Id.STEEL])


static func type_name(id: int) -> String:
	return get_type(id)["name"]


## Segment types this coaster type may use.
static func allows_segment(id: int, seg: int) -> bool:
	if seg == TrackPoint.Segment.LAUNCH:
		return get_type(id)["launch"]
	return true
