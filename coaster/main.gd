extends Node3D
## Top-level controller: owns the coaster being edited, runs analysis on a
## worker thread after every edit, and switches between Edit, Ride and Results.
##
##   Edit    - orbit camera, control-point handles, live colour overlay + stats
##   Ride    - real-time TrainSim, POV/chase camera, rider reactions, audio
##   Results - ratings breakdown and problem spots (tap to jump to them)

enum Mode { EDIT, RIDE, RESULTS }

const RIDE_SPEEDS := [1.0, 2.0, 4.0]

var mode: int = Mode.EDIT
var data: TrackData
var history := EditHistory.new()
var analysis: TrackAnalyzer          # latest finished analysis
var analysis_data: TrackData         # the exact track that analysis describes
var overlay_mode: int = TrackOverlay.Mode.ZONES

var track_view: TrackView
var editor: TrackEditor
var orbit_cam: OrbitCamera
var ride_cam: RideCamera
var train_view: TrainView
var audio: RideAudio
var hud: Hud

var _dirty := false
var _job_id := -1
var _job_result := {}
var _sim: TrainSim
var _acc := 0.0
var _ride_speed_i := 0
var _bank_edit_open := false
var _framed_once := false


func _ready() -> void:
	WorldBuilder.build(self)
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
		request_analysis()
		if not live: _refresh_point())
	hud = Hud.new()
	add_child(hud)
	hud.setup(self)
	_set_track(DefaultTracks.starter())


## Never leave a worker running while the scene (and its scripts) go away.
func _exit_tree() -> void:
	if _job_id >= 0:
		WorkerThreadPool.wait_for_task_completion(_job_id)
		_job_id = -1


# -----------------------------------------------------------------------------
# Analysis (background)
# -----------------------------------------------------------------------------

func request_analysis() -> void:
	_dirty = true


func _process(dt: float) -> void:
	if _job_id >= 0 and WorkerThreadPool.is_task_completed(_job_id):
		WorkerThreadPool.wait_for_task_completion(_job_id)
		_job_id = -1
		_apply_job()
	if _dirty and _job_id < 0:
		_start_job()
	hud.set_busy(_job_id >= 0 or _dirty)
	if mode == Mode.RIDE:
		_ride_process(dt)


func _start_job() -> void:
	_dirty = false
	var copy := data.copy()
	_job_id = WorkerThreadPool.add_task(_run_job.bind(copy, overlay_mode), false, "Analyse coaster")


## Runs on a worker thread. Only touches its own copy of the data and pure
## RefCounted logic; the result is read by the main thread after completion.
func _run_job(copy: TrackData, ov: int) -> void:
	var a := TrackAnalyzer.analyze(copy)
	var chunks := []
	if a.valid:
		chunks = TrackMeshBuilder.build_arrays(a.spline, TrackOverlay.colors(ov, a.spline, a.record))
	_job_result = {"analysis": a, "chunks": chunks, "data": copy}


func _apply_job() -> void:
	var a: TrackAnalyzer = _job_result["analysis"]
	analysis = a
	analysis_data = _job_result["data"]
	if a.valid:
		track_view.show_track(a.spline, _job_result["chunks"])
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
	if train_view.cars.size() != analysis_data.num_cars:
		train_view.build(analysis_data.num_cars)
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


func add_point() -> void:
	var i := _selected_or_last()
	_begin_edit()
	TrackTools.add_point_after(data, i, _current_spline())
	_after_edit(true)
	editor.select(i + 1)


func delete_point() -> void:
	if editor.selected < 0:
		hud.toast("Select a point first")
		return
	if data.points.size() <= 4:
		hud.toast("A track needs at least 4 points")
		return
	_begin_edit()
	var i := editor.selected
	TrackTools.remove_point(data, i)
	_after_edit(true)
	editor.select(mini(i, data.points.size() - 1))


func insert_element(kind: int) -> void:
	var i := _selected_or_last()
	var sp := _current_spline()
	var speed := 15.0
	var heading := Vector3.FORWARD
	if sp != null:
		heading = TrackTools.heading_at(sp, i)
		speed = absf(analysis.record.sample_speed[sp.index_at(sp.point_s[i])])
	var pts := Elements.build(kind, data.points[i].position, heading, speed)
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
	_begin_edit()
	data.points[editor.selected].segment = seg
	_after_edit()


func set_auto_bank(on: bool) -> void:
	if editor.selected < 0:
		return
	_begin_edit()
	var p := data.points[editor.selected]
	p.auto_bank = on
	if not on and analysis != null and analysis.valid and _current_spline() != null:
		# Start manual banking from what auto-bank was doing.
		var sp := _current_spline()
		p.bank_deg = snappedf(rad_to_deg(sp.rolls[sp.index_at(sp.point_s[editor.selected])]), 5.0)
	_after_edit()


## Bank slider moves: one undo step per drag (opened on first change).
func set_bank(deg: float) -> void:
	if editor.selected < 0:
		return
	if not _bank_edit_open:
		_begin_edit()
		_bank_edit_open = true
	data.points[editor.selected].bank_deg = deg
	request_analysis()


func commit_bank() -> void:
	_bank_edit_open = false
	_refresh_point()


func nudge(delta: Vector3) -> void:
	editor.nudge(delta)


func set_height_mode(on: bool) -> void:
	editor.height_mode = on
	hud.toast("Dragging a point now moves it up/down" if on else "Dragging a point now moves it across the ground")


func set_snap(on: bool) -> void:
	editor.snap = on


func set_overlay(mode_i: int) -> void:
	overlay_mode = mode_i
	request_analysis()


func _current_spline() -> TrackSpline:
	if analysis == null or not analysis.valid or analysis_data == null:
		return null
	if analysis_data.points.size() != data.points.size():
		return null
	return analysis.spline


# -----------------------------------------------------------------------------
# Camera helpers
# -----------------------------------------------------------------------------

func frame_track() -> void:
	if data.points.is_empty():
		return
	var aabb := AABB(data.points[0].position, Vector3.ZERO)
	for p in data.points:
		aabb = aabb.expand(p.position)
	orbit_cam.focus(aabb.get_center(), clampf(aabb.size.length() * 0.85, 30.0, 800.0))


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

func new_track(blank: bool) -> void:
	_set_track(DefaultTracks.blank() if blank else DefaultTracks.starter())


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
	hud.toast("Loaded \"%s\"" % d.name)


func delete_saved(file: String) -> void:
	CoasterStorage.delete(file)


# -----------------------------------------------------------------------------
# Ride
# -----------------------------------------------------------------------------

func start_ride() -> void:
	if analysis == null or not analysis.valid:
		hud.toast("The track needs at least 4 points")
		return
	if _dirty or _job_id >= 0:
		hud.toast("Riding the last analysed version of the track")
	mode = Mode.RIDE
	editor.visible = false
	editor.enabled = false
	_sim = TrainSim.new()
	_sim.setup(analysis.spline, analysis_data, true, TrainSim.RIDE_DT)
	train_view.build(analysis_data.num_cars)
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
	ride_cam.update(_sim, dt)
	audio.update(_sim, train_view.screams_started(), dt)
	hud.update_ride(_sim, train_view.sick_count(), train_view.riders.size())
	if _sim.finished:
		_finish_ride()


func _finish_ride() -> void:
	_sim.finalize()
	var ratings := RideScorer.score(_sim.record, _sim.spline)
	mode = Mode.RESULTS
	audio.stop()
	orbit_cam.current = true
	editor.visible = true
	editor.enabled = false
	hud.show_results(ratings, _sim.completed, train_view.sick_count(), train_view.riders.size())
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
	if not (event is InputEventKey) or not event.pressed or event.echo or hud.any_dialog_open():
		return
	var k: InputEventKey = event
	var ctrl := k.ctrl_pressed or k.meta_pressed
	match mode:
		Mode.EDIT:
			if ctrl and k.keycode == KEY_Z:
				redo() if k.shift_pressed else undo()
			elif ctrl and k.keycode == KEY_Y:
				redo()
			elif k.keycode == KEY_DELETE or k.keycode == KEY_BACKSPACE:
				delete_point()
			elif k.keycode == KEY_INSERT or k.keycode == KEY_N:
				add_point()
			elif k.keycode == KEY_SPACE or k.keycode == KEY_ENTER:
				start_ride()
			elif k.keycode == KEY_F:
				focus_selected()
			elif k.keycode == KEY_H:
				hud.height_toggle.button_pressed = not hud.height_toggle.button_pressed
			elif k.keycode == KEY_PAGEUP:
				nudge(Vector3.UP)
			elif k.keycode == KEY_PAGEDOWN:
				nudge(Vector3.DOWN)
			elif k.keycode == KEY_ESCAPE:
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
			else:
				return
		Mode.RESULTS:
			if k.keycode == KEY_ESCAPE:
				back_to_editor()
			elif k.keycode == KEY_SPACE or k.keycode == KEY_ENTER:
				start_ride()
			else:
				return
	get_viewport().set_input_as_handled()
