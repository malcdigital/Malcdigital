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
