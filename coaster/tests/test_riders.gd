extends RefCounted
var runner


func _rider(bravery: float) -> Rider:
	var r := Rider.new()
	r.setup(1)
	r.bravery = bravery
	return r


func _feel(r: Rider, vg: float, lg: float, speed: float, seconds: float) -> void:
	var t := 0.0
	while t < seconds:
		r.feel(vg, lg, speed, 1.0 / 60.0)
		t += 1.0 / 60.0


func test_brave_rider_raises_hands_in_airtime() -> void:
	var r := _rider(0.9)
	_feel(r, 0.0, 0.0, 15.0, 1.0)
	runner.check(r.mood == Rider.Mood.HANDS_UP, "hands up in airtime (mood %d)" % r.mood)
	r.free()


func test_timid_rider_grips_under_high_g() -> void:
	var r := _rider(0.1)
	_feel(r, 3.8, 0.0, 20.0, 1.0)
	runner.check(r.mood == Rider.Mood.GRIP, "grips the bar (mood %d)" % r.mood)
	r.free()


func test_sloshing_makes_riders_sick() -> void:
	var r := _rider(0.3)
	_feel(r, 1.0, 1.4, 15.0, 6.0)
	runner.check(r.mood == Rider.Mood.SICK, "sick after sustained lateral G (mood %d)" % r.mood)
	r.reset()
	runner.check(r.mood == Rider.Mood.CALM, "reset clears sickness")
	r.free()


func test_scream_flag_fires_once() -> void:
	var r := _rider(0.3)
	var screams := 0
	for i in 60:
		r.feel(0.0, 0.0, 15.0, 1.0 / 60.0)
		if r.scream_started:
			screams += 1
	runner.check(screams == 1, "one scream event per scream (got %d)" % screams)
	r.free()
