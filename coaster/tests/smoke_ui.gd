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
		if main._job_id < 0 and not main._dirty:
			return


func _run() -> void:
	var main: Node = load("res://main.tscn").instantiate()
	root.add_child(main)
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
