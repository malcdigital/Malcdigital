extends RefCounted
var runner


func test_starter_coaster_scores_sensibly() -> void:
	var r := TrackAnalyzer.analyze(DefaultTracks.starter()).ratings
	runner.check(r.thrill > 5.0 and r.thrill <= 10.0, "thrill in range (%.1f)" % r.thrill)
	runner.check(r.intensity > 1.0 and r.intensity < 7.0, "intensity in range (%.1f)" % r.intensity)
	runner.check(r.nausea < 5.0, "nausea low (%.1f)" % r.nausea)
	for p in r.problems:
		runner.check(p["severity"] != GLimits.Zone.DANGER, "no red problems on the starter (%s)" % p["message"])


func test_airtime_hill_adds_airtime() -> void:
	var hill := TrackAnalyzer.analyze(TestTracks.launched(Elements.Kind.HILL, 22.0)).ratings
	var flat := TrackAnalyzer.analyze(TestTracks.launched(Elements.Kind.STRAIGHT, 22.0)).ratings
	runner.check(hill.stats["airtime"] > 0.8, "hill gives airtime (%.2f s)" % hill.stats["airtime"])
	runner.check(hill.thrill > flat.thrill, "airtime raises thrill")


func test_tight_valley_is_flagged() -> void:
	# A sharp V-shaped valley at speed should produce a red vertical-G problem.
	var t := TestTracks.launched(Elements.Kind.STRAIGHT, 25.0)
	var e := t.points[3].position
	t.points.insert(4, TrackPoint.new(e + Vector3(0, 10, -15)))
	t.points.insert(5, TrackPoint.new(e + Vector3(0, 1, -20)))
	t.points.insert(6, TrackPoint.new(e + Vector3(0, 10, -25)))
	var r := TrackAnalyzer.analyze(t).ratings
	var found := false
	for p in r.problems:
		if p["kind"] == "vertical" and p["severity"] == GLimits.Zone.DANGER:
			found = true
	runner.check(found, "dangerous vertical G found")


func test_inversions_raise_intensity() -> void:
	var loop := TrackAnalyzer.analyze(TestTracks.launched(Elements.Kind.LOOP, 22.0)).ratings
	var flat := TrackAnalyzer.analyze(TestTracks.launched(Elements.Kind.STRAIGHT, 22.0)).ratings
	runner.check(loop.intensity > flat.intensity, "loop more intense than straight")
	runner.check(loop.stats["inversions"] == 1, "one inversion")


func test_g_zones() -> void:
	runner.check(GLimits.vertical_zone(1.0) == GLimits.Zone.SAFE, "1 g safe")
	runner.check(GLimits.vertical_zone(4.2) == GLimits.Zone.INTENSE, "4.2 g intense")
	runner.check(GLimits.vertical_zone(6.0) == GLimits.Zone.DANGER, "6 g dangerous")
	runner.check(GLimits.vertical_zone(-2.0) == GLimits.Zone.DANGER, "-2 g dangerous")
	runner.check(GLimits.lateral_zone(1.0) == GLimits.Zone.INTENSE, "1 g lateral intense")
