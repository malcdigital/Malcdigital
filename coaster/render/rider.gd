class_name Rider
extends Node3D
## A simple low-poly rider who reacts to the forces they feel.
## Built from primitives so there are no assets to load. All materials and
## meshes are shared between riders (static), so a train of riders costs a
## handful of draw calls and no per-frame allocation.

enum Mood { CALM, HANDS_UP, SCREAM, GRIP, SICK }

static var _meshes := {}
static var _skin: StandardMaterial3D
static var _sick: StandardMaterial3D
static var _mouth_mat: StandardMaterial3D
static var _shirts: Array[StandardMaterial3D] = []

var mood: int = Mood.CALM
## 0 = terrified, 1 = fearless. Decides how a rider reacts.
var bravery := 0.5
## Builds up with sloshing and harsh forces; past the rider's limit they get sick.
var nausea := 0.0
## Set for one frame when this rider starts screaming (for audio).
var scream_started := false

var _hold := 0.0
var _time := 0.0
var _head: MeshInstance3D
var _mouth: MeshInstance3D
var _torso: Node3D
var _arm_l: Node3D
var _arm_r: Node3D
# Current animated pose.
var _arm_pitch := 70.0
var _arm_spread := 0.0
var _lean := 0.0
var _head_tilt := 0.0
var _mouth_open := 0.0


static func _init_shared() -> void:
	if _skin != null:
		return
	_skin = StandardMaterial3D.new()
	_skin.albedo_color = Color(0.93, 0.76, 0.62)
	_sick = StandardMaterial3D.new()
	_sick.albedo_color = Color(0.55, 0.8, 0.35)
	_mouth_mat = StandardMaterial3D.new()
	_mouth_mat.albedo_color = Color(0.25, 0.05, 0.05)
	for c in [Color(0.2, 0.45, 0.9), Color(0.9, 0.25, 0.3), Color(0.25, 0.7, 0.4), Color(0.95, 0.75, 0.2), Color(0.6, 0.35, 0.8), Color(0.15, 0.15, 0.18)]:
		var m := StandardMaterial3D.new()
		m.albedo_color = c
		_shirts.append(m)
	var torso := CapsuleMesh.new()
	torso.radius = 0.17
	torso.height = 0.62
	torso.radial_segments = 8
	torso.rings = 2
	var head := SphereMesh.new()
	head.radius = 0.13
	head.height = 0.27
	head.radial_segments = 10
	head.rings = 6
	var arm := CapsuleMesh.new()
	arm.radius = 0.05
	arm.height = 0.5
	arm.radial_segments = 6
	arm.rings = 1
	var mouth := SphereMesh.new()
	mouth.radius = 0.045
	mouth.height = 0.09
	mouth.radial_segments = 6
	mouth.rings = 3
	_meshes = {"torso": torso, "head": head, "arm": arm, "mouth": mouth}


func setup(seed_value: int) -> void:
	_init_shared()
	var rng := RandomNumberGenerator.new()
	rng.seed = seed_value
	bravery = rng.randf()
	var shirt := _shirts[rng.randi() % _shirts.size()]
	_torso = Node3D.new()
	add_child(_torso)
	var body := MeshInstance3D.new()
	body.mesh = _meshes["torso"]
	body.material_override = shirt
	body.position = Vector3(0, 0.3, 0)
	_torso.add_child(body)
	_head = MeshInstance3D.new()
	_head.mesh = _meshes["head"]
	_head.material_override = _skin
	_head.position = Vector3(0, 0.74, 0)
	_torso.add_child(_head)
	_mouth = MeshInstance3D.new()
	_mouth.mesh = _meshes["mouth"]
	_mouth.material_override = _mouth_mat
	_mouth.position = Vector3(0, -0.04, -0.115)
	_mouth.scale = Vector3(1, 0.2, 0.5)
	_head.add_child(_mouth)
	_arm_l = _make_arm(shirt, -0.22)
	_arm_r = _make_arm(shirt, 0.22)
	for mi in [body, _head, _mouth]:
		mi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF


func _make_arm(mat: Material, x: float) -> Node3D:
	var pivot := Node3D.new()
	pivot.position = Vector3(x, 0.55, 0)
	_torso.add_child(pivot)
	var mi := MeshInstance3D.new()
	mi.mesh = _meshes["arm"]
	mi.material_override = mat
	mi.position = Vector3(0, -0.25, 0)
	mi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	pivot.add_child(mi)
	return pivot


func reset() -> void:
	nausea = 0.0
	mood = Mood.CALM
	_hold = 0.0
	_head.material_override = _skin


## Called every frame with what this rider feels: vertical and lateral G (g)
## and speed (m/s).
func feel(vg: float, lg: float, speed: float, dt: float) -> void:
	scream_started = false
	_time += dt
	# Nausea builds from sideways sloshing, crushing G and negative G, and
	# slowly fades. Braver riders have stronger stomachs.
	nausea += dt * (maxf(absf(lg) - 0.5, 0.0) * 0.7 + maxf(vg - 3.0, 0.0) * 0.35 + (0.25 if vg < -0.3 else 0.0))
	nausea = maxf(nausea - dt * 0.03, 0.0)
	if mood != Mood.SICK and nausea > 1.6 + bravery * 2.5:
		_set_mood(Mood.SICK)
	_hold -= dt
	if mood != Mood.SICK and _hold <= 0.0:
		var want := Mood.CALM
		if vg < 0.25:
			want = Mood.HANDS_UP if bravery > 0.45 else Mood.SCREAM
		elif vg > 3.0 or absf(lg) > 0.9:
			want = Mood.SCREAM if bravery > 0.6 else Mood.GRIP
		elif speed > 18.0 and bravery > 0.7:
			want = Mood.HANDS_UP
		elif speed > 14.0 and bravery < 0.25:
			want = Mood.GRIP
		if want != mood:
			_set_mood(want)
	_animate(dt)


func _set_mood(m: int) -> void:
	if m == Mood.SCREAM and mood != Mood.SCREAM:
		scream_started = true
	mood = m
	_hold = 0.8
	_head.material_override = _sick if m == Mood.SICK else _skin


func _animate(dt: float) -> void:
	# Target pose for the current mood (degrees / unitless).
	var pitch := 70.0      # arms forward holding the lap bar
	var spread := 0.0
	var lean := 0.0
	var tilt := 0.0
	var mouth := 0.1
	match mood:
		Mood.HANDS_UP:
			pitch = 165.0 + sin(_time * 7.0) * 8.0
			spread = 18.0
			tilt = -10.0
			mouth = 0.5
		Mood.SCREAM:
			pitch = 135.0 + sin(_time * 11.0) * 10.0
			spread = 35.0
			tilt = -22.0
			mouth = 1.0
		Mood.GRIP:
			pitch = 85.0
			spread = -6.0
			lean = 12.0
			tilt = 15.0
			mouth = 0.0
		Mood.SICK:
			pitch = 25.0
			spread = -10.0
			lean = 22.0
			tilt = 30.0
			mouth = 0.3 + 0.2 * sin(_time * 3.0)
	var w := 1.0 - exp(-10.0 * dt)
	_arm_pitch = lerpf(_arm_pitch, pitch, w)
	_arm_spread = lerpf(_arm_spread, spread, w)
	_lean = lerpf(_lean, lean, w)
	_head_tilt = lerpf(_head_tilt, tilt, w)
	_mouth_open = lerpf(_mouth_open, mouth, w)
	_arm_l.rotation = Vector3(deg_to_rad(_arm_pitch), 0.0, deg_to_rad(-_arm_spread))
	_arm_r.rotation = Vector3(deg_to_rad(_arm_pitch), 0.0, deg_to_rad(_arm_spread))
	_torso.rotation.x = deg_to_rad(-_lean)
	_head.rotation.x = deg_to_rad(-_head_tilt)
	_mouth.scale = Vector3(1.0, 0.2 + _mouth_open, 0.5)
