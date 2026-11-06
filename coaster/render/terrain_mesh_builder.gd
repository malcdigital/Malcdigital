class_name TerrainMeshBuilder
extends RefCounted
## Builds the terrain mesh arrays (safe on a worker thread). Colour comes from
## height and slope: sand by the water, grass, rock on steep faces, and a
## light path colour inside contract zones.

const GRASS := Color(0.4, 0.6, 0.27)
const GRASS_HIGH := Color(0.48, 0.64, 0.31)
const ROCK := Color(0.6, 0.56, 0.5)
const SAND := Color(0.7, 0.64, 0.46)
const LAKE_BED := Color(0.38, 0.42, 0.32)
const PATH := Color(0.87, 0.8, 0.64)


## Endless flat ground around the terrain square (a frame with a hole, so it
## never covers a lake dug below height 0).
static func outer_ground_arrays(t: TerrainData) -> Array:
	var verts := PackedVector3Array()
	var colors := PackedColorArray()
	var normals := PackedVector3Array()
	var indices := PackedInt32Array()
	var x0 := t.origin.x
	var z0 := t.origin.y
	var x1 := x0 + TerrainData.SIZE
	var z1 := z0 + TerrainData.SIZE
	var far := 3000.0
	# Four rectangles: north, south, west, east of the terrain.
	var rects := [
		[x0 - far, z0 - far, x1 + far, z0], [x0 - far, z1, x1 + far, z1 + far],
		[x0 - far, z0, x0, z1], [x1, z0, x1 + far, z1]]
	for r in rects:
		var b := verts.size()
		for c in [[r[0], r[1]], [r[2], r[1]], [r[2], r[3]], [r[0], r[3]]]:
			verts.append(Vector3(c[0], 0.0, c[1]))
			normals.append(Vector3.UP)
			colors.append(GRASS)
		indices.append_array(PackedInt32Array([b, b + 1, b + 2, b, b + 2, b + 3]))
	var arr := []
	arr.resize(Mesh.ARRAY_MAX)
	arr[Mesh.ARRAY_VERTEX] = verts
	arr[Mesh.ARRAY_NORMAL] = normals
	arr[Mesh.ARRAY_COLOR] = colors
	arr[Mesh.ARRAY_INDEX] = indices
	return arr


static func build_arrays(t: TerrainData, h: PackedFloat32Array, zones: Array) -> Array:
	var res := TerrainData.RES
	var cell := TerrainData.CELL
	var verts := PackedVector3Array()
	var normals := PackedVector3Array()
	var colors := PackedColorArray()
	var indices := PackedInt32Array()
	verts.resize(res * res)
	normals.resize(res * res)
	colors.resize(res * res)
	var water := t.water_level if t.has_water() else -1e9
	for j in res:
		for i in res:
			var idx := j * res + i
			var y := h[idx]
			var w := t.grid_to_world(i, j)
			verts[idx] = Vector3(w.x, y, w.y)
			var hl := h[j * res + maxi(i - 1, 0)]
			var hr := h[j * res + mini(i + 1, res - 1)]
			var hd := h[maxi(j - 1, 0) * res + i]
			var hu := h[mini(j + 1, res - 1) * res + i]
			var n := Vector3(hl - hr, 2.0 * cell, hd - hu).normalized()
			normals[idx] = n
			var c := GRASS.lerp(GRASS_HIGH, clampf(y / 30.0, 0.0, 1.0))
			if y < water + 0.6:
				c = SAND if y > water - 0.8 else LAKE_BED
			c = c.lerp(ROCK, smoothstep(0.72, 0.5, n.y))
			for z in zones:
				var rect: Rect2 = z["rect"]
				if rect.has_point(w):
					c = PATH
			colors[idx] = c
	for j in res - 1:
		for i in res - 1:
			var a := j * res + i
			var b := a + 1
			var c := a + res
			var d := c + 1
			indices.append(a)
			indices.append(b)
			indices.append(d)
			indices.append(a)
			indices.append(d)
			indices.append(c)
	var arr := []
	arr.resize(Mesh.ARRAY_MAX)
	arr[Mesh.ARRAY_VERTEX] = verts
	arr[Mesh.ARRAY_NORMAL] = normals
	arr[Mesh.ARRAY_COLOR] = colors
	arr[Mesh.ARRAY_INDEX] = indices
	return arr
