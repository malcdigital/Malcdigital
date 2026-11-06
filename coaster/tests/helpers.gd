class_name TestTracks
extends RefCounted
## Small purpose-built tracks for tests.

const P := TrackPoint.Segment


## A flat oval with a station, at height y. No hills: good for friction tests.
static func flat_oval(y: float = 1.0, radius: float = 30.0, straight: float = 60.0) -> TrackData:
	var t := TrackData.new()
	var pts: Array[TrackPoint] = []
	pts.append(TrackPoint.new(Vector3(0, y, 0), P.STATION))
	pts.append(TrackPoint.new(Vector3(0, y, -straight * 0.5), P.STATION))
	pts.append(TrackPoint.new(Vector3(0, y, -straight)))
	pts.append_array(Elements.turn(Vector3(0, y, -straight), Vector3.FORWARD, 1.0, radius, PI, 0.0))
	var e: Vector3 = pts.back().position
	pts.append(TrackPoint.new(Vector3(e.x, y, -straight * 0.5)))
	pts.append(TrackPoint.new(Vector3(e.x, y, 0)))
	pts.append_array(Elements.turn(Vector3(e.x, y, 0), Vector3.BACK, 1.0, radius, PI, 0.0))
	pts.pop_back()
	t.points = pts
	return t


## Station, a launch, then the given element, then a long flat return.
static func launched(kind: int, speed: float, friction: bool = false, ctx: Dictionary = {}) -> TrackData:
	var t := TrackData.new()
	if not friction:
		t.friction = 0.0
		t.drag = 0.0
	t.launch_speed = speed
	t.launch_accel = 15.0
	var pts: Array[TrackPoint] = [
		TrackPoint.new(Vector3(0, 1, 0), P.STATION),
		TrackPoint.new(Vector3(0, 1, -15), P.STATION),
		TrackPoint.new(Vector3(0, 1, -20), P.LAUNCH),
		TrackPoint.new(Vector3(0, 1, -90)),
	]
	pts.append_array(Elements.build(kind, Vector3(0, 1, -90), Vector3.FORWARD, speed, ctx))
	var e: Vector3 = pts.back().position
	pts.append(TrackPoint.new(e + Vector3(0, 0, -40)))
	pts.append(TrackPoint.new(Vector3(e.x, 1, e.z - 60), P.BRAKE))
	pts.append_array(Elements.turn(Vector3(e.x, 1, e.z - 60), Vector3.FORWARD, -1.0, 40.0, PI, 0.0))
	var r: Vector3 = pts.back().position
	for p in pts.slice(pts.size() - 12):
		p.segment = P.BRAKE
	pts.append(TrackPoint.new(Vector3(r.x, 1, 30), P.BRAKE))
	pts.append_array(Elements.turn(Vector3(r.x, 1, 30), Vector3.BACK, -1.0, r.x * 0.5, PI, 0.0))
	for p in pts.slice(pts.size() - 6):
		p.segment = P.STATION
	t.points = pts
	return t


## Flat terrain with a lake dug along the launched test track (z -95..-165).
static func lake_terrain() -> TerrainData:
	var t := TerrainData.new()
	t.water_level = -1.2
	for z in range(-95, -170, -4):
		for i in 3:
			t.sculpt(Vector3(0, 0, z), 14.0, 2.0, TerrainData.Brush.LOWER)
	t.base = t.heights.duplicate()
	return t
