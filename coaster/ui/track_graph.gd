class_name TrackGraph
extends Control
## Strip chart of the whole circuit: speed (blue line) and vertical G (coloured
## by comfort zone) against distance, with lateral G as a faint band. Tapping it
## jumps the camera to that part of the track.

signal picked(s: float)

var spline: TrackSpline
var record: RideRecord
var problems: Array[Dictionary] = []
var marker_s := -1.0

const G_MIN := -2.0
const G_MAX := 6.0


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_STOP
	custom_minimum_size = Vector2(200, 84)


func set_data(p_spline: TrackSpline, p_record: RideRecord, p_problems: Array[Dictionary]) -> void:
	spline = p_spline
	record = p_record
	problems = p_problems
	queue_redraw()


func set_marker(s: float) -> void:
	marker_s = s
	queue_redraw()


func _gui_input(event: InputEvent) -> void:
	if spline == null or spline.count == 0:
		return
	if (event is InputEventMouseButton and event.pressed and event.button_index == MOUSE_BUTTON_LEFT) \
			or (event is InputEventMouseMotion and (event.button_mask & MOUSE_BUTTON_MASK_LEFT) != 0):
		var s := clampf(event.position.x / size.x, 0.0, 1.0) * spline.length
		marker_s = s
		queue_redraw()
		picked.emit(s)
		accept_event()


func _y_for_g(g: float) -> float:
	return size.y * (1.0 - (clampf(g, G_MIN, G_MAX) - G_MIN) / (G_MAX - G_MIN))


func _draw() -> void:
	draw_rect(Rect2(Vector2.ZERO, size), Color(0.05, 0.07, 0.1, 0.72))
	if spline == null or record == null or spline.count == 0:
		return
	var n := spline.count
	var w := size.x
	# Reference lines: 0 g and 1 g.
	draw_line(Vector2(0, _y_for_g(0.0)), Vector2(w, _y_for_g(0.0)), Color(1, 1, 1, 0.15), 1.0)
	draw_line(Vector2(0, _y_for_g(1.0)), Vector2(w, _y_for_g(1.0)), Color(1, 1, 1, 0.3), 1.0)
	# Problem regions.
	for p in problems:
		var x0: float = p["s_start"] / spline.length * w
		var x1: float = maxf(p["s_end"] / spline.length * w, x0 + 2.0)
		var c := GLimits.zone_color(p["severity"])
		draw_rect(Rect2(x0, 0, x1 - x0, size.y), Color(c, 0.22))
	var step := maxi(1, n / int(maxf(w, 1.0)))
	var max_v := 1.0
	for k in n:
		max_v = maxf(max_v, absf(record.sample_speed[k]))
	var prev_g := Vector2.ZERO
	var prev_v := Vector2.ZERO
	var first := true
	for k in range(0, n, step):
		var x := float(k) / float(n) * w
		var g := record.sample_g_vert[k]
		var pg := Vector2(x, _y_for_g(g))
		var pv := Vector2(x, size.y * (1.0 - absf(record.sample_speed[k]) / max_v * 0.92))
		var lat := absf(record.sample_g_lat[k])
		if lat > 0.3:
			draw_line(Vector2(x, size.y), Vector2(x, size.y - lat / 2.0 * size.y * 0.5), Color(1.0, 0.5, 0.9, 0.35), float(step) + 0.5)
		if not first:
			draw_line(prev_v, pv, Color(0.4, 0.7, 1.0, 0.9), 1.5)
			var c := GLimits.zone_color(GLimits.vertical_zone(g))
			if record.sample_visited[k] == 0:
				c = Color(0.5, 0.5, 0.5)
			draw_line(prev_g, pg, c, 2.0)
		prev_g = pg
		prev_v = pv
		first = false
	if marker_s >= 0.0:
		var mx := marker_s / spline.length * w
		draw_line(Vector2(mx, 0), Vector2(mx, size.y), Color(1, 0.85, 0.1), 2.0)
	var font := get_theme_default_font()
	var fs := 12
	draw_string(font, Vector2(6, 14), "speed  (max %.0f km/h)" % (max_v * 3.6), HORIZONTAL_ALIGNMENT_LEFT, -1, fs, Color(0.4, 0.7, 1.0))
	draw_string(font, Vector2(6, 28), "vertical G", HORIZONTAL_ALIGNMENT_LEFT, -1, fs, GLimits.COLOR_SAFE)
	draw_string(font, Vector2(6, size.y - 4), "lateral G", HORIZONTAL_ALIGNMENT_LEFT, -1, fs, Color(1.0, 0.5, 0.9, 0.8))
