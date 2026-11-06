class_name TrackAnalyzer
extends RefCounted
## One call that does everything the editor needs after an edit:
##   bake spline -> simulate (for speeds) -> apply auto-banking ->
##   simulate again (for G-forces on the banked track) -> score.
## Banking does not change speed (it only rotates which way the force points,
## not how big it is), so the first simulation's speeds are exact for the second.

var spline: TrackSpline
var record: RideRecord
var ratings: RideRatings
var valid := false


static func analyze(data: TrackData) -> TrackAnalyzer:
	var a := TrackAnalyzer.new()
	a.spline = TrackSpline.new()
	if not data.is_valid() or not a.spline.bake(data):
		return a
	var sim := TrainSim.new()
	sim.setup(a.spline, data, true, TrainSim.PREVIEW_DT)
	var first := sim.run_to_end()
	a.spline.apply_banking(data, first.sample_speed)
	sim.setup(a.spline, data, true, TrainSim.PREVIEW_DT)
	a.record = sim.run_to_end()
	a.ratings = RideScorer.score(a.record, a.spline)
	a.valid = true
	return a
