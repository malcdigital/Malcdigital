class_name TrackPoint
extends RefCounted
## One control point of the track spline. Pure data: no rendering, no nodes.
##
## The `segment` field describes the stretch of track that STARTS at this point
## and runs to the next point (the last point's segment runs back to point 0,
## because tracks are closed circuits).

enum Segment { NORMAL, LIFT, LAUNCH, BRAKE, STATION }

const SEGMENT_NAMES := ["Normal", "Chain lift", "Launch", "Brakes", "Station"]

var position := Vector3.ZERO
## Manual roll in degrees, used where auto_bank is off. Values beyond ±180 are
## allowed so that e.g. 0 -> 360 between two points makes a full heartline roll.
var bank_deg := 0.0
## When true the game picks the roll that cancels lateral G (see TrackSpline).
var auto_bank := true
var segment: int = Segment.NORMAL
## Interior point of a generated element. Shown as a small dot in the editor so
## an element reads as one piece; it can still be dragged.
var minor := false


func _init(p: Vector3 = Vector3.ZERO, seg: int = Segment.NORMAL, bank: float = 0.0, auto: bool = true) -> void:
	position = p
	segment = seg
	bank_deg = bank
	auto_bank = auto


func copy() -> TrackPoint:
	var p := TrackPoint.new(position, segment, bank_deg, auto_bank)
	p.minor = minor
	return p


func to_dict() -> Dictionary:
	var d := {
		"p": [snappedf(position.x, 0.001), snappedf(position.y, 0.001), snappedf(position.z, 0.001)],
		"b": snappedf(bank_deg, 0.01),
		"a": auto_bank,
		"s": segment,
	}
	if minor:
		d["m"] = true
	return d


static func from_dict(d: Dictionary) -> TrackPoint:
	var p: Array = d.get("p", [0, 0, 0])
	var tp := TrackPoint.new(
		Vector3(float(p[0]), float(p[1]), float(p[2])),
		clampi(int(d.get("s", Segment.NORMAL)), 0, Segment.STATION),
		float(d.get("b", 0.0)),
		bool(d.get("a", true)))
	tp.minor = bool(d.get("m", false))
	return tp
