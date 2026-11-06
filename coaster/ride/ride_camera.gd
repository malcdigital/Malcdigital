class_name RideCamera
extends Camera3D
## First-person (front seat) and chase camera for test rides.
## In POV, dragging looks around; the view eases back to straight ahead.

enum Mode { POV, CHASE }

var mode: int = Mode.POV
var _look := Vector2.ZERO        # yaw, pitch offsets (radians) from dragging
var _dragging := false
var _chase_pos := Vector3.ZERO
var _chase_init := false


func _ready() -> void:
	# A larger near plane keeps depth precision usable on 16-bit depth
	# buffers (some phones / WebGL); nothing is closer than the car nose anyway.
	near = 0.15
	far = 2500.0


func toggle() -> void:
	mode = Mode.CHASE if mode == Mode.POV else Mode.POV
	_chase_init = false
	fov = 80.0 if mode == Mode.POV else 65.0


func start() -> void:
	_look = Vector2.ZERO
	_chase_init = false
	fov = 80.0 if mode == Mode.POV else 65.0


func handle_input(event: InputEvent) -> bool:
	if mode != Mode.POV:
		return false
	if event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT:
		_dragging = event.pressed
		return true
	if event is InputEventMouseMotion and _dragging:
		_look.x = clampf(_look.x - event.relative.x * 0.005, -2.4, 2.4)
		_look.y = clampf(_look.y - event.relative.y * 0.005, -1.1, 1.1)
		return true
	return false


func update(sim: TrainSim, dt: float) -> void:
	var sp := sim.spline
	if mode == Mode.POV:
		# Front row, between the two seats, at eye height above the heartline.
		var xf := sp.transform_at(sim.car_s(0))
		if not _dragging:
			_look = _look.lerp(Vector2.ZERO, 1.0 - exp(-1.5 * dt))
		var b := xf.basis * Basis(Vector3.UP, _look.x) * Basis(Vector3.RIGHT, _look.y)
		global_transform = Transform3D(b, xf * Vector3(0, 0.25, -0.6))
	else:
		var back := sp.transform_at(sim.car_s(sim.data.num_cars - 1))
		var mid := sp.position_at(sim.middle_s())
		# Behind and above the last car, in world-up terms so the camera
		# does not spin through loops.
		var behind := back.basis.z
		behind.y = 0.0
		behind = behind.normalized() if behind.length() > 0.1 else Vector3.BACK
		var want := back.origin + behind * 11.0 + Vector3.UP * 5.0
		want.y = maxf(want.y, 1.0)
		if not _chase_init:
			_chase_pos = want
			_chase_init = true
		_chase_pos = _chase_pos.lerp(want, 1.0 - exp(-3.0 * dt))
		global_position = _chase_pos
		if _chase_pos.distance_to(mid) > 0.5:
			look_at(mid, Vector3.UP)
