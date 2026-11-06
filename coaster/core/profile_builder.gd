class_name ProfileBuilder
extends RefCounted
## Designs vertical track profiles (hills, drops, loops) from the G-forces we
## want riders to feel, instead of from hand-placed points.
##
## Work in a 2D side view: x = distance forward, y = height, θ = pitch angle of
## the track. For a train at speed v on a curve of signed curvature κ (positive
## = curving upwards / towards the rider's head), the vertical G the rider
## feels is
##
##     n = cosθ + v²·κ / g          (gravity's share + centripetal share)
##
## Solve for the curvature that produces a desired n:
##
##     κ = g·(n - cosθ) / v²
##
## and integrate along arc length:  θ += κ·ds,  x += cosθ·ds,  y += sinθ·ds,
## with v from energy conservation  v² = v0² - 2g·(y - y0)  (friction ignored -
## the real ride will be very slightly slower, which only softens the forces).
##
## This is how real loops end up as "teardrops": a constant-ish G target with
## speed dropping near the top forces the radius to shrink there.

const G := 9.81
const STEP := 0.25
## Max rate of change of felt G (g per second): limits jerk, which riders feel
## as a "snap". Per metre of track that is JERK / v.
const JERK := 4.0

var points := PackedVector2Array()
var thetas := PackedFloat32Array()
var _theta := 0.0
var _pos := Vector2.ZERO
var _n := 1.0
var _v0sq := 0.0


func _init(v0: float) -> void:
	_v0sq = v0 * v0
	points.append(Vector2.ZERO)
	thetas.append(0.0)


func speed_sq() -> float:
	return maxf(_v0sq - 2.0 * G * _pos.y, 4.0)


## Follow target G `n_target` (float, or Callable(theta) -> float) until the
## pitch angle passes `until_theta`, or `max_len` metres have elapsed.
## `straight` keeps κ = 0 (n just follows cosθ).
func phase(n_target: Variant, until_theta: float, max_len: float = 400.0, straight: bool = false) -> void:
	var dir := signf(until_theta - _theta)
	var travelled := 0.0
	while travelled < max_len:
		if not straight and dir != 0.0 and (_theta - until_theta) * dir >= 0.0:
			break
		var target: float = n_target.call(_theta) if n_target is Callable else float(n_target)
		var kappa := 0.0
		if straight:
			_n = cos(_theta)
		else:
			_n = move_toward(_n, target, JERK * STEP / sqrt(speed_sq()))
			kappa = G * (_n - cos(_theta)) / speed_sq()
		_theta += kappa * STEP
		_pos += Vector2(cos(_theta), sin(_theta)) * STEP
		travelled += STEP
		points.append(_pos)
		thetas.append(_theta)


func position() -> Vector2:
	return _pos


func theta() -> float:
	return _theta


## Pick roughly evenly spaced points (every `spacing` metres of arc), always
## keeping the last one, for use as spline control points.
func resample(spacing: float) -> PackedVector2Array:
	var out := PackedVector2Array()
	var every := maxi(1, roundi(spacing / STEP))
	for i in range(every, points.size(), every):
		out.append(points[i])
	if out.is_empty() or out[out.size() - 1] != points[points.size() - 1]:
		out.append(points[points.size() - 1])
	return out


## Airtime hill: pull up at `n_pull` g to angle `alpha`, then float over the
## crest at `n_air` g. The descent is the mirror image of the climb, so the
## hill is symmetric and ends exactly at the entry height (with no friction the
## speed and forces mirror too).
static func hill(v0: float, alpha: float, n_pull: float = 2.4, n_air: float = 0.0) -> PackedVector2Array:
	var b := ProfileBuilder.new(v0)
	b.phase(n_pull, alpha)
	b.phase(n_air, 0.0)
	return _mirror_resample(b.points, 4.0)


## Vertical loop: G follows n_bottom at the base easing to n_top over the top.
## Returns the full loop in 2D; the caller adds a sideways shift.
static func loop(v0: float, n_bottom: float = 3.4, n_top: float = 0.9) -> PackedVector2Array:
	var b := ProfileBuilder.new(v0)
	var law := func(th: float) -> float:
		return n_top + (n_bottom - n_top) * (1.0 + cos(th)) * 0.5
	b.phase(law, PI)
	return _mirror_resample(b.points, 3.0)


## Completes a half profile by mirroring it about the vertical line through its
## last point (crest of a hill / top of a loop), then resamples it.
static func _mirror_resample(half: PackedVector2Array, spacing: float) -> PackedVector2Array:
	var top := half[half.size() - 1]
	var full := half.duplicate()
	for i in range(half.size() - 2, -1, -1):
		var p := half[i]
		full.append(Vector2(2.0 * top.x - p.x, p.y))
	var out := PackedVector2Array()
	var every := maxi(1, roundi(spacing / STEP))
	for i in range(every, full.size(), every):
		out.append(full[i])
	if out[out.size() - 1] != full[full.size() - 1]:
		out.append(full[full.size() - 1])
	return out


## Drop from height h0 down to `y_end` (relative: negative), going over the
## edge at `n_crest` g, steepest angle `beta`, pulling out at `n_pull` g.
static func drop(v0: float, y_end: float, beta: float = deg_to_rad(55.0), n_crest: float = 0.35, n_pull: float = 3.0) -> PackedVector2Array:
	# Find how long the straight steep section must be so the pull-out lands at
	# y_end. Ending height falls monotonically with straight length: bisect.
	var lo := 0.0
	var hi := 400.0
	var best: ProfileBuilder = null
	for i in 24:
		var mid := (lo + hi) * 0.5
		var b := ProfileBuilder.new(v0)
		b.phase(n_crest, -beta)
		b.phase(0.0, 0.0, mid, true)
		b.phase(n_pull, 0.0)
		best = b
		if b.position().y > y_end:
			lo = mid
		else:
			hi = mid
	return best.resample(4.0)
