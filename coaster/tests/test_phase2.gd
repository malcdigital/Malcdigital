extends RefCounted
var runner


# --- Terrain ------------------------------------------------------------------

func test_terrain_sculpt_and_save() -> void:
	var t := TerrainData.new()
	runner.near(t.height_at(10, -50), 0.0, 1e-6, "flat to start")
	t.sculpt(Vector3(10, 0, -50), 12.0, 5.0, TerrainData.Brush.RAISE)
	runner.check(t.height_at(10, -50) > 3.5, "raise lifts the centre (%.1f m)" % t.height_at(10, -50))
	runner.near(t.height_at(40, -50), 0.0, 1e-6, "outside the brush untouched")
	runner.check(t.earthworks_m3() > 100.0, "earthworks counted")
	t.sculpt(Vector3(10, 0, -50), 12.0, 1.0, TerrainData.Brush.FLATTEN, 2.0)
	runner.check(absf(t.height_at(10, -50) - 2.0) < 0.5, "flatten moves towards the target (%.1f m)" % t.height_at(10, -50))
	var d := TrackData.new()
	d.terrain = t
	var back := TrackData.from_dict(JSON.parse_string(JSON.stringify(d.to_dict())))
	runner.near(back.terrain.height_at(10, -50), t.height_at(10, -50), 0.06, "sculpted terrain survives save/load")


func test_presets_keep_station_flat() -> void:
	for p in TerrainData.PRESET_NAMES.size():
		var t := TerrainData.make(p)
		runner.near(t.height_at(0, -10), 0.0, 0.01, "%s: station area flat" % TerrainData.PRESET_NAMES[p])
	runner.check(TerrainData.make(TerrainData.Preset.LAKE).has_water(), "lake preset has water")
	runner.check(TerrainData.make(TerrainData.Preset.HILLS).height_at(150, -200) != 0.0 or TerrainData.make(TerrainData.Preset.HILLS).height_at(-120, -250) != 0.0, "hills are hilly")


func test_raycast_hits_ground() -> void:
	var t := TerrainData.new()
	var hit = t.raycast(Vector3(0, 50, 0), Vector3(0, -1, 0.2).normalized())
	runner.check(hit != null and absf((hit as Vector3).y) < 0.2, "ray lands on the ground")


# --- Tunnels, water, near misses ----------------------------------------------

func test_track_through_a_hill_is_a_tunnel() -> void:
	var t := TestTracks.launched(Elements.Kind.STRAIGHT, 20.0)
	for i in 6:
		t.terrain.sculpt(Vector3(0, 0, -130), 26.0, 4.0, TerrainData.Brush.RAISE)
	var a := TrackAnalyzer.analyze(t)
	runner.check(a.site.tunnel_length > 15.0, "tunnel found (%.0f m)" % a.site.tunnel_length)
	runner.check(a.ratings.stats["tunnel_length"] > 15.0, "tunnel in stats")
	var has_cost := false
	for p in a.cost_parts:
		if str(p["label"]).begins_with("Tunnels"):
			has_cost = true
	runner.check(has_cost, "tunnels cost money")
	runner.check(a.site.near_misses.size() >= 1, "diving into the tunnel at speed is a near miss")


func test_splashdown_splashes_and_slows_the_train() -> void:
	var t := TestTracks.launched(Elements.Kind.SPLASHDOWN, 20.0, true, {"water_level": -1.2})
	t.terrain = TestTracks.lake_terrain()
	var a := TrackAnalyzer.analyze(t)
	runner.check(a.record.splashes >= 1, "train splashes (%d)" % a.record.splashes)
	runner.check(a.ratings.stats["splashes"] >= 1, "splash in stats")
	var dry := TestTracks.launched(Elements.Kind.SPLASHDOWN, 20.0, true, {"water_level": -1.2})
	var b := TrackAnalyzer.analyze(dry)
	runner.check(b.record.splashes == 0, "no lake, no splash")
	runner.check(a.record.duration > b.record.duration, "water drag slows the ride (%.1f s vs %.1f s)" % [a.record.duration, b.record.duration])
	for p in a.ratings.problems:
		runner.check(p["kind"] != "water", "a proper splashdown does not submerge riders")


func test_too_deep_is_a_problem() -> void:
	var t := TestTracks.launched(Elements.Kind.SPLASHDOWN, 20.0, true, {"water_level": 2.5})
	t.terrain = TestTracks.lake_terrain()
	t.terrain.water_level = 2.5
	var a := TrackAnalyzer.analyze(t)
	var found := false
	for p in a.ratings.problems:
		if p["kind"] == "water":
			found = true
	runner.check(found, "train under water is flagged")


func test_scenery_near_miss_and_collision() -> void:
	var t := TestTracks.launched(Elements.Kind.STRAIGHT, 25.0)
	var base := TrackAnalyzer.analyze(t)
	t.props.append(Props.make(Props.Kind.TREE, 4.0, -150.0))
	var near := TrackAnalyzer.analyze(t)
	runner.check(near.site.near_misses.size() > base.site.near_misses.size(), "tree beside the track is a near miss")
	runner.check(near.ratings.thrill > base.ratings.thrill, "near misses add thrill")
	t.props.append(Props.make(Props.Kind.TREE, 0.3, -200.0))
	var hit := TrackAnalyzer.analyze(t)
	var crash := false
	for p in hit.ratings.problems:
		if p["kind"] == "collision" and p["severity"] == GLimits.Zone.DANGER:
			crash = true
	runner.check(crash, "tree on the track is a collision")


func test_supports_skip_inversions_and_stand_on_ground() -> void:
	var a := TrackAnalyzer.analyze(DefaultTracks.starter())
	runner.check(a.site.beams.size() > 20, "supports placed (%d)" % a.site.beams.size())
	for bm in a.site.beams:
		var p: Vector3 = bm["a"]
		runner.check(absf(p.y) < 0.01, "support base on the ground")
		break
	for bm in a.site.beams:
		runner.check(a.spline.ups[int(bm["k"])].y >= 0.55, "no support under inverted or steep track")


# --- Coaster types --------------------------------------------------------------

func test_wing_seats_feel_the_roll() -> void:
	var t := TestTracks.launched(Elements.Kind.HEARTLINE_ROLL, 16.0)
	t.set_type(CoasterTypes.Id.WING)
	var a := TrackAnalyzer.analyze(t)
	var sp := a.spline
	# Find the middle of the roll (largest twist).
	var best := 0
	for k in sp.count:
		if absf(sp.twists[k]) > absf(sp.twists[best]):
			best = k
	var s := best * sp.ds
	var v := absf(a.record.sample_speed[best])
	var centre := sp.g_forces_at(s, v, 0.0)
	runner.near(sp.g_forces_offset(s, v, 0.0, 0.0).x, centre.x, 1e-5, "zero offset matches the heartline")
	var outer := sp.g_forces_offset(s, v, 0.0, 1.6)
	# Centripetal from rolling: (v*tau)^2 * 1.6 m, in g.
	var expected := pow(v * sp.twists[best], 2) * 1.6 / 9.81
	runner.check(expected > 0.3, "roll is fast enough to matter (%.2f g)" % expected)
	runner.check(absf(outer.x - centre.x) + absf(outer.y - centre.y) > expected * 0.5, "wing seat feels extra force (%.2f vs %.2f)" % [outer.x, centre.x])


func test_wooden_cannot_invert_and_rattles() -> void:
	var t := TestTracks.launched(Elements.Kind.LOOP, 22.0, true)
	t.set_type(CoasterTypes.Id.WOODEN)
	var a := TrackAnalyzer.analyze(t)
	var flagged := false
	for p in a.ratings.problems:
		if p["kind"] == "type":
			flagged = true
	runner.check(flagged, "wooden inversion flagged")
	var rattle := false
	for p in a.ratings.intensity_parts:
		if p["label"] == "Wooden rattle":
			rattle = true
	runner.check(rattle, "wooden rattle adds intensity")
	runner.near(t.friction, CoasterTypes.get_type(CoasterTypes.Id.WOODEN)["friction"], 1e-6, "type sets friction")


func test_flying_riders_tolerate_less() -> void:
	runner.check(GLimits.vertical_zone(4.5) == GLimits.Zone.INTENSE, "4.5 g intense when seated")
	runner.check(GLimits.vertical_zone(4.5, 0.82) == GLimits.Zone.DANGER, "4.5 g dangerous when flying")
	runner.check(GLimits.vertical_zone(1.0, 0.82) == GLimits.Zone.SAFE, "1 g always safe")


func test_launch_only_on_launched_type() -> void:
	var t := TestTracks.launched(Elements.Kind.STRAIGHT, 20.0)
	t.set_type(CoasterTypes.Id.STEEL)
	for p in t.points:
		runner.check(p.segment != TrackPoint.Segment.LAUNCH, "steel converts launch to lift")
	runner.check(CoasterTypes.allows_segment(CoasterTypes.Id.LAUNCHED, TrackPoint.Segment.LAUNCH), "launched allows launch")


# --- Cost, contracts, progress --------------------------------------------------

func test_cost_is_sensible() -> void:
	var a := TrackAnalyzer.analyze(DefaultTracks.starter())
	runner.check(a.cost > 800000.0 and a.cost < 3000000.0, "starter costs %s" % CostModel.money(a.cost))
	var w := DefaultTracks.starter()
	w.set_type(CoasterTypes.Id.WOODEN)
	runner.check(TrackAnalyzer.analyze(w).cost < a.cost, "wooden track is cheaper than steel")


func test_contract_evaluation() -> void:
	var d := DefaultTracks.starter()
	d.contract_id = "first_steps"
	var a := TrackAnalyzer.analyze(d)
	var r := ContractEvaluator.evaluate(Contracts.find("first_steps"), d, a)
	runner.check(r["passed"], "starter meets First Steps")
	runner.check(r["stars"] >= 1, "at least one star")
	var tight := Contracts.find("height_limit")
	var r2 := ContractEvaluator.evaluate(tight, d, a)
	runner.check(not r2["passed"], "starter (35 m) fails the 25 m height limit")


func test_zone_violation() -> void:
	var d := DefaultTracks.starter()
	d.contract_id = "into_the_hill"
	var a := TrackAnalyzer.analyze(d)
	runner.check(a.site.zone_violations.is_empty(), "starter misses the path zone")
	var d2 := DefaultTracks.blank()
	# Put a support in the path: move a high point over the zone.
	d2.contract_id = "into_the_hill"
	d2.points[3].position = Vector3(-45, 12, -8)
	var a2 := TrackAnalyzer.analyze(d2)
	runner.check(not a2.site.zone_violations.is_empty(), "support in the path is a violation")


func test_progress_unlocks() -> void:
	var path := "user://test_progress.json"
	if FileAccess.file_exists(path):
		DirAccess.remove_absolute(path)
	var p := ProgressStore.load_or_new(path)
	runner.check(p.is_available(0) and not p.is_available(1), "only the first contract is open")
	runner.check(not p.unlocked_types().has(CoasterTypes.Id.LAUNCHED), "launched starts locked")
	p.record("first_steps", 2)
	runner.check(p.is_available(1), "finishing a contract opens the next")
	var unlocked := p.record("family_woodie", 1)
	runner.check(unlocked == CoasterTypes.Id.LAUNCHED, "Family Woodie unlocks the launched coaster")
	var again := ProgressStore.load_or_new(path)
	runner.check(again.best("first_steps") == 2 and again.total_stars() == 3, "progress is saved")
	p.record("first_steps", 1)
	runner.check(ProgressStore.load_or_new(path).best("first_steps") == 2, "a worse result keeps the best")
	DirAccess.remove_absolute(path)
