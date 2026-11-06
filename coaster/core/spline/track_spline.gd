class_name TrackSpline
extends RefCounted
## The baked, arc-length parameterised track.
##
## The editor gives us a loose list of control points. Physics, rendering and
## scoring all want something else: "where is the track, which way is up and
## how hard is it curving, `s` metres from the start?" Baking answers that once
## and stores it in flat packed arrays sampled every `ds` metres, so lookups
## during the ride are a couple of array reads and a lerp - no allocations.
##
## Pipeline:
##   1. Centripetal Catmull-Rom through the control points (closed loop).
##      Centripetal knots (alpha = 0.5) never overshoot into cusps or
##      self-loops, which uniform Catmull-Rom does on uneven point spacing.
##   2. Dense sampling, then resampling at uniform arc length.
##   3. Tangent T = dP/ds and curvature vector K = d²P/ds² (points at the centre
##      of the turn, |K| = 1/radius). K is lightly smoothed: Catmull-Rom is only
##      C1, so raw curvature steps at every control point, which would show up
##      as G-force spikes a real (flexible, multi-axle) train never feels.
##   4. A base "unbanked" frame transported along the track (see _build_frames).
##   5. Banking (roll about T), either manual or automatic (apply_banking).
##
## Everything here is in metres, seconds and radians. World up is +Y.

const DEFAULT_SPACING := 0.5
const G := 9.81
## How strongly the base frame is pulled back to "level" per metre of track.
const UPRIGHT_PULL_PER_M := 0.08
## Curvature smoothing radius in metres (roughly half a car length).
const CURVATURE_SMOOTH_M := 1.5
## Auto-bank smoothing radius in metres: limits how fast the track can roll.
const BANK_SMOOTH_M := 5.0

var length := 0.0
var count := 0
var ds := DEFAULT_SPACING

var positions := PackedVector3Array()
var tangents := PackedVector3Array()
var curvatures := PackedVector3Array()
var base_ups := PackedVector3Array()
var ups := PackedVector3Array()
var rights := PackedVector3Array()
var rolls := PackedFloat32Array()
var segments := PackedByteArray()
## Which control-point segment each sample lies on, and how far along it (0..1).
var sample_segment := PackedInt32Array()
var sample_t := PackedFloat32Array()
## Arc length at which each control point sits.
var point_s := PackedFloat32Array()
var inversions := 0


# -----------------------------------------------------------------------------
# Baking
# -----------------------------------------------------------------------------

## Bakes geometry and the unbanked frame. Call apply_banking() afterwards
## (TrackAnalyzer does both, because auto-banking needs a speed estimate).
func bake(data: TrackData, spacing: float = DEFAULT_SPACING) -> bool:
	var n := data.points.size()
	if n < 3:
		count = 0
		length = 0.0
		return false

	# --- 1+2. Dense Catmull-Rom sampling ------------------------------------
	var dense_p := PackedVector3Array()
	var dense_s := PackedFloat32Array()
	var dense_seg := PackedInt32Array()
	var dense_t := PackedFloat32Array()
	point_s.resize(n)
	var acc := 0.0
	var prev := data.points[0].position
	for i in n:
		var p0 := data.points[(i - 1 + n) % n].position
		var p1 := data.points[i].position
		var p2 := data.points[(i + 1) % n].position
		var p3 := data.points[(i + 2) % n].position
		var knots := _centripetal_knots(p0, p1, p2, p3)
		var steps := clampi(ceili(p1.distance_to(p2) / 0.2), 12, 2000)
		point_s[i] = acc
		for k in steps:
			var t := float(k) / float(steps)
			var p := _catmull_rom(p0, p1, p2, p3, knots, t)
			acc += p.distance_to(prev) if dense_p.size() > 0 else 0.0
			prev = p
			dense_p.append(p)
			dense_s.append(acc)
			dense_seg.append(i)
			dense_t.append(t)
	# Close the circuit back at point 0.
	acc += data.points[0].position.distance_to(prev)
	dense_p.append(data.points[0].position)
	dense_s.append(acc)
	dense_seg.append(n - 1)
	dense_t.append(1.0)
	length = acc
	if length < 1.0:
		count = 0
		return false

	count = maxi(16, roundi(length / spacing))
	ds = length / float(count)
	positions.resize(count)
	segments.resize(count)
	sample_segment.resize(count)
	sample_t.resize(count)
	var j := 0
	for k in count:
		var target := float(k) * ds
		while j < dense_s.size() - 2 and dense_s[j + 1] < target:
			j += 1
		var span := maxf(dense_s[j + 1] - dense_s[j], 1e-6)
		var f := clampf((target - dense_s[j]) / span, 0.0, 1.0)
		positions[k] = dense_p[j].lerp(dense_p[j + 1], f)
		var seg := dense_seg[j]
		var t_next := dense_t[j + 1] if dense_seg[j + 1] == seg else 1.0
		sample_segment[k] = seg
		sample_t[k] = lerpf(dense_t[j], t_next, f)
		segments[k] = data.points[seg].segment

	# --- 3. Tangent and curvature by finite differences ----------------------
	tangents.resize(count)
	curvatures.resize(count)
	var inv_ds2 := 1.0 / (ds * ds)
	for k in count:
		var pa := positions[(k - 1 + count) % count]
		var pb := positions[k]
		var pc := positions[(k + 1) % count]
		tangents[k] = (pc - pa).normalized()
		# Second derivative w.r.t. arc length = curvature vector.
		curvatures[k] = (pc - 2.0 * pb + pa) * inv_ds2
	_smooth_vec3(curvatures, maxi(1, roundi(CURVATURE_SMOOTH_M / ds)))
	for k in count:
		# Curvature must be perpendicular to the tangent; drop numerical leftovers.
		var t := tangents[k]
		curvatures[k] -= t * curvatures[k].dot(t)

	# --- 4. Base frame --------------------------------------------------------
	_build_frames()
	# Until banking is applied, the banked frame equals the base frame.
	rolls.resize(count)
	rolls.fill(0.0)
	ups = base_ups.duplicate()
	rights.resize(count)
	for k in count:
		rights[k] = tangents[k].cross(ups[k]).normalized()
	_count_inversions()
	return true


## Builds the unbanked "up" vector at every sample.
##
## We cannot just project world-up onto the plane perpendicular to T: in a
## vertical loop that flips 180° as the track passes vertical, and the top of a
## loop would come out "right side up". Instead we *transport* the frame along
## the track (each step: remove the component of `up` along the new tangent and
## renormalise - a first-order rotation-minimising frame), which carries the
## frame smoothly through loops and over the top.
##
## Pure transport slowly drifts after twisted 3D curves, leaving straight track
## with a stray roll. So whenever the track is not steep and the frame is not
## upside down, we gently pull it back towards level. Loops and inversions are
## untouched because the pull is disabled while steep or inverted.
func _build_frames() -> void:
	base_ups.resize(count)
	var pull := 1.0 - pow(1.0 - UPRIGHT_PULL_PER_M, ds)
	var up := Vector3.UP
	# Two passes: the second starts from where the first ended so the seam
	# where the circuit closes is continuous.
	for pass_i in 2:
		for k in count:
			var t := tangents[k]
			up = up - t * up.dot(t)
			if up.length_squared() < 1e-8:
				up = Vector3.BACK - t * t.z
			up = up.normalized()
			if absf(t.y) < 0.85:
				var level := (Vector3.UP - t * t.y).normalized()
				if up.dot(level) > 0.0:
					up = up.slerp(level, pull).normalized()
			base_ups[k] = up


## Applies banking (roll about the tangent) to produce the final up/right.
##
## `speeds` is the expected speed at each sample (from a test simulation). With
## auto-bank, we choose the roll that makes lateral G zero - the way a real
## designer banks a turn so riders are pushed straight into their seats:
##
##   The force riders feel per unit mass (the "specific force") is
##       f = a - g_vec = v²·K + g·Y          (ignoring along-track acceleration)
##   Split f in the base frame: fu = f·U0, fr = f·R0. Rolling by θ gives
##       up(θ)    = U0·cosθ + R0·sinθ
##       right(θ) = R0·cosθ - U0·sinθ
##       lateral  = f·right(θ) = fr·cosθ - fu·sinθ
##   which is zero when tanθ = fr / fu.
##
## When fu is small or negative (airtime, top of a loop) the "ideal" bank is
## meaningless, so it fades to zero there. The result is then smoothed so the
## track cannot roll unrealistically fast.
func apply_banking(data: TrackData, speeds: PackedFloat32Array) -> void:
	if count == 0:
		return
	var n := data.points.size()
	var auto_roll := PackedFloat32Array()
	auto_roll.resize(count)
	var gy := Vector3(0.0, G, 0.0)
	for k in count:
		var v := speeds[k] if k < speeds.size() else 0.0
		var f := curvatures[k] * (v * v) + gy
		var u0 := base_ups[k]
		var r0 := tangents[k].cross(u0)
		var fu := f.dot(u0)
		var fr := f.dot(r0)
		var weight := clampf((fu / G - 0.2) / 0.3, 0.0, 1.0)
		auto_roll[k] = atan(fr / fu) * weight if fu > 0.01 else 0.0
	var radius := maxi(1, roundi(BANK_SMOOTH_M / ds))
	_smooth_float(auto_roll, radius)
	_smooth_float(auto_roll, radius)

	for k in count:
		var i := sample_segment[k]
		var a := data.points[i]
		var b := data.points[(i + 1) % n]
		var st := smoothstep(0.0, 1.0, sample_t[k])
		var manual := deg_to_rad(lerpf(a.bank_deg, b.bank_deg, st))
		var w := lerpf(1.0 if a.auto_bank else 0.0, 1.0 if b.auto_bank else 0.0, st)
		var roll := lerpf(manual, auto_roll[k], w)
		rolls[k] = roll
		var u0 := base_ups[k]
		var r0 := tangents[k].cross(u0)
		var up := (u0 * cos(roll) + r0 * sin(roll)).normalized()
		ups[k] = up
		rights[k] = tangents[k].cross(up).normalized()
	_count_inversions()


func _count_inversions() -> void:
	# Hysteresis so a track hovering around 90° of roll is not counted twice.
	inversions = 0
	var inverted := false
	for k in count:
		var y := ups[k].y
		if not inverted and y < -0.3:
			inverted = true
			inversions += 1
		elif inverted and y > 0.3:
			inverted = false


# -----------------------------------------------------------------------------
# Lookups (allocation free; all take an arc length `s` that may be outside
# [0, length) - it wraps around the circuit).
# -----------------------------------------------------------------------------

func index_at(s: float) -> int:
	return int(fposmod(s, length) / ds) % count


func position_at(s: float) -> Vector3:
	var x := fposmod(s, length) / ds
	var i := int(x) % count
	return positions[i].lerp(positions[(i + 1) % count], x - floorf(x))


func tangent_at(s: float) -> Vector3:
	var x := fposmod(s, length) / ds
	var i := int(x) % count
	return tangents[i].lerp(tangents[(i + 1) % count], x - floorf(x)).normalized()


func up_at(s: float) -> Vector3:
	var x := fposmod(s, length) / ds
	var i := int(x) % count
	return ups[i].lerp(ups[(i + 1) % count], x - floorf(x)).normalized()


func curvature_at(s: float) -> Vector3:
	var x := fposmod(s, length) / ds
	var i := int(x) % count
	return curvatures[i].lerp(curvatures[(i + 1) % count], x - floorf(x))


func segment_at(s: float) -> int:
	return segments[int(fposmod(s, length) / ds + 0.5) % count]


## Orientation of a car at `s`: X = right, Y = up, -Z = forward (Godot convention).
func basis_at(s: float) -> Basis:
	var t := tangent_at(s)
	var up := up_at(s)
	up = (up - t * up.dot(t)).normalized()
	return Basis(t.cross(up), up, -t)


func transform_at(s: float) -> Transform3D:
	return Transform3D(basis_at(s), position_at(s))


## G-forces felt by a rider at `s` moving at `v` with along-track acceleration
## `a_t`. Returns Vector3(vertical, lateral, longitudinal) in g.
##
##   acceleration      a = v²·K + a_t·T
##   specific force    f = a - g_vec = a + g·Y   (what the seat pushes you with)
##   vertical G  = f·up / g      (1.0 sitting still, >1 pressed down, <0 airtime)
##   lateral G   = f·right / g   (positive = pushed towards the right)
##   longit. G   = f·T / g
func g_forces_at(s: float, v: float, a_t: float) -> Vector3:
	var t := tangent_at(s)
	var f := curvature_at(s) * (v * v) + t * a_t + Vector3(0.0, G, 0.0)
	var up := up_at(s)
	var right := t.cross(up)
	return Vector3(f.dot(up) / G, -f.dot(right) / G, f.dot(t) / G)


func max_height() -> float:
	var h := -INF
	for p in positions:
		h = maxf(h, p.y)
	return h


func min_height() -> float:
	var h := INF
	for p in positions:
		h = minf(h, p.y)
	return h


## Largest continuous height loss anywhere along the circuit.
func max_drop() -> float:
	var best := 0.0
	var top := positions[0].y if count > 0 else 0.0
	for k in count * 2:  # twice round so a drop that crosses the seam is seen
		var y := positions[k % count].y
		if k > 0 and y > positions[(k - 1) % count].y:
			top = y
		best = maxf(best, top - y)
	return best


## Arc length of the sample closest to a world position (used by the editor UI).
func nearest_s(world: Vector3) -> float:
	var best := INF
	var best_k := 0
	for k in count:
		var d := positions[k].distance_squared_to(world)
		if d < best:
			best = d
			best_k = k
	return float(best_k) * ds


# -----------------------------------------------------------------------------
# Math helpers
# -----------------------------------------------------------------------------

## Knot values for centripetal parameterisation: t_{i+1} = t_i + |P_{i+1}-P_i|^0.5
static func _centripetal_knots(p0: Vector3, p1: Vector3, p2: Vector3, p3: Vector3) -> Vector4:
	var t1 := sqrt(maxf(p0.distance_to(p1), 1e-4))
	var t2 := t1 + sqrt(maxf(p1.distance_to(p2), 1e-4))
	var t3 := t2 + sqrt(maxf(p2.distance_to(p3), 1e-4))
	return Vector4(0.0, t1, t2, t3)


## Barry-Goldman pyramidal evaluation of a Catmull-Rom segment between p1 and
## p2 at local parameter t in [0, 1].
static func _catmull_rom(p0: Vector3, p1: Vector3, p2: Vector3, p3: Vector3, kn: Vector4, t: float) -> Vector3:
	var t0 := kn.x
	var t1 := kn.y
	var t2 := kn.z
	var t3 := kn.w
	var u := lerpf(t1, t2, t)
	var a1 := p0 * ((t1 - u) / (t1 - t0)) + p1 * ((u - t0) / (t1 - t0))
	var a2 := p1 * ((t2 - u) / (t2 - t1)) + p2 * ((u - t1) / (t2 - t1))
	var a3 := p2 * ((t3 - u) / (t3 - t2)) + p3 * ((u - t2) / (t3 - t2))
	var b1 := a1 * ((t2 - u) / (t2 - t0)) + a2 * ((u - t0) / (t2 - t0))
	var b2 := a2 * ((t3 - u) / (t3 - t1)) + a3 * ((u - t1) / (t3 - t1))
	return b1 * ((t2 - u) / (t2 - t1)) + b2 * ((u - t1) / (t2 - t1))


## Circular moving average (the track is a closed loop).
static func _smooth_vec3(arr: PackedVector3Array, radius: int) -> void:
	var n := arr.size()
	radius = mini(radius, n / 2 - 1)
	if n == 0 or radius <= 0:
		return
	var src := arr.duplicate()
	var sum := Vector3.ZERO
	for k in range(-radius, radius + 1):
		sum += src[(k + n) % n]
	var inv := 1.0 / float(2 * radius + 1)
	for k in n:
		arr[k] = sum * inv
		sum += src[(k + radius + 1) % n] - src[(k - radius + n) % n]


static func _smooth_float(arr: PackedFloat32Array, radius: int) -> void:
	var n := arr.size()
	radius = mini(radius, n / 2 - 1)
	if n == 0 or radius <= 0:
		return
	var src := arr.duplicate()
	var sum := 0.0
	for k in range(-radius, radius + 1):
		sum += src[(k + n) % n]
	var inv := 1.0 / float(2 * radius + 1)
	for k in n:
		arr[k] = sum * inv
		sum += src[(k + radius + 1) % n] - src[(k - radius + n) % n]
