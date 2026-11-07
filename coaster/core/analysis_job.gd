class_name AnalysisJob
extends RefCounted
## The full after-edit analysis, written so it can be done a slice at a time:
##   bake spline -> simulate for speeds -> auto-bank -> simulate again for
##   G-forces on the banked track -> score -> (optionally) build mesh arrays.
##
## Desktop and mobile builds run a job to completion on a worker thread. The
## web build has no threads, so Main calls run() with a small time budget
## every frame instead; the game keeps rendering at full frame rate while the
## analysis finishes over a few frames.
##
## Banking does not change speed (it only rotates which way the force points,
## not how big it is), so the first pass's speeds are valid for the second.

enum Stage { BAKE, SPEED_PASS, FORCE_PASS, SITE, SCORE, MESH, TERRAIN, DONE }

## The speed-only pass can use a coarser step: speeds converge quickly and the
## G-forces we report come from the second, finer pass.
const SPEED_PASS_DT := 1.0 / 30.0
## Sim steps between time-budget checks (one step is ~10 µs on desktop).
const STEPS_PER_CHECK := 64

var data: TrackData
var overlay_mode := 0
var build_meshes := true

var result := TrackAnalyzer.new()
var chunks := []
## Terrain mesh arrays with cuttings dug out (built with the track meshes).
var terrain_arrays := []
## Fingerprint of the terrain as drawn; when it matches `skip_terrain_key`
## (what is already on screen) the terrain mesh is not rebuilt.
var terrain_key := 0
var skip_terrain_key := -1
var terrain_unchanged := false
var stage: int = Stage.BAKE

var _sim: TrainSim
var _colors: PackedColorArray
var _chunk := 0


func _init(p_data: TrackData, p_overlay: int = 0, p_build_meshes: bool = true) -> void:
	data = p_data
	overlay_mode = p_overlay
	build_meshes = p_build_meshes


func is_done() -> bool:
	return stage == Stage.DONE


## Do up to `budget_usec` microseconds of work. Returns true once finished.
func run(budget_usec: int) -> bool:
	var t0 := Time.get_ticks_usec()
	while stage != Stage.DONE:
		_advance(t0, budget_usec)
		if Time.get_ticks_usec() - t0 >= budget_usec:
			break
	return stage == Stage.DONE


func _advance(t0: int, budget: int) -> void:
	match stage:
		Stage.BAKE:
			result.spline = TrackSpline.new()
			if data.open:
				# Unfinished track: draw it (with supports and cost) but don't ride it.
				if data.points.size() < 2 or not result.spline.bake(data):
					stage = Stage.DONE
					return
				result.open = true
				result.spline.apply_banking(data, PackedFloat32Array())
				result.site = SiteAnalysis.new()
				result.site.classify(result.spline, data)
				stage = Stage.SITE
				return
			if not data.is_valid() or not result.spline.bake(data):
				stage = Stage.DONE
				return
			result.site = SiteAnalysis.new()
			result.site.classify(result.spline, data)
			_sim = TrainSim.new()
			_sim.setup(result.spline, data, true, SPEED_PASS_DT)
			_sim.fast = true
			stage = Stage.SPEED_PASS
		Stage.SPEED_PASS:
			if _run_sim(t0, budget):
				_sim.finalize()
				result.spline.apply_banking(data, _sim.record.sample_speed)
				_sim.setup(result.spline, data, true, TrainSim.PREVIEW_DT)
				_sim.fast = false
				stage = Stage.FORCE_PASS
		Stage.FORCE_PASS:
			if _run_sim(t0, budget):
				_sim.finalize()
				result.record = _sim.record
				stage = Stage.SITE
		Stage.SITE:
			result.site.build(result.spline, data, result.record, Contracts.zones(data.contract_id))
			stage = Stage.SCORE
		Stage.SCORE:
			if not result.open:
				result.ratings = RideScorer.score(result.record, result.spline, data, result.site)
			var c := CostModel.estimate(data, result.spline, result.site)
			result.cost = c["total"]
			result.cost_parts.assign(c["parts"])
			var h := 0.0
			for k in result.spline.count:
				h = maxf(h, result.spline.positions[k].y - result.site.ground[k])
			result.max_height_above_ground = h
			result.valid = not result.open
			if build_meshes:
				_colors = TrackOverlay.colors(overlay_mode if not result.open else TrackOverlay.Mode.PAINT, result.spline, result.record, float(data.type_info()["g_scale"]), data.type_info()["spine"])
				stage = Stage.MESH
			else:
				stage = Stage.DONE
		Stage.MESH:
			if _chunk < TrackMeshBuilder.chunk_count(result.spline):
				chunks.append(TrackMeshBuilder.build_chunk(result.spline, _colors, _chunk, data.type_info(), result.site.env))
				_chunk += 1
			else:
				stage = Stage.TERRAIN
		Stage.TERRAIN:
			terrain_key = hash(result.site.render_heights) ^ hash(data.terrain.water_level) ^ data.contract_id.hash()
			if terrain_key == skip_terrain_key:
				terrain_unchanged = true
			else:
				terrain_arrays = TerrainMeshBuilder.build_arrays(data.terrain, result.site.render_heights, Contracts.zones(data.contract_id))
			stage = Stage.DONE


## Steps the current sim until it finishes (true) or the budget runs out.
func _run_sim(t0: int, budget: int) -> bool:
	while not _sim.finished:
		for i in STEPS_PER_CHECK:
			_sim.step()
			if _sim.finished:
				break
		if Time.get_ticks_usec() - t0 >= budget:
			return _sim.finished
	return true
