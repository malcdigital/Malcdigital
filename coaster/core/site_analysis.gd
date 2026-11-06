class_name SiteAnalysis
extends RefCounted
## Everything about how the track sits in the world, beyond its own shape:
##
##   - terrain: which parts run in the open, in a cutting (trench) or in a tunnel
##   - water: how deep the train dips into a lake (splashdowns)
##   - supports: where columns go, skipping ones that would hit other track
##   - near misses: places riders' heads pass close to other track, supports,
##     scenery or terrain at speed (thrilling), and collisions (dangerous)
##   - contract zones: areas that must stay clear (e.g. a park path)
##
## All of it is pure data: TrackView draws the supports and tunnels from here,
## the cost model prices them, and the scorer rewards near misses.

enum Env { OPEN, CUT, TUNNEL }
enum Hit { TRACK, SUPPORT, PROP, TERRAIN }

const HIT_NAMES := ["track", "support", "scenery", "the ground"]

## Car envelope around the heartline (metres).
const CAR_BOTTOM := 1.5
const CAR_TOP := 1.2
## Earth needed above the car roof to count as a tunnel instead of a cutting.
const TUNNEL_COVER := 1.5
## Head clearance (to the surface of an object) that feels like a near miss.
const NEAR_MISS := 2.5
const COLLISION := 0.3
const NEAR_MISS_MIN_SPEED := 8.0
## Ignore our own structure within this arc distance (the train itself, the
## supports directly under it).
const SELF_ARC := 15.0
const SUPPORT_EVERY_M := 8.0
const HASH_CELL := 4.0

var env := PackedByteArray()            # per sample, Env
var ground := PackedFloat32Array()      # per sample, terrain height under the heartline
var water_depth := PackedFloat32Array() # per sample, how deep the car bottom is in water
## Each beam: {"a": Vector3, "b": Vector3, "r": float, "k": sample index}
var beams: Array[Dictionary] = []
var support_height_total := 0.0
var supports_blocked := 0
var tunnel_length := 0.0
var tunnel_entries := 0
var cut_length := 0.0
## Each: {"s": float, "kind": Hit, "clearance": float}
var near_misses: Array[Dictionary] = []
var collisions: Array[Dictionary] = []
var submerged: Array[Dictionary] = []
var zone_violations: Array[Dictionary] = []
## Terrain heights with cuttings dug out, for drawing.
var render_heights := PackedFloat32Array()

# Spatial hash of obstacles: cell -> PackedInt32Array of item indices.
var _hash := {}
var _item_pos := PackedVector3Array()
var _item_r := PackedFloat32Array()
var _item_k := PackedInt32Array()
var _item_kind := PackedByteArray()


# -----------------------------------------------------------------------------
# Pass 1: before simulating (needs only positions, not banking)
# -----------------------------------------------------------------------------

func classify(spline: TrackSpline, data: TrackData) -> void:
	var n := spline.count
	var terrain := data.terrain
	env.resize(n)
	ground.resize(n)
	water_depth.resize(n)
	tunnel_length = 0.0
	tunnel_entries = 0
	cut_length = 0.0
	submerged.clear()
	var prev_env := -1
	for k in n:
		var p := spline.positions[k]
		var g := terrain.height_at(p.x, p.z)
		ground[k] = g
		var e := Env.OPEN
		if g > p.y - CAR_BOTTOM + 0.3:
			e = Env.TUNNEL if g >= p.y + CAR_TOP + TUNNEL_COVER else Env.CUT
		env[k] = e
		if e == Env.TUNNEL:
			tunnel_length += spline.ds
			if prev_env != Env.TUNNEL:
				tunnel_entries += 1
		elif e == Env.CUT:
			cut_length += spline.ds
		prev_env = e
		# Water: only over the lake, where the ground is below the water line.
		var d := 0.0
		if terrain.has_water() and g < terrain.water_level and e == Env.OPEN:
			d = maxf(terrain.water_level - (p.y - CAR_BOTTOM), 0.0)
		water_depth[k] = d
		if d > CAR_BOTTOM + CAR_TOP * 0.5:
			_add_event(submerged, float(k) * spline.ds, Hit.TERRAIN, d)
	spline.water_depth = water_depth


# -----------------------------------------------------------------------------
# Pass 2: after banking and simulating
# -----------------------------------------------------------------------------

func build(spline: TrackSpline, data: TrackData, record: RideRecord, zones: Array) -> void:
	var ty := data.type_info()
	_hash.clear()
	_item_pos = PackedVector3Array()
	_item_r = PackedFloat32Array()
	_item_k = PackedInt32Array()
	_item_kind = PackedByteArray()
	beams.clear()
	near_misses.clear()
	collisions.clear()
	zone_violations.clear()
	support_height_total = 0.0
	supports_blocked = 0
	var n := spline.count
	var flying: bool = ty["prone"]

	# Track structure as obstacles: the car envelope around the heartline and
	# the rails/spine below (or above, for flying).
	for k in range(0, n, 2):
		var p := spline.positions[k]
		var u := spline.ups[k]
		_add_item(p, 1.0, k, Hit.TRACK)
		_add_item(p + u * (1.2 if flying else -1.3), 0.45, k, Hit.TRACK)

	_plan_supports(spline, data, ty)
	for pr in data.props:
		var base := Vector3(pr["x"], data.terrain.height_at(pr["x"], pr["z"]), pr["z"])
		var h := Props.height(pr)
		var r := Props.radius(pr)
		var y := 0.0
		while y <= h:
			_add_item(base + Vector3.UP * y, r, -1, Hit.PROP)
			y += 1.5

	_scan_clearances(spline, data, record, ty)
	_check_zones(spline, data, zones)
	_carve(spline, data)


func _add_item(p: Vector3, r: float, k: int, kind: int) -> void:
	var i := _item_pos.size()
	_item_pos.append(p)
	_item_r.append(r)
	_item_k.append(k)
	_item_kind.append(kind)
	var c := Vector3i(floori(p.x / HASH_CELL), floori(p.y / HASH_CELL), floori(p.z / HASH_CELL))
	if not _hash.has(c):
		_hash[c] = PackedInt32Array()
	var arr: PackedInt32Array = _hash[c]
	arr.append(i)
	_hash[c] = arr


## Closest obstacle surface to `h`, ignoring structure within SELF_ARC of
## sample `k`. Returns Vector2(clearance, kind).
func _nearest(h: Vector3, k: int, n: int, ds: float, reach: float) -> Vector2:
	var best := INF
	var kind := -1
	var c0 := Vector3i(floori(h.x / HASH_CELL), floori(h.y / HASH_CELL), floori(h.z / HASH_CELL))
	var span := ceili(reach / HASH_CELL)
	for dx in range(-span, span + 1):
		for dy in range(-span, span + 1):
			for dz in range(-span, span + 1):
				var key := c0 + Vector3i(dx, dy, dz)
				if not _hash.has(key):
					continue
				for i in _hash[key]:
					var ik := _item_k[i]
					if ik >= 0:
						var arc := absi(ik - k)
						arc = mini(arc, n - arc)
						if float(arc) * ds < SELF_ARC:
							continue
					var d := h.distance_to(_item_pos[i]) - _item_r[i]
					if d < best:
						best = d
						kind = _item_kind[i]
	return Vector2(best, kind)


func _plan_supports(spline: TrackSpline, data: TrackData, ty: Dictionary) -> void:
	var n := spline.count
	var every := maxi(1, roundi(SUPPORT_EVERY_M / spline.ds))
	var style: String = ty["style"]
	var terrain := data.terrain
	for k in range(0, n, every):
		if env[k] != Env.OPEN:
			continue
		var p := spline.positions[k]
		var u := spline.ups[k]
		var r := spline.rights[k]
		if u.y < 0.55:
			continue   # steep or inverted: held by the neighbouring supports
		var flat_r := Vector3(r.x, 0.0, r.z).normalized()
		var new_beams: Array[Dictionary] = []
		if style == "flying":
			# Riders hang under the rails, so the column stands beside the
			# track and an arm reaches over to the rails.
			var attach := p + u * 1.5
			var side := attach + flat_r * 2.6
			var g := terrain.height_at(side.x, side.z)
			if attach.y - g < 1.0:
				continue
			new_beams.append({"a": Vector3(side.x, g, side.z), "b": side + Vector3.UP * 0.3, "r": 0.32, "k": k})
			new_beams.append({"a": side + Vector3.UP * 0.3, "b": attach, "r": 0.22, "k": k})
		else:
			var top := p - u * 1.95
			var g := terrain.height_at(top.x, top.z)
			if top.y - g < 0.6:
				continue
			if style == "wood":
				# A wooden bent: two posts and a cross brace.
				var a := top - flat_r * 1.2
				var b := top + flat_r * 1.2
				var ga := terrain.height_at(a.x, a.z)
				var gb := terrain.height_at(b.x, b.z)
				new_beams.append({"a": Vector3(a.x, ga, a.z), "b": a, "r": 0.16, "k": k})
				new_beams.append({"a": Vector3(b.x, gb, b.z), "b": b, "r": 0.16, "k": k})
				new_beams.append({"a": Vector3(a.x, ga, a.z), "b": b, "r": 0.09, "k": k})
				new_beams.append({"a": a, "b": b, "r": 0.1, "k": k})
			else:
				new_beams.append({"a": Vector3(top.x, g, top.z), "b": top, "r": 0.3, "k": k})
		# Skip a support that would pass through another part of the track.
		var blocked := false
		for bm in new_beams:
			var a: Vector3 = bm["a"]
			var b: Vector3 = bm["b"]
			var len := a.distance_to(b)
			var steps := maxi(1, ceili(len / 1.5))
			for i in steps + 1:
				var q := a.lerp(b, float(i) / steps)
				if _nearest(q, k, n, spline.ds, 2.0).x < 0.6:
					blocked = true
					break
			if blocked:
				break
		if blocked:
			supports_blocked += 1
			continue
		for bm in new_beams:
			beams.append(bm)
			var a: Vector3 = bm["a"]
			var b: Vector3 = bm["b"]
			support_height_total += a.distance_to(b)
			var len := a.distance_to(b)
			var steps := maxi(1, ceili(len / 1.5))
			for i in steps + 1:
				_add_item(a.lerp(b, float(i) / steps), bm["r"], k, Hit.SUPPORT)


func _scan_clearances(spline: TrackSpline, data: TrackData, record: RideRecord, ty: Dictionary) -> void:
	var n := spline.count
	var offset: float = ty["seat_offset"]
	var flying: bool = ty["prone"]
	var run_start := -1
	var run_best := INF
	var run_kind := 0
	var run_s := 0.0
	for k in range(0, n + 2, 2):
		var clearance := INF
		var kind := 0
		var kk := k % n
		var speed := absf(record.sample_speed[kk]) if record != null and k < n else 0.0
		if k < n:
			var p := spline.positions[kk]
			var u := spline.ups[kk]
			var r := spline.rights[kk]
			var heads: Array[Vector3] = []
			if flying:
				heads.append(p - u * 0.2 + spline.tangents[kk] * 0.6)
			elif offset > 0.0:
				heads.append(p + u * 0.5 + r * offset)
				heads.append(p + u * 0.5 - r * offset)
			else:
				heads.append(p + u * 0.5)
			for h in heads:
				var hit := _nearest(h, kk, n, spline.ds, NEAR_MISS + 1.5)
				if hit.x < clearance:
					clearance = hit.x
					kind = int(hit.y)
				# Terrain beside / above the head (only out in the open; in a
				# tunnel the walls are part of the tunnel).
				if env[kk] == Env.OPEN:
					var above := data.terrain.height_at(h.x, h.z) - h.y
					if above > 0.0 and -above < clearance:
						clearance = -above    # head below the ground surface
						kind = Hit.TERRAIN
					for side in [-2.8, 2.8]:
						var q: Vector3 = h + Vector3(r.x, 0, r.z).normalized() * side
						if data.terrain.height_at(q.x, q.z) > h.y:
							var c := absf(side) - 1.0
							if c < clearance:
								clearance = c
								kind = Hit.TERRAIN
			if clearance < COLLISION and speed > 0.1:
				_add_event(collisions, float(kk) * spline.ds, kind, clearance)
		var close := k < n and clearance < NEAR_MISS and clearance >= COLLISION and speed >= NEAR_MISS_MIN_SPEED
		if close:
			if run_start < 0:
				run_start = kk
				run_best = INF
			if clearance < run_best:
				run_best = clearance
				run_kind = kind
				run_s = float(kk) * spline.ds
		elif run_start >= 0:
			near_misses.append({"s": run_s, "kind": run_kind, "clearance": run_best})
			run_start = -1
	# Diving into a tunnel at speed is a near miss of its own.
	var prev := Env.OPEN
	for k in n:
		if env[k] == Env.TUNNEL and prev != Env.TUNNEL and record != null and absf(record.sample_speed[k]) >= NEAR_MISS_MIN_SPEED:
			near_misses.append({"s": float(k) * spline.ds, "kind": Hit.TERRAIN, "clearance": 1.0})
		prev = env[k]


## Merge repeated hits at neighbouring samples into one event.
func _add_event(list: Array[Dictionary], s: float, kind: int, value: float) -> void:
	if not list.is_empty() and absf(float(list[list.size() - 1]["s"]) - s) < 6.0:
		if value < float(list[list.size() - 1]["clearance"]):
			list[list.size() - 1]["clearance"] = value
		return
	list.append({"s": s, "kind": kind, "clearance": value})


## Zones: [{"rect": Rect2 (x, z, w, d), "clear": metres of headroom}]
func _check_zones(spline: TrackSpline, data: TrackData, zones: Array) -> void:
	for z in zones:
		var rect: Rect2 = z["rect"]
		var clear: float = z["clear"]
		for bm in beams:
			var a: Vector3 = bm["a"]
			if rect.has_point(Vector2(a.x, a.z)):
				_add_event(zone_violations, float(bm["k"]) * spline.ds, Hit.SUPPORT, 0.0)
		for k in range(0, spline.count, 2):
			var p := spline.positions[k]
			if rect.has_point(Vector2(p.x, p.z)) and env[k] == Env.OPEN and p.y - CAR_BOTTOM - ground[k] < clear:
				_add_event(zone_violations, float(k) * spline.ds, Hit.TRACK, p.y - CAR_BOTTOM - ground[k])


## Dig cuttings: lower terrain vertices next to track that runs just below the
## surface, so the track runs through a trench instead of through solid ground.
## Also dig a short approach at each tunnel mouth.
func _carve(spline: TrackSpline, data: TrackData) -> void:
	var t := data.terrain
	render_heights = t.heights.duplicate()
	var n := spline.count
	for k in n:
		var cut := env[k] == Env.CUT
		if not cut and env[k] == Env.TUNNEL:
			# Near a portal: dig the first few metres so the mouth is open.
			var prev_open := env[(k - 6 + n) % n] != Env.TUNNEL or env[(k + 6) % n] != Env.TUNNEL
			cut = prev_open
		if not cut:
			continue
		var p := spline.positions[k]
		var floor_y := p.y - CAR_BOTTOM - 0.3
		var g := t.world_to_grid(p.x, p.z)
		var rad := 4.5 / TerrainData.CELL
		for j in range(maxi(0, int(g.y - rad) - 1), mini(TerrainData.RES, int(g.y + rad) + 2)):
			for i in range(maxi(0, int(g.x - rad) - 1), mini(TerrainData.RES, int(g.x + rad) + 2)):
				var d := Vector2(i, j).distance_to(g) * TerrainData.CELL
				if d > 4.5:
					continue
				# Trench walls slope up from the floor.
				var y := floor_y + maxf(d - 2.2, 0.0) * 1.2
				var idx := j * TerrainData.RES + i
				render_heights[idx] = minf(render_heights[idx], y)
