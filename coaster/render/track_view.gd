class_name TrackView
extends Node3D
## Shows the track: chunked rail meshes with two LODs, supports and the station
## platform. Rebuilt whenever the analysis of the track changes.

const LOD_SWITCH_DISTANCE := 110.0
const SUPPORT_EVERY_M := 8.0

var steel_material: StandardMaterial3D
var spine_material: StandardMaterial3D
var support_material: StandardMaterial3D
var platform_material: StandardMaterial3D

var _chunk_root: Node3D
var _supports: MultiMeshInstance3D
var _platforms: Node3D


func _ready() -> void:
	steel_material = StandardMaterial3D.new()
	steel_material.albedo_color = Color(0.72, 0.74, 0.78)
	steel_material.metallic = 0.6
	steel_material.roughness = 0.35
	spine_material = StandardMaterial3D.new()
	spine_material.vertex_color_use_as_albedo = true
	spine_material.roughness = 0.5
	support_material = StandardMaterial3D.new()
	support_material.albedo_color = Color(0.55, 0.58, 0.62)
	support_material.roughness = 0.6
	platform_material = StandardMaterial3D.new()
	platform_material.albedo_color = Color(0.45, 0.42, 0.38)
	_chunk_root = Node3D.new()
	add_child(_chunk_root)
	_supports = MultiMeshInstance3D.new()
	add_child(_supports)
	_platforms = Node3D.new()
	add_child(_platforms)


## `chunks` comes from TrackMeshBuilder.build_arrays (possibly built on a
## worker thread).
func show_track(spline: TrackSpline, chunks: Array) -> void:
	for c in _chunk_root.get_children():
		c.queue_free()
	for lods in chunks:
		for li in lods.size():
			var mi := MeshInstance3D.new()
			mi.mesh = TrackMeshBuilder.to_mesh(lods[li], steel_material, spine_material)
			# LOD switch by camera distance. A small overlap avoids gaps.
			if li == 0:
				mi.visibility_range_end = LOD_SWITCH_DISTANCE
				mi.visibility_range_end_margin = 5.0
			else:
				mi.visibility_range_begin = LOD_SWITCH_DISTANCE - 5.0
				mi.visibility_range_begin_margin = 5.0
				mi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
			_chunk_root.add_child(mi)
	_build_supports(spline)
	_build_platforms(spline)


func _build_supports(sp: TrackSpline) -> void:
	var xforms: Array[Transform3D] = []
	if sp != null and sp.count > 0:
		var every := maxi(1, roundi(SUPPORT_EVERY_M / sp.ds))
		for k in range(0, sp.count, every):
			var u := sp.ups[k]
			# Only support track that is roughly upright; steep and inverted
			# parts (loops) hang from their neighbours.
			if u.y < 0.55:
				continue
			var bottom := sp.positions[k] - u * (TrackMeshBuilder.HEART_TO_RAIL + TrackMeshBuilder.SPINE_DROP + 0.2)
			if bottom.y < 0.6:
				continue
			var b := Basis().scaled(Vector3(1.0, bottom.y, 1.0))
			xforms.append(Transform3D(b, Vector3(bottom.x, bottom.y * 0.5, bottom.z)))
	var mm := MultiMesh.new()
	mm.transform_format = MultiMesh.TRANSFORM_3D
	var cyl := CylinderMesh.new()
	cyl.top_radius = 0.28
	cyl.bottom_radius = 0.36
	cyl.height = 1.0
	cyl.radial_segments = 8
	cyl.rings = 1
	cyl.material = support_material
	mm.mesh = cyl
	mm.instance_count = xforms.size()
	for i in xforms.size():
		mm.set_instance_transform(i, xforms[i])
	_supports.multimesh = mm


func _build_platforms(sp: TrackSpline) -> void:
	for c in _platforms.get_children():
		c.queue_free()
	if sp == null or sp.count == 0:
		return
	# One platform box per contiguous run of station samples.
	var k := 0
	var n := sp.count
	# Start scanning just after a non-station sample so a run across the seam is whole.
	var offset := 0
	while offset < n and sp.segments[offset] == TrackPoint.Segment.STATION:
		offset += 1
	var run_start := -1
	for i in n + 1:
		k = (offset + i) % n
		var is_station := i < n and sp.segments[k] == TrackPoint.Segment.STATION
		if is_station and run_start < 0:
			run_start = i
		elif not is_station and run_start >= 0:
			_add_platform(sp, (offset + run_start) % n, (offset + i - 1) % n)
			run_start = -1


func _add_platform(sp: TrackSpline, ka: int, kb: int) -> void:
	var a := sp.positions[ka]
	var b := sp.positions[kb]
	var length := a.distance_to(b)
	if length < 2.0:
		return
	var mid := (a + b) * 0.5
	var fwd := (b - a).normalized()
	var right := fwd.cross(Vector3.UP).normalized()
	var mi := MeshInstance3D.new()
	var box := BoxMesh.new()
	box.size = Vector3(3.0, 0.6, length)
	box.material = platform_material
	mi.mesh = box
	var basis := Basis(right, Vector3.UP, -fwd)
	var floor_y := mid.y - TrackMeshBuilder.HEART_TO_RAIL + 0.1
	mi.transform = Transform3D(basis, Vector3(mid.x, floor_y - 0.3, mid.z) + right * 2.4)
	_platforms.add_child(mi)
	# Simple roof on posts.
	var roof := MeshInstance3D.new()
	var rb := BoxMesh.new()
	rb.size = Vector3(6.5, 0.2, length + 2.0)
	rb.material = platform_material
	roof.mesh = rb
	roof.transform = Transform3D(basis, Vector3(mid.x, floor_y + 3.4, mid.z) + right * 1.2)
	_platforms.add_child(roof)
