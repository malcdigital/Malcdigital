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


static func chunk_count(spline: TrackSpline) -> int:
	if spline == null or spline.count == 0:
		return 0
	# An open track has no segment from its last sample back to the first.
	var spans := spline.count if spline.closed else spline.count - 1
	return ceili(float(spans) / CHUNK_SAMPLES)


## One chunk at every LOD: an Array (per LOD) of surface dictionaries
## {"steel": arrays, "spine": arrays, "tunnel": arrays}.
## `ty` is the coaster type (CoasterTypes), `env` the per-sample terrain
## classification from SiteAnalysis (for tunnels).
static func build_chunk(spline: TrackSpline, spine_colors: PackedColorArray, index: int,
		ty: Dictionary = {}, env: PackedByteArray = PackedByteArray()) -> Array:
	if ty.is_empty():
		ty = CoasterTypes.get_type(CoasterTypes.Id.STEEL)
	var start := index * CHUNK_SAMPLES
	var end := mini(start + CHUNK_SAMPLES, spline.count if spline.closed else spline.count - 1)   # inclusive end sample
	var lods := []
	for lod in LODS:
		lods.append(_build_chunk(spline, spine_colors, start, end, lod, ty, env))
	return lods


## All chunks at once.
static func build_arrays(spline: TrackSpline, spine_colors: PackedColorArray, ty: Dictionary = {}, env: PackedByteArray = PackedByteArray()) -> Array:
	var chunks := []
	for i in chunk_count(spline):
		chunks.append(build_chunk(spline, spine_colors, i, ty, env))
	return chunks


const TUNNEL_RADIUS := 3.2
const TUNNEL_COLOR := Color(0.32, 0.3, 0.28)


static func _build_chunk(sp: TrackSpline, colors: PackedColorArray, k0: int, k1: int, lod: Dictionary,
		ty: Dictionary, env: PackedByteArray) -> Dictionary:
	var stride: int = lod["stride"]
	var steel := _Surface.new()
	var spine := _Surface.new()
	var tunnel := _Surface.new()
	var style: String = ty["style"]
	var rail_col: Color = ty["rail"]
	var tie_col: Color = ty["tie"]
	var paint: Color = ty["spine"]
	# Flying coasters hang the train under the rails, so the structure sits
	# above the heartline instead of below it.
	var dir := 1.0 if style == "flying" else -1.0
	var wood := style == "wood"
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
	var rings_t := []
	for idx in ks.size():
		var kk := ks[idx]
		var p := sp.positions[kk]
		var u := sp.ups[kk]
		var r := sp.rights[kk]
		var c := p + u * (HEART_TO_RAIL * dir)
		var col := colors[kk] if kk < colors.size() else paint
		if wood:
			# Flat steel strap rails on a wooden deck.
			rings_l.append(steel.ring(c - r * GAUGE_HALF, r, u, 0.1, 4, rail_col, PI * 0.25))
			rings_r.append(steel.ring(c + r * GAUGE_HALF, r, u, 0.1, 4, rail_col, PI * 0.25))
		else:
			rings_l.append(steel.ring(c - r * GAUGE_HALF, r, u, RAIL_RADIUS, rail_sides, rail_col, 0.0))
			rings_r.append(steel.ring(c + r * GAUGE_HALF, r, u, RAIL_RADIUS, rail_sides, rail_col, 0.0))
			rings_s.append(spine.ring(c + u * (SPINE_DROP * dir), r, u, SPINE_HALF * 1.41, spine_sides, col, PI * 0.25))
		if env.size() == sp.count and env[kk] == SiteAnalysis.Env.TUNNEL:
			rings_t.append(tunnel.ring(p + u * 0.2, r, u, TUNNEL_RADIUS, 10 if stride == 1 else 6, TUNNEL_COLOR, 0.0))
		else:
			rings_t.append(-1)
	for idx in range(1, ks.size()):
		steel.connect_rings(rings_l[idx - 1], rings_l[idx], 4 if wood else rail_sides)
		steel.connect_rings(rings_r[idx - 1], rings_r[idx], 4 if wood else rail_sides)
		if not wood:
			spine.connect_rings(rings_s[idx - 1], rings_s[idx], spine_sides)
		if rings_t[idx - 1] >= 0 and rings_t[idx] >= 0:
			# Seen from inside: reversed winding.
			tunnel.connect_rings(rings_t[idx], rings_t[idx - 1], 10 if stride == 1 else 6)
	# Flip tunnel normals to face inwards.
	for i in tunnel.normals.size():
		tunnel.normals[i] = -tunnel.normals[i]

	# Cross ties. Wooden track: dense, wide ties that carry the overlay colour.
	var every: int = lod["tie_every"]
	if wood:
		every = maxi(1, every / 2)
	# Ties are instances of one unit box (a MultiMesh), so building them is just
	# writing transforms: far cheaper than generating their vertices.
	var first_tie := k0 + posmod(-k0, every)
	var ties := PackedFloat32Array()
	for kk in range(first_tie, k1, every):
		var p := sp.positions[kk]
		var t := sp.tangents[kk]
		var u := sp.ups[kk]
		var r := sp.rights[kk]
		if wood:
			var col := colors[kk] if kk < colors.size() else tie_col
			_instance(ties, p + u * ((HEART_TO_RAIL + 0.18) * dir), r * 1.9, u * 0.18, t * 0.22, col.lerp(tie_col, 0.35))
		else:
			var c := p + u * ((HEART_TO_RAIL + 0.09) * dir)
			_instance(ties, c, r * (GAUGE_HALF * 2.0 + 0.04), u * 0.1, t * 0.14, tie_col)
			_instance(ties, c + u * (SPINE_DROP * 0.5 * dir), r * 0.1, u * SPINE_DROP, t * 0.12, tie_col)
	return {"steel": steel.arrays(), "spine": spine.arrays(), "tunnel": tunnel.arrays(), "ties": ties}


## Append one MultiMesh instance (3x4 transform, row-major, then a colour) for
## a unit box scaled to full extents x, y, z and centred on c.
static func _instance(buf: PackedFloat32Array, c: Vector3, x: Vector3, y: Vector3, z: Vector3, col: Color) -> void:
	buf.append_array(PackedFloat32Array([x.x, y.x, z.x, c.x, x.y, y.y, z.y, c.y, x.z, y.z, z.z, c.z, col.r, col.g, col.b, col.a]))


static func to_mesh(surfaces: Dictionary, steel_mat: Material, spine_mat: Material, tunnel_mat: Material = null) -> ArrayMesh:
	var mesh := ArrayMesh.new()
	for key in ["steel", "spine", "tunnel"]:
		if not surfaces.has(key):
			continue
		var arr: Array = surfaces[key]
		if (arr[Mesh.ARRAY_VERTEX] as PackedVector3Array).is_empty():
			continue
		mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arr)
		var mat := steel_mat
		if key == "spine":
			mat = spine_mat
		elif key == "tunnel":
			mat = tunnel_mat if tunnel_mat != null else steel_mat
		mesh.surface_set_material(mesh.get_surface_count() - 1, mat)
	return mesh


## Growable vertex/index buffers for one surface.
class _Surface:
	var verts := PackedVector3Array()
	var normals := PackedVector3Array()
	var colors := PackedColorArray()
	var indices := PackedInt32Array()

	func _add(v: Vector3, nrm: Vector3, c: Color) -> void:
		verts.append(v)
		normals.append(nrm)
		colors.append(c)

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
			indices.append(a + i)
			indices.append(b + i)
			indices.append(b + j)
			indices.append(a + i)
			indices.append(b + j)
			indices.append(a + j)

	## Box centred at c with half-extent axis vectors x, y, z.
	func box(c: Vector3, x: Vector3, y: Vector3, z: Vector3, col: Color = Color.WHITE) -> void:
		_face(c, x, y, z, col)
		_face(c, -x, y, -z, col)
		_face(c, y, z, x, col)
		_face(c, -y, z, -x, col)
		_face(c, z, x, y, col)
		_face(c, -z, x, -y, col)

	func _face(c: Vector3, nrm: Vector3, a: Vector3, b: Vector3, col: Color) -> void:
		var base := verts.size()
		var nn := nrm.normalized()
		_add(c + nrm - a - b, nn, col)
		_add(c + nrm + a - b, nn, col)
		_add(c + nrm + a + b, nn, col)
		_add(c + nrm - a + b, nn, col)
		indices.append(base)
		indices.append(base + 2)
		indices.append(base + 1)
		indices.append(base)
		indices.append(base + 3)
		indices.append(base + 2)

	func arrays() -> Array:
		var arr := []
		arr.resize(Mesh.ARRAY_MAX)
		arr[Mesh.ARRAY_VERTEX] = verts
		arr[Mesh.ARRAY_NORMAL] = normals
		arr[Mesh.ARRAY_COLOR] = colors
		arr[Mesh.ARRAY_INDEX] = indices
		return arr
