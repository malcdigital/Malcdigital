extends SceneTree
## Prints an analysis of the starter coaster: handy while tuning.
func _initialize() -> void:
	var t0 := Time.get_ticks_usec()
	var a := TrackAnalyzer.analyze(DefaultTracks.starter())
	print("analyze ms: ", (Time.get_ticks_usec() - t0) / 1000.0)
	print("length %.1f samples %d inversions %d" % [a.spline.length, a.spline.count, a.spline.inversions])
	print("completed ", a.record.completed, " stalled ", a.record.stalled, " stall_s ", a.record.stall_s, " dur ", a.record.duration)
	for k in range(0, a.spline.count, 16):
		var p := a.spline.positions[k]
		print("s=%6.1f pos=(%6.1f %5.1f %7.1f) v=%5.1f vg=%5.2f lg=%5.2f roll=%5.0f seg=%d" % [k * a.spline.ds, p.x, p.y, p.z, a.record.sample_speed[k], a.record.sample_g_vert[k], a.record.sample_g_lat[k], rad_to_deg(a.spline.rolls[k]), a.spline.segments[k]])
	var r := a.ratings
	print("thrill %.1f intensity %.1f nausea %.1f  %s" % [r.thrill, r.intensity, r.nausea, r.verdict])
	print(r.stats)
	for p in r.problems:
		print(p)
	quit()
