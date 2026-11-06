class_name RideRatings
extends RefCounted
## Output of RideScorer: the three headline ratings, where each came from, the
## raw ride statistics, and a list of problem spots on the track.

var thrill := 0.0
var intensity := 0.0
var nausea := 0.0

## Each entry: {"label": String, "value": float} - contribution to the rating.
var thrill_parts: Array[Dictionary] = []
var intensity_parts: Array[Dictionary] = []
var nausea_parts: Array[Dictionary] = []

## Raw statistics (see RideScorer for definitions).
var stats := {}

## Each entry: {"s": float, "s_start": float, "s_end": float, "kind": String,
##              "severity": int (GLimits.Zone), "value": float, "message": String}
var problems: Array[Dictionary] = []

var verdict := ""


static func label_for(value: float) -> String:
	if value < 2.0: return "Very low"
	if value < 4.0: return "Low"
	if value < 6.0: return "Medium"
	if value < 8.0: return "High"
	return "Very high"
