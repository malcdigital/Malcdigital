class_name TrackTools
extends RefCounted
## Editing operations on TrackData that are independent of any UI.


## Laplacian smoothing: pull each point towards the average of its neighbours.
## Station points are pinned so the platform stays straight and level.
static func smooth(data: TrackData, strength: float = 0.5, only_index: int = -1) -> void:
	var n := data.points.size()
	if n < 3:
		return
	var src: Array[Vector3] = []
	for p in data.points:
		src.append(p.position)
	for i in n:
		if only_index >= 0 and absi(i - only_index) > 1 and absi(i - only_index) != n - 1:
			continue
		var p := data.points[i]
		if p.segment == TrackPoint.Segment.STATION or data.points[(i - 1 + n) % n].segment == TrackPoint.Segment.STATION:
			continue
		var avg := (src[(i - 1 + n) % n] + src[(i + 1) % n]) * 0.5
		var target := src[i].lerp(avg, strength)
		target.y = maxf(target.y, Elements.MIN_HEIGHT)
		p.position = target


static func insert_points(data: TrackData, after_index: int, pts: Array[TrackPoint]) -> void:
	var at := after_index + 1
	for p in pts:
		data.points.insert(at, p)
		at += 1


## A new point a little way along the track from `index`.
static func add_point_after(data: TrackData, index: int, spline: TrackSpline) -> void:
	var n := data.points.size()
	var a := data.points[index]
	var b := data.points[(index + 1) % n]
	var p := TrackPoint.new((a.position + b.position) * 0.5, a.segment, (a.bank_deg + b.bank_deg) * 0.5, a.auto_bank)
	if spline != null and spline.count > 0 and index < spline.point_s.size():
		var s0 := spline.point_s[index]
		var s1 := spline.point_s[(index + 1) % n] if index + 1 < n else spline.length
		p.position = spline.position_at((s0 + s1) * 0.5)
	data.points.insert(index + 1, p)


static func remove_point(data: TrackData, index: int) -> bool:
	var min_points := 2 if data.open else 4
	if data.points.size() <= min_points or index < 0 or index >= data.points.size():
		return false
	data.points.remove_at(index)
	return true


## Horizontal heading of the track at control point `index`.
static func heading_at(spline: TrackSpline, index: int) -> Vector3:
	if spline == null or spline.count == 0 or index >= spline.point_s.size():
		return Vector3.FORWARD
	var t := spline.tangent_at(spline.point_s[index])
	return Vector3(t.x, 0.0, t.z).normalized() if Vector3(t.x, 0.0, t.z).length() > 0.05 else Vector3.FORWARD
