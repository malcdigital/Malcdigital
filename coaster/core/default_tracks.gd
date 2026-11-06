class_name DefaultTracks
extends RefCounted
## Built-in starter coasters.


## A complete sit-down coaster: station, chain lift, first drop, airtime hill,
## banked 180° turn, vertical loop, a second hill, a wide turn home, brakes.
## The elements come from the same generators the player uses.
static func starter() -> TrackData:
	var t := TrackData.new()
	t.name = "Starter coaster"
	var P := TrackPoint.Segment
	var pts: Array[TrackPoint] = [
		TrackPoint.new(Vector3(0, 1, 0), P.STATION),
		TrackPoint.new(Vector3(0, 1, -24), P.STATION),
		TrackPoint.new(Vector3(0, 1.5, -34), P.LIFT),
		TrackPoint.new(Vector3(0, 32, -76), P.LIFT),
		TrackPoint.new(Vector3(0, 35, -86)),
	]
	_append(pts, Elements.Kind.DROP, 4.5)
	_append(pts, Elements.Kind.HILL, 24.0)
	_append(pts, Elements.Kind.STRAIGHT, 23.0)
	_append(pts, Elements.Kind.UTURN_RIGHT, 22.0)
	_append(pts, Elements.Kind.LOOP, 21.0)
	_append(pts, Elements.Kind.HILL, 18.0)

	# Wide right-hand 180° turn that lands the track on the station line
	# (x = 0, heading -Z) with room for a brake run before the platform.
	var here := pts[pts.size() - 1].position
	var probe := Elements.turn(Vector3.ZERO, Vector3.BACK, 1.0, 30.0, PI, 0.0)
	var probe_end := probe[probe.size() - 1].position
	var radius := 30.0 * here.x / -probe_end.x
	var reach: float = Elements.turn(Vector3(0, here.y, 0), Vector3.BACK, 1.0, radius, PI, 0.0).back().position.z
	var turn_start := Vector3(here.x, here.y, 52.0 - reach)
	if turn_start.z > here.z + 10.0:
		pts.append(TrackPoint.new(Vector3(here.x, here.y, lerpf(here.z, turn_start.z, 0.5))))
		pts.append(TrackPoint.new(turn_start))
	var home := Elements.turn(turn_start, Vector3.BACK, 1.0, radius, PI, 0.0)
	for i in home.size() - 1:
		home[i].minor = true
	pts.append_array(home)
	pts.append_array([
		TrackPoint.new(Vector3(0, here.y, 40), P.BRAKE),
		TrackPoint.new(Vector3(0, lerpf(here.y, 1.0, 0.5), 24), P.BRAKE),
		TrackPoint.new(Vector3(0, 1.0, 10), P.STATION),
	] as Array[TrackPoint])
	t.points = pts
	return t


static func _append(pts: Array[TrackPoint], kind: int, speed: float) -> void:
	var a := pts[pts.size() - 2].position
	var b := pts[pts.size() - 1].position
	pts.append_array(Elements.build(kind, b, b - a, speed))


## A small flat oval: the minimum to start designing from scratch.
static func blank() -> TrackData:
	var t := TrackData.new()
	t.name = "New coaster"
	var P := TrackPoint.Segment
	var pts: Array[TrackPoint] = [
		TrackPoint.new(Vector3(0, 1, 0), P.STATION),
		TrackPoint.new(Vector3(0, 1, -24), P.STATION),
		TrackPoint.new(Vector3(0, 1.5, -34), P.LIFT),
		TrackPoint.new(Vector3(0, 12, -56)),
		TrackPoint.new(Vector3(0, 12, -64)),
	]
	pts.append_array(Elements.turn(Vector3(0, 12, -64), Vector3.FORWARD, 1.0, 14.0, PI, 10.0))
	var e := pts[pts.size() - 1].position
	pts.append(TrackPoint.new(Vector3(e.x, 2.0, -30)))
	pts.append(TrackPoint.new(Vector3(e.x, 1.0, 0), P.BRAKE))
	pts.append_array(Elements.turn(Vector3(e.x, 1.0, 0), Vector3.BACK, 1.0, e.x * 0.5 - 0.5, PI, 0.0))
	for i in range(pts.size() - 8, pts.size()):
		pts[i].segment = P.STATION if i >= pts.size() - 2 else P.BRAKE
	pts.pop_back()
	t.points = pts
	return t
