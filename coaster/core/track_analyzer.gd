class_name TrackAnalyzer
extends RefCounted
## Result of analysing a track: the baked spline (with banking), the simulated
## ride and its ratings. See AnalysisJob for how it is computed.

var spline: TrackSpline
var record: RideRecord
var ratings: RideRatings
var site: SiteAnalysis
var cost := 0.0
var cost_parts: Array[Dictionary] = []
var max_height_above_ground := 0.0
var valid := false


## Analyse in one go (tests, tools, worker threads).
static func analyze(data: TrackData) -> TrackAnalyzer:
	var job := AnalysisJob.new(data, 0, false)
	job.run(1 << 62)
	return job.result
