class_name TerrainView
extends Node3D
## Draws the terrain, the lake, contract zones and scenery props.

var _ground: MeshInstance3D
var _far: MeshInstance3D
var _water: MeshInstance3D
var _props: Node3D
var _material: ShaderMaterial
var _water_mat: StandardMaterial3D
var _trunk_mm: MultiMeshInstance3D
var _crown_mm: MultiMeshInstance3D
var _rock_mm: MultiMeshInstance3D
var _tower_mm: MultiMeshInstance3D


func _ready() -> void:
	_material = ShaderMaterial.new()
	_material.shader = load("res://render/ground.gdshader")
	_ground = MeshInstance3D.new()
	_ground.material_override = _material
	_ground.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	add_child(_ground)
	# Endless flat ground beyond the terrain grid.
	_far = MeshInstance3D.new()
	var far_mesh := ArrayMesh.new()
	far_mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, TerrainMeshBuilder.outer_ground_arrays(TerrainData.new()))
	_far.mesh = far_mesh
	_far.material_override = _material
	_far.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	add_child(_far)
	_water = MeshInstance3D.new()
	var wp := PlaneMesh.new()
	wp.size = Vector2(TerrainData.SIZE, TerrainData.SIZE)
	_water.mesh = wp
	_water_mat = StandardMaterial3D.new()
	_water_mat.albedo_color = Color(0.1, 0.36, 0.62, 0.88)
	_water_mat.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	_water_mat.roughness = 0.08
	_water_mat.metallic = 0.25
	_water.material_override = _water_mat
	_water.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	add_child(_water)
	_props = Node3D.new()
	add_child(_props)
	var trunk := CylinderMesh.new()
	trunk.top_radius = 0.25
	trunk.bottom_radius = 0.35
	trunk.height = 1.0
	trunk.radial_segments = 6
	trunk.material = _mat(Color(0.4, 0.28, 0.18))
	var crown := CylinderMesh.new()
	crown.top_radius = 0.0
	crown.bottom_radius = 1.0
	crown.height = 1.0
	crown.radial_segments = 8
	crown.material = _mat(Color(0.18, 0.4, 0.2))
	var rock := SphereMesh.new()
	rock.radius = 1.0
	rock.height = 2.0
	rock.radial_segments = 7
	rock.rings = 4
	rock.material = _mat(Color(0.5, 0.48, 0.45))
	var tower := BoxMesh.new()
	tower.size = Vector3.ONE
	tower.material = _mat(Color(0.75, 0.75, 0.78))
	_trunk_mm = _mm(trunk)
	_crown_mm = _mm(crown)
	_rock_mm = _mm(rock)
	_tower_mm = _mm(tower)


static func _mat(c: Color) -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	m.albedo_color = c
	m.roughness = 0.85
	return m


func _mm(mesh: Mesh) -> MultiMeshInstance3D:
	var mmi := MultiMeshInstance3D.new()
	var mm := MultiMesh.new()
	mm.transform_format = MultiMesh.TRANSFORM_3D
	mm.mesh = mesh
	mmi.multimesh = mm
	_props.add_child(mmi)
	return mmi


## Draw from prepared arrays (TerrainMeshBuilder output).
func show_terrain(t: TerrainData, arrays: Array) -> void:
	var mesh := ArrayMesh.new()
	mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
	_ground.mesh = mesh
	_water.visible = t.has_water()
	if t.has_water():
		var c := t.origin + Vector2.ONE * TerrainData.SIZE * 0.5
		_water.position = Vector3(c.x, t.water_level, c.y)


## Quick rebuild straight from heights (while sculpting, no cuttings).
func show_raw(t: TerrainData, zones: Array) -> void:
	show_terrain(t, TerrainMeshBuilder.build_arrays(t, t.heights, zones))


func show_props(t: TerrainData, props: Array[Dictionary]) -> void:
	var trunks: Array[Transform3D] = []
	var crowns: Array[Transform3D] = []
	var rocks: Array[Transform3D] = []
	var towers: Array[Transform3D] = []
	for p in props:
		var x: float = p["x"]
		var z: float = p["z"]
		var s: float = p["s"]
		var g := t.height_at(x, z)
		var r := Props.radius(p)
		var h := Props.height(p)
		var yaw := fmod(x * 12.9898 + z * 78.233, TAU)
		match int(p["k"]):
			Props.Kind.TREE:
				trunks.append(Transform3D(Basis().scaled(Vector3(s, h * 0.35, s)), Vector3(x, g + h * 0.175, z)))
				crowns.append(Transform3D(Basis(Vector3.UP, yaw).scaled(Vector3(r, h * 0.75, r)), Vector3(x, g + h * 0.25 + h * 0.375, z)))
			Props.Kind.ROCK:
				rocks.append(Transform3D(Basis(Vector3.UP, yaw).scaled(Vector3(r, h * 0.5, r * 0.8)), Vector3(x, g + h * 0.3, z)))
			Props.Kind.TOWER:
				towers.append(Transform3D(Basis(Vector3.UP, yaw).scaled(Vector3(r * 1.4, h, r * 1.4)), Vector3(x, g + h * 0.5, z)))
	_fill(_trunk_mm, trunks)
	_fill(_crown_mm, crowns)
	_fill(_rock_mm, rocks)
	_fill(_tower_mm, towers)


func _fill(mmi: MultiMeshInstance3D, xf: Array[Transform3D]) -> void:
	mmi.multimesh.instance_count = xf.size()
	for i in xf.size():
		mmi.multimesh.set_instance_transform(i, xf[i])
