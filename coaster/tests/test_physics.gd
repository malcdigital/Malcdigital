extends RefCounted
var runner


func _sim(t: TrackData, banked: bool = true) -> TrainSim:
	var sp := TrackSpline.new()
	sp.bake(t)
	var sim := TrainSim.new()
	sim.setup(sp, t, true)
	if banked:
		var rec := sim.run_to_end()
		sp.apply_banking(t, rec.sample_speed)
		sim.setup(sp, t, true)
	return sim


func test_frictionless_drop_conserves_energy() -> void:
	# A single car rolling down a drop with no friction or drag: ½v² + g·y is
	# constant (to integration error) everywhere away from the ride systems.
	var t := TestTracks.launched(Elements.Kind.HILL, 20.0)
	t.num_cars = 1
	var sim := _sim(t, false)
	var e0 := -1.0
	var worst := 0.0
	while not sim.finished and sim.time < 60.0:
		sim.step()
		var seg := sim.spline.segment_at(sim.s)
		if seg != TrackPoint.Segment.NORMAL:
			e0 = -1.0
			continue
		if e0 < 0.0:
			e0 = sim.energy()
		worst = maxf(worst, absf(sim.energy() - e0) / e0)
	runner.check(worst < 0.01, "energy drift < 1%% (got %.3f%%)" % (worst * 100.0))


func test_drop_speed_matches_free_fall() -> void:
	# v at the bottom of a frictionless drop of height h is sqrt(v0² + 2gh).
	var t := TrackData.new()
	t.friction = 0.0
	t.drag = 0.0
	t.num_cars = 1
	var P := TrackPoint.Segment
	t.points = [
		TrackPoint.new(Vector3(0, 41, 0), P.STATION), TrackPoint.new(Vector3(0, 41, -20), P.STATION),
		TrackPoint.new(Vector3(0, 41, -30)),
	] as Array[TrackPoint]
	t.points.append_array(Elements.build(Elements.Kind.DROP, Vector3(0, 41, -30), Vector3.FORWARD, 1.5))
	var e: Vector3 = t.points.back().position
	t.points.append(TrackPoint.new(e + Vector3(0, 0, -50)))
	t.points.append(TrackPoint.new(e + Vector3(30, 0, -80), P.BRAKE))
	t.points.append(TrackPoint.new(Vector3(30, 41, 30), P.LIFT))
	var sim := _sim(t, false)
	var h0 := 41.0
	var bottom_v := 0.0
	while not sim.finished and sim.time < 30.0:
		sim.step()
		if sim.spline.position_at(sim.s).y < 2.0:
			bottom_v = maxf(bottom_v, sim.v)
	var expected := sqrt(t.station_speed * t.station_speed + 2.0 * 9.81 * (h0 - 1.5))
	runner.near(bottom_v, expected, expected * 0.02, "speed at bottom")


func test_friction_and_drag_slow_the_train() -> void:
	var t := TestTracks.launched(Elements.Kind.STRAIGHT, 25.0, true)
	var sp := TrackSpline.new()
	sp.bake(t)
	var sim := TrainSim.new()
	sim.setup(sp, t, false)
	var peak := 0.0
	var after := 0.0
	while not sim.finished and sim.time < 40.0:
		sim.step()
		if sim.spline.segment_at(sim.car_s(t.num_cars - 1)) == TrackPoint.Segment.NORMAL and sim.spline.segment_at(sim.s) == TrackPoint.Segment.NORMAL:
			peak = maxf(peak, sim.v)
			after = sim.v
	runner.check(peak > 20.0, "launch reached speed (%.1f)" % peak)
	runner.check(after < peak - 0.3, "train decelerates on the flat (%.2f -> %.2f)" % [peak, after])


func test_launch_reaches_target_speed() -> void:
	var t := TestTracks.launched(Elements.Kind.STRAIGHT, 30.0)
	var sim := _sim(t, false)
	var peak := 0.0
	while not sim.finished and sim.time < 30.0:
		sim.step()
		peak = maxf(peak, sim.v)
	runner.near(peak, 30.0, 0.6, "launch speed")


func test_chain_lift_carries_train_to_the_top() -> void:
	var a := TrackAnalyzer.analyze(DefaultTracks.starter())
	runner.check(a.record.completed, "starter coaster completes its lap")
	runner.check(a.record.rollbacks == 0, "no rollbacks on the starter coaster")
	# On the lift, speed is held at lift speed.
	var sp := a.spline
	var k := sp.index_at(sp.point_s[3] - 5.0)
	runner.near(a.record.sample_speed[k], 4.5, 0.2, "chain speed on the lift")


func test_too_tall_hill_stalls_and_rolls_back() -> void:
	# A launch to 15 m/s cannot clear a 30 m hill (needs ~24 m/s).
	var t := TestTracks.launched(Elements.Kind.STRAIGHT, 15.0, true)
	var e := t.points[3].position
	t.points.insert(4, TrackPoint.new(e + Vector3(0, 15, -25)))
	t.points.insert(5, TrackPoint.new(e + Vector3(0, 30, -45)))
	t.points.insert(6, TrackPoint.new(e + Vector3(0, 15, -65)))
	var a := TrackAnalyzer.analyze(t)
	runner.check(not a.record.completed, "train does not complete")
	runner.check(a.record.rollbacks >= 1, "train rolls back")
	runner.check(a.record.stall_s > 0.0, "stall position recorded")
	var stall_problem := false
	for p in a.ratings.problems:
		if p["kind"] == "stall":
			stall_problem = true
	runner.check(stall_problem, "stall is reported as a problem spot")


func test_g_force_at_bottom_of_loop() -> void:
	# At the bottom of a loop: vertical G = 1 + v²/(g·r). Our loop designer
	# targets ~3.4 g there, which must also be what the sim measures.
	var a := TrackAnalyzer.analyze(TestTracks.launched(Elements.Kind.LOOP, 22.0))
	runner.check(a.ratings.stats["max_g_vert"] > 2.8 and a.ratings.stats["max_g_vert"] < 3.8,
		"loop peak G in designed range (got %.2f)" % a.ratings.stats["max_g_vert"])


func test_step_is_deterministic() -> void:
	var a := TrackAnalyzer.analyze(DefaultTracks.starter())
	var b := TrackAnalyzer.analyze(DefaultTracks.starter())
	runner.near(a.record.duration, b.record.duration, 1e-9, "same input, same ride")
