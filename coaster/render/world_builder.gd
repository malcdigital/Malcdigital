class_name WorldBuilder
extends RefCounted
## Flat terrain, sky, sun and fog.


static func build(parent: Node3D) -> void:
	var env := WorldEnvironment.new()
	var e := Environment.new()
	var sky := Sky.new()
	var sky_mat := ProceduralSkyMaterial.new()
	sky_mat.sky_top_color = Color(0.24, 0.45, 0.82)
	sky_mat.sky_horizon_color = Color(0.68, 0.8, 0.92)
	sky_mat.ground_horizon_color = Color(0.6, 0.68, 0.62)
	sky_mat.ground_bottom_color = Color(0.3, 0.38, 0.28)
	sky_mat.sun_angle_max = 30.0
	sky.sky_material = sky_mat
	e.background_mode = Environment.BG_SKY
	e.sky = sky
	e.ambient_light_source = Environment.AMBIENT_SOURCE_SKY
	e.ambient_light_energy = 0.55
	e.tonemap_mode = Environment.TONE_MAPPER_FILMIC
	e.fog_enabled = true
	e.fog_light_color = Color(0.68, 0.78, 0.9)
	e.fog_density = 0.0003
	e.fog_sky_affect = 0.0
	env.environment = e
	parent.add_child(env)

	var sun := DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-50, -35, 0)
	sun.light_energy = 1.05
	sun.shadow_enabled = true
	sun.directional_shadow_max_distance = 160.0
	sun.directional_shadow_mode = DirectionalLight3D.SHADOW_PARALLEL_2_SPLITS
	parent.add_child(sun)

	var ground := MeshInstance3D.new()
	var plane := PlaneMesh.new()
	plane.size = Vector2(3000, 3000)
	ground.mesh = plane
	var mat := ShaderMaterial.new()
	mat.shader = load("res://render/ground.gdshader")
	ground.material_override = mat
	ground.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	parent.add_child(ground)
