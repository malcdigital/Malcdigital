extends RefCounted
var runner


func test_circle_length_matches_geometry() -> void:
	# 16 points on a radius-20 circle: Catmull-Rom length should be ~2πr.
	var t := TrackData.new()
	for i in 16:
		var a := TAU * i / 16.0
		t.points.append(TrackPoint.new(Vector3(cos(a) * 20.0, 5.0, sin(a) * 20.0)))
	var sp := TrackSpline.new()
	runner.check(sp.bake(t), "bake succeeds")
	runner.near(sp.length, TAU * 20.0, 0.5, "circumference")
	# Curvature magnitude 1/r everywhere.
	var k := sp.curvatures[sp.count / 3].length()
	runner.near(k, 1.0 / 20.0, 0.003, "curvature = 1/radius")


func test_samples_are_evenly_spaced() -> void:
	var sp := TrackSpline.new()
	sp.bake(DefaultTracks.starter())
	var worst := 0.0
	for k in range(1, sp.count):
		worst = maxf(worst, absf(sp.positions[k].distance_to(sp.positions[k - 1]) - sp.ds))
	runner.check(worst < 0.05, "uniform arc-length spacing (worst error %.3f m)" % worst)


func test_frames_are_orthonormal() -> void:
	var a := TrackAnalyzer.analyze(DefaultTracks.starter())
	var sp := a.spline
	var worst := 0.0
	for k in sp.count:
		worst = maxf(worst, absf(sp.tangents[k].dot(sp.ups[k])))
		worst = maxf(worst, absf(sp.ups[k].length() - 1.0))
		worst = maxf(worst, absf(sp.rights[k].dot(sp.tangents[k])))
	runner.check(worst < 0.02, "T, up, right orthonormal (worst %.4f)" % worst)


func test_loop_counts_one_inversion_and_flat_track_none() -> void:
	var loop := TrackAnalyzer.analyze(TestTracks.launched(Elements.Kind.LOOP, 22.0))
	runner.check(loop.spline.inversions == 1, "loop = 1 inversion (got %d)" % loop.spline.inversions)
	var oval := TrackAnalyzer.analyze(TestTracks.flat_oval())
	runner.check(oval.spline.inversions == 0, "flat oval = 0 inversions")


func test_top_of_loop_is_upside_down() -> void:
	var a := TrackAnalyzer.analyze(TestTracks.launched(Elements.Kind.LOOP, 22.0))
	var sp := a.spline
	var top_k := 0
	for k in sp.count:
		if sp.positions[k].y > sp.positions[top_k].y:
			top_k = k
	runner.check(sp.ups[top_k].y < -0.9, "up points down at top of loop (y=%.2f)" % sp.ups[top_k].y)


func test_auto_bank_cancels_lateral_g_in_turns() -> void:
	var t := TestTracks.flat_oval(1.0, 25.0, 60.0)
	t.station_speed = 1.5
	# Give the train some speed with a launch on the back straight.
	t.points[2].segment = TrackPoint.Segment.LAUNCH
	t.launch_speed = 18.0
	var a := TrackAnalyzer.analyze(t)
	var max_lat := 0.0
	for k in a.spline.count:
		if a.record.sample_visited[k] == 1 and absf(a.record.sample_speed[k]) > 10.0:
			max_lat = maxf(max_lat, absf(a.record.sample_g_lat[k]))
	runner.check(max_lat < 0.35, "auto-banked turns keep lateral G low (got %.2f)" % max_lat)


func test_auto_bezier_matches_centripetal_catmull_rom() -> void:
	var rng := RandomNumberGenerator.new()
	rng.seed = 7
	var pts: Array[TrackPoint] = []
	for i in 6:
		pts.append(TrackPoint.new(Vector3(rng.randf_range(-30, 30), rng.randf_range(0, 20), rng.randf_range(-30, 30))))
	var worst := 0.0
	for i in 6:
		var p0 := pts[(i - 1 + 6) % 6].position
		var p1 := pts[i].position
		var p2 := pts[(i + 1) % 6].position
		var p3 := pts[(i + 2) % 6].position
		var kn := TrackSpline._centripetal_knots(p0, p1, p2, p3)
		var c := TrackSpline.segment_controls(pts, i, true)
		for k in 11:
			var t := k / 10.0
			worst = maxf(worst, TrackSpline._catmull_rom(p0, p1, p2, p3, kn, t).distance_to(TrackSpline.bezier(c, t)))
	runner.check(worst < 0.01, "auto handles reproduce Catmull-Rom exactly (worst %.4f m)" % worst)


func test_manual_handles_shape_the_curve() -> void:
	var t := TestTracks.launched(Elements.Kind.STRAIGHT, 15.0)
	var auto_sp := TrackSpline.new()
	auto_sp.bake(t)
	var i := 4
	var h := TrackSpline.current_handles(t.points, i, true)
	runner.check(h[0].normalized().dot(h[1].normalized()) < -0.99, "auto handles are opposite (smooth)")
	t.points[i].handle_mode = TrackPoint.Handle.SMOOTH
	t.points[i].handle_in = h[0]
	t.points[i].handle_out = h[1]
	var same := TrackSpline.new()
	same.bake(t)
	runner.near(same.length, auto_sp.length, 0.05, "copying the auto handles keeps the shape")
	t.points[i].handle_out = h[1] + Vector3(15, 0, 0)
	var bent := TrackSpline.new()
	bent.bake(t)
	runner.check(absf(bent.length - auto_sp.length) > 0.5, "dragging a handle bends the track")
	var back := TrackPoint.from_dict(JSON.parse_string(JSON.stringify(t.points[i].to_dict())))
	runner.check(back.handle_mode == TrackPoint.Handle.SMOOTH and back.handle_out.distance_to(t.points[i].handle_out) < 0.01, "handles saved")


func test_bezier_turn_uses_few_points() -> void:
	var pts := Elements.build(Elements.Kind.TURN_LEFT, Vector3(0, 1, 0), Vector3.FORWARD, 18.0)
	runner.check(pts.size() <= 4, "90° turn is a handful of points (%d)" % pts.size())
	runner.check(pts[0].handle_mode == TrackPoint.Handle.SMOOTH, "turn points have curve handles")
	var a := TrackAnalyzer.analyze(TestTracks.launched(Elements.Kind.UTURN_RIGHT, 20.0))
	runner.check(a.record.completed, "track with a Bezier U-turn completes")
