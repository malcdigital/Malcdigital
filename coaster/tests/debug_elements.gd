extends SceneTree
## Launches a train into each element at a range of speeds and prints peak G.
func _initialize() -> void:
	for kind in [Elements.Kind.HILL, Elements.Kind.LOOP]:
		for v in [8.0, 12.0, 18.0, 24.0, 30.0]:
			_try(kind, v, 1.0)
	for h in [20.0, 35.0, 60.0]:
		_try(Elements.Kind.DROP, 4.5, h)
	quit()

func _try(kind: int, v: float, h: float) -> void:
	var t := TrackData.new()
	t.friction = 0.0
	t.drag = 0.0
	t.num_cars = 1
	t.launch_speed = v
	t.launch_accel = 30.0
	var P := TrackPoint.Segment
	t.points = [TrackPoint.new(Vector3(0, h, 0), P.STATION), TrackPoint.new(Vector3(0, h, -10), P.LAUNCH), TrackPoint.new(Vector3(0, h, -40))] as Array[TrackPoint]
	if kind == Elements.Kind.DROP:
		t.points[1].segment = P.LAUNCH
	var els := Elements.build(kind, Vector3(0, h, -40), Vector3.FORWARD, v)
	t.points.append_array(els)
	var last := t.points[t.points.size() - 1].position
	# Far-away return so the closing segment does not matter.
	t.points.append(TrackPoint.new(last + Vector3(0, 0, -60)))
	t.points.append(TrackPoint.new(Vector3(200, last.y, last.z - 60), P.BRAKE))
	t.points.append(TrackPoint.new(Vector3(200, h, 60), P.BRAKE))
	t.points.append(TrackPoint.new(Vector3(0, h, 30), P.STATION))
	var a := TrackAnalyzer.analyze(t)
	var mx := -INF
	var mn := INF
	var ml := 0.0
	var top := -INF
	var s0 := a.spline.point_s[3]
	var s1 := a.spline.point_s[3 + els.size() - 2]
	for k in a.spline.count:
		var s := k * a.spline.ds
		if s < s0 or s > s1: continue
		mx = maxf(mx, a.record.sample_g_vert[k]); mn = minf(mn, a.record.sample_g_vert[k]); ml = maxf(ml, absf(a.record.sample_g_lat[k]))
		top = maxf(top, a.spline.positions[k].y)
	print("%s v=%.0f h=%.0f pts=%d  maxG %.2f minG %.2f lat %.2f  top %.1f inv %d" % [Elements.NAMES[kind], v, h, els.size(), mx, mn, ml, top, a.spline.inversions])
