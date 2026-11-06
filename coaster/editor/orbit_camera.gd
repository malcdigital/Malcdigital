class_name OrbitCamera
extends Camera3D
## Editor camera that orbits a target point.
##
## Mouse:  left-drag orbit, right/middle-drag pan, wheel zoom, WASD/arrows pan.
## Touch:  one finger orbit, two fingers pinch to zoom and drag to pan.
## The editor decides first whether a press grabbed a control point; only
## presses on empty space reach this camera (see TrackEditor).

var target := Vector3(20, 5, -120)
var yaw := deg_to_rad(-35.0)
var pitch := deg_to_rad(-28.0)
var distance := 170.0

var _orbiting := false
var _panning := false
var _touches := {}           # index -> position
var _pinch_dist := 0.0
var _pinch_mid := Vector2.ZERO
var _focus_tween: Tween


func _ready() -> void:
	fov = 60.0
	far = 3000.0
	near = 0.1
	_apply()


func multi_touch() -> bool:
	return _touches.size() >= 2


## Begin orbiting/panning from a press on empty space.
func begin_drag(button: int) -> void:
	_orbiting = button == MOUSE_BUTTON_LEFT
	_panning = button == MOUSE_BUTTON_RIGHT or button == MOUSE_BUTTON_MIDDLE


func end_drag() -> void:
	_orbiting = false
	_panning = false


func handle_input(event: InputEvent) -> bool:
	if event is InputEventScreenTouch:
		if event.pressed:
			_touches[event.index] = event.position
		else:
			_touches.erase(event.index)
		if _touches.size() >= 2:
			_orbiting = false
			_pinch_dist = _pinch_distance()
			_pinch_mid = _pinch_midpoint()
		return false
	if event is InputEventScreenDrag:
		_touches[event.index] = event.position
		if _touches.size() >= 2:
			var d := _pinch_distance()
			var mid := _pinch_midpoint()
			if _pinch_dist > 1.0:
				zoom(_pinch_dist / maxf(d, 1.0))
			pan(mid - _pinch_mid)
			_pinch_dist = d
			_pinch_mid = mid
			return true
		return false
	if event is InputEventMouseButton:
		if event.button_index == MOUSE_BUTTON_WHEEL_UP and event.pressed:
			zoom(0.88)
			return true
		if event.button_index == MOUSE_BUTTON_WHEEL_DOWN and event.pressed:
			zoom(1.0 / 0.88)
			return true
		if not event.pressed:
			end_drag()
		elif event.button_index == MOUSE_BUTTON_RIGHT or event.button_index == MOUSE_BUTTON_MIDDLE:
			begin_drag(event.button_index)
			return true
	if event is InputEventMouseMotion and not multi_touch():
		if _orbiting:
			orbit(event.relative)
			return true
		if _panning:
			pan(event.relative)
			return true
	if event is InputEventMagnifyGesture:
		zoom(1.0 / event.factor)
		return true
	if event is InputEventPanGesture:
		pan(-event.delta * 8.0)
		return true
	return false


func _process(dt: float) -> void:
	if not current:
		return
	var move := Vector2.ZERO
	if Input.is_key_pressed(KEY_W) or Input.is_key_pressed(KEY_UP): move.y += 1.0
	if Input.is_key_pressed(KEY_S) or Input.is_key_pressed(KEY_DOWN): move.y -= 1.0
	if Input.is_key_pressed(KEY_A) or Input.is_key_pressed(KEY_LEFT): move.x -= 1.0
	if Input.is_key_pressed(KEY_D) or Input.is_key_pressed(KEY_RIGHT): move.x += 1.0
	if move != Vector2.ZERO and not Input.is_key_pressed(KEY_CTRL):
		var fwd := Vector3(sin(yaw), 0, cos(yaw)) * -1.0
		var right := Vector3(cos(yaw), 0, -sin(yaw))
		target += (right * move.x + fwd * move.y) * distance * 0.8 * dt
		_apply()


func orbit(rel: Vector2) -> void:
	yaw -= rel.x * 0.006
	pitch = clampf(pitch - rel.y * 0.006, deg_to_rad(-88.0), deg_to_rad(-3.0))
	_apply()


func pan(rel: Vector2) -> void:
	var scale := distance * 0.0016
	var right := global_transform.basis.x
	var fwd := Vector3(-global_transform.basis.z.x, 0, -global_transform.basis.z.z).normalized()
	target += (-right * rel.x + fwd * rel.y) * scale
	_apply()


func zoom(factor: float) -> void:
	distance = clampf(distance * factor, 6.0, 900.0)
	_apply()


## Smoothly move the orbit target to a point (e.g. a problem spot).
func focus(point: Vector3, new_distance: float = -1.0) -> void:
	if _focus_tween:
		_focus_tween.kill()
	var from_t := target
	var from_d := distance
	var to_d := new_distance if new_distance > 0.0 else distance
	_focus_tween = create_tween().set_trans(Tween.TRANS_CUBIC).set_ease(Tween.EASE_OUT)
	_focus_tween.tween_method(func(w: float) -> void:
		target = from_t.lerp(point, w)
		distance = lerpf(from_d, to_d, w)
		_apply(), 0.0, 1.0, 0.5)


func _apply() -> void:
	var dir := Vector3(cos(pitch) * sin(yaw), sin(pitch), cos(pitch) * cos(yaw))
	global_position = target - dir * distance
	if global_position.y < 0.5:
		global_position.y = 0.5
	look_at(target, Vector3.UP)


func _pinch_distance() -> float:
	var pts: Array = _touches.values()
	return (pts[0] as Vector2).distance_to(pts[1]) if pts.size() >= 2 else 0.0


func _pinch_midpoint() -> Vector2:
	var pts: Array = _touches.values()
	return ((pts[0] as Vector2) + (pts[1] as Vector2)) * 0.5 if pts.size() >= 2 else Vector2.ZERO
