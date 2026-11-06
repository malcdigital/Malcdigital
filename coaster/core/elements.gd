class_name Elements
extends RefCounted
## Generators for common coaster elements. Each returns new control points to
## insert AFTER an entry point, built in a local frame:
##   entry   = world position of the point we build from
##   forward = horizontal direction of travel (normalised, y = 0)
## Points are placed so the Catmull-Rom spline through them gives the right
## shape; the entry point itself is not included.

enum Kind { HILL, DROP, LOOP, HELIX_LEFT, HELIX_RIGHT, TURN_LEFT, TURN_RIGHT, LIFT_HILL, LAUNCH, STRAIGHT, BRAKES, UTURN_LEFT, UTURN_RIGHT, SPLASHDOWN, HEARTLINE_ROLL }

const NAMES := {
	Kind.HILL: "Airtime hill",
	Kind.DROP: "Drop",
	Kind.LOOP: "Vertical loop",
	Kind.HELIX_LEFT: "Helix (left)",
	Kind.HELIX_RIGHT: "Helix (right)",
	Kind.TURN_LEFT: "Turn left 90°",
	Kind.TURN_RIGHT: "Turn right 90°",
	Kind.LIFT_HILL: "Chain lift hill",
	Kind.LAUNCH: "Launch track",
	Kind.STRAIGHT: "Straight",
	Kind.BRAKES: "Brake run",
	Kind.UTURN_LEFT: "Turn left 180°",
	Kind.UTURN_RIGHT: "Turn right 180°",
	Kind.SPLASHDOWN: "Splashdown",
	Kind.HEARTLINE_ROLL: "Heartline roll",
}

const MIN_HEIGHT := 1.0


## `speed` is the expected train speed at the entry (m/s); some elements use
## it to pick a sensible size, which is the "snap to a good element" assist.
## `ctx` can carry {"water_level": float} for the splashdown.
static func build(kind: int, entry: Vector3, forward: Vector3, speed: float, ctx: Dictionary = {}) -> Array[TrackPoint]:
	var pts := _build(kind, entry, forward, speed, ctx)
	# Interior points of dense, generated shapes are "minor": the editor
	# shows them as small dots so the element reads as one piece.
	if pts.size() > 4:
		for i in range(0, pts.size() - 1):
			pts[i].minor = true
	return pts


static func _build(kind: int, entry: Vector3, forward: Vector3, speed: float, ctx: Dictionary) -> Array[TrackPoint]:
	forward = Vector3(forward.x, 0.0, forward.z)
	if forward.length_squared() < 1e-6:
		forward = Vector3.FORWARD
	forward = forward.normalized()
	var right := forward.cross(Vector3.UP).normalized()
	var v := maxf(speed, 8.0)
	match kind:
		Kind.HILL:
			# Pull-up angle grows with speed so faster trains get bigger hills.
			var alpha := deg_to_rad(clampf(12.0 + v * 1.1, 20.0, 48.0))
			return _profile(entry, forward, right, ProfileBuilder.hill(v, alpha), 0.0, 10.0)
		Kind.DROP:
			var y_end := MIN_HEIGHT + 0.5 - entry.y
			if y_end > -3.0:
				y_end = -3.0
			return _profile(entry, forward, right, ProfileBuilder.drop(speed, y_end), 0.0, 10.0)
		Kind.LOOP:
			# Below ~14 m/s a loop gets so small the train cannot fit through it.
			var prof := ProfileBuilder.loop(maxf(v, 14.0))
			var top := 0.0
			for p in prof:
				top = maxf(top, p.y)
			# Sideways shift so the exit runs beside the entry instead of into it.
			# Wing seats stick out beside the track: give their legs room.
			var wing: float = ctx.get("seat_offset", 0.0)
			return _profile(entry, forward, right, prof, clampf(top * 0.1, 2.2, 3.4) + wing * 2.4, 10.0, 6.0)
		Kind.HELIX_LEFT, Kind.HELIX_RIGHT:
			var dir := -1.0 if kind == Kind.HELIX_LEFT else 1.0
			# Radius for ~1.8 g of sideways pull, which auto-bank turns into a
			# comfortable ~2 g straight into the seat.
			var radius := clampf(v * v / (9.81 * 1.8), 12.0, 30.0)
			var drop := clampf(entry.y - MIN_HEIGHT, 0.0, radius * 0.7)
			return turn(entry, forward, dir, radius, TAU, drop)
		Kind.TURN_LEFT, Kind.TURN_RIGHT, Kind.UTURN_LEFT, Kind.UTURN_RIGHT:
			var dir := -1.0 if kind == Kind.TURN_LEFT or kind == Kind.UTURN_LEFT else 1.0
			var angle := PI * 0.5 if kind == Kind.TURN_LEFT or kind == Kind.TURN_RIGHT else PI
			var radius := clampf(v * v / (9.81 * 1.5), 10.0, 35.0)
			return turn(entry, forward, dir, radius, angle, 0.0)
		Kind.LIFT_HILL:
			var h := 30.0
			var pts := _pts(entry, forward, right, [
				[8.0, 0.0, 1.0], [h * 1.2, 0.0, h * 0.85], [h * 1.45, 0.0, h], [h * 1.75, 0.0, h * 0.82]])
			pts[0].segment = TrackPoint.Segment.LIFT
			pts[1].segment = TrackPoint.Segment.LIFT
			return pts
		Kind.LAUNCH:
			var pts := _pts(entry, forward, right, [[12.0, 0.0, 0.0], [55.0, 0.0, 0.0], [70.0, 0.0, 0.0]])
			pts[0].segment = TrackPoint.Segment.LAUNCH
			return pts
		Kind.SPLASHDOWN:
			# Dip so only the bottom of the car (about 0.45 m) enters the water.
			var water: float = ctx.get("water_level", -1000.0)
			var bottom := water + SiteAnalysis.CAR_BOTTOM - 0.45 if water > -999.0 else MIN_HEIGHT
			var d := maxf(entry.y - bottom, 0.0)
			var len := maxf(60.0, d * 6.0)
			var out: Array[TrackPoint] = []
			for o in [[0.2, 0.15], [0.38, 0.8], [0.5, 1.0], [0.62, 0.8], [0.8, 0.15], [1.0, 0.0], [1.15, 0.0]]:
				out.append(TrackPoint.new(entry + forward * (len * o[0]) + Vector3.UP * (-d * o[1])))
			return out
		Kind.HEARTLINE_ROLL:
			# A full roll about the riders' heartline on straight track: banking
			# goes 0 -> 360° across the points (auto-bank off).
			var len := clampf(v * 2.2, 30.0, 60.0)
			var out: Array[TrackPoint] = []
			for i in 6:
				var f := float(i) / 5.0
				var p := TrackPoint.new(entry + forward * (6.0 + len * f), TrackPoint.Segment.NORMAL, 360.0 * smoothstep(0.0, 1.0, f), false)
				out.append(p)
			out.append(TrackPoint.new(entry + forward * (len + 16.0), TrackPoint.Segment.NORMAL, 360.0, true))
			out[0].bank_deg = 0.0
			return out
		Kind.BRAKES:
			var pts := _pts(entry, forward, right, [[8.0, 0.0, 0.0], [30.0, 0.0, 0.0]])
			pts[0].segment = TrackPoint.Segment.BRAKE
			pts[1].segment = TrackPoint.Segment.BRAKE
			return pts
	return _pts(entry, forward, right, [[15.0, 0.0, 0.0], [30.0, 0.0, 0.0]])


## Converts a 2D side-view profile (x forward, y up) to control points. The
## sideways `shift` is applied gradually over the profile. `lead_out` adds a
## straight point after the element; `lead_in` moves the element forwards.
static func _profile(entry: Vector3, fwd: Vector3, right: Vector3, prof: PackedVector2Array,
		shift: float, lead_out: float, lead_in: float = 0.0) -> Array[TrackPoint]:
	var out: Array[TrackPoint] = []
	var n := prof.size()
	if lead_in > 0.0:
		out.append(TrackPoint.new(entry + fwd * lead_in))
	for i in n:
		var p := prof[i]
		var lat := shift * smoothstep(0.0, 1.0, float(i + 1) / float(n))
		var w := entry + fwd * (p.x + lead_in) + right * lat + Vector3.UP * p.y
		w.y = maxf(w.y, MIN_HEIGHT)
		out.append(TrackPoint.new(w))
	if lead_out > 0.0 and n > 0:
		var last := out[out.size() - 1].position
		out.append(TrackPoint.new(last + fwd * lead_out))
	return out


## Points given as [forward, right, up] offsets from the entry.
static func _pts(entry: Vector3, fwd: Vector3, right: Vector3, offsets: Array) -> Array[TrackPoint]:
	var out: Array[TrackPoint] = []
	for o in offsets:
		var p: Vector3 = entry + fwd * float(o[0]) + right * float(o[1]) + Vector3.UP * float(o[2])
		p.y = maxf(p.y, MIN_HEIGHT)
		out.append(TrackPoint.new(p))
	return out


## Horizontal turn (or helix, when `angle` > 180° and `drop` > 0).
##
## A circle joined straight onto straight track has a sudden jump in curvature,
## which riders feel as a sideways jolt and which banking cannot follow. Real
## turns use transition spirals (clothoids): curvature ramps linearly from 0 to
## 1/radius over a transition length, stays constant, then ramps back down.
## We integrate that heading-vs-distance law and sample control points along it.
static func turn(entry: Vector3, fwd: Vector3, dir: float, radius: float, angle: float, drop: float) -> Array[TrackPoint]:
	var k_max := 1.0 / radius
	# Each transition turns through k_max * L / 2 radians; cap them at a third
	# of the total angle each so short turns still get a constant section.
	var trans := minf(radius * 0.8, angle / 3.0 * 2.0 / k_max)
	var arc := (angle - k_max * trans) / k_max   # length of the constant part
	var total := 2.0 * trans + arc
	var step := 0.5
	var heading := 0.0
	var pos := entry
	var out: Array[TrackPoint] = []
	var next_pt := 4.0
	var travelled := 0.0
	while travelled < total - 1e-3:
		var s_mid := travelled + step * 0.5
		var k := k_max
		if s_mid < trans:
			k = k_max * s_mid / trans
		elif s_mid > total - trans:
			k = k_max * (total - s_mid) / trans
		heading += k * step
		var d := fwd.rotated(Vector3.UP, -heading * dir)
		pos += d * step
		travelled += step
		pos.y = maxf(entry.y - drop * smoothstep(0.0, 1.0, travelled / total), MIN_HEIGHT)
		if travelled >= next_pt or travelled >= total - 1e-3:
			out.append(TrackPoint.new(pos))
			next_pt += 4.0
	return out
