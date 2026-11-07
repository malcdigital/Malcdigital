extends SceneTree
## End-to-end smoke test of the real game scene (headless):
## loads Main, waits for analysis, drags a control point with synthetic mouse
## events, checks undo, inserts an element, and runs a test ride to the
## results screen.   godot --headless --path . -s res://tests/smoke_ui.gd

var failures := 0


func check(cond: bool, msg: String) -> void:
	print(("  ok   " if cond else "  FAIL ") + msg)
	if not cond:
		failures += 1


func _initialize() -> void:
	_run.call_deferred()


func _frames(n: int) -> void:
	for i in n:
		await process_frame


func _wait_analysis(main: Node) -> void:
	for i in 600:
		await process_frame
		if not main._job_busy():
			return


func _run() -> void:
	var main: Node = load("res://main.tscn").instantiate()
	root.add_child(main)
	await _wait_analysis(main)
	check(main.data.open and main.data.points.size() == 2, "the game starts with just a station")
	check(main.analysis != null and main.analysis.open, "the station is drawn as an unfinished track")

	# Build from scratch: extend, add an element, try to ride, then close.
	main.add_point()
	check(main.data.points.size() == 3, "+ Point extends from the end of the station")
	main.insert_element(Elements.Kind.LIFT_HILL)
	check(main.data.points.size() > 3 and main.data.open, "elements build on the open end")
	await _wait_analysis(main)
	main.start_ride()
	check(main.mode == main.Mode.EDIT, "an unfinished track can't be ridden")
	main.insert_element(Elements.Kind.UTURN_RIGHT)
	var last: Vector3 = main.data.points[main.data.points.size() - 1].position
	main.editor.select(main.data.points.size() - 1)
	main._begin_edit()
	main.data.points.append(TrackPoint.new(Vector3(last.x, 1, 10), TrackPoint.Segment.BRAKE))
	main.data.points.append(TrackPoint.new(Vector3(0, 1, 8), TrackPoint.Segment.BRAKE))
	main._after_edit(true)
	check(not main.data.open, "bringing the end back to the station closes the circuit")
	await _wait_analysis(main)
	check(main.analysis.valid, "closed track is analysed for a ride")

	main.new_track(false)
	await _wait_analysis(main)
	check(main.analysis != null and main.analysis.valid, "starter coaster analysed")

	# Drag point 3 (top of the lift) sideways with synthetic mouse events.
	var cam: Camera3D = main.orbit_cam
	main.orbit_cam.focus(main.data.points[3].position, 60.0)
	await _frames(40)
	var idx := 3
	var before: Vector3 = main.data.points[idx].position
	var screen := cam.unproject_position(before)
	_mouse_button(main.editor, screen, true)
	for i in 10:
		_mouse_move(main.editor, screen + Vector2(8 * (i + 1), 0), Vector2(8, 0))
	_mouse_button(main.editor, screen + Vector2(80, 0), false)
	var after: Vector3 = main.data.points[idx].position
	check(main.editor.selected == idx, "tapping a handle selects it")
	check(after.distance_to(before) > 1.0, "dragging moves the point (%.1f m)" % after.distance_to(before))
	check(is_equal_approx(after.y, before.y), "a normal drag keeps the height")
	check(main.history.can_undo(), "drag is undoable")
	main.undo()
	check(main.data.points[idx].position.distance_to(before) < 0.01, "undo restores the point")
	main.redo()
	check(main.data.points[idx].position.distance_to(after) < 0.01, "redo re-applies it")
	main.undo()

	# Insert an airtime hill after the selected point.
	var n: int = main.data.points.size()
	main.editor.select(main.data.points.size() - 8)
	main.insert_element(Elements.Kind.HILL)
	check(main.data.points.size() > n, "element inserted")
	main.undo()
	check(main.data.points.size() == n, "element insert undone")
	await _wait_analysis(main)

	# Ride to the end at 4x.
	main.start_ride()
	check(main.mode == main.Mode.RIDE, "ride started")
	main._ride_speed_i = 2
	for i in 6000:
		await process_frame
		if main.mode != main.Mode.RIDE:
			break
	check(main.mode == main.Mode.RESULTS, "ride reached the results screen")
	check(main.hud.results_panel.visible, "results visible")
	main.back_to_editor()
	check(main.hud.editor_ui.visible, "back in the editor")

	# Multi-select: select three points and drag them together.
	main.orbit_cam.focus(main.data.points[3].position, 70.0)
	await _frames(40)
	main.editor.select(3)
	main.editor.toggle_select(4)
	main.editor.toggle_select(5)
	check(main.editor.selection.size() == 3, "three points selected")
	var b3: Vector3 = main.data.points[3].position
	var b5: Vector3 = main.data.points[5].position
	var sc := cam.unproject_position(b3)
	_mouse_button(main.editor, sc, true)
	for i in 8:
		_mouse_move(main.editor, sc + Vector2(10 * (i + 1), 0), Vector2(10, 0))
	_mouse_button(main.editor, sc + Vector2(80, 0), false)
	var d3: Vector3 = main.data.points[3].position - b3
	var d5: Vector3 = main.data.points[5].position - b5
	check(d3.length() > 1.0 and d3.distance_to(d5) < 0.01, "the group moves together (%.1f m)" % d3.length())
	main.undo()
	# Curve handle: drag the outgoing handle of one point.
	main.editor.select(3)
	await _frames(2)
	var hp: PackedVector3Array = main.editor.handle_positions()
	var hs := cam.unproject_position(hp[1])
	_mouse_button(main.editor, hs, true)
	for i in 6:
		_mouse_move(main.editor, hs + Vector2(0, -12 * (i + 1)), Vector2(0, -12))
	_mouse_button(main.editor, hs + Vector2(0, -72), false)
	check(main.data.points[3].handle_mode == TrackPoint.Handle.SMOOTH, "dragging a handle makes the point Smooth")
	var hh: PackedVector3Array = TrackSpline.current_handles(main.data.points, 3, true)
	check(hh[0].normalized().dot(hh[1].normalized()) < -0.99, "Smooth keeps the handles opposite")
	main.set_handle_mode(TrackPoint.Handle.AUTO)
	check(main.data.points[3].handle_mode == TrackPoint.Handle.AUTO, "handles reset to Auto")
	await _wait_analysis(main)
	# Double-tap a Smooth point: its curve resets to Auto.
	main.set_handle_mode(TrackPoint.Handle.SMOOTH)
	await _frames(30)
	await create_timer(0.5).timeout
	var ps := cam.unproject_position(main.data.points[3].position)
	for i in 2:
		_mouse_button(main.editor, ps, true)
		_mouse_button(main.editor, ps, false)
	check(main.data.points[3].handle_mode == TrackPoint.Handle.AUTO, "double-tap resets the curve")
	# Double-tap empty ground: a new point appears after the selected one.
	await create_timer(0.5).timeout
	var before_n: int = main.data.points.size()
	var gs := ps + Vector2(0, 120)
	for i in 2:
		_mouse_button(main.editor, gs, true)
		_mouse_button(main.editor, gs, false)
	check(main.data.points.size() == before_n + 1, "double-tap on the ground adds a point")
	main.undo()
	await create_timer(0.5).timeout
	await _wait_analysis(main)

	# --- Phase 2 --------------------------------------------------------------
	# Coaster type switch (steel -> wooden is unlocked from the start).
	main.set_coaster_type(CoasterTypes.Id.WOODEN)
	check(main.data.coaster_type == CoasterTypes.Id.WOODEN, "switch to wooden")
	main.set_coaster_type(CoasterTypes.Id.FLYING)
	check(main.data.coaster_type == CoasterTypes.Id.WOODEN or main.progress.unlocked_types().has(CoasterTypes.Id.FLYING), "locked types stay locked")
	main.undo()
	check(main.data.coaster_type == CoasterTypes.Id.STEEL, "type change is undoable")
	await _wait_analysis(main)

	# Sculpt with the terrain tool: a press on the ground, hold, release.
	main.set_tool(TrackEditor.Tool.TERRAIN)
	main.orbit_cam.focus(Vector3(60, 0, -60), 120.0)
	await _frames(40)
	var target := Vector3(60, 0, -60)
	var sp := cam.unproject_position(target)
	var h0: float = main.data.terrain.height_at(60, -60)
	_mouse_button(main.editor, sp, true)
	for i in 30:
		_mouse_move(main.editor, sp + Vector2(i % 3, 0), Vector2(1, 0))
		await process_frame
	_mouse_button(main.editor, sp, false)
	var h1: float = main.data.terrain.height_at(main.editor.brush_point().x, main.editor.brush_point().z)
	check(h1 > h0 + 0.5, "raise brush lifts the ground (%.1f -> %.1f m)" % [h0, h1])
	main.undo()
	check(main.data.terrain.earthworks_m3() < 1.0, "sculpting is undoable")

	# Scenery: tap to place a tree, tap it again to remove it.
	main.set_tool(TrackEditor.Tool.SCENERY)
	await _frames(5)
	_mouse_button(main.editor, sp, true)
	_mouse_button(main.editor, sp, false)
	check(main.data.props.size() == 1, "tap places a tree")
	_mouse_button(main.editor, sp, true)
	_mouse_button(main.editor, sp, false)
	check(main.data.props.is_empty(), "tapping it again removes it")
	main.set_tool(TrackEditor.Tool.TRACK)

	# Contract: start the first one and see goals evaluated.
	main.start_contract("first_steps")
	await _wait_analysis(main)
	check(main.data.contract_id == "first_steps", "contract started")
	check(main.data.open, "contracts start from just the station")
	main.hud.brief_panel.visible = false
	main.leave_contract()
	await _wait_analysis(main)
	check(main.contract_result.is_empty(), "leaving the contract returns to sandbox")

	# Save and load round trip through the UI layer.
	main.save_track("Smoke Test Coaster")
	var file := CoasterStorage.file_name_for("Smoke Test Coaster")
	main.load_saved(file)
	check(main.data.name == "Smoke Test Coaster", "saved coaster loads")
	CoasterStorage.delete(file)
	await _wait_analysis(main)
	main.queue_free()
	await _frames(2)
	print("\nsmoke: %d failures" % failures)
	quit(1 if failures > 0 else 0)


func _mouse_button(target: Node, pos: Vector2, pressed: bool) -> void:
	var e := InputEventMouseButton.new()
	e.button_index = MOUSE_BUTTON_LEFT
	e.pressed = pressed
	e.position = pos
	e.global_position = pos
	target._unhandled_input(e)


func _mouse_move(target: Node, pos: Vector2, rel: Vector2) -> void:
	var e := InputEventMouseMotion.new()
	e.position = pos
	e.global_position = pos
	e.relative = rel
	e.button_mask = MOUSE_BUTTON_MASK_LEFT
	target._unhandled_input(e)
