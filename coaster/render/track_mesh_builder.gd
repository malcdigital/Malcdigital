class_name TrackMeshBuilder
extends RefCounted
## Builds the track geometry (two running rails, a box spine and cross ties)
## from a baked TrackSpline.
##
## The track is split into chunks of CHUNK_SAMPLES samples so the renderer can
## cull them, and each chunk is built at two levels of detail which the
## TrackView swaps with visibility ranges. build_arrays() only fills packed
## arrays (no engine resources), so it is safe to run on a worker thread; the
## main thread turns them into ArrayMeshes with to_mesh().
##
## Geometry is placed relative to the heartline (the line through riders'
## chests that the spline follows): rails sit HEART_TO_RAIL below it.

const HEART_TO_RAIL := 1.05
const GAUGE_HALF := 0.55
const RAIL_RADIUS := 0.075
const SPINE_DROP := 0.5       # spine centre below the rail centre line
const SPINE_HALF := 0.17
const CHUNK_SAMPLES := 80

## Level-of-detail settings: [sample stride, rail sides, spine sides, tie every N samples]
const LODS := [
	{"stride": 1, "rail_sides": 6, "spine_sides": 4, "tie_every": 2},
	{"stride": 3, "rail_sides": 3, "spine_sides": 4, "tie_every": 12},
]


## Returns an Array (per chunk) of Arrays (per LOD) of surface dictionaries:
##   {"steel": surface_arrays, "spine": surface_arrays, "aabb": AABB}
static func build_arrays(spline: TrackSpline, spine_colors: PackedColorArray) -> Array:
	var chunks := []
	if spline == null or spline.count == 0:
		return chunks
	var n := spline.count
	var start := 0
	while start < n:
		var end := mini(start + CHUNK_SAMPLES, n)   # inclusive end sample (wraps at n)
		var lods := []
		for lod in LODS:
			lods.append(_build_chunk(spline, spine_colors, start, end, lod))
		chunks.append(lods)
		start = end
	return chunks


static func _build_chunk(sp: TrackSpline, colors: PackedColorArray, k0: int, k1: int, lod: Dictionary) -> Dictionary:
	var stride: int = lod["stride"]
	var steel := _Surface.new()
	var spine := _Surface.new()
	# Sample indices for this chunk, always including both ends so chunks join.
	var ks := PackedInt32Array()
	var k := k0
	while k < k1:
		ks.append(k)
		k += stride
	ks.append(k1 % sp.count)

	var rail_sides: int = lod["rail_sides"]
	var spine_sides: int = lod["spine_sides"]
	var rings_l := []
	var rings_r := []
	var rings_s := []
	for idx in ks.size():
		var kk := ks[idx]
		var p := sp.positions[kk]
		var u := sp.ups[kk]
		var r := sp.rights[kk]
		var c := p - u * HEART_TO_RAIL
		var col := colors[kk] if kk < colors.size() else Color(0.85, 0.3, 0.15)
		rings_l.append(steel.ring(c - r * GAUGE_HALF, r, u, RAIL_RADIUS, rail_sides, Color.WHITE, 0.0))
		rings_r.append(steel.ring(c + r * GAUGE_HALF, r, u, RAIL_RADIUS, rail_sides, Color.WHITE, 0.0))
		rings_s.append(spine.ring(c - u * SPINE_DROP, r, u, SPINE_HALF * 1.41, spine_sides, col, PI * 0.25))
	for idx in range(1, ks.size()):
		steel.connect_rings(rings_l[idx - 1], rings_l[idx], rail_sides)
		steel.connect_rings(rings_r[idx - 1], rings_r[idx], rail_sides)
		spine.connect_rings(rings_s[idx - 1], rings_s[idx], spine_sides)

	# Cross ties: a flat bar between the rails and a web down to the spine.
	var every: int = lod["tie_every"]
	var first_tie := k0 + posmod(-k0, every)
	for kk in range(first_tie, k1, every):
		var p := sp.positions[kk]
		var t := sp.tangents[kk]
		var u := sp.ups[kk]
		var r := sp.rights[kk]
		var c := p - u * (HEART_TO_RAIL + 0.09)
		steel.box(c, r * (GAUGE_HALF + 0.02), u * 0.05, t * 0.07)
		steel.box(c - u * (SPINE_DROP * 0.5), r * 0.05, u * (SPINE_DROP * 0.5), t * 0.06)
	return {"steel": steel.arrays(), "spine": spine.arrays(), "aabb": steel.aabb.merge(spine.aabb)}


static func to_mesh(surfaces: Dictionary, steel_mat: Material, spine_mat: Material) -> ArrayMesh:
	var mesh := ArrayMesh.new()
	for key in ["steel", "spine"]:
		var arr: Array = surfaces[key]
		if (arr[Mesh.ARRAY_VERTEX] as PackedVector3Array).is_empty():
			continue
		mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arr)
		mesh.surface_set_material(mesh.get_surface_count() - 1, steel_mat if key == "steel" else spine_mat)
	return mesh


## Growable vertex/index buffers for one surface.
class _Surface:
	var verts := PackedVector3Array()
	var normals := PackedVector3Array()
	var colors := PackedColorArray()
	var indices := PackedInt32Array()
	var aabb := AABB()
	var _first := true

	func _add(v: Vector3, nrm: Vector3, c: Color) -> void:
		verts.append(v)
		normals.append(nrm)
		colors.append(c)
		if _first:
			aabb = AABB(v, Vector3.ZERO)
			_first = false
		else:
			aabb = aabb.expand(v)

	## Ring of `sides` vertices around `center` in the plane spanned by r and u.
	## Returns the index of its first vertex.
	func ring(center: Vector3, r: Vector3, u: Vector3, radius: float, sides: int, c: Color, phase: float) -> int:
		var base := verts.size()
		for i in sides:
			var a := phase + TAU * float(i) / float(sides)
			var d := r * cos(a) + u * sin(a)
			_add(center + d * radius, d, c)
		return base

	func connect_rings(a: int, b: int, sides: int) -> void:
		for i in sides:
			var j := (i + 1) % sides
			indices.append_array([a + i, b + i, b + j, a + i, b + j, a + j])

	## Box centred at c with half-extent axis vectors x, y, z.
	func box(c: Vector3, x: Vector3, y: Vector3, z: Vector3) -> void:
		var faces := [[x, y, z], [-x, y, -z], [y, z, x], [-y, z, -x], [z, x, y], [-z, x, -y]]
		for f in faces:
			var nrm: Vector3 = f[0]
			var a: Vector3 = f[1]
			var b: Vector3 = f[2]
			var base := verts.size()
			var nn := nrm.normalized()
			_add(c + nrm - a - b, nn, Color.WHITE)
			_add(c + nrm + a - b, nn, Color.WHITE)
			_add(c + nrm + a + b, nn, Color.WHITE)
			_add(c + nrm - a + b, nn, Color.WHITE)
			indices.append_array([base, base + 2, base + 1, base, base + 3, base + 2])

	func arrays() -> Array:
		var arr := []
		arr.resize(Mesh.ARRAY_MAX)
		arr[Mesh.ARRAY_VERTEX] = verts
		arr[Mesh.ARRAY_NORMAL] = normals
		arr[Mesh.ARRAY_COLOR] = colors
		arr[Mesh.ARRAY_INDEX] = indices
		return arr
