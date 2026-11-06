class_name TrainSim
extends RefCounted
## One-dimensional train simulation along a baked TrackSpline.
##
## The train is a rigid chain of cars: one shared distance `s` (of the front
## car) and one shared speed `v` along the track. That is exactly how a real
## coaster train behaves along its rails, and it reduces the physics to a
## single equation of motion along the track:
##
##     dv/dt = a_gravity + a_systems - a_friction - a_drag
##
## averaged over every car, so a long train really does get "pulled over" a
## hill by the cars already on the far side.
##
## Energy conservation falls out naturally: with friction and drag at zero,
## a_gravity = -g·T.y means  d(½v²)/dt = v·dv/dt = -g·T.y·v = -g·dy/dt,
## i.e. ½v² + g·y is constant. Friction and drag only ever remove energy;
## lifts and launches add it.
##
## step() is allocation-free: only floats, Vector3 (a value type) and reads
## from packed arrays.

const G := 9.81
## Physics rate for live rides. 120 Hz keeps energy drift tiny with
## semi-implicit Euler; editor previews use 60 Hz (see setup()).
const RIDE_DT := 1.0 / 120.0
const PREVIEW_DT := 1.0 / 60.0
## Chain dog / tyre acceleration when they catch the train (m/s²).
const DRIVE_ACCEL := 2.5
## Give up if the train has not made forward progress for this long.
const STALL_TIMEOUT := 12.0
const MAX_RIDE_TIME := 600.0

var spline: TrackSpline
var data: TrackData

var s := 0.0            # unwrapped arc length of the FRONT car
var v := 0.0            # m/s along the track (negative = rolling backwards)
var a_t := 0.0          # last tangential acceleration (m/s²), for G-forces
var time := 0.0
var start_s := 0.0
var best_s := 0.0       # furthest point reached (unwrapped)
var _since_progress := 0.0
var _was_moving_forward := true

var finished := false
var completed := false
var stalled := false
var stall_s := -1.0
var rollbacks := 0

var dt := RIDE_DT
var record: RideRecord
var _record_every := 2   # ticks per record entry (aim for 60 Hz records)
var _tick := 0
var _last_k := -1


func setup(p_spline: TrackSpline, p_data: TrackData, capture: bool = true, p_dt: float = RIDE_DT) -> void:
	spline = p_spline
	dt = p_dt
	_record_every = maxi(1, roundi((1.0 / 60.0) / dt))
	data = p_data
	# The train starts at rest with its back car at the start of the circuit
	# (point 0 should be the station), so the whole train sits in the station.
	start_s = data.train_length() + 1.0
	s = start_s
	best_s = s
	v = 0.0
	a_t = 0.0
	time = 0.0
	finished = false
	completed = false
	stalled = false
	stall_s = -1.0
	rollbacks = 0
	_since_progress = 0.0
	_was_moving_forward = true
	_tick = 0
	_last_k = -1
	if capture:
		record = RideRecord.new()
		record.interval = dt * _record_every
		record.allocate(int(MAX_RIDE_TIME / record.interval) + 2, spline.count)
	else:
		record = null


## Distance of car `i` (0 = front) along the track.
func car_s(i: int) -> float:
	return s - float(i) * data.car_spacing


func middle_s() -> float:
	return s - 0.5 * data.train_length()


## Advance the simulation by one fixed step of DT seconds.
func step() -> void:
	if finished:
		return
	var n := data.num_cars
	var inv_n := 1.0 / float(n)
	var gravity := 0.0
	var normal := 0.0
	var on_lift := 0.0
	var on_launch := 0.0
	var on_brake := 0.0
	var on_station := 0.0
	var gy := Vector3(0.0, G, 0.0)
	for i in n:
		var cs := s - float(i) * data.car_spacing
		var t := spline.tangent_at(cs)
		# Gravity's component along the track: g_vec · T = (0,-g,0)·T = -g·T.y
		gravity += -G * t.y
		# Normal force per unit mass. The rails must supply the specific force
		# f = v²·K + g·Y (centripetal acceleration minus gravity), except the
		# part along T, which the train's own acceleration takes care of.
		# Its magnitude is what presses the wheels on the rails, and rolling
		# friction is proportional to it (|N| includes both up-stop and side
		# friction wheels, so we use the full perpendicular magnitude).
		var f := spline.curvature_at(cs) * (v * v) + gy
		normal += (f - t * f.dot(t)).length()
		match spline.segment_at(cs):
			TrackPoint.Segment.LIFT: on_lift += inv_n
			TrackPoint.Segment.LAUNCH: on_launch += inv_n
			TrackPoint.Segment.BRAKE: on_brake += inv_n
			TrackPoint.Segment.STATION: on_station += inv_n
	gravity *= inv_n
	normal *= inv_n

	# Ride systems.
	var system := 0.0
	if on_launch > 0.0 and v < data.launch_speed:
		system += data.launch_accel * on_launch      # LSM fins only push cars over them
	if on_brake > 0.0 and v > data.brake_speed:
		system -= data.brake_decel * on_brake
	# NOTE: brake runs also have drive tyres (handled below with the station
	# tyres) so a train that has been braked can always crawl home.

	# Resistances always oppose motion: friction  mu·|N|,  drag  k·v².
	var resist := data.friction * normal + data.drag * v * v
	var drive := gravity + system
	var v_new: float
	if absf(v) < 1e-3 and absf(drive) <= resist:
		v_new = 0.0          # static friction holds the train
	else:
		var dir := signf(v) if absf(v) >= 1e-3 else signf(drive)
		v_new = v + (drive - dir * resist) * dt
		# Friction can stop the train but never reverse it within a step.
		if dir != 0.0 and signf(v_new) != dir and absf(drive) <= resist:
			v_new = 0.0

	# Chain lift: the chain dog catches the train if it is slower than the
	# chain and drags it up at chain speed; anti-rollback stops it going back.
	if on_lift > 0.0:
		if v_new < data.lift_speed:
			v_new = maxf(v_new, minf(data.lift_speed, maxf(v, 0.0) + DRIVE_ACCEL * dt))
	# Station drive tyres push (or slow) the train towards station speed.
	if on_station > 0.0:
		var target := data.station_speed
		if v_new < target:
			v_new = minf(target, maxf(v_new, maxf(v, 0.0) + DRIVE_ACCEL * dt))
		elif v_new > target:
			v_new = maxf(target, v_new - 4.0 * dt)
	elif on_brake > 0.0 and v_new < data.brake_speed and v_new > -0.5:
		# Brake-run tyres only push forwards, up to brake speed.
		v_new = minf(data.brake_speed, maxf(v_new, maxf(v, 0.0) + DRIVE_ACCEL * dt))

	a_t = (v_new - v) / dt
	# Semi-implicit (symplectic) Euler: position uses the updated velocity.
	v = v_new
	s += v * dt
	time += dt

	# Rollback / stall bookkeeping.
	if v < -0.05 and _was_moving_forward:
		_was_moving_forward = false
		rollbacks += 1
		if stall_s < 0.0:
			stall_s = fposmod(s, spline.length)
	elif v > 0.05:
		_was_moving_forward = true
	if s > best_s + 0.05:
		best_s = s
		_since_progress = 0.0
	else:
		_since_progress += dt

	if s - start_s >= spline.length:
		finished = true
		completed = true
	elif _since_progress > STALL_TIMEOUT or time > MAX_RIDE_TIME:
		finished = true
		stalled = true
		if stall_s < 0.0:
			stall_s = fposmod(best_s, spline.length)

	if record != null:
		_capture()


func _capture() -> void:
	var ms := middle_s()
	var g := spline.g_forces_at(ms, v, a_t)
	var k := spline.index_at(ms)
	# At speed the middle car can skip a sample or two per tick; fill those so
	# the editor overlay has no holes.
	var first := k
	if _last_k >= 0:
		var gap := (k - _last_k + spline.count) % spline.count
		if gap > 1 and gap < 12:
			first = (_last_k + 1) % spline.count
	_last_k = k
	var j := first
	while true:
		record.sample_speed[j] = v
		record.sample_g_vert[j] = g.x
		record.sample_g_lat[j] = g.y
		record.sample_visited[j] = 1
		if j == k:
			break
		j = (j + 1) % spline.count
	_tick += 1
	if _tick % _record_every != 0 or record.size >= record.capacity():
		return
	var r := record.size
	record.s[r] = ms
	record.speed[r] = v
	record.g_vert[r] = g.x
	record.g_lat[r] = g.y
	record.g_long[r] = g.z
	record.height[r] = spline.position_at(ms).y
	record.roll[r] = spline.rolls[k]
	record.size = r + 1


## Run the whole ride as fast as possible (used by the editor and tests).
func run_to_end() -> RideRecord:
	while not finished:
		step()
	finalize()
	return record


## Copy the end-of-ride flags into the record. Call once the ride is over.
func finalize() -> void:
	if record == null:
		return
	record.completed = completed
	record.stalled = stalled
	record.stall_s = stall_s
	record.rollbacks = rollbacks
	record.duration = time


## Total mechanical energy per unit mass of the front car: ½v² + g·y (J/kg).
func energy() -> float:
	return 0.5 * v * v + G * spline.position_at(s).y
