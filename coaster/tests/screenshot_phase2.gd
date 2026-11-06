extends SceneTree
## Phase 2 screenshots (needs a display).
##   xvfb-run godot --path . --rendering-method gl_compatibility -s res://tests/screenshot_phase2.gd -- <out_dir>

var out_dir := "user://shots"
var main: Node


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size() > 0:
		out_dir = args[0]
	DirAccess.make_dir_recursive_absolute(out_dir)
	_run.call_deferred()


func _frames(n: int) -> void:
	for i in n:
		await process_frame


func _settle() -> void:
	for i in 900:
		await process_frame
		if not main._job_busy():
			break
	await _frames(20)


func _shot(name: String) -> void:
	await _frames(3)
	root.get_viewport().get_texture().get_image().save_png("%s/%s.png" % [out_dir, name])
	print("saved ", name)


func _type(id: int) -> void:
	main.data.set_type(id)
	main._after_edit(true)
	main.hud.refresh_type(main.data, main.progress)


func _run() -> void:
	main = load("res://main.tscn").instantiate()
	root.add_child(main)
	await _settle()
	# 1. Contract brief on the hills.
	main.hud.show_contracts()
	await _frames(5)
	await _shot("p2_01_contracts")
	main.hud.contracts_panel.visible = false
	main.start_contract("first_steps")
	await _settle()
	await _shot("p2_02_brief")
	main.hud.brief_panel.visible = false
	# 2. Starter coaster as a wing coaster on the lake, with scenery.
	main.new_track(false)
	await _settle()
	main.data.terrain = TerrainData.make(TerrainData.Preset.LAKE)
	_type(CoasterTypes.Id.WING)
	for z in range(-150, -60, 12):
		main.data.props.append(Props.make(Props.Kind.TREE, -12.0, float(z), 1.0))
	main.data.props.append(Props.make(Props.Kind.ROCK, 6.0, -175.0, 1.2))
	main.request_analysis()
	await _settle()
	main.orbit_cam.focus(Vector3(40, 5, -170), 150.0)
	main.orbit_cam.yaw = deg_to_rad(-60)
	await _frames(40)
	await _shot("p2_03_wing_lake")
	# 3. Wooden on hills, close up.
	main.data.terrain = TerrainData.make(TerrainData.Preset.HILLS)
	_type(CoasterTypes.Id.WOODEN)
	await _settle()
	main.orbit_cam.focus(Vector3(0, 20, -150), 55.0)
	main.orbit_cam.yaw = deg_to_rad(70)
	main.orbit_cam.pitch = deg_to_rad(-15)
	await _frames(40)
	await _shot("p2_04_wooden_hills")
	# 4. Terrain tool with a tunnel through a raised hill.
	main.set_tool(TrackEditor.Tool.TERRAIN)
	for i in 30:
		main.data.terrain.sculpt(Vector3(60, 0, -60), 30.0, 1.0, TerrainData.Brush.RAISE)
	main._after_edit()
	_type(CoasterTypes.Id.STEEL)
	await _settle()
	main.orbit_cam.focus(Vector3(55, 10, -70), 110.0)
	main.orbit_cam.yaw = deg_to_rad(-110)
	main.orbit_cam.pitch = deg_to_rad(-30)
	await _frames(40)
	await _shot("p2_05_terrain_tunnel")
	main.set_tool(TrackEditor.Tool.TRACK)
	# 5. Flying coaster POV and chase.
	main.data.terrain = TerrainData.new()
	_type(CoasterTypes.Id.FLYING)
	await _settle()
	main.start_ride()
	for i in 3600:
		main._sim.step()
	await _frames(10)
	await _shot("p2_06_flying_pov")
	main.toggle_ride_camera()
	for i in 300:
		main._sim.step()
	await _frames(40)
	await _shot("p2_07_flying_chase")
	main.stop_ride()
	# 6. Contract results.
	main.data.contract_id = "first_steps"
	_type(CoasterTypes.Id.STEEL)
	await _settle()
	main.start_ride()
	while not main._sim.finished:
		main._sim.step()
	await _frames(10)
	await _shot("p2_08_results")
	quit()
