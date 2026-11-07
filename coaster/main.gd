extends Node3D
## Top-level controller: owns the coaster being edited, runs analysis on a
## worker thread after every edit, and switches between Edit, Ride and Results.
##
##   Edit    - orbit camera, control-point handles, live colour overlay + stats
##   Ride    - real-time TrainSim, POV/chase camera, rider reactions, audio
##   Results - ratings breakdown and problem spots (tap to jump to them),
##             plus the contract verdict and stars when playing a contract

enum Mode { EDIT, RIDE, RESULTS }

const RIDE_SPEEDS := [1.0, 2.0, 4.0]

var mode: int = Mode.EDIT
var data: TrackData
var history := EditHistory.new()
var analysis: TrackAnalyzer          # latest finished analysis
var analysis_data: TrackData         # the exact track that analysis describes
var overlay_mode: int = TrackOverlay.Mode.ZONES

var track_view: TrackView
var terrain_view: TerrainView
var progress: ProgressStore
## Contract evaluation of the latest analysis ({} in sandbox).
var contract_result := {}
var brush: int = TerrainData.Brush.RAISE
var prop_kind := Props.Kind.TREE   # -1 = remove
var _last_terrain_draw := 0
var _train_type := -1
var _splashes_seen := 0
var _terrain_key := -1
## How far + Point places a new point from the end of an unfinished track (m).
var point_spacing := 15.0
var editor: TrackEditor
var orbit_cam: OrbitCamera
var ride_cam: RideCamera
var train_view: TrainView
var audio: RideAudio
var hud: Hud

var _dirty := false
var _job_id := -1
var _sim: TrainSim
var _acc := 0.0
var _ride_speed_i := 0
var _bank_edit_open := false
var _framed_once := false


func _ready() -> void:
	WorldBuilder.build(self)
	progress = ProgressStore.load_or_new()
	terrain_view = TerrainView.new()
	add_child(terrain_view)
	track_view = TrackView.new()
	add_child(track_view)
	orbit_cam = OrbitCamera.new()
	add_child(orbit_cam)
	orbit_cam.current = true
	ride_cam = RideCamera.new()
	add_child(ride_cam)
	train_view = TrainView.new()
	add_child(train_view)
	audio = RideAudio.new()
	add_child(audio)
	editor = TrackEditor.new()
	editor.camera = orbit_cam
	add_child(editor)
	editor.selection_changed.connect(func(_i: int) -> void: _refresh_point())
	editor.edit_started.connect(_begin_edit)
	editor.points_moved.connect(func(live: bool) -> void:
		if live and not _threaded:
			# No threads (web): don't re-analyse on every drag step, which would
			# keep the game busy. Show a quick outline; analyse on release.
			editor.show_preview()
			return
		if not live:
			_maybe_close()
		request_analysis()
		if not live: _refresh_point())
	editor.ground_stroke.connect(_on_ground_stroke)
	editor.ground_tap.connect(_on_ground_tap)
	editor.point_double_tapped.connect(_on_point_double_tapped)
	editor.ground_double_tapped.connect(_on_ground_double_tapped)
	hud = Hud.new()
	add_child(hud)
	hud.setup(self)
	_set_track(DefaultTracks.empty())
	editor.select(1)   # end of the platform: elements get added from here
	hud.toast("Just a station. Select its end and use Add element or + Point to build, then bring the track back here.", 5.0)
	hud.refresh_type(data, progress)


## Never leave a worker running while the scene (and its scripts) go away.
func _exit_tree() -> void:
	if _job_id >= 0:
		WorkerThreadPool.wait_for_task_completion(_job_id)
		_job_id = -1


# -----------------------------------------------------------------------------
# Analysis (background)
#
# With threads (desktop, mobile) the whole AnalysisJob runs on a worker. The
# web build has none, so the job runs a few milliseconds per frame instead:
# the game keeps drawing smoothly and the results arrive a few frames later.
# -----------------------------------------------------------------------------

## Per-frame analysis budget when there are no threads (microseconds).
const SLICE_BUDGET_USEC := 8000

var _threaded := not OS.has_feature("web") and OS.get_environment("COASTER_NO_THREADS") == ""
var _job: AnalysisJob


func request_analysis() -> void:
	_dirty = true


func _process(dt: float) -> void:
	if _job != null:
		if _threaded:
			if WorkerThreadPool.is_task_completed(_job_id):
				WorkerThreadPool.wait_for_task_completion(_job_id)
				_job_id = -1
				_apply_job()
		elif _job.run(SLICE_BUDGET_USEC):
			_apply_job()
	if _dirty and _job == null:
		_start_job()
	hud.set_busy(_job != null or _dirty)
	if mode == Mode.RIDE:
		_ride_process(dt)
	elif editor.is_stroking():
		_sculpt(dt)


func _start_job() -> void:
	_dirty = false
	_job = AnalysisJob.new(data.copy(), overlay_mode, true)
	_job.skip_terrain_key = _terrain_key
	if _threaded:
		_job_id = WorkerThreadPool.add_task(_job.run.bind(1 << 62), false, "Analyse coaster")


func _job_busy() -> bool:
	return _job != null or _dirty


func _apply_job() -> void:
	var job := _job
	_job = null
	var a := job.result
	analysis = a
	analysis_data = job.data
	editor.hide_preview()
	if not job.terrain_unchanged:
		if job.terrain_arrays.is_empty():
			terrain_view.show_raw(job.data.terrain, Contracts.zones(job.data.contract_id))
			_terrain_key = -1
		else:
			terrain_view.show_terrain(job.data.terrain, job.terrain_arrays)
			_terrain_key = job.terrain_key
	terrain_view.show_props(job.data.terrain, job.data.props)
	contract_result = {}
	if a.valid and job.data.contract_id != "":
		contract_result = ContractEvaluator.evaluate(Contracts.find(job.data.contract_id), job.data, a)
	if a.open:
		track_view.show_track(a.spline, job.chunks, a.site, job.data.type_info())
		editor.show_problems([] as Array[Dictionary], null)
		if mode != Mode.RIDE:
			_park_train()
		if not _framed_once:
			_framed_once = true
			frame_track()
	elif a.valid:
		track_view.show_track(a.spline, job.chunks, a.site, job.data.type_info())
		editor.show_problems(a.ratings.problems, a.spline)
		if mode != Mode.RIDE:
			_park_train()
		if not _framed_once:
			_framed_once = true
			frame_track()
	else:
		track_view.show_track(null, [])
		editor.show_problems([] as Array[Dictionary], null)
	hud.update_analysis(a)
	_refresh_point()


func _park_train() -> void:
	if train_view.cars.size() != analysis_data.num_cars or _train_type != analysis_data.coaster_type:
		train_view.build(analysis_data.num_cars, analysis_data.type_info())
		_train_type = analysis_data.coaster_type
	train_view.place_at(analysis.spline, analysis_data.train_length() + 1.0, analysis_data.car_spacing)


# -----------------------------------------------------------------------------
# Editing
# -----------------------------------------------------------------------------

func _set_track(d: TrackData) -> void:
	data = d
	history.clear()
	editor.set_data(data)
	editor.select(-1)
	_framed_once = false
	request_analysis()
	_refresh_history()


func _begin_edit() -> void:
	history.push(data)
	_refresh_history()


func _after_edit(rebuild_handles: bool = false) -> void:
	_maybe_close()
	if rebuild_handles:
		editor.set_data(data)
	else:
		editor.refresh_handles()
	request_analysis()
	_refresh_point()
	_refresh_history()


func _refresh_history() -> void:
	hud.refresh_history(history.can_undo(), history.can_redo())


func _refresh_point() -> void:
	var sp: TrackSpline = analysis.spline if analysis != null and analysis.valid else null
	var rec: RideRecord = analysis.record if analysis != null and analysis.valid else null
	# Only trust per-point stats if the analysis matches the current point count.
	if analysis_data == null or analysis_data.points.size() != data.points.size():
		sp = null
	hud.refresh_point(data, editor.selected, sp, rec)


func undo() -> void:
	var r := history.undo(data)
	if r != null:
		data = r
		_after_edit(true)


func redo() -> void:
	var r := history.redo(data)
	if r != null:
		data = r
		_after_edit(true)


func _selected_or_last() -> int:
	return editor.selected if editor.selected >= 0 else data.points.size() - 1


## An unfinished track closes itself once its end comes back to the station.
func _maybe_close() -> void:
	if data.ready_to_close():
		data.open = false
		hud.toast("Circuit complete! The track now joins the station. Press Test ride.", 4.0)


func add_point() -> void:
	var i := _selected_or_last()
	_begin_edit()
	if data.open and i == data.points.size() - 1:
		# Extend the unfinished track straight on from its end.
		var a := data.points[i - 1].position
		var b := data.points[i].position
		var dir := (b - a).normalized() if a.distance_to(b) > 0.01 else Vector3.FORWARD
		var p := TrackPoint.new(b + dir * point_spacing, TrackPoint.Segment.NORMAL)
		if data.points[i].segment != TrackPoint.Segment.STATION:
			p.segment = data.points[i].segment
		data.points.append(p)
	else:
		TrackTools.add_point_after(data, i, _current_spline())
	_after_edit(true)
	editor.select(i + 1)


func delete_point() -> void:
	if editor.selected < 0:
		hud.toast("Select a point first")
		return
	if editor.selected <= 1 and data.open:
		hud.toast("The station platform stays. Build out from its end.")
		return
	if data.points.size() <= (2 if data.open else 4):
		hud.toast("A track needs at least 4 points")
		return
	# Delete every selected point (highest index first so indices stay valid).
	var doomed: Array[int] = editor.selection.duplicate()
	doomed.sort()
	doomed.reverse()
	if data.open:
		doomed = doomed.filter(func(i: int) -> bool: return i > 1)
	var keep := (2 if data.open else 4)
	if data.points.size() - doomed.size() < keep:
		hud.toast("A track needs at least %d points" % keep)
		return
	_begin_edit()
	var first: int = doomed.back() if not doomed.is_empty() else editor.selected
	for i in doomed:
		TrackTools.remove_point(data, i)
	_after_edit(true)
	editor.select(mini(first, data.points.size() - 1))


func insert_element(kind: int) -> void:
	var i := _selected_or_last()
	var sp := _current_spline()
	var speed := 15.0
	var heading := Vector3.FORWARD
	if sp != null:
		heading = TrackTools.heading_at(sp, i)
		if analysis.record != null:
			speed = absf(analysis.record.sample_speed[sp.index_at(sp.point_s[i])])
		elif data.open:
			speed = 3.0   # leaving the station slowly
	elif i > 0:
		var d := data.points[i].position - data.points[i - 1].position
		heading = d.normalized() if d.length() > 0.01 else Vector3.FORWARD
	var ctx := {"water_level": data.terrain.water_level, "seat_offset": data.type_info()["seat_offset"]}
	if kind == Elements.Kind.LAUNCH and not data.type_info()["launch"]:
		hud.toast("Only launched coasters have launch motors")
		return
	var pts := Elements.build(kind, data.points[i].position, heading, speed, ctx)
	if pts.is_empty():
		return
	_begin_edit()
	TrackTools.insert_points(data, i, pts)
	_after_edit(true)
	editor.select(i + pts.size())
	hud.toast("Added %s (%d points). Check the track still joins up." % [Elements.NAMES[kind], pts.size()])


func smooth() -> void:
	_begin_edit()
	TrackTools.smooth(data, 0.5, editor.selected)
	_after_edit()
	hud.toast("Smoothed %s" % ("around the selected point" if editor.selected >= 0 else "the whole track"))


func set_segment(seg: int) -> void:
	if editor.selected < 0:
		return
	if not CoasterTypes.allows_segment(data.coaster_type, seg):
		hud.toast("%s coasters can't use %s" % [CoasterTypes.type_name(data.coaster_type), TrackPoint.SEGMENT_NAMES[seg].to_lower()])
		hud.refresh_point(data, editor.selected, _current_spline(), analysis.record if analysis else null)
		return
	_begin_edit()
	for i in editor.selection:
		data.points[i].segment = seg
	_after_edit()


func set_auto_bank(on: bool) -> void:
	if editor.selected < 0:
		return
	_begin_edit()
	var sp := _current_spline()
	for i in editor.selection:
		var p := data.points[i]
		p.auto_bank = on
		if not on and sp != null:
			# Start manual banking from what auto-bank was doing.
			p.bank_deg = snappedf(rad_to_deg(sp.rolls[sp.index_at(sp.point_s[i])]), 5.0)
	_after_edit()


## Bank slider moves: one undo step per drag (opened on first change).
func set_bank(deg: float) -> void:
	if editor.selected < 0:
		return
	if not _bank_edit_open:
		_begin_edit()
		_bank_edit_open = true
	for i in editor.selection:
		data.points[i].bank_deg = deg
	request_analysis()


## Curve handle mode for the selected points (Auto / Smooth / Corner).
func set_handle_mode(mode: int) -> void:
	if editor.selected < 0:
		return
	_begin_edit()
	for i in editor.selection:
		var p := data.points[i]
		if mode != TrackPoint.Handle.AUTO and p.handle_mode == TrackPoint.Handle.AUTO:
			var cur := TrackSpline.current_handles(data.points, i, not data.open)
			p.handle_in = cur[0]
			p.handle_out = cur[1]
		p.handle_mode = mode
	_after_edit()


## Double-click / double-tap on a point: reset its curve to Auto.
func _on_point_double_tapped(i: int) -> void:
	if i < 0 or i >= data.points.size():
		return
	editor.select(i)
	if data.points[i].handle_mode == TrackPoint.Handle.AUTO:
		hud.toast("Curve is already automatic")
		return
	_begin_edit()
	data.points[i].handle_mode = TrackPoint.Handle.AUTO
	_after_edit()
	hud.toast("Curve reset to automatic")


## Double-click / double-tap on empty ground: add a point there, after the
## selected point (or at the end of an unfinished track), at its height.
func _on_ground_double_tapped(g: Vector3) -> void:
	var i := _selected_or_last()
	var y := data.points[i].position.y
	_begin_edit()
	var p := TrackPoint.new(Vector3(g.x, y, g.z))
	if data.points[i].segment != TrackPoint.Segment.STATION:
		p.segment = data.points[i].segment
	if editor.snap:
		p.position = p.position.snapped(Vector3.ONE * editor.snap_step)
	data.points.insert(i + 1, p)
	_after_edit(true)
	editor.select(mini(i + 1, data.points.size() - 1))


func cycle_handle_mode() -> void:
	if editor.selected < 0:
		return
	set_handle_mode((data.points[editor.selected].handle_mode + 1) % TrackPoint.HANDLE_NAMES.size())
	hud.toast("Curve: " + TrackPoint.HANDLE_NAMES[data.points[editor.selected].handle_mode])


func reset_curves() -> void:
	if editor.selected < 0:
		return
	set_handle_mode(TrackPoint.Handle.AUTO)
	hud.toast("Curve reset to automatic")


func toggle_auto_bank() -> void:
	if editor.selected >= 0:
		set_auto_bank(not data.points[editor.selected].auto_bank)
		hud.toast("Auto-bank " + ("on" if data.points[editor.selected].auto_bank else "off"))


func bank_step(deg: float) -> void:
	if editor.selected < 0:
		return
	if data.points[editor.selected].auto_bank:
		set_auto_bank(false)
	set_bank(clampf(data.points[editor.selected].bank_deg + deg, -360.0, 360.0))
	commit_bank()
	hud.toast("Bank %d°" % int(data.points[editor.selected].bank_deg))


func select_step(d: int) -> void:
	var n := data.points.size()
	if n == 0:
		return
	var i := (editor.selected + d + n) % n if editor.selected >= 0 else 0
	editor.select(i)


func set_point_spacing(m: float) -> void:
	point_spacing = m


func set_multi_select(on: bool) -> void:
	editor.multi_mode = on
	hud.toast("Multi-select on: tap points to add or remove them, drag any of them to move them all" if on else "Multi-select off", 3.5)


func select_all_points() -> void:
	editor.select_all()


func set_launch_speed(v: float) -> void:
	if not _bank_edit_open:
		_begin_edit()
		_bank_edit_open = true
	data.launch_speed = v
	request_analysis()


func commit_bank() -> void:
	_bank_edit_open = false
	_refresh_point()


func nudge(delta: Vector3) -> void:
	editor.nudge(delta)


func set_height_mode(on: bool) -> void:
	editor.height_mode = on
	hud.toast("Height mode on: dragging a point moves it up and down" if on else "Height mode off: dragging a point moves it across the ground")


func set_snap(on: bool) -> void:
	editor.snap = on


func set_overlay(mode_i: int) -> void:
	overlay_mode = mode_i
	request_analysis()


func _current_spline() -> TrackSpline:
	if analysis == null or analysis.spline == null or analysis.spline.count == 0 or analysis_data == null:
		return null
	if not analysis.valid and not analysis.open:
		return null
	if analysis_data.points.size() != data.points.size():
		return null
	return analysis.spline


# -----------------------------------------------------------------------------
# Coaster type, terrain and scenery
# -----------------------------------------------------------------------------

func set_coaster_type(id: int) -> void:
	if id == data.coaster_type:
		return
	if data.contract_id != "":
		hud.toast("This contract needs a %s coaster" % CoasterTypes.type_name(data.coaster_type))
		hud.refresh_type(data, progress)
		return
	if not progress.unlocked_types().has(id):
		hud.toast("Finish more contracts to unlock the %s coaster" % CoasterTypes.type_name(id))
		hud.refresh_type(data, progress)
		return
	_begin_edit()
	data.set_type(id)
	_after_edit(true)
	hud.refresh_type(data, progress)
	hud.toast("%s: %s" % [CoasterTypes.type_name(id), data.type_info()["blurb"]], 4.0)


func set_tool(t: int) -> void:
	editor.set_tool(t)
	hud.show_tool(t)
	if t == TrackEditor.Tool.TERRAIN:
		hud.toast("Drag on the ground to sculpt. Two fingers (or Alt + drag) move the camera.", 4.0)
	elif t == TrackEditor.Tool.SCENERY:
		hud.toast("Tap the ground to place scenery. Passing close to it at speed is a near miss.", 4.0)


func set_brush(b: int) -> void:
	brush = b


func set_brush_size(r: float) -> void:
	editor.brush_radius = r


func set_prop_kind(k: int) -> void:
	prop_kind = k


func set_terrain_preset(p: int) -> void:
	if data.contract_id != "":
		hud.toast("A contract's site can be sculpted but not replaced")
		return
	_begin_edit()
	data.terrain = TerrainData.make(p)
	_after_edit()
	hud.toast("Terrain: %s" % TerrainData.PRESET_NAMES[p])


var _flatten_to := 0.0

func _on_ground_stroke(phase: int, point: Vector3) -> void:
	if phase == TrackEditor.Stroke.BEGIN:
		_flatten_to = data.terrain.height_at(point.x, point.z)
	elif phase == TrackEditor.Stroke.END:
		terrain_view.show_raw(data.terrain, Contracts.zones(data.contract_id))
		_terrain_key = -1
		_after_edit()


## While the brush is held down: sculpt at a steady rate under it.
func _sculpt(dt: float) -> void:
	var p := editor.brush_point()
	var rate := 6.0 * dt   # metres per second at the brush centre
	match brush:
		TerrainData.Brush.RAISE, TerrainData.Brush.LOWER:
			data.terrain.sculpt(p, editor.brush_radius, rate, brush)
		_:
			data.terrain.sculpt(p, editor.brush_radius, minf(3.0 * dt, 1.0), brush, _flatten_to)
	# Redraw a few times a second (a full terrain rebuild is not free).
	var now := Time.get_ticks_msec()
	if now - _last_terrain_draw > 180:
		_last_terrain_draw = now
		terrain_view.show_raw(data.terrain, Contracts.zones(data.contract_id))
		_terrain_key = -1


func _on_ground_tap(point: Vector3) -> void:
	# Tapping an existing prop removes it; otherwise place the chosen kind.
	var nearest := -1
	var best := 6.0
	for i in data.props.size():
		var d := Vector2(data.props[i]["x"], data.props[i]["z"]).distance_to(Vector2(point.x, point.z))
		if d < best:
			best = d
			nearest = i
	if prop_kind < 0 or nearest >= 0:
		if nearest < 0:
			return
		_begin_edit()
		data.props.remove_at(nearest)
	else:
		_begin_edit()
		var s := 0.8 + fposmod(point.x * 0.37 + point.z * 0.11, 0.5)
		data.props.append(Props.make(prop_kind, snappedf(point.x, 0.1), snappedf(point.z, 0.1), s))
	terrain_view.show_props(data.terrain, data.props)
	_after_edit()


# -----------------------------------------------------------------------------
# Contracts
# -----------------------------------------------------------------------------

func start_contract(id: String) -> void:
	var c := Contracts.find(id)
	if c.is_empty():
		return
	var i := Contracts.index_of(id)
	if not progress.is_available(i):
		hud.toast("Finish the previous contract first")
		return
	var d := DefaultTracks.empty(c["type"])
	d.name = c["title"]
	d.terrain = TerrainData.make(c["terrain"])
	d.contract_id = id
	_set_track(d)
	editor.select(1)
	set_tool(TrackEditor.Tool.TRACK)
	hud.refresh_type(data, progress)
	hud.show_brief(c)


func leave_contract() -> void:
	if data.contract_id == "":
		return
	data.contract_id = ""
	data.name += " (sandbox)"
	request_analysis()
	hud.refresh_type(data, progress)


func next_contract_id() -> String:
	var i := Contracts.index_of(data.contract_id)
	if i >= 0 and i + 1 < Contracts.LIST.size() and progress.is_available(i + 1):
		return Contracts.LIST[i + 1]["id"]
	return ""


# -----------------------------------------------------------------------------
# Camera helpers
# -----------------------------------------------------------------------------

func frame_track() -> void:
	if data.points.is_empty():
		return
	var aabb := AABB(data.points[0].position, Vector3.ZERO)
	for p in data.points:
		aabb = aabb.expand(p.position)
	orbit_cam.focus(aabb.get_center(), clampf(aabb.size.length() * 0.62, 70.0, 800.0))


func focus_selected() -> void:
	if editor.selected >= 0:
		orbit_cam.focus(data.points[editor.selected].position, 40.0)


## Jump the editor camera to distance `s` along the track.
func focus_s(s: float, from_results: bool) -> void:
	if from_results:
		back_to_editor()
	if analysis == null or not analysis.valid:
		return
	orbit_cam.focus(analysis.spline.position_at(s), 45.0 if from_results else orbit_cam.distance)
	hud.graph.set_marker(s)


# -----------------------------------------------------------------------------
# Files
# -----------------------------------------------------------------------------

func new_empty_track() -> void:
	var d := DefaultTracks.empty(data.coaster_type if data.contract_id == "" else CoasterTypes.Id.STEEL)
	if data.contract_id == "":
		d.terrain = data.terrain.copy()
	_set_track(d)
	editor.select(1)
	hud.refresh_type(data, progress)
	hud.toast("Just a station. Use Add element or + Point from its end, then bring the track back to the start of the station.", 5.0)


func new_track(blank: bool) -> void:
	if blank:
		var d := DefaultTracks.blank(data.coaster_type if data.contract_id == "" else CoasterTypes.Id.STEEL)
		d.terrain = data.terrain.copy() if data.contract_id == "" else TerrainData.new()
		_set_track(d)
	else:
		_set_track(DefaultTracks.starter())
	hud.refresh_type(data, progress)


func save_track(name_text: String) -> void:
	if name_text.strip_edges() != "":
		data.name = name_text.strip_edges()
	var err := CoasterStorage.save(data)
	hud.toast("Saved \"%s\"" % data.name if err == OK else "Could not save (error %d)" % err)
	hud.update_analysis(analysis)


func load_saved(file: String) -> void:
	var d := CoasterStorage.load_coaster(file)
	if d == null:
		hud.toast("Could not load that coaster")
		return
	_set_track(d)
	hud.refresh_type(data, progress)
	hud.toast("Loaded \"%s\"" % d.name)


func delete_saved(file: String) -> void:
	CoasterStorage.delete(file)


# -----------------------------------------------------------------------------
# Ride
# -----------------------------------------------------------------------------

func start_ride() -> void:
	if data.open or (analysis != null and analysis.open):
		hud.toast("Finish the circuit first: bring the end of the track back to the green handle at the start of the station.", 4.5)
		return
	if analysis == null or not analysis.valid:
		hud.toast("The track needs at least 4 points")
		return
	if _job_busy():
		hud.toast("Riding the last analysed version of the track")
	mode = Mode.RIDE
	editor.visible = false
	editor.enabled = false
	_sim = TrainSim.new()
	_sim.setup(analysis.spline, analysis_data, true, TrainSim.RIDE_DT)
	_splashes_seen = 0
	train_view.build(analysis_data.num_cars, analysis_data.type_info())
	_train_type = analysis_data.coaster_type
	train_view.reset_riders()
	ride_cam.start()
	ride_cam.current = true
	audio.start(_sim)
	_acc = 0.0
	_ride_speed_i = 0
	hud.set_ride_speed_label(1.0)
	hud.set_ride_camera_label(ride_cam.mode == RideCamera.Mode.POV)
	hud.show_ride()


func _ride_process(dt: float) -> void:
	var mult: float = RIDE_SPEEDS[_ride_speed_i]
	_acc += minf(dt, 0.1) * mult
	var steps := 0
	while _acc >= _sim.dt and steps < 60 and not _sim.finished:
		_sim.step()
		_acc -= _sim.dt
		steps += 1
	train_view.update_from_sim(_sim, dt, true)
	if _sim.splashes > _splashes_seen:
		_splashes_seen = _sim.splashes
		var xf := _sim.spline.transform_at(_sim.s)
		Effects.splash(self, Vector3(xf.origin.x, data.terrain.water_level, xf.origin.z), -xf.basis.z)
	ride_cam.update(_sim, dt)
	audio.update(_sim, train_view.screams_started(), dt)
	hud.update_ride(_sim, train_view.sick_count(), train_view.riders.size())
	if _sim.finished:
		_finish_ride()


func _finish_ride() -> void:
	_sim.finalize()
	var ratings := RideScorer.score(_sim.record, _sim.spline, analysis_data, analysis.site)
	mode = Mode.RESULTS
	audio.stop()
	orbit_cam.current = true
	editor.visible = true
	editor.enabled = false
	hud.show_results(ratings, _sim.completed, train_view.sick_count(), train_view.riders.size())
	if analysis_data.contract_id != "":
		# The contract is judged on the analysed design (the same physics as
		# the ride you just watched).
		var res := ContractEvaluator.evaluate(Contracts.find(analysis_data.contract_id), analysis_data, analysis)
		var before := progress.best(analysis_data.contract_id)
		var unlocked := -1
		if res["stars"] > 0:
			unlocked = progress.record(analysis_data.contract_id, res["stars"])
		hud.show_contract_result(Contracts.find(analysis_data.contract_id), res, before, unlocked, next_contract_id())
	if not _sim.completed:
		orbit_cam.focus(_sim.spline.position_at(_sim.stall_s), 50.0)


func stop_ride() -> void:
	audio.stop()
	back_to_editor()


func back_to_editor() -> void:
	mode = Mode.EDIT
	orbit_cam.current = true
	editor.visible = true
	editor.enabled = true
	hud.show_editor()
	if analysis != null and analysis.valid:
		_park_train()


func toggle_ride_camera() -> void:
	ride_cam.toggle()
	hud.set_ride_camera_label(ride_cam.mode == RideCamera.Mode.POV)


func cycle_ride_speed() -> void:
	_ride_speed_i = (_ride_speed_i + 1) % RIDE_SPEEDS.size()
	hud.set_ride_speed_label(RIDE_SPEEDS[_ride_speed_i])


# -----------------------------------------------------------------------------
# Input
# -----------------------------------------------------------------------------

func _unhandled_input(event: InputEvent) -> void:
	if mode == Mode.RIDE and ride_cam.handle_input(event):
		get_viewport().set_input_as_handled()


func _unhandled_key_input(event: InputEvent) -> void:
	if not (event is InputEventKey) or not event.pressed or event.echo:
		return
	var k: InputEventKey = event
	if hud.any_dialog_open():
		if k.keycode == KEY_ESCAPE:
			hud.close_dialogs()
			get_viewport().set_input_as_handled()
		return
	var ctrl := k.ctrl_pressed or k.meta_pressed
	if k.keycode == KEY_F1 or (k.keycode == KEY_SLASH and k.shift_pressed) or k.unicode == 63:   # F1 or ?
		hud.show_shortcuts()
		get_viewport().set_input_as_handled()
		return
	match mode:
		Mode.EDIT:
			if ctrl and k.keycode == KEY_Z:
				redo() if k.shift_pressed else undo()
			elif ctrl and k.keycode == KEY_Y:
				redo()
			elif ctrl and k.keycode == KEY_A:
				select_all_points()
			elif ctrl and k.keycode == KEY_S:
				hud.open_save()
			elif ctrl and k.keycode == KEY_O:
				hud.open_load()
			elif ctrl:
				return
			elif k.keycode == KEY_DELETE or k.keycode == KEY_BACKSPACE:
				delete_point()
			elif k.keycode == KEY_INSERT or k.keycode == KEY_N:
				add_point()
			elif k.keycode == KEY_SPACE or k.keycode == KEY_ENTER:
				start_ride()
			elif k.keycode == KEY_F:
				focus_selected()
			elif k.keycode == KEY_HOME:
				frame_track()
			elif k.keycode == KEY_H:
				hud.height_toggle.button_pressed = not hud.height_toggle.button_pressed
			elif k.keycode == KEY_G:
				hud.snap_toggle.button_pressed = not hud.snap_toggle.button_pressed
			elif k.keycode == KEY_M:
				hud.multi_toggle.button_pressed = not hud.multi_toggle.button_pressed
			elif k.keycode == KEY_C:
				cycle_handle_mode()
			elif k.keycode == KEY_X:
				reset_curves()
			elif k.keycode == KEY_B:
				toggle_auto_bank()
			elif k.keycode == KEY_BRACKETLEFT or k.keycode == KEY_BRACKETRIGHT:
				bank_step(-15.0 if k.keycode == KEY_BRACKETLEFT else 15.0)
			elif k.keycode == KEY_TAB:
				select_step(-1 if k.shift_pressed else 1)
			elif k.keycode == KEY_PAGEUP:
				nudge(Vector3.UP * (5.0 if k.shift_pressed else 1.0))
			elif k.keycode == KEY_PAGEDOWN:
				nudge(Vector3.DOWN * (5.0 if k.shift_pressed else 1.0))
			elif k.keycode == KEY_1 or k.keycode == KEY_2 or k.keycode == KEY_3:
				set_tool(k.keycode - KEY_1)
			elif k.keycode == KEY_O:
				hud.overlay_option.select((hud.overlay_option.selected + 1) % hud.overlay_option.item_count)
				set_overlay(hud.overlay_option.get_selected_id())
			elif k.keycode == KEY_ESCAPE:
				if editor.tool != TrackEditor.Tool.TRACK:
					set_tool(TrackEditor.Tool.TRACK)
				else:
					editor.select(-1)
			else:
				return
		Mode.RIDE:
			if k.keycode == KEY_C:
				toggle_ride_camera()
			elif k.keycode == KEY_ESCAPE or k.keycode == KEY_SPACE:
				stop_ride()
			elif k.keycode == KEY_TAB:
				cycle_ride_speed()
			elif k.keycode == KEY_R:
				start_ride()
			else:
				return
		Mode.RESULTS:
			if k.keycode == KEY_ESCAPE:
				back_to_editor()
			elif k.keycode == KEY_SPACE or k.keycode == KEY_ENTER or k.keycode == KEY_R:
				start_ride()
			else:
				return
	get_viewport().set_input_as_handled()
