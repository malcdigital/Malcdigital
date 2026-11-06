class_name TrainView
extends Node3D
## The visible train: cars placed along the spline from the TrainSim state,
## with four reacting riders per car.

const RIDERS_PER_ROW := 2
const ROWS := 2

var cars: Array[Node3D] = []
var riders: Array[Rider] = []   # car-major order
var _num_cars := 0


var _offset_g := false   # wing seats feel forces from their own position


## Build the train for a coaster type (CoasterTypes dictionary).
func build(num_cars: int, ty: Dictionary = {}) -> void:
	if ty.is_empty():
		ty = CoasterTypes.get_type(CoasterTypes.Id.STEEL)
	for c in get_children():
		c.queue_free()
	cars.clear()
	riders.clear()
	_num_cars = num_cars
	_offset_g = float(ty["seat_offset"]) > 0.0
	var body_mat := StandardMaterial3D.new()
	body_mat.albedo_color = ty["car"]
	body_mat.metallic = 0.3
	body_mat.roughness = 0.4
	var dark := StandardMaterial3D.new()
	dark.albedo_color = Color(0.12, 0.12, 0.14)
	var seat := BoxMesh.new()
	seat.size = Vector3(1.4, 0.7, 0.18)
	seat.material = dark
	var bogie := BoxMesh.new()
	bogie.size = Vector3(1.3, 0.25, 0.6)
	bogie.material = dark
	var nose := PrismMesh.new()
	nose.size = Vector3(1.5, 0.7, 0.3)  # rotated below: y = length, z = height
	nose.material = dark
	var style: String = ty["style"]
	var wing := float(ty["seat_offset"]) > 0.0
	var seed_value := 17
	for i in num_cars:
		var car := Node3D.new()
		add_child(car)
		cars.append(car)
		if style == "flying":
			# Carrier above the riders, hanging from the rails overhead.
			var body := BoxMesh.new()
			body.size = Vector3(1.6, 0.35, 2.3)
			body.material = body_mat
			_mesh(car, body, Vector3(0, 0.45, 0))
			_mesh(car, bogie, Vector3(0, 0.95, -0.7))
			_mesh(car, bogie, Vector3(0, 0.95, 0.7))
			for row in 2:
				for side in 2:
					var r := _rider(car, Vector3(-0.38 + 0.76 * side, -0.05, -0.55 + 1.0 * row), seed_value)
					r.rotation_degrees.x = -90.0   # lying face down, head forward
					seed_value += 31
		elif wing:
			# Narrow centre body with seats out on wings either side.
			var body := BoxMesh.new()
			body.size = Vector3(0.9, 0.5, 2.1)
			body.material = body_mat
			_mesh(car, body, Vector3(0, -0.75, 0))
			_mesh(car, bogie, Vector3(0, -1.0, -0.7))
			_mesh(car, bogie, Vector3(0, -1.0, 0.7))
			var wing_mesh := BoxMesh.new()
			wing_mesh.size = Vector3(4.6, 0.12, 0.9)
			wing_mesh.material = body_mat
			_mesh(car, wing_mesh, Vector3(0, -0.55, 0))
			var wseat := BoxMesh.new()
			wseat.size = Vector3(1.3, 0.7, 0.16)
			wseat.material = dark
			for side in [-1.0, 1.0]:
				_mesh(car, wseat, Vector3(1.6 * side, -0.25, 0.38))
				for j in 2:
					_rider(car, Vector3(side * (1.25 + 0.7 * j), -0.5, 0.0), seed_value)
					seed_value += 31
		else:
			var body := BoxMesh.new()
			body.size = Vector3(1.6, 0.5, 2.3)
			body.material = body_mat
			_mesh(car, body, Vector3(0, -0.72, 0))
			_mesh(car, bogie, Vector3(0, -1.0, -0.7))
			_mesh(car, bogie, Vector3(0, -1.0, 0.7))
			if i == 0:
				var n := _mesh(car, nose, Vector3(0, -0.82, -1.5))
				n.rotation_degrees = Vector3(-90, 0, 0)
			for row in ROWS:
				var z := -0.45 + 0.9 * row
				_mesh(car, seat, Vector3(0, -0.25, z + 0.38))
				for side in RIDERS_PER_ROW:
					_rider(car, Vector3(-0.36 + 0.72 * side, -0.5, z), seed_value)
					seed_value += 31


func _rider(car: Node3D, pos: Vector3, seed_value: int) -> Rider:
	var r := Rider.new()
	car.add_child(r)
	r.position = pos
	r.setup(seed_value)
	riders.append(r)
	return r


func _mesh(parent: Node3D, mesh: Mesh, pos: Vector3) -> MeshInstance3D:
	var mi := MeshInstance3D.new()
	mi.mesh = mesh
	mi.position = pos
	parent.add_child(mi)
	return mi


## Position cars from the sim. `react` also drives rider reactions.
func update_from_sim(sim: TrainSim, dt: float, react: bool) -> void:
	var per_car := RIDERS_PER_ROW * ROWS
	for i in cars.size():
		var cs := sim.car_s(i)
		cars[i].transform = sim.spline.transform_at(cs)
		if react:
			var g := sim.spline.g_forces_at(cs, sim.v, sim.a_t)
			for j in per_car:
				var rider := riders[i * per_car + j]
				if _offset_g:
					var go := sim.spline.g_forces_offset(cs, sim.v, sim.a_t, rider.position.x)
					rider.feel(go.x, go.y, absf(sim.v), dt)
				else:
					rider.feel(g.x, g.y, absf(sim.v), dt)


func place_at(spline: TrackSpline, front_s: float, spacing: float) -> void:
	for i in cars.size():
		cars[i].transform = spline.transform_at(front_s - spacing * i)


func reset_riders() -> void:
	for r in riders:
		r.reset()


## Number of riders that started screaming this frame.
func screams_started() -> int:
	var n := 0
	for r in riders:
		if r.scream_started:
			n += 1
	return n


func sick_count() -> int:
	var n := 0
	for r in riders:
		if r.mood == Rider.Mood.SICK:
			n += 1
	return n
