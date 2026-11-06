extends SceneTree
## Minimal headless test runner (no plugins needed).
##   godot --headless --path . -s res://tests/run_tests.gd
## Runs every `test_*` method in every tests/test_*.gd file and exits with a
## non-zero code if anything fails.

var failures := 0
var checks := 0
var _current := ""


func _initialize() -> void:
	var files: Array[String] = []
	for f in DirAccess.get_files_at("res://tests"):
		if f.begins_with("test_") and f.ends_with(".gd"):
			files.append(f)
	files.sort()
	var tests := 0
	var t0 := Time.get_ticks_msec()
	for f in files:
		var script: GDScript = load("res://tests/" + f)
		if script == null or not script.can_instantiate():
			failures += 1
			printerr("  FAIL %s did not compile" % f)
			continue
		var inst = script.new()
		inst.set("runner", self)
		for m in script.get_script_method_list():
			var name: String = m["name"]
			if not name.begins_with("test_"):
				continue
			_current = "%s::%s" % [f.get_basename(), name]
			var before := failures
			inst.call(name)
			tests += 1
			print(("  ok   " if failures == before else "  FAIL ") + _current)
	print("\n%d tests, %d checks, %d failures (%d ms)" % [tests, checks, failures, Time.get_ticks_msec() - t0])
	quit(1 if failures > 0 else 0)


func check(cond: bool, msg: String) -> void:
	checks += 1
	if not cond:
		failures += 1
		printerr("       %s: %s" % [_current, msg])


func near(a: float, b: float, tol: float, msg: String) -> void:
	check(absf(a - b) <= tol, "%s (got %.4f, expected %.4f ± %.4f)" % [msg, a, b, tol])
