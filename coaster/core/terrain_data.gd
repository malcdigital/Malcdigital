class_name TerrainData
extends RefCounted
## Heightfield terrain the coaster is built on, plus an optional lake.
##
## A square grid of RES x RES height samples, CELL metres apart, covering
## SIZE x SIZE metres from `origin` (x, z). Heights are metres; the station
## area of every preset sits at height 0.
##
## `base` keeps the preset's original heights so earthworks can be costed.

enum Preset { FLAT, HILLS, LAKE, CANYON }

const PRESET_NAMES := ["Flat meadow", "Rolling hills", "Lakeside", "Canyon"]
const RES := 129
const CELL := 4.0
const SIZE := CELL * (RES - 1)        # 512 m
const NO_WATER := -1000.0

var origin := Vector2(-220.0, -360.0)  # world (x, z) of grid corner [0, 0]
var heights := PackedFloat32Array()
var base := PackedFloat32Array()
var water_level := NO_WATER
var preset: int = Preset.FLAT


func _init() -> void:
	heights.resize(RES * RES)
	heights.fill(0.0)
	base = heights.duplicate()


func has_water() -> bool:
	return water_level > NO_WATER + 1.0


func copy() -> TerrainData:
	var t := TerrainData.new()
	t.origin = origin
	t.heights = heights.duplicate()
	t.base = base.duplicate()
	t.water_level = water_level
	t.preset = preset
	return t


# -----------------------------------------------------------------------------
# Presets
# -----------------------------------------------------------------------------

static func make(p: int) -> TerrainData:
	var t := TerrainData.new()
	t.preset = p
	var noise := FastNoiseLite.new()
	noise.seed = 1234 + p
	noise.noise_type = FastNoiseLite.TYPE_SIMPLEX_SMOOTH
	noise.frequency = 0.006
	noise.fractal_octaves = 3
	for j in RES:
		for i in RES:
			var w := t.grid_to_world(i, j)
			var h := 0.0
			match p:
				Preset.HILLS:
					h = maxf(noise.get_noise_2d(w.x, w.y) * 34.0 + 8.0, 0.0)
				Preset.LAKE:
					# A lake east of the station, gentle hills beyond it.
					var d := w.distance_to(Vector2(70.0, -150.0))
					h = -6.0 * (1.0 - smoothstep(30.0, 62.0, d)) + maxf(noise.get_noise_2d(w.x, w.y) * 14.0, 0.0) * smoothstep(80.0, 140.0, d)
				Preset.CANYON:
					# Two ridges with a valley running north-south between them.
					var ridge := smoothstep(25.0, 70.0, absf(w.x - 30.0))
					h = ridge * (28.0 + noise.get_noise_2d(w.x, w.y) * 14.0)
			# Keep the station area flat and at height 0, and fade to 0 at the
			# edges so the terrain meets the endless flat ground beyond it.
			var station := smoothstep(26.0, 50.0, w.distance_to(Vector2(0.0, -10.0)))
			var edge := minf(minf(i, RES - 1 - i), minf(j, RES - 1 - j)) * CELL
			t.heights[j * RES + i] = h * station * smoothstep(0.0, 60.0, edge)
	if p == Preset.LAKE:
		t.water_level = -1.2
	t.base = t.heights.duplicate()
	return t


# -----------------------------------------------------------------------------
# Queries
# -----------------------------------------------------------------------------

func grid_to_world(i: int, j: int) -> Vector2:
	return origin + Vector2(i, j) * CELL


func world_to_grid(x: float, z: float) -> Vector2:
	return (Vector2(x, z) - origin) / CELL


## Bilinearly interpolated ground height. Outside the grid: the nearest edge.
func height_at(x: float, z: float) -> float:
	var g := world_to_grid(x, z)
	var gx := clampf(g.x, 0.0, RES - 1.001)
	var gz := clampf(g.y, 0.0, RES - 1.001)
	var i := int(gx)
	var j := int(gz)
	var fx := gx - i
	var fz := gz - j
	var h00 := heights[j * RES + i]
	var h10 := heights[j * RES + i + 1]
	var h01 := heights[(j + 1) * RES + i]
	var h11 := heights[(j + 1) * RES + i + 1]
	return lerpf(lerpf(h00, h10, fx), lerpf(h01, h11, fx), fz)


## Water depth at a point (0 where there is no lake).
func water_depth_at(x: float, z: float) -> float:
	if not has_water():
		return 0.0
	return maxf(water_level - height_at(x, z), 0.0)


## Where a ray first hits the ground (or water), or null. Simple ray march.
func raycast(from: Vector3, dir: Vector3, max_dist: float = 2500.0) -> Variant:
	var step := 1.0
	var prev := from
	var t := 0.0
	while t < max_dist:
		t += step
		var p := from + dir * t
		var ground := height_at(p.x, p.z)
		if has_water():
			ground = maxf(ground, water_level)
		if p.y <= ground:
			# Refine between prev and p.
			var a := prev
			var b := p
			for k in 8:
				var m := (a + b) * 0.5
				var gm := height_at(m.x, m.z)
				if has_water():
					gm = maxf(gm, water_level)
				if m.y <= gm:
					b = m
				else:
					a = m
			return b
		prev = p
		step = minf(step * 1.08, 8.0)
	return null


# -----------------------------------------------------------------------------
# Sculpting
# -----------------------------------------------------------------------------

enum Brush { RAISE, LOWER, FLATTEN, SMOOTH }

const BRUSH_NAMES := ["Raise", "Lower", "Flatten", "Smooth"]
const MIN_HEIGHT := -30.0
const MAX_HEIGHT := 80.0


## Apply a brush at world (x, z). `amount` is metres at the centre for
## raise/lower, or blend strength (0..1) for flatten/smooth. Falloff is a
## smooth bump out to `radius`.
func sculpt(center: Vector3, radius: float, amount: float, brush: int, flatten_to: float = 0.0) -> void:
	var g := world_to_grid(center.x, center.z)
	var r := radius / CELL
	var i0 := maxi(0, int(g.x - r) - 1)
	var i1 := mini(RES - 1, int(g.x + r) + 1)
	var j0 := maxi(0, int(g.y - r) - 1)
	var j1 := mini(RES - 1, int(g.y + r) + 1)
	var src := heights.duplicate() if brush == Brush.SMOOTH else PackedFloat32Array()
	for j in range(j0, j1 + 1):
		for i in range(i0, i1 + 1):
			var d := Vector2(i, j).distance_to(g) / r
			if d >= 1.0:
				continue
			var w := 1.0 - smoothstep(0.0, 1.0, d)
			var idx := j * RES + i
			var h := heights[idx]
			match brush:
				Brush.RAISE:
					h += amount * w
				Brush.LOWER:
					h -= amount * w
				Brush.FLATTEN:
					h = lerpf(h, flatten_to, clampf(amount * w, 0.0, 1.0))
				Brush.SMOOTH:
					var avg := (src[idx] + src[j * RES + maxi(i - 1, 0)] + src[j * RES + mini(i + 1, RES - 1)]
						+ src[maxi(j - 1, 0) * RES + i] + src[mini(j + 1, RES - 1) * RES + i]) / 5.0
					h = lerpf(h, avg, clampf(amount * w, 0.0, 1.0))
			heights[idx] = clampf(h, MIN_HEIGHT, MAX_HEIGHT)


## Cubic metres of earth moved compared with the preset.
func earthworks_m3() -> float:
	var total := 0.0
	for i in heights.size():
		total += absf(heights[i] - base[i])
	return total * CELL * CELL


# -----------------------------------------------------------------------------
# Saving: heights as int16 decimetres, only the difference from the preset.
# -----------------------------------------------------------------------------

func to_dict() -> Dictionary:
	var d := {"preset": preset, "water": water_level}
	var changed := false
	var bytes := PackedByteArray()
	bytes.resize(heights.size() * 2)
	for i in heights.size():
		var dv := roundi((heights[i] - base[i]) * 10.0)
		if dv != 0:
			changed = true
		bytes.encode_s16(i * 2, clampi(dv, -32768, 32767))
	if changed:
		d["delta"] = Marshalls.raw_to_base64(bytes.compress(FileAccess.COMPRESSION_DEFLATE))
		d["delta_size"] = bytes.size()
	return d


static func from_dict(d: Dictionary) -> TerrainData:
	var t := TerrainData.make(clampi(int(d.get("preset", Preset.FLAT)), 0, Preset.CANYON))
	t.water_level = float(d.get("water", t.water_level))
	if d.has("delta"):
		var bytes := Marshalls.base64_to_raw(str(d["delta"])).decompress(int(d.get("delta_size", RES * RES * 2)), FileAccess.COMPRESSION_DEFLATE)
		if bytes.size() == RES * RES * 2:
			for i in t.heights.size():
				t.heights[i] = t.base[i] + bytes.decode_s16(i * 2) / 10.0
	return t
