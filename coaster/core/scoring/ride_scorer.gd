class_name RideScorer
extends RefCounted
## Turns a RideRecord into Thrill / Intensity / Nausea ratings (0-10 scale).
##
## These are hand-tuned game formulas, not real-world science, but each term
## maps to something riders actually notice:
##   Thrill    - speed, big drops, airtime, inversions, a good length, strong
##               (but not crushing) positive G. Too much intensity kills it.
##   Intensity - how hard the forces are: peak and sustained G, negative G,
##               lateral G, inversions, top speed.
##   Nausea    - lateral sloshing, rapid G changes (jerk), fast rolling,
##               inversions, negative G and length.
## Every term is recorded with its contribution so the results screen can show
## the player *why* they got a score.

const AIRTIME_G := 0.2         # vertical G below this counts as airtime
const EJECTOR_G := -0.5        # below this is "ejector" airtime
const HIGH_G := 3.5
const MIN_PROBLEM_LENGTH := 1.0   # metres; ignore single-sample blips


## `data` and `site` are optional: without them the score covers only the
## ride itself (no coaster-type effects, near misses, tunnels or collisions).
static func score(record: RideRecord, spline: TrackSpline, data: TrackData = null, site: SiteAnalysis = null) -> RideRatings:
	var r := RideRatings.new()
	var ty := data.type_info() if data != null else CoasterTypes.get_type(CoasterTypes.Id.STEEL)
	var rattle: float = ty["rattle"]
	var near := site.near_misses.size() if site != null else 0
	var tunnel_entries := site.tunnel_entries if site != null else 0
	var tunnel_len := site.tunnel_length if site != null else 0.0
	var dt := record.interval
	var n := record.size

	# --- Statistics ----------------------------------------------------------
	var max_speed := 0.0
	var speed_sum := 0.0
	var max_vg := -INF
	var min_vg := INF
	var max_lg := 0.0
	var airtime := 0.0
	var ejector := 0.0
	var high_g_time := 0.0
	var lateral_time := 0.0
	var neg_time := 0.0
	var jerk_sum := 0.0
	var roll_rate_sum := 0.0
	for i in n:
		var vg := record.g_vert[i]
		var lg := absf(record.g_lat[i])
		max_speed = maxf(max_speed, absf(record.speed[i]))
		speed_sum += absf(record.speed[i])
		max_vg = maxf(max_vg, vg)
		min_vg = minf(min_vg, vg)
		max_lg = maxf(max_lg, lg)
		if vg < AIRTIME_G:
			airtime += dt
		if vg < EJECTOR_G:
			ejector += dt
		if vg < 0.0:
			neg_time += dt
		if vg > HIGH_G:
			high_g_time += dt
		if lg > 0.6:
			# Weighted time: 1 s at 1.2 g sideways counts as 2 s at 0.6 g.
			lateral_time += dt * (1.0 + (lg - 0.6) / 0.6)
		if i > 0:
			# Total change in felt force; divided by duration below this is the
			# average jerk (g per second).
			jerk_sum += absf(vg - record.g_vert[i - 1]) + absf(record.g_lat[i] - record.g_lat[i - 1])
			roll_rate_sum += absf(angle_difference(record.roll[i - 1], record.roll[i]))
	var duration := record.duration
	var avg_jerk := jerk_sum / maxf(duration, 1.0)          # g/s averaged over the ride
	var avg_roll_rate := roll_rate_sum / maxf(duration, 1.0)  # rad/s averaged over the ride
	var inversions := spline.inversions
	var max_drop := spline.max_drop()

	r.stats = {
		"length": spline.length,
		"duration": duration,
		"max_speed": max_speed,
		"avg_speed": speed_sum / maxf(float(n), 1.0),
		"max_height": spline.max_height(),
		"max_drop": max_drop,
		"max_g_vert": max_vg if n > 0 else 1.0,
		"min_g_vert": min_vg if n > 0 else 1.0,
		"max_g_lat": max_lg,
		"airtime": airtime,
		"ejector_airtime": ejector,
		"inversions": inversions,
		"high_g_time": high_g_time,
		"avg_jerk": avg_jerk,
		"completed": record.completed,
		"rollbacks": record.rollbacks,
		"near_misses": near,
		"splashes": record.splashes,
		"tunnel_length": tunnel_len,
		"type": ty["name"],
	}
	var avg_speed: float = r.stats["avg_speed"]

	# --- Intensity -----------------------------------------------------------
	_part(r.intensity_parts, "Peak positive G", 2.2 * clampf((max_vg - 1.5) / 3.5, 0.0, 1.3))
	_part(r.intensity_parts, "Sustained high G", minf(2.0, 0.8 * high_g_time))
	_part(r.intensity_parts, "Negative G", 1.6 * clampf(-min_vg / 1.5, 0.0, 1.3))
	_part(r.intensity_parts, "Lateral G", 2.0 * clampf((max_lg - 0.3) / 1.4, 0.0, 1.3))
	_part(r.intensity_parts, "Inversions", minf(2.0, 0.45 * inversions))
	_part(r.intensity_parts, "Top speed", 1.6 * clampf(max_speed / 40.0, 0.0, 1.3))
	# A wooden coaster's rattle shakes riders about more the faster it goes.
	_part(r.intensity_parts, "Wooden rattle", 2.0 * rattle * clampf(avg_speed / 18.0, 0.0, 1.3))
	_part(r.intensity_parts, "Water splash", minf(1.0, 0.5 * record.splashes))
	r.intensity = _total(r.intensity_parts)

	# --- Thrill --------------------------------------------------------------
	_part(r.thrill_parts, "Top speed", 2.0 * clampf(max_speed / 32.0, 0.0, 1.25))
	_part(r.thrill_parts, "Biggest drop", 1.6 * clampf(max_drop / 45.0, 0.0, 1.25))
	_part(r.thrill_parts, "Airtime", minf(2.2, 0.55 * airtime + 0.6 * ejector))
	_part(r.thrill_parts, "Inversions", minf(2.0, 0.6 * inversions))
	_part(r.thrill_parts, "Positive G", 1.0 * clampf((max_vg - 1.5) / 2.0, 0.0, 1.0))
	_part(r.thrill_parts, "Ride length", 1.2 * clampf(duration / 70.0, 0.0, 1.0))
	# Wing seats make every close pass feel closer.
	var near_w := 0.3 * (1.3 if float(ty["seat_offset"]) > 0.0 else 1.0)
	_part(r.thrill_parts, "Near misses", minf(1.8, near_w * near))
	_part(r.thrill_parts, "Splashdowns", minf(1.4, 0.7 * record.splashes))
	_part(r.thrill_parts, "Tunnels", minf(0.75, 0.25 * tunnel_entries))
	_part(r.thrill_parts, "Wooden character", 0.8 * rattle * clampf(r.stats["airtime"] / 3.0, 0.0, 1.0))
	if r.intensity > 7.5:
		_part(r.thrill_parts, "Too intense", -1.2 * (r.intensity - 7.5))
	if not record.completed:
		_part(r.thrill_parts, "Train stalled", -3.0)
	r.thrill = _total(r.thrill_parts)

	# --- Nausea --------------------------------------------------------------
	_part(r.nausea_parts, "Lateral sloshing", minf(3.0, 0.22 * lateral_time))
	_part(r.nausea_parts, "Jerky transitions", minf(2.5, 0.35 * maxf(avg_jerk - 1.0, 0.0)))
	_part(r.nausea_parts, "Fast rolling", minf(2.0, 2.0 * avg_roll_rate))
	_part(r.nausea_parts, "Inversions", minf(2.0, 0.4 * inversions))
	_part(r.nausea_parts, "Negative G", minf(1.5, 0.35 * neg_time))
	_part(r.nausea_parts, "Ride length", minf(1.0, duration / 150.0))
	if record.rollbacks > 0:
		_part(r.nausea_parts, "Rolling backwards", minf(2.0, 0.7 * record.rollbacks))
	_part(r.nausea_parts, "Wooden rattle", 1.5 * rattle * clampf(duration / 90.0, 0.0, 1.0))
	r.nausea = _total(r.nausea_parts)

	r.problems = find_problems(record, spline, float(ty["g_scale"]))
	_site_problems(r.problems, spline, data, site)
	r.problems.sort_custom(func(a, b): return a["severity"] > b["severity"] or (a["severity"] == b["severity"] and a["s"] < b["s"]))
	r.verdict = _verdict(r)
	return r


static func _part(parts: Array[Dictionary], label: String, value: float) -> void:
	if absf(value) >= 0.05:
		parts.append({"label": label, "value": value})


static func _total(parts: Array[Dictionary]) -> float:
	var t := 0.0
	for p in parts:
		t += float(p["value"])
	return clampf(t, 0.0, 10.0)


## Scans the per-sample overlay data for stretches that are intense/dangerous,
## too slow, or where the train stalled. Contiguous samples are merged into one
## problem with its worst value.
static func _site_problems(out: Array[Dictionary], spline: TrackSpline, data: TrackData, site: SiteAnalysis) -> void:
	var D := GLimits.Zone.DANGER
	if data != null and not bool(data.type_info()["inversions"]) and spline.inversions > 0:
		# Find the first upside-down sample to point at.
		for k in spline.count:
			if spline.ups[k].y < -0.3:
				out.append({"s": k * spline.ds, "s_start": k * spline.ds, "s_end": k * spline.ds, "kind": "type",
					"severity": D, "value": 0.0, "message": "%s track can't go upside down. Remove this inversion." % data.type_info()["name"]})
				break
	if site == null:
		return
	for c in site.collisions:
		out.append({"s": c["s"], "s_start": c["s"], "s_end": c["s"], "kind": "collision", "severity": D, "value": c["clearance"],
			"message": "Riders' heads would hit %s here. Move the track or what's in the way." % SiteAnalysis.HIT_NAMES[c["kind"]]})
	for w in site.submerged:
		out.append({"s": w["s"], "s_start": w["s"], "s_end": w["s"], "kind": "water", "severity": D, "value": w["clearance"],
			"message": "The train goes under water here (%.1f m deep). Raise it so only the bottom of the car dips in." % w["clearance"]})
	for z in site.zone_violations:
		out.append({"s": z["s"], "s_start": z["s"], "s_end": z["s"], "kind": "zone", "severity": D, "value": 0.0,
			"message": "The marked area must stay clear: keep supports out of it and track at least 4 m above it."})


static func find_problems(record: RideRecord, spline: TrackSpline, g_scale: float = 1.0) -> Array[Dictionary]:
	var out: Array[Dictionary] = []
	if spline.count == 0:
		return out
	if record.stall_s >= 0.0:
		var msg := "The train runs out of energy here and rolls back. Lower this hill or add speed before it."
		if record.completed:
			msg = "The train rolls back here before recovering. Lower this hill or add speed before it."
		out.append({"s": record.stall_s, "s_start": record.stall_s, "s_end": record.stall_s,
			"kind": "stall", "severity": GLimits.Zone.DANGER, "value": 0.0, "message": msg})
	_scan(out, record, spline, "vertical", g_scale)
	_scan(out, record, spline, "lateral", g_scale)
	out.sort_custom(func(a, b): return a["severity"] > b["severity"] or (a["severity"] == b["severity"] and a["s"] < b["s"]))
	return out


static func _scan(out: Array[Dictionary], record: RideRecord, spline: TrackSpline, axis: String, g_scale: float) -> void:
	var n := spline.count
	var run_start := -1
	var worst := 0.0
	var worst_k := 0
	var zone_max := 0
	for k in n + 1:
		var zone := 0
		var g := 0.0
		if k < n and record.sample_visited[k] == 1:
			g = record.sample_g_vert[k] if axis == "vertical" else record.sample_g_lat[k]
			zone = GLimits.vertical_zone(g, g_scale) if axis == "vertical" else GLimits.lateral_zone(g, g_scale)
		if zone > 0:
			if run_start < 0:
				run_start = k
				worst = g
				worst_k = k
				zone_max = zone
			var further := (absf(g - 1.0) > absf(worst - 1.0)) if axis == "vertical" else (absf(g) > absf(worst))
			if further:
				worst = g
				worst_k = k
			zone_max = maxi(zone_max, zone)
		elif run_start >= 0:
			var s0 := float(run_start) * spline.ds
			var s1 := float(k - 1) * spline.ds
			if s1 - s0 >= MIN_PROBLEM_LENGTH:
				out.append({"s": float(worst_k) * spline.ds, "s_start": s0, "s_end": s1,
					"kind": axis, "severity": zone_max, "value": worst,
					"message": _message(axis, worst, zone_max)})
			run_start = -1


static func _message(axis: String, g: float, zone: int) -> String:
	var how := "dangerous" if zone == GLimits.Zone.DANGER else "intense"
	if axis == "lateral":
		return "%.1f g sideways is %s. Bank this turn more (auto-bank) or widen it." % [absf(g), how]
	if g > 1.0:
		return "%.1f g pushing down is %s. Make this valley or loop wider." % [g, how]
	return "%.1f g lifting out of the seat is %s. Round off this crest." % [g, how]


static func _verdict(r: RideRatings) -> String:
	if not bool(r.stats.get("completed", false)):
		return "The train never made it home. Fix the stall first."
	var red := 0
	for p in r.problems:
		if p["severity"] == GLimits.Zone.DANGER:
			red += 1
	if red > 0:
		return "Riders would be hurt in %d place%s. Fix the red spots." % [red, "" if red == 1 else "s"]
	if r.nausea > 7.0:
		return "Exciting, but a lot of riders will be feeling sick."
	if r.thrill >= 7.0:
		return "A great ride: riders will queue for this."
	if r.thrill >= 4.5:
		return "A solid ride. More airtime or a bigger drop would push it further."
	return "A gentle ride. Add height, speed or airtime for more thrills."
