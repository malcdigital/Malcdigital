extends RefCounted
var runner


func test_round_trip_serialization() -> void:
	var t := DefaultTracks.starter()
	t.points[5].bank_deg = 42.5
	t.points[5].auto_bank = false
	var back := TrackData.from_dict(JSON.parse_string(JSON.stringify(t.to_dict())))
	runner.check(back.points.size() == t.points.size(), "same point count")
	runner.check(back.points[5].position.distance_to(t.points[5].position) < 0.01, "position kept")
	runner.near(back.points[5].bank_deg, 42.5, 0.01, "bank kept")
	runner.check(not back.points[5].auto_bank, "auto-bank flag kept")
	runner.check(back.points[2].segment == TrackPoint.Segment.LIFT, "segment type kept")
	runner.near(back.lift_speed, t.lift_speed, 1e-6, "systems kept")


func test_undo_redo() -> void:
	var h := EditHistory.new()
	var t := DefaultTracks.starter()
	var n := t.points.size()
	h.push(t)
	t.points.remove_at(5)
	h.push(t)
	t.points[0].position.x = 99.0
	var u1 := h.undo(t)
	runner.check(u1.points[0].position.x == 0.0, "undo restores the move")
	var u2 := h.undo(u1)
	runner.check(u2.points.size() == n, "second undo restores the deleted point")
	runner.check(h.undo(u2) == null, "nothing more to undo")
	var r1 := h.redo(u2)
	runner.check(r1.points.size() == n - 1, "redo re-applies the delete")
	h.push(r1)
	runner.check(not h.can_redo(), "a new edit clears redo")


func test_save_and_load() -> void:
	var t := DefaultTracks.starter()
	t.name = "Test Save Coaster"
	runner.check(CoasterStorage.save(t) == OK, "save ok")
	var file := CoasterStorage.file_name_for(t.name)
	var found := false
	for e in CoasterStorage.list():
		if e["file"] == file:
			found = true
	runner.check(found, "listed after save")
	var back := CoasterStorage.load_coaster(file)
	runner.check(back != null and back.points.size() == t.points.size(), "loads back")
	CoasterStorage.delete(file)
	runner.check(CoasterStorage.load_coaster(file) == null, "deleted")


func test_smoothing_keeps_station_fixed() -> void:
	var t := DefaultTracks.starter()
	t.points[8].position.y += 6.0
	var station := t.points[0].position
	TrackTools.smooth(t, 0.5)
	runner.check(t.points[0].position == station, "station point not moved")


func test_elements_stay_above_ground() -> void:
	for kind in Elements.NAMES.keys():
		for p in Elements.build(kind, Vector3(0, 2, 0), Vector3.FORWARD, 20.0):
			runner.check(p.position.y >= Elements.MIN_HEIGHT - 1e-4, "%s above ground" % Elements.NAMES[kind])
