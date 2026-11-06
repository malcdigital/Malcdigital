class_name TrackData
extends RefCounted
## Serializable description of a whole coaster: the control points the player
## edits plus train and ride-system settings. Everything that is saved lives here.

const FORMAT_VERSION := 2

var name := "Untitled coaster"
var points: Array[TrackPoint] = []
var coaster_type: int = CoasterTypes.Id.STEEL
var terrain := TerrainData.new()
## Scenery: [{"k": Props.Kind, "x": float, "z": float, "s": scale}]
var props: Array[Dictionary] = []
## Contract this coaster is being built for ("" = sandbox).
var contract_id := ""

# --- Train -------------------------------------------------------------------
var num_cars := 5
var car_spacing := 2.6          # metres between car centres along the track

# --- Ride systems (all speeds in m/s, accelerations in m/s²) ------------------
var lift_speed := 4.5           # chain speed on lift segments
var launch_speed := 28.0        # launch motors push until this speed
var launch_accel := 11.0        # ~1.1 g of thrust
var brake_speed := 4.0          # brakes slow the train down to this speed
var brake_decel := 6.0
var station_speed := 2.5        # drive tyres in the station

# --- Resistance ----------------------------------------------------------------
## Rolling friction coefficient: friction force = mu * normal force.
var friction := 0.012
## Air drag coefficient k (1/m): drag deceleration = k * v².
## k = ½·ρ·Cd·A / m ≈ ½ · 1.2 kg/m³ · 1.0 · 1.4 m² / 3000 kg ≈ 0.0003.
var drag := 0.0003


## Deep copy without a JSON round trip (cheap enough to do on every edit).
func copy() -> TrackData:
	var t := TrackData.new()
	t.name = name
	for p in points:
		t.points.append(p.copy())
	t.coaster_type = coaster_type
	t.terrain = terrain.copy()
	for pr in props:
		t.props.append(pr.duplicate())
	t.contract_id = contract_id
	t.num_cars = num_cars
	t.car_spacing = car_spacing
	t.lift_speed = lift_speed
	t.launch_speed = launch_speed
	t.launch_accel = launch_accel
	t.brake_speed = brake_speed
	t.brake_decel = brake_decel
	t.station_speed = station_speed
	t.friction = friction
	t.drag = drag
	return t


## Switch coaster type: physics constants come from the type.
func set_type(id: int) -> void:
	coaster_type = id
	var ty := CoasterTypes.get_type(id)
	friction = ty["friction"]
	drag = ty["drag"]
	if not ty["launch"]:
		for p in points:
			if p.segment == TrackPoint.Segment.LAUNCH:
				p.segment = TrackPoint.Segment.LIFT


func type_info() -> Dictionary:
	return CoasterTypes.get_type(coaster_type)


func to_dict() -> Dictionary:
	var pts := []
	for p in points:
		pts.append(p.to_dict())
	return {
		"version": FORMAT_VERSION,
		"name": name,
		"points": pts,
		"train": {"cars": num_cars, "spacing": car_spacing},
		"systems": {
			"lift_speed": lift_speed, "launch_speed": launch_speed, "launch_accel": launch_accel,
			"brake_speed": brake_speed, "brake_decel": brake_decel, "station_speed": station_speed,
		},
		"resistance": {"friction": friction, "drag": drag},
		"type": coaster_type,
		"terrain": terrain.to_dict(),
		"props": props,
		"contract": contract_id,
	}


static func from_dict(d: Dictionary) -> TrackData:
	var t := TrackData.new()
	t.name = str(d.get("name", "Untitled coaster"))
	for pd in d.get("points", []):
		if pd is Dictionary:
			t.points.append(TrackPoint.from_dict(pd))
	var train: Dictionary = d.get("train", {})
	t.num_cars = clampi(int(train.get("cars", t.num_cars)), 1, 12)
	t.car_spacing = float(train.get("spacing", t.car_spacing))
	var sys: Dictionary = d.get("systems", {})
	t.lift_speed = float(sys.get("lift_speed", t.lift_speed))
	t.launch_speed = float(sys.get("launch_speed", t.launch_speed))
	t.launch_accel = float(sys.get("launch_accel", t.launch_accel))
	t.brake_speed = float(sys.get("brake_speed", t.brake_speed))
	t.brake_decel = float(sys.get("brake_decel", t.brake_decel))
	t.station_speed = float(sys.get("station_speed", t.station_speed))
	var res: Dictionary = d.get("resistance", {})
	t.friction = float(res.get("friction", t.friction))
	t.drag = float(res.get("drag", t.drag))
	t.coaster_type = clampi(int(d.get("type", CoasterTypes.Id.STEEL)), 0, CoasterTypes.Id.FLYING)
	if d.has("terrain") and d["terrain"] is Dictionary:
		t.terrain = TerrainData.from_dict(d["terrain"])
	for pr in d.get("props", []):
		if pr is Dictionary:
			t.props.append({"k": int(pr.get("k", 0)), "x": float(pr.get("x", 0)), "z": float(pr.get("z", 0)), "s": float(pr.get("s", 1))})
	t.contract_id = str(d.get("contract", ""))
	return t


func is_valid() -> bool:
	return points.size() >= 4


func train_length() -> float:
	return car_spacing * float(num_cars - 1)
