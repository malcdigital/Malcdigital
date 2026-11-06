class_name Hud
extends CanvasLayer
## All 2D UI, built in code. Calls back into Main for every action.
## Buttons are large (52 px tall at the 1280x720 base size, which scales up on
## high-res screens) so everything works with fingers as well as a mouse.

var main: Node   # Main (untyped to avoid a cyclic class reference)

var root: Control
var theme_res: Theme

# Editor widgets
var editor_ui: Control
var stats_label: RichTextLabel
var point_panel: PanelContainer
var point_title: Label
var segment_option: OptionButton
var auto_bank_check: CheckButton
var bank_slider: HSlider
var bank_label: Label
var height_label: Label
var height_toggle: Button
var snap_toggle: Button
var undo_btn: Button
var redo_btn: Button
var overlay_option: OptionButton
var graph: TrackGraph
var graph_toggle: Button
var busy_label: Label
var type_option: OptionButton
var launch_label: Label
var launch_slider: HSlider
var _tool_buttons: Array[Button] = []
var _tool_groups := {}         # TrackEditor.Tool -> Array[Control]
var _stats_compact := false
var _last_analysis: TrackAnalyzer
var contracts_panel: PanelContainer
var contracts_list: ItemList
var contract_info: Label
var contract_start: Button
var brief_panel: PanelContainer
var brief_label: Label

# Ride widgets
var ride_ui: Control
var speed_label: Label
var g_label: RichTextLabel
var ride_info: Label
var cam_btn: Button
var fast_btn: Button

# Results / dialogs
var results_panel: PanelContainer
var results_box: VBoxContainer
var save_panel: PanelContainer
var save_name: LineEdit
var load_panel: PanelContainer
var load_list: ItemList
var _load_files: Array[String] = []
var toast_label: Label
var _toast_time := 0.0
var _updating := false


func setup(p_main: Node) -> void:
	main = p_main
	_update_scale()   # before building, so controls measure text at the final scale
	_build_theme()
	root = Control.new()
	root.set_anchors_preset(Control.PRESET_FULL_RECT)
	root.mouse_filter = Control.MOUSE_FILTER_IGNORE
	root.theme = theme_res
	add_child(root)
	_build_editor_ui()
	_build_ride_ui()
	_build_results()
	_build_dialogs()
	_build_contract_dialogs()
	toast_label = Label.new()
	toast_label.set_anchors_preset(Control.PRESET_CENTER_TOP)
	toast_label.position = Vector2(-300, 80)
	toast_label.size = Vector2(600, 40)
	toast_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	toast_label.add_theme_color_override("font_outline_color", Color.BLACK)
	toast_label.add_theme_constant_override("outline_size", 6)
	toast_label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	root.add_child(toast_label)
	show_editor()


func _process(dt: float) -> void:
	_update_scale()
	if _toast_time > 0.0:
		_toast_time -= dt
		toast_label.modulate.a = clampf(_toast_time, 0.0, 1.0)


func toast(text: String, seconds: float = 2.5) -> void:
	toast_label.text = text
	_toast_time = seconds


# -----------------------------------------------------------------------------
# Theme and helpers
# -----------------------------------------------------------------------------

func _build_theme() -> void:
	theme_res = Theme.new()
	theme_res.default_font_size = 18
	var panel := StyleBoxFlat.new()
	panel.bg_color = Color(0.07, 0.09, 0.13, 0.82)
	panel.set_corner_radius_all(10)
	panel.set_content_margin_all(10)
	theme_res.set_stylebox("panel", "PanelContainer", panel)
	var btn := StyleBoxFlat.new()
	btn.bg_color = Color(0.16, 0.2, 0.28, 0.92)
	btn.set_corner_radius_all(8)
	btn.content_margin_left = 14
	btn.content_margin_right = 14
	btn.content_margin_top = 8
	btn.content_margin_bottom = 8
	var hover := btn.duplicate()
	hover.bg_color = Color(0.22, 0.28, 0.4, 0.95)
	var pressed := btn.duplicate()
	pressed.bg_color = Color(0.95, 0.55, 0.15, 0.95)
	var disabled := btn.duplicate()
	disabled.bg_color = Color(0.12, 0.14, 0.18, 0.6)
	for cls in ["Button", "OptionButton", "MenuButton", "CheckButton"]:
		theme_res.set_stylebox("normal", cls, btn)
		theme_res.set_stylebox("hover", cls, hover)
		theme_res.set_stylebox("pressed", cls, pressed)
		theme_res.set_stylebox("hover_pressed", cls, pressed)
		theme_res.set_stylebox("disabled", cls, disabled)
		theme_res.set_stylebox("focus", cls, StyleBoxEmpty.new())


func _button(text: String, cb: Callable, toggle: bool = false) -> Button:
	var b := Button.new()
	b.text = text
	b.custom_minimum_size = Vector2(52, 52)
	b.toggle_mode = toggle
	b.focus_mode = Control.FOCUS_NONE
	if toggle:
		b.toggled.connect(func(on: bool) -> void: cb.call(on))
	else:
		b.pressed.connect(cb)
	return b


func _column(parent: Control, at_top: bool) -> VBoxContainer:
	var v := VBoxContainer.new()
	v.add_theme_constant_override("separation", 6)
	v.mouse_filter = Control.MOUSE_FILTER_IGNORE
	parent.add_child(v)
	v.set_anchors_preset(Control.PRESET_TOP_WIDE if at_top else Control.PRESET_BOTTOM_WIDE)
	v.offset_left = 8
	v.offset_right = -8
	v.offset_top = 8 if at_top else -8
	v.offset_bottom = 8 if at_top else -8
	v.grow_vertical = Control.GROW_DIRECTION_END if at_top else Control.GROW_DIRECTION_BEGIN
	return v


## Phones: the UI is laid out for 1280x720 and normally scales with the
## window, which makes it tiny on a small (or portrait) screen. When the
## short side of the screen is small, scale up so buttons stay finger-sized.
## Works in CSS/logical pixels so high-DPI screens are treated the same.
var _last_window_size := Vector2i.ZERO
var compact := false

func _update_scale() -> void:
	var win := get_window()
	if win.size == _last_window_size:
		return
	_last_window_size = win.size
	var dpr := maxf(DisplayServer.screen_get_scale(), 1.0)
	var size_css := Vector2(win.size) / dpr
	var base := minf(size_css.x / 1280.0, size_css.y / 720.0)
	var short_side := minf(size_css.x, size_css.y)
	var was_compact := compact
	compact = short_side < 620.0
	var want := maxf(base, short_side / 560.0) if compact else base
	win.content_scale_factor = maxf(1.0, want / maxf(base, 0.01))
	if root != null:
		# Re-measure every control's text at the new scale.
		root.propagate_notification(Control.NOTIFICATION_THEME_CHANGED)
	if compact and not was_compact and graph != null:
		graph_toggle.button_pressed = false   # make room on small screens


func _panel(parent: Control) -> PanelContainer:
	var p := PanelContainer.new()
	parent.add_child(p)
	return p


func _bar(parent: Control, preset: int) -> HBoxContainer:
	var bar := HBoxContainer.new()
	bar.add_theme_constant_override("separation", 6)
	parent.add_child(bar)
	bar.set_anchors_and_offsets_preset(preset, Control.PRESET_MODE_MINSIZE, 8)
	return bar


# -----------------------------------------------------------------------------
# Editor UI
# -----------------------------------------------------------------------------

func _build_editor_ui() -> void:
	editor_ui = Control.new()
	editor_ui.set_anchors_preset(Control.PRESET_FULL_RECT)
	editor_ui.mouse_filter = Control.MOUSE_FILTER_IGNORE
	root.add_child(editor_ui)

	# Layout: a column pinned to the top (toolbar, then stats + point panel) and
	# one pinned to the bottom (graph, then toolbar). Toolbars are flow
	# containers so they wrap onto two rows on narrow (portrait) screens.
	var top_v := _column(editor_ui, true)
	var bottom_v := _column(editor_ui, false)

	# --- Top bar ---------------------------------------------------------------
	var top := HFlowContainer.new()
	top.add_theme_constant_override("h_separation", 6)
	top.add_theme_constant_override("v_separation", 6)
	top.mouse_filter = Control.MOUSE_FILTER_IGNORE
	top_v.add_child(top)
	undo_btn = _button("Undo", func() -> void: main.undo())
	redo_btn = _button("Redo", func() -> void: main.redo())
	top.add_child(undo_btn)
	top.add_child(redo_btn)
	var file_menu := MenuButton.new()
	file_menu.text = "File"
	file_menu.custom_minimum_size = Vector2(52, 52)
	file_menu.flat = false
	var fp := file_menu.get_popup()
	fp.add_theme_font_size_override("font_size", 22)
	fp.add_item("Contracts...", 4)
	fp.add_separator()
	fp.add_item("Save...", 0)
	fp.add_item("Load...", 1)
	fp.add_separator()
	fp.add_item("New: starter coaster", 2)
	fp.add_item("New: blank track", 3)
	fp.add_separator()
	for i in TerrainData.PRESET_NAMES.size():
		fp.add_item("Terrain: " + TerrainData.PRESET_NAMES[i], 10 + i)
	fp.add_separator()
	fp.add_item("Leave contract (sandbox)", 5)
	fp.id_pressed.connect(_on_file_menu)
	top.add_child(file_menu)
	top.add_child(_button("Contracts", func() -> void: show_contracts()))
	overlay_option = OptionButton.new()
	overlay_option.custom_minimum_size = Vector2(52, 52)
	overlay_option.focus_mode = Control.FOCUS_NONE
	for i in TrackOverlay.NAMES.size():
		overlay_option.add_item(TrackOverlay.NAMES[i], i)
	overlay_option.get_popup().add_theme_font_size_override("font_size", 22)
	overlay_option.item_selected.connect(func(i: int) -> void: main.set_overlay(i))
	top.add_child(overlay_option)
	type_option = OptionButton.new()
	type_option.custom_minimum_size = Vector2(52, 52)
	type_option.focus_mode = Control.FOCUS_NONE
	type_option.get_popup().add_theme_font_size_override("font_size", 22)
	for id in CoasterTypes.ORDER:
		type_option.add_item(CoasterTypes.type_name(id), id)
	type_option.item_selected.connect(func(i: int) -> void:
		if not _updating: main.set_coaster_type(type_option.get_item_id(i)))
	top.add_child(type_option)
	graph_toggle = _button("Graph", func(on: bool) -> void: graph.visible = on, true)
	graph_toggle.set_pressed_no_signal(not compact)
	top.add_child(graph_toggle)
	var spacer := Control.new()
	spacer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	spacer.mouse_filter = Control.MOUSE_FILTER_IGNORE
	top.add_child(spacer)
	busy_label = Label.new()
	busy_label.text = ""
	busy_label.modulate = Color(1, 1, 1, 0.6)
	top.add_child(busy_label)
	var ride := _button("Test ride", func() -> void: main.start_ride())
	ride.add_theme_font_size_override("font_size", 22)
	ride.add_theme_color_override("font_color", Color(1.0, 0.85, 0.3))
	top.add_child(ride)

	# --- Stats (top left) ------------------------------------------------------
	var row := HBoxContainer.new()
	row.mouse_filter = Control.MOUSE_FILTER_IGNORE
	top_v.add_child(row)
	var sp := _panel(row)
	sp.size_flags_vertical = Control.SIZE_SHRINK_BEGIN
	# Tap the stats panel to fold it down to two lines (handy on phones).
	sp.mouse_filter = Control.MOUSE_FILTER_STOP
	sp.gui_input.connect(func(e: InputEvent) -> void:
		if e is InputEventMouseButton and e.pressed and e.button_index == MOUSE_BUTTON_LEFT:
			_stats_compact = not _stats_compact
			update_analysis(_last_analysis))
	stats_label = RichTextLabel.new()
	stats_label.bbcode_enabled = true
	stats_label.fit_content = true
	stats_label.scroll_active = false
	stats_label.custom_minimum_size = Vector2(265, 0)
	stats_label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	stats_label.add_theme_font_size_override("normal_font_size", 15)
	stats_label.add_theme_font_size_override("bold_font_size", 15)
	sp.add_child(stats_label)
	var row_gap := Control.new()
	row_gap.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	row_gap.mouse_filter = Control.MOUSE_FILTER_IGNORE
	row.add_child(row_gap)

	# --- Bottom bar ------------------------------------------------------------
	graph = TrackGraph.new()
	bottom_v.add_child(graph)
	graph.visible = not compact
	graph.picked.connect(func(s: float) -> void: main.focus_s(s, false))
	var bottom := HFlowContainer.new()
	bottom.add_theme_constant_override("h_separation", 6)
	bottom.add_theme_constant_override("v_separation", 6)
	bottom.mouse_filter = Control.MOUSE_FILTER_IGNORE
	bottom_v.add_child(bottom)
	# Tool switch: Track / Terrain / Scenery. Each tool shows its own buttons.
	var group := ButtonGroup.new()
	for t in [TrackEditor.Tool.TRACK, TrackEditor.Tool.TERRAIN, TrackEditor.Tool.SCENERY]:
		var b := _button(["Track", "Terrain", "Scenery"][t], func(on: bool) -> void:
			if on: main.set_tool(t), true)
		b.button_group = group
		b.add_theme_color_override("font_color", Color(1.0, 0.85, 0.3))
		bottom.add_child(b)
		_tool_buttons.append(b)
	_tool_buttons[0].set_pressed_no_signal(true)
	var track_tools: Array[Control] = []
	track_tools.append(_button("+ Point", func() -> void: main.add_point()))
	track_tools.append(_button("Delete", func() -> void: main.delete_point()))
	var el := MenuButton.new()
	el.text = "Add element"
	el.custom_minimum_size = Vector2(52, 52)
	el.flat = false
	var ep := el.get_popup()
	ep.add_theme_font_size_override("font_size", 22)
	for kind in [Elements.Kind.HILL, Elements.Kind.DROP, Elements.Kind.LOOP, Elements.Kind.HEARTLINE_ROLL, Elements.Kind.HELIX_LEFT,
			Elements.Kind.HELIX_RIGHT, Elements.Kind.TURN_LEFT, Elements.Kind.TURN_RIGHT, Elements.Kind.UTURN_LEFT,
			Elements.Kind.UTURN_RIGHT, Elements.Kind.SPLASHDOWN, Elements.Kind.LIFT_HILL, Elements.Kind.LAUNCH, Elements.Kind.BRAKES, Elements.Kind.STRAIGHT]:
		ep.add_item(Elements.NAMES[kind], kind)
	ep.id_pressed.connect(func(id: int) -> void: main.insert_element(id))
	track_tools.append(el)
	track_tools.append(_button("Smooth", func() -> void: main.smooth()))
	height_toggle = _button("Height mode", func(on: bool) -> void: main.set_height_mode(on), true)
	track_tools.append(height_toggle)
	snap_toggle = _button("Snap", func(on: bool) -> void: main.set_snap(on), true)
	snap_toggle.set_pressed_no_signal(true)
	track_tools.append(snap_toggle)

	var terrain_tools: Array[Control] = []
	var bgroup := ButtonGroup.new()
	for b_i in TerrainData.BRUSH_NAMES.size():
		var bb := _button(TerrainData.BRUSH_NAMES[b_i], func(on: bool) -> void:
			if on: main.set_brush(b_i), true)
		bb.button_group = bgroup
		if b_i == 0:
			bb.set_pressed_no_signal(true)
		terrain_tools.append(bb)
	var size_box := HBoxContainer.new()
	var size_label := Label.new()
	size_label.text = "Size"
	size_box.add_child(size_label)
	var size_slider := HSlider.new()
	size_slider.min_value = 6
	size_slider.max_value = 40
	size_slider.value = 14
	size_slider.custom_minimum_size = Vector2(130, 52)
	size_slider.value_changed.connect(func(v: float) -> void: main.set_brush_size(v))
	size_box.add_child(size_slider)
	terrain_tools.append(size_box)

	var scenery_tools: Array[Control] = []
	var pgroup := ButtonGroup.new()
	var kinds := [[Props.Kind.TREE, "Tree"], [Props.Kind.ROCK, "Rock"], [Props.Kind.TOWER, "Tower"], [-1, "Remove"]]
	for kd in kinds:
		var k: int = kd[0]
		var pb := _button(kd[1], func(on: bool) -> void:
			if on: main.set_prop_kind(k), true)
		pb.button_group = pgroup
		if k == Props.Kind.TREE:
			pb.set_pressed_no_signal(true)
		scenery_tools.append(pb)

	_tool_groups = {TrackEditor.Tool.TRACK: track_tools, TrackEditor.Tool.TERRAIN: terrain_tools, TrackEditor.Tool.SCENERY: scenery_tools}
	for t in _tool_groups:
		for c in _tool_groups[t]:
			bottom.add_child(c)
			c.visible = t == TrackEditor.Tool.TRACK
	var spacer2 := Control.new()
	spacer2.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	spacer2.mouse_filter = Control.MOUSE_FILTER_IGNORE
	bottom.add_child(spacer2)
	bottom.add_child(_button("Fit view", func() -> void: main.frame_track()))

	# --- Point inspector (right) ------------------------------------------------
	point_panel = _panel(row)
	point_panel.size_flags_vertical = Control.SIZE_SHRINK_BEGIN
	point_panel.custom_minimum_size = Vector2(240, 0)
	var v := VBoxContainer.new()
	v.add_theme_constant_override("separation", 6)
	point_panel.add_child(v)
	point_title = Label.new()
	v.add_child(point_title)
	segment_option = OptionButton.new()
	segment_option.custom_minimum_size = Vector2(0, 48)
	segment_option.focus_mode = Control.FOCUS_NONE
	segment_option.get_popup().add_theme_font_size_override("font_size", 22)
	for i in TrackPoint.SEGMENT_NAMES.size():
		segment_option.add_item(TrackPoint.SEGMENT_NAMES[i], i)
	segment_option.item_selected.connect(func(i: int) -> void:
		if not _updating: main.set_segment(i))
	v.add_child(segment_option)
	auto_bank_check = CheckButton.new()
	auto_bank_check.text = "Auto-bank"
	auto_bank_check.focus_mode = Control.FOCUS_NONE
	auto_bank_check.toggled.connect(func(on: bool) -> void:
		if not _updating: main.set_auto_bank(on))
	v.add_child(auto_bank_check)
	bank_label = Label.new()
	v.add_child(bank_label)
	bank_slider = HSlider.new()
	bank_slider.min_value = -360
	bank_slider.max_value = 360
	bank_slider.step = 5
	bank_slider.custom_minimum_size = Vector2(0, 36)
	bank_slider.value_changed.connect(func(val: float) -> void:
		bank_label.text = "Bank: %d°" % int(val)
		if not _updating: main.set_bank(val))
	bank_slider.drag_ended.connect(func(_c: bool) -> void: main.commit_bank())
	v.add_child(bank_slider)
	launch_label = Label.new()
	v.add_child(launch_label)
	launch_slider = HSlider.new()
	launch_slider.min_value = 10
	launch_slider.max_value = 45
	launch_slider.step = 1
	launch_slider.custom_minimum_size = Vector2(0, 36)
	launch_slider.value_changed.connect(func(val: float) -> void:
		launch_label.text = "Launch speed: %d km/h" % roundi(val * 3.6)
		if not _updating: main.set_launch_speed(val))
	launch_slider.drag_ended.connect(func(_c: bool) -> void: main.commit_bank())
	v.add_child(launch_slider)
	height_label = Label.new()
	v.add_child(height_label)
	var hb := HBoxContainer.new()
	hb.add_child(_button("Up 1 m", func() -> void: main.nudge(Vector3.UP)))
	hb.add_child(_button("Down 1 m", func() -> void: main.nudge(Vector3.DOWN)))
	hb.add_child(_button("Focus", func() -> void: main.focus_selected()))
	v.add_child(hb)
	point_panel.visible = false


func _on_file_menu(id: int) -> void:
	match id:
		0:
			save_name.text = main.data.name
			_open(save_panel)
		1:
			_refresh_load_list()
			_open(load_panel)
		2:
			main.new_track(false)
		3:
			main.new_track(true)
		4:
			show_contracts()
		5:
			main.leave_contract()
		_:
			if id >= 10:
				main.set_terrain_preset(id - 10)


func show_editor() -> void:
	editor_ui.visible = true
	ride_ui.visible = false
	results_panel.visible = false


func set_busy(busy: bool) -> void:
	busy_label.text = "analysing..." if busy else "%d fps" % Engine.get_frames_per_second()


func refresh_history(can_undo: bool, can_redo: bool) -> void:
	undo_btn.disabled = not can_undo
	redo_btn.disabled = not can_redo


func refresh_point(data: TrackData, index: int, spline: TrackSpline, record: RideRecord) -> void:
	point_panel.visible = index >= 0 and index < data.points.size()
	if not point_panel.visible:
		graph.set_marker(-1.0)
		return
	_updating = true
	var p := data.points[index]
	point_title.text = "Point %d of %d" % [index + 1, data.points.size()]
	segment_option.select(p.segment)
	auto_bank_check.button_pressed = p.auto_bank
	var launch := p.segment == TrackPoint.Segment.LAUNCH
	launch_label.visible = launch
	launch_slider.visible = launch
	launch_slider.value = data.launch_speed
	launch_label.text = "Launch speed: %d km/h" % roundi(data.launch_speed * 3.6)
	bank_slider.editable = not p.auto_bank
	bank_slider.value = p.bank_deg
	bank_label.text = "Bank: %d°" % int(p.bank_deg) if not p.auto_bank else "Bank: automatic"
	var extra := ""
	if spline != null and record != null and index < spline.point_s.size():
		var s := spline.point_s[index]
		var k := spline.index_at(s)
		extra = "\n%.0f km/h · %.1f g vert · %.1f g lat" % [absf(record.sample_speed[k]) * 3.6, record.sample_g_vert[k], record.sample_g_lat[k]]
		graph.set_marker(s)
	height_label.text = "Height: %.1f m%s" % [p.position.y, extra]
	_updating = false


func update_analysis(a: TrackAnalyzer) -> void:
	_last_analysis = a
	var d: TrackData = main.data
	var c := Contracts.find(d.contract_id)
	var head := "[b]%s[/b]  [color=#9ab]%s[/color]" % [d.name, CoasterTypes.type_name(d.coaster_type)]
	if a == null or not a.valid:
		stats_label.text = head + "\n[b]Track needs at least 4 points[/b]"
		graph.set_data(null, null, [] as Array[Dictionary])
		return
	var st := a.ratings.stats
	var r := a.ratings
	var status := "[color=#6f6]Completes the circuit[/color]"
	if not a.record.completed:
		status = "[color=#f66]STALLS at %.0f m[/color]" % a.record.stall_s
	elif a.record.rollbacks > 0:
		status = "[color=#fc4]Rolls back at %.0f m[/color]" % a.record.stall_s
	var reds := 0
	var yellows := 0
	for p in r.problems:
		if p["severity"] == GLimits.Zone.DANGER: reds += 1
		else: yellows += 1
	var budget: float = c.get("budget", 0.0)
	var cost := CostModel.money(a.cost)
	if budget > 0.0:
		cost = "[color=#%s]%s[/color] of %s" % ["6f6" if a.cost <= budget else "f66", cost, CostModel.money(budget)]
	var t := "%s\n%s · Cost %s\n" % [head, status, cost]
	t += "Thrill [b]%.1f[/b] · Intensity [b]%.1f[/b] · Nausea [b]%.1f[/b]" % [r.thrill, r.intensity, r.nausea]
	if not _stats_compact:
		t += "\nLength %.0f m · Height %.0f m · %.0f km/h · %.0f s\n" % [st["length"], a.max_height_above_ground, st["max_speed"] * 3.6, st["duration"]]
		t += "G: %s / %s · lat %s · Airtime %.1f s\n" % [_gfmt(st["max_g_vert"], GLimits.vertical_zone(st["max_g_vert"])),
			_gfmt(st["min_g_vert"], GLimits.vertical_zone(st["min_g_vert"])), _gfmt(st["max_g_lat"], GLimits.lateral_zone(st["max_g_lat"])), st["airtime"]]
		t += "Inversions %d · Near misses %d · Splashes %d · Tunnel %.0f m" % [st["inversions"], st["near_misses"], st["splashes"], st["tunnel_length"]]
		if reds + yellows > 0:
			t += "\n[color=#f66]%d red[/color] · [color=#fc4]%d yellow[/color] spots" % [reds, yellows]
		var res: Dictionary = main.contract_result
		if not res.is_empty():
			t += "\n[b]Contract: %s[/b]  (stars now: %d)" % [c.get("title", ""), res["stars"]]
			for g in res["goals"]:
				var ok: bool = g["ok"]
				t += "\n[color=#%s]%s[/color] %s%s [color=#9ab](%s)[/color]" % ["6f6" if ok else ("fc4" if g["bonus"] else "f66"),
					"YES" if ok else "NO ", "Bonus: " if g["bonus"] else "", g["text"], g["detail"]]
	else:
		t += "\n[color=#9ab](tap for details)[/color]"
	stats_label.text = t
	graph.set_data(a.spline, a.record, r.problems)


func refresh_type(data: TrackData, progress: ProgressStore) -> void:
	_updating = true
	var unlocked := progress.unlocked_types()
	for i in type_option.item_count:
		var id := type_option.get_item_id(i)
		var locked := not unlocked.has(id)
		type_option.set_item_text(i, CoasterTypes.type_name(id) + (" (locked)" if locked else ""))
		type_option.set_item_disabled(i, locked or (data.contract_id != "" and id != data.coaster_type))
		if id == data.coaster_type:
			type_option.select(i)
	_updating = false


func show_tool(t: int) -> void:
	for k in _tool_groups:
		for c in _tool_groups[k]:
			c.visible = k == t
	for i in _tool_buttons.size():
		_tool_buttons[i].set_pressed_no_signal(i == t)
	if t != TrackEditor.Tool.TRACK:
		point_panel.visible = false


static func _gfmt(g: float, zone: int) -> String:
	return "[color=#%s]%.1f[/color]" % [GLimits.zone_color(zone).to_html(false), g]


# -----------------------------------------------------------------------------
# Ride UI
# -----------------------------------------------------------------------------

func _build_ride_ui() -> void:
	ride_ui = Control.new()
	ride_ui.set_anchors_preset(Control.PRESET_FULL_RECT)
	ride_ui.mouse_filter = Control.MOUSE_FILTER_IGNORE
	root.add_child(ride_ui)
	var p := _panel(ride_ui)
	p.position = Vector2(8, 8)
	p.mouse_filter = Control.MOUSE_FILTER_IGNORE
	var v := VBoxContainer.new()
	p.add_child(v)
	speed_label = Label.new()
	speed_label.add_theme_font_size_override("font_size", 40)
	v.add_child(speed_label)
	g_label = RichTextLabel.new()
	g_label.bbcode_enabled = true
	g_label.fit_content = true
	g_label.scroll_active = false
	g_label.custom_minimum_size = Vector2(230, 0)
	g_label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	g_label.add_theme_font_size_override("normal_font_size", 20)
	v.add_child(g_label)
	ride_info = Label.new()
	ride_info.add_theme_font_size_override("font_size", 15)
	v.add_child(ride_info)
	var bar := HBoxContainer.new()
	bar.add_theme_constant_override("separation", 6)
	bar.mouse_filter = Control.MOUSE_FILTER_IGNORE
	ride_ui.add_child(bar)
	bar.set_anchors_preset(Control.PRESET_TOP_WIDE)
	bar.offset_top = 8
	bar.offset_left = 8
	bar.offset_right = -8
	var spacer := Control.new()
	spacer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	spacer.mouse_filter = Control.MOUSE_FILTER_IGNORE
	bar.add_child(spacer)
	cam_btn = _button("Camera: POV", func() -> void: main.toggle_ride_camera())
	bar.add_child(cam_btn)
	fast_btn = _button("Speed 1×", func() -> void: main.cycle_ride_speed())
	bar.add_child(fast_btn)
	bar.add_child(_button("Stop", func() -> void: main.stop_ride()))


func show_ride() -> void:
	editor_ui.visible = false
	results_panel.visible = false
	ride_ui.visible = true


func set_ride_camera_label(pov: bool) -> void:
	cam_btn.text = "Camera: POV" if pov else "Camera: Chase"


func set_ride_speed_label(mult: float) -> void:
	fast_btn.text = "Speed %d×" % int(mult)


func update_ride(sim: TrainSim, sick: int, riders: int) -> void:
	speed_label.text = "%d km/h" % roundi(absf(sim.v) * 3.6)
	var g := sim.spline.g_forces_at(sim.car_s(0), sim.v, sim.a_t)
	g_label.text = "Vertical %s g\nLateral %s g" % [_gfmt(g.x, GLimits.vertical_zone(g.x)), _gfmt(g.y, GLimits.lateral_zone(g.y))]
	var seg := sim.spline.segment_at(sim.middle_s())
	var what := ""
	match seg:
		TrackPoint.Segment.LIFT: what = " · on the lift"
		TrackPoint.Segment.LAUNCH: what = " · LAUNCH!"
		TrackPoint.Segment.BRAKE: what = " · braking"
	if sim.v < -0.1:
		what = " · ROLLING BACK"
	ride_info.text = "%.0f s · %d%% done · %d fps%s%s" % [sim.time, clampi(int((sim.s - sim.start_s) / sim.spline.length * 100.0), 0, 100), Engine.get_frames_per_second(), what,
		(" · %d/%d riders sick" % [sick, riders]) if sick > 0 else ""]


# -----------------------------------------------------------------------------
# Results
# -----------------------------------------------------------------------------

func _build_results() -> void:
	results_panel = _panel(root)
	results_panel.set_anchors_preset(Control.PRESET_FULL_RECT)
	results_panel.offset_left = 60
	results_panel.offset_right = -60
	results_panel.offset_top = 30
	results_panel.offset_bottom = -30
	var outer := VBoxContainer.new()
	results_panel.add_child(outer)
	var scroll := ScrollContainer.new()
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	outer.add_child(scroll)
	results_box = VBoxContainer.new()
	results_box.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	results_box.add_theme_constant_override("separation", 8)
	scroll.add_child(results_box)
	var buttons := HBoxContainer.new()
	buttons.alignment = BoxContainer.ALIGNMENT_CENTER
	buttons.add_theme_constant_override("separation", 12)
	buttons.add_child(_button("Ride again", func() -> void: main.start_ride()))
	buttons.add_child(_button("Back to editor", func() -> void: main.back_to_editor()))
	outer.add_child(buttons)
	results_panel.visible = false


func show_results(r: RideRatings, completed: bool, sick: int, riders: int) -> void:
	editor_ui.visible = false
	ride_ui.visible = false
	results_panel.visible = true
	for c in results_box.get_children():
		c.queue_free()
	var title := Label.new()
	title.text = "Ride complete" if completed else "The train didn't make it"
	title.add_theme_font_size_override("font_size", 30)
	results_box.add_child(title)
	var verdict := Label.new()
	verdict.text = r.verdict
	verdict.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	results_box.add_child(verdict)

	var ratings := HBoxContainer.new()
	ratings.add_theme_constant_override("separation", 16)
	results_box.add_child(ratings)
	ratings.add_child(_rating_card("Thrill", r.thrill, r.thrill_parts, Color(1.0, 0.6, 0.2)))
	ratings.add_child(_rating_card("Intensity", r.intensity, r.intensity_parts, Color(0.95, 0.3, 0.35)))
	ratings.add_child(_rating_card("Nausea", r.nausea, r.nausea_parts, Color(0.45, 0.85, 0.35)))

	var st := r.stats
	var stats := Label.new()
	stats.text = "Top speed %.0f km/h · Length %.0f m · Ride time %.0f s · Biggest drop %.0f m\nMax G %.1f · Min G %.1f · Max lateral %.1f · Airtime %.1f s · Inversions %d%s" % [
		st["max_speed"] * 3.6, st["length"], st["duration"], st["max_drop"],
		st["max_g_vert"], st["min_g_vert"], st["max_g_lat"], st["airtime"], st["inversions"],
		("\n%d of %d riders felt sick" % [sick, riders]) if sick > 0 else ""]
	stats.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	stats.add_theme_font_size_override("font_size", 16)
	results_box.add_child(stats)

	var ph := Label.new()
	ph.text = "Problem spots" if not r.problems.is_empty() else "No problem spots: nice work!"
	ph.add_theme_font_size_override("font_size", 22)
	results_box.add_child(ph)
	for p in r.problems.slice(0, 12):
		var row := HBoxContainer.new()
		row.add_theme_constant_override("separation", 10)
		var dot := ColorRect.new()
		dot.color = GLimits.zone_color(p["severity"])
		dot.custom_minimum_size = Vector2(14, 14)
		dot.size_flags_vertical = Control.SIZE_SHRINK_CENTER
		row.add_child(dot)
		var l := Label.new()
		l.text = "At %.0f m: %s" % [p["s"], p["message"]]
		l.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		l.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		l.add_theme_font_size_override("font_size", 16)
		row.add_child(l)
		var s: float = p["s"]
		row.add_child(_button("Show", func() -> void: main.focus_s(s, true)))
		results_box.add_child(row)


func _rating_card(title: String, value: float, parts: Array[Dictionary], color: Color) -> Control:
	var v := VBoxContainer.new()
	v.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var t := Label.new()
	t.text = "%s  %.1f  (%s)" % [title, value, RideRatings.label_for(value)]
	t.add_theme_font_size_override("font_size", 20)
	v.add_child(t)
	var bar := ProgressBar.new()
	bar.max_value = 10.0
	bar.value = value
	bar.show_percentage = false
	bar.custom_minimum_size = Vector2(0, 14)
	var fill := StyleBoxFlat.new()
	fill.bg_color = color
	fill.set_corner_radius_all(4)
	bar.add_theme_stylebox_override("fill", fill)
	v.add_child(bar)
	for p in parts:
		var l := Label.new()
		var val: float = p["value"]
		l.text = "%s %+.1f" % [p["label"], val]
		l.add_theme_font_size_override("font_size", 14)
		l.modulate = Color(1, 1, 1, 0.85) if val >= 0.0 else Color(1, 0.6, 0.6)
		v.add_child(l)
	return v


# -----------------------------------------------------------------------------
# Save / load dialogs
# -----------------------------------------------------------------------------

func _build_dialogs() -> void:
	save_panel = _dialog("Save coaster")
	var sv: VBoxContainer = save_panel.get_child(0)
	save_name = LineEdit.new()
	save_name.placeholder_text = "Coaster name"
	save_name.custom_minimum_size = Vector2(380, 48)
	sv.add_child(save_name)
	var sb := HBoxContainer.new()
	sb.alignment = BoxContainer.ALIGNMENT_END
	sb.add_child(_button("Cancel", func() -> void: save_panel.visible = false))
	sb.add_child(_button("Save", func() -> void:
		main.save_track(save_name.text)
		save_panel.visible = false))
	sv.add_child(sb)

	load_panel = _dialog("Load coaster")
	var lv: VBoxContainer = load_panel.get_child(0)
	load_list = ItemList.new()
	load_list.custom_minimum_size = Vector2(420, 260)
	load_list.add_theme_font_size_override("font_size", 20)
	lv.add_child(load_list)
	var lb := HBoxContainer.new()
	lb.alignment = BoxContainer.ALIGNMENT_END
	lb.add_child(_button("Delete", func() -> void:
		var sel := load_list.get_selected_items()
		if sel.size() > 0:
			main.delete_saved(_load_files[sel[0]])
			_refresh_load_list()))
	lb.add_child(_button("Cancel", func() -> void: load_panel.visible = false))
	lb.add_child(_button("Load", func() -> void:
		var sel := load_list.get_selected_items()
		if sel.size() > 0:
			main.load_saved(_load_files[sel[0]])
			load_panel.visible = false))
	lv.add_child(lb)


## Show a dialog centred on screen (and kept inside it).
func _open(p: PanelContainer) -> void:
	p.visible = true
	p.reset_size()
	_center.call_deferred(p)


func _center(p: PanelContainer) -> void:
	p.reset_size()
	var area := root.size
	p.position = Vector2(maxf((area.x - p.size.x) * 0.5, 8.0), maxf((area.y - p.size.y) * 0.5, 8.0))


func _dialog(title: String) -> PanelContainer:
	var p := PanelContainer.new()
	root.add_child(p)
	p.set_anchors_preset(Control.PRESET_CENTER)
	p.grow_horizontal = Control.GROW_DIRECTION_BOTH
	p.grow_vertical = Control.GROW_DIRECTION_BOTH
	var v := VBoxContainer.new()
	v.add_theme_constant_override("separation", 10)
	p.add_child(v)
	var l := Label.new()
	l.text = title
	l.add_theme_font_size_override("font_size", 24)
	v.add_child(l)
	p.visible = false
	return p


func _refresh_load_list() -> void:
	load_list.clear()
	_load_files.clear()
	for e in CoasterStorage.list():
		load_list.add_item(e["name"])
		_load_files.append(e["file"])
	if _load_files.is_empty():
		load_list.add_item("(no saved coasters yet)")
		load_list.set_item_disabled(0, true)


func any_dialog_open() -> bool:
	return save_panel.visible or load_panel.visible or contracts_panel.visible or brief_panel.visible


# -----------------------------------------------------------------------------
# Contracts
# -----------------------------------------------------------------------------

func _build_contract_dialogs() -> void:
	contracts_panel = _dialog("Contracts")
	var v: VBoxContainer = contracts_panel.get_child(0)
	var total := Label.new()
	total.name = "Total"
	v.add_child(total)
	var hb := BoxContainer.new()   # list and details side by side, stacked when narrow
	hb.vertical = compact and get_window().size.x < get_window().size.y
	hb.add_theme_constant_override("separation", 12)
	v.add_child(hb)
	contracts_list = ItemList.new()
	contracts_list.custom_minimum_size = Vector2(280, 260)
	contracts_list.add_theme_font_size_override("font_size", 18)
	contracts_list.item_selected.connect(_on_contract_selected)
	hb.add_child(contracts_list)
	contract_info = Label.new()
	contract_info.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	contract_info.custom_minimum_size = Vector2(320, 0)
	contract_info.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	contract_info.add_theme_font_size_override("font_size", 16)
	var info_scroll := ScrollContainer.new()
	info_scroll.custom_minimum_size = Vector2(340, 260)
	info_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	info_scroll.add_child(contract_info)
	hb.add_child(info_scroll)
	var bb := HBoxContainer.new()
	bb.alignment = BoxContainer.ALIGNMENT_END
	bb.add_child(_button("Close", func() -> void: contracts_panel.visible = false))
	contract_start = _button("Start contract", func() -> void:
		var sel := contracts_list.get_selected_items()
		if sel.size() > 0:
			contracts_panel.visible = false
			main.start_contract(Contracts.LIST[sel[0]]["id"]))
	bb.add_child(contract_start)
	v.add_child(bb)

	brief_panel = _dialog("Brief")
	var bv: VBoxContainer = brief_panel.get_child(0)
	brief_label = Label.new()
	brief_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	brief_label.custom_minimum_size = Vector2(minf(440.0, root.size.x - 60.0) if root.size.x > 100.0 else 440.0, 0)
	bv.add_child(brief_label)
	var bbb := HBoxContainer.new()
	bbb.alignment = BoxContainer.ALIGNMENT_END
	bbb.add_child(_button("Start building", func() -> void: brief_panel.visible = false))
	bv.add_child(bbb)


func show_contracts() -> void:
	var progress: ProgressStore = main.progress
	contracts_list.clear()
	for i in Contracts.LIST.size():
		var c: Dictionary = Contracts.LIST[i]
		var stars := progress.best(c["id"])
		var label := "%d. %s" % [i + 1, c["title"]]
		if not progress.is_available(i):
			label += "  (locked)"
		elif stars > 0:
			label += "  %s" % "*".repeat(stars)
		contracts_list.add_item(label)
	(contracts_panel.get_child(0).get_node("Total") as Label).text = "Stars earned: %d of %d" % [progress.total_stars(), Contracts.LIST.size() * 3]
	var pick := 0
	for i in Contracts.LIST.size():
		if progress.is_available(i):
			pick = i
	contracts_list.select(pick)
	_on_contract_selected(pick)
	_open(contracts_panel)


func _on_contract_selected(i: int) -> void:
	var progress: ProgressStore = main.progress
	var c: Dictionary = Contracts.LIST[i]
	contract_info.text = _brief_text(c) + ("\n\nBest: %d of 3 stars" % progress.best(c["id"]) if progress.best(c["id"]) > 0 else "")
	contract_start.disabled = not progress.is_available(i)
	if not progress.is_available(i):
		contract_info.text += "\n\nFinish the previous contract to open this one."


func _brief_text(c: Dictionary) -> String:
	var t := "%s\n%s\n\nCoaster: %s · Site: %s · Budget: %s\nGoals:" % [c["title"], c["brief"],
		CoasterTypes.type_name(c["type"]), TerrainData.PRESET_NAMES[c["terrain"]], CostModel.money(c["budget"])]
	for g in c["goals"]:
		t += "\n  %s%s" % ["Bonus: " if g.get("bonus", false) else "- ", Contracts.goal_text(g)]
	if c.has("unlocks"):
		t += "\nReward: unlocks the %s coaster" % CoasterTypes.type_name(c["unlocks"])
	return t


func show_brief(c: Dictionary) -> void:
	brief_label.text = _brief_text(c) + "\n\nThe station and a small starter loop are in place. Build out from there; the stats panel tracks every goal live."
	_open(brief_panel)


func show_contract_result(c: Dictionary, res: Dictionary, before: int, unlocked: int, next_id: String) -> void:
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 4)
	var title := Label.new()
	var stars: int = res["stars"]
	title.text = "Contract: %s  -  %s" % [c["title"], ("%d of 3 stars" % stars) if res["passed"] else "not met yet"]
	title.add_theme_font_size_override("font_size", 22)
	title.add_theme_color_override("font_color", Color(1.0, 0.85, 0.3) if res["passed"] else Color(1.0, 0.55, 0.5))
	box.add_child(title)
	for g in res["goals"]:
		var l := Label.new()
		var ok: bool = g["ok"]
		l.text = "%s  %s%s  (%s)" % ["YES" if ok else "NO ", "Bonus: " if g["bonus"] else "", g["text"], g["detail"]]
		l.add_theme_font_size_override("font_size", 15)
		l.add_theme_color_override("font_color", Color(0.5, 0.95, 0.5) if ok else (Color(1.0, 0.8, 0.3) if g["bonus"] else Color(1.0, 0.5, 0.45)))
		box.add_child(l)
	if stars > before and before > 0:
		box.add_child(_note("New best: %d stars (was %d)." % [stars, before]))
	if unlocked >= 0:
		box.add_child(_note("Unlocked: the %s coaster! Try it in the sandbox or the next contracts." % CoasterTypes.type_name(unlocked)))
	if res["passed"] and next_id != "":
		box.add_child(_button("Next contract: %s" % Contracts.find(next_id)["title"], func() -> void: main.start_contract(next_id)))
	results_box.add_child(box)
	results_box.move_child(box, 2)


func _note(text: String) -> Label:
	var l := Label.new()
	l.text = text
	l.add_theme_font_size_override("font_size", 17)
	l.add_theme_color_override("font_color", Color(1.0, 0.85, 0.3))
	l.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	return l
