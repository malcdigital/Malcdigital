class_name Props
extends RefCounted
## Scenery the player can place. Props matter to the ride: passing close to
## them is a thrilling near miss; passing through them is a crash.

enum Kind { TREE, ROCK, TOWER }

const NAMES := ["Tree", "Rock", "Tower"]
## Collision cylinder per kind (before scale): radius, height (metres).
const SHAPES := [
	{"radius": 2.2, "height": 11.0, "cost": 2000.0},
	{"radius": 3.0, "height": 4.5, "cost": 1500.0},
	{"radius": 2.0, "height": 24.0, "cost": 30000.0},
]


static func radius(p: Dictionary) -> float:
	return SHAPES[p["k"]]["radius"] * float(p["s"])


static func height(p: Dictionary) -> float:
	return SHAPES[p["k"]]["height"] * float(p["s"])


static func make(kind: int, x: float, z: float, s: float = 1.0) -> Dictionary:
	return {"k": kind, "x": x, "z": z, "s": s}
