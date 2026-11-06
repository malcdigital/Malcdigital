class_name TrackEditor
extends Node3D
## In-world editing of control points: handles you can tap/click, drag across
## the ground, or drag up and down (hold Shift, or turn on Height mode for touch).
##
## The editor only changes TrackData and emits signals; Main owns undo history,
## re-analysis and the rest of the UI.

signal selection_changed(index: int)
## Emitted while dragging (live = true) and when an edit is complete (live = false).
signal points_moved(live: bool)
## Emitted once, just before a drag first moves a point, so Main can snapshot for undo.
signal edit_started

const PICK_RADIUS_PX := 34.0
const DRAG_THRESHOLD_PX := 6.0
const MAX_HEIGHT := 150.0

var data: TrackData
var camera: OrbitCamera
var selected := -1
var height_mode := false     # toggled from the UI; Shift does the same on desktop
var snap := true
var snap_step := 0.5
var enabled := true

var _handles: Array[MeshInstance3D] = []
var _stems: Array[MeshInstance3D] = []
var _materials := {}
var _selected_mat: StandardMaterial3D
var _sphere: SphereMesh
var _stem_mesh: CylinderMesh
var _press_pos := Vector2.ZERO
var _pressing := false
var _dragging_point := false
var _drag_started := false
var _drag_offset := Vector3.ZERO
var _markers: Node3D


func _ready() -> void:
	_sphere = SphereMesh.new()
	_sphere.radius = 0.9
	_sphere.height = 1.8
	_sphere.radial_segments = 12
	_sphere.rings = 6
	_stem_mesh = CylinderMesh.new()
	_stem_mesh.top_radius = 0.06
	_stem_mesh.bottom_radius = 0.06
	_stem_mesh.height = 1.0
	_stem_mesh.radial_segments = 4
	_stem_mesh.rings = 1
	var colors := {
		TrackPoint.Segment.NORMAL: Color(0.95, 0.95, 1.0),
		TrackPoint.Segment.LIFT: Color(0.3, 0.55, 1.0),
		TrackPoint.Segment.LAUNCH: Color(1.0, 0.35, 0.9),
		TrackPoint.Segment.BRAKE: Color(1.0, 0.45, 0.2),
		TrackPoint.Segment.STATION: Color(0.4, 0.9, 0.5),
	}
	for seg in colors:
		_materials[seg] = _flat(colors[seg], 0.85)
	_selected_mat = _flat(Color(1.0, 0.85, 0.1), 1.0)
	_markers = Node3D.new()
	add_child(_markers)


static func _flat(c: Color, alpha: float) -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	m.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	m.albedo_color = Color(c, alpha)
	if alpha < 1.0:
		m.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	m.no_depth_test = false
	return m


func set_data(d: TrackData) -> void:
	data = d
	if selected >= data.points.size():
		selected = -1
	rebuild_handles()


func rebuild_handles() -> void:
	for h in _handles:
		h.queue_free()
	for s in _stems:
		s.queue_free()
	_handles.clear()
	_stems.clear()
	if data == null:
		return
	for i in data.points.size():
		var h := MeshInstance3D.new()
		h.mesh = _sphere
		h.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		add_child(h)
		_handles.append(h)
		var st := MeshInstance3D.new()
		st.mesh = _stem_mesh
		st.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		add_child(st)
		_stems.append(st)
	refresh_handles()


func refresh_handles() -> void:
	for i in _handles.size():
		var p := data.points[i]
		var h := _handles[i]
		h.position = p.position
		var sel := i == selected
		h.material_override = _selected_mat if sel else _materials[p.segment]
		# Handles grow with camera distance so they stay tappable.
		var d := camera.global_position.distance_to(p.position) if camera else 50.0
		# Roughly constant size on screen so handles stay tappable when far away.
		var s := clampf(d / 85.0, 0.5, 6.0) * (1.5 if sel else (0.35 if p.minor else 1.0))
		h.scale = Vector3.ONE * s
		var st := _stems[i]
		st.visible = sel or p.position.y > 2.0
		st.position = Vector3(p.position.x, p.position.y * 0.5, p.position.z)
		st.scale = Vector3(s, maxf(p.position.y, 0.01), s)
		st.material_override = h.material_override


var _last_cam := Transform3D()

func _process(_dt: float) -> void:
	# Handle sizes depend on camera distance: only redo them when it moved.
	if visible and data != null and camera != null and camera.global_transform != _last_cam:
		_last_cam = camera.global_transform
		refresh_handles()


func select(index: int) -> void:
	selected = index
	refresh_handles()
	selection_changed.emit(selected)


## Problem-spot markers (from RideScorer) shown as floating diamonds.
func show_problems(problems: Array[Dictionary], spline: TrackSpline) -> void:
	for c in _markers.get_children():
		c.queue_free()
	if spline == null or spline.count == 0:
		return
	var prism := PrismMesh.new()
	prism.size = Vector3(1.6, 2.2, 1.6)
	for p in problems:
		var mi := MeshInstance3D.new()
		mi.mesh = prism
		mi.material_override = _flat(GLimits.zone_color(p["severity"]), 0.9)
		mi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		var s: float = p["s"]
		mi.position = spline.position_at(s) + Vector3.UP * 4.0
		mi.rotation_degrees.x = 180.0  # point down at the track
		_markers.add_child(mi)


func set_markers_visible(v: bool) -> void:
	_markers.visible = v


# -----------------------------------------------------------------------------
# Input
# -----------------------------------------------------------------------------

func _unhandled_input(event: InputEvent) -> void:
	if not enabled or not visible or data == null or camera == null:
		return
	if camera.handle_input(event):
		get_viewport().set_input_as_handled()
		return
	if camera.multi_touch():
		# A second finger turns the gesture into pinch/pan: abandon any drag.
		if _dragging_point and _drag_started:
			points_moved.emit(false)
		_pressing = false
		_dragging_point = false
		return
	if event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT:
		if event.pressed:
			_pressing = true
			_press_pos = event.position
			_drag_started = false
			var hit := _pick(event.position)
			if hit >= 0:
				_dragging_point = true
				if hit != selected:
					select(hit)
				_drag_offset = Vector3.ZERO
				var on_plane: Variant = _ray_to_drag_target(event.position, data.points[hit].position, false)
				if on_plane != null:
					_drag_offset = data.points[hit].position - on_plane
			else:
				_dragging_point = false
				camera.begin_drag(MOUSE_BUTTON_LEFT)
		elif _pressing:
			if _dragging_point and _drag_started:
				points_moved.emit(false)
			elif not _drag_started and _pick(event.position) < 0 and selected >= 0:
				select(-1)   # tap on empty space deselects
			_pressing = false
			_dragging_point = false
			camera.end_drag()
		else:
			camera.end_drag()
		get_viewport().set_input_as_handled()
	elif event is InputEventMouseMotion and _pressing:
		if not _drag_started and event.position.distance_to(_press_pos) < DRAG_THRESHOLD_PX:
			return
		if not _drag_started:
			_drag_started = true
			if _dragging_point:
				edit_started.emit()
		if _dragging_point and selected >= 0:
			_drag_point(event.position)
		get_viewport().set_input_as_handled()


func _pick(screen: Vector2) -> int:
	var best := -1
	var best_d := PICK_RADIUS_PX * maxf(1.0, get_viewport().get_visible_rect().size.y / 720.0)
	for i in data.points.size():
		var p := data.points[i].position
		if camera.is_position_behind(p):
			continue
		var d := camera.unproject_position(p).distance_to(screen)
		if data.points[i].minor and i != selected:
			d *= 1.8   # prefer big (major) handles when they are close together
		if d < best_d:
			best_d = d
			best = i
	return best


func _vertical_drag() -> bool:
	return height_mode or Input.is_key_pressed(KEY_SHIFT)


## Where the mouse ray meets the drag surface: a horizontal plane through the
## point (move across the ground) or a vertical plane facing the camera
## (move up and down).
func _ray_to_drag_target(screen: Vector2, point: Vector3, vertical: bool) -> Variant:
	var origin := camera.project_ray_origin(screen)
	var dir := camera.project_ray_normal(screen)
	var plane: Plane
	if vertical:
		var n := -camera.global_transform.basis.z
		n.y = 0.0
		if n.length() < 0.01:
			return null
		plane = Plane(n.normalized(), point)
	else:
		plane = Plane(Vector3.UP, point)
	return plane.intersects_ray(origin, dir)


func _drag_point(screen: Vector2) -> void:
	var p := data.points[selected]
	var vertical := _vertical_drag()
	var hit = _ray_to_drag_target(screen, p.position, vertical)
	if hit == null:
		return
	var np: Vector3 = p.position
	if vertical:
		np.y = (hit as Vector3).y
	else:
		var h: Vector3 = hit + Vector3(_drag_offset.x, 0, _drag_offset.z)
		np.x = h.x
		np.z = h.z
	if snap:
		np = np.snapped(Vector3.ONE * snap_step)
	np.y = clampf(np.y, Elements.MIN_HEIGHT, MAX_HEIGHT)
	if np != p.position:
		p.position = np
		refresh_handles()
		points_moved.emit(true)


## Nudge the selected point (keyboard / on-screen buttons).
func nudge(delta: Vector3) -> void:
	if selected < 0:
		return
	edit_started.emit()
	var p := data.points[selected]
	p.position = (p.position + delta)
	p.position.y = clampf(p.position.y, Elements.MIN_HEIGHT, MAX_HEIGHT)
	refresh_handles()
	points_moved.emit(false)
