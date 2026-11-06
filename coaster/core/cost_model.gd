class_name CostModel
extends RefCounted
## What a coaster costs to build. Game numbers in dollars, chosen so a decent
## starter coaster lands around $1.5M and the contract budgets bite.

const STATION := 150000.0
const LIFT_PER_M := 900.0
const LAUNCH_PER_M := 9000.0
const BRAKE_PER_M := 600.0
const TUNNEL_PER_M := 6000.0
const CUT_PER_M := 1200.0
const EARTH_PER_M3 := 12.0
const INVERSION := 40000.0
const TRAIN_CAR := 60000.0


## Returns {"total": float, "parts": [{"label": String, "value": float}]}
static func estimate(data: TrackData, spline: TrackSpline, site: SiteAnalysis) -> Dictionary:
	var ty := data.type_info()
	var parts: Array[Dictionary] = []
	var seg_len := {}
	for k in spline.count:
		var seg := spline.segments[k]
		seg_len[seg] = seg_len.get(seg, 0.0) + spline.ds
	parts.append({"label": "%s track (%.0f m)" % [ty["name"], spline.length], "value": spline.length * float(ty["cost_per_m"])})
	parts.append({"label": "Station", "value": STATION})
	parts.append({"label": "Train (%d cars)" % data.num_cars, "value": TRAIN_CAR * data.num_cars})
	_add(parts, "Chain lift", seg_len.get(TrackPoint.Segment.LIFT, 0.0) * LIFT_PER_M)
	_add(parts, "Launch motors", seg_len.get(TrackPoint.Segment.LAUNCH, 0.0) * LAUNCH_PER_M)
	_add(parts, "Brakes", seg_len.get(TrackPoint.Segment.BRAKE, 0.0) * BRAKE_PER_M)
	if site != null:
		_add(parts, "Supports", site.support_height_total * float(ty["support_cost_per_m"]))
		_add(parts, "Tunnels (%.0f m)" % site.tunnel_length, site.tunnel_length * TUNNEL_PER_M)
		_add(parts, "Cuttings", site.cut_length * CUT_PER_M)
	_add(parts, "Inversions", spline.inversions * INVERSION)
	_add(parts, "Earthworks", data.terrain.earthworks_m3() * EARTH_PER_M3)
	var scenery := 0.0
	for p in data.props:
		scenery += float(Props.SHAPES[p["k"]]["cost"])
	_add(parts, "Scenery", scenery)
	var total := 0.0
	for p in parts:
		total += float(p["value"])
	return {"total": total, "parts": parts}


static func _add(parts: Array[Dictionary], label: String, value: float) -> void:
	if value >= 1.0:
		parts.append({"label": label, "value": value})


static func money(v: float) -> String:
	if absf(v) >= 1e6:
		return "$%.2fM" % (v / 1e6)
	if absf(v) >= 1e3:
		return "$%.0fk" % (v / 1e3)
	return "$%.0f" % v
