extends SceneTree
## Renders screenshots of the main states (needs a display; not part of the tests).
##   xvfb-run godot --path . --rendering-method gl_compatibility -s res://tests/screenshot.gd -- <out_dir>

var out_dir := "user://shots"


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size() > 0:
		out_dir = args[0]
	DirAccess.make_dir_recursive_absolute(out_dir)
	_run.call_deferred()


func _frames(n: int) -> void:
	for i in n:
		await process_frame


func _shot(name: String) -> void:
	await _frames(3)
	var img := root.get_viewport().get_texture().get_image()
	img.save_png("%s/%s.png" % [out_dir, name])
	print("saved ", name)


func _run() -> void:
	var main: Node = load("res://main.tscn").instantiate()
	root.add_child(main)
	await _frames(30)
	main.new_track(false)   # the game starts empty; show the starter coaster
	await _frames(90)
	await _shot("01_editor")
	main.editor.select(30)
	main.focus_selected()
	await _frames(60)
	await _shot("02_selected")
	main.orbit_cam.focus(Vector3(70, 10, -210), 60.0)
	main.orbit_cam.yaw = deg_to_rad(60)
	await _frames(60)
	await _shot("03_loop_closeup")
	main.start_ride()
	# Fast-forward the sim to the first drop.
	for i in 3300:
		main._sim.step()
	await _frames(10)
	await _shot("04_pov")
	main.toggle_ride_camera()
	for i in 1200:
		main._sim.step()
	await _frames(30)
	await _shot("05_chase")
	while not main._sim.finished:
		main._sim.step()
	await _frames(10)
	await _shot("06_results")
	quit()
