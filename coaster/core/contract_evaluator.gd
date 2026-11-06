class_name ContractEvaluator
extends RefCounted
## Checks a coaster against a contract. Returns
##   {"goals": [{"text", "ok", "bonus", "detail"}], "passed": bool, "stars": int}
## Budget is always an implicit required goal.


static func evaluate(contract: Dictionary, data: TrackData, a: TrackAnalyzer) -> Dictionary:
	var out: Array[Dictionary] = []
	var goals: Array = contract.get("goals", []).duplicate()
	goals.insert(1, {"kind": "budget"})
	var passed := true
	var bonus_met := 0
	for g in goals:
		var r := _check(g, contract, data, a)
		var bonus: bool = g.get("bonus", false)
		out.append({"text": Contracts.goal_text(g), "ok": r[0], "bonus": bonus, "detail": r[1]})
		if bonus:
			if r[0]:
				bonus_met += 1
		elif not r[0]:
			passed = false
	var stars := 0
	if passed:
		stars = 1 + bonus_met
	return {"goals": out, "passed": passed, "stars": mini(stars, 3)}


## Returns [ok: bool, detail: String]
static func _check(g: Dictionary, contract: Dictionary, data: TrackData, a: TrackAnalyzer) -> Array:
	if a == null or not a.valid:
		return [false, "no track"]
	var st := a.ratings.stats
	var v: float = g.get("value", 0.0)
	var budget: float = contract.get("budget", INF)
	match g["kind"]:
		"complete":
			return [a.record.completed, "stalls" if not a.record.completed else "yes"]
		"budget":
			return [a.cost <= budget, "%s of %s" % [CostModel.money(a.cost), CostModel.money(budget)]]
		"max_cost_frac":
			return [a.cost <= budget * v, CostModel.money(a.cost)]
		"max_height":
			# Height above the ground under the track, as a planner measures it.
			var h := a.max_height_above_ground
			return [h <= v + 0.05, "%.1f m" % h]
		"min_thrill":
			return [a.ratings.thrill >= v, "%.1f" % a.ratings.thrill]
		"max_intensity":
			return [a.ratings.intensity <= v, "%.1f" % a.ratings.intensity]
		"max_nausea":
			return [a.ratings.nausea <= v, "%.1f" % a.ratings.nausea]
		"min_speed_kmh":
			var kmh: float = st["max_speed"] * 3.6
			return [kmh >= v, "%.0f km/h" % kmh]
		"min_inversions":
			return [st["inversions"] >= int(v), str(st["inversions"])]
		"min_splashes":
			return [st["splashes"] >= int(v), str(st["splashes"])]
		"min_tunnel_m":
			return [st["tunnel_length"] >= v, "%.0f m" % st["tunnel_length"]]
		"min_near_misses":
			return [st["near_misses"] >= int(v), str(st["near_misses"])]
		"no_lift":
			var lift := false
			for p in data.points:
				if p.segment == TrackPoint.Segment.LIFT:
					lift = true
			return [not lift, "has a lift" if lift else "yes"]
		"needs_launch":
			var launch := false
			for p in data.points:
				if p.segment == TrackPoint.Segment.LAUNCH:
					launch = true
			return [launch, "yes" if launch else "no launch"]
		"zones_clear":
			var n := a.site.zone_violations.size()
			return [n == 0, "clear" if n == 0 else "%d problem%s" % [n, "" if n == 1 else "s"]]
		"no_red":
			var reds := 0
			for p in a.ratings.problems:
				if p["severity"] == GLimits.Zone.DANGER:
					reds += 1
			return [reds == 0, "none" if reds == 0 else str(reds)]
	return [false, "?"]
