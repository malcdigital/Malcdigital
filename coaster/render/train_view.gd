class_name TrainView
extends Node3D
## The visible train: cars placed along the spline from the TrainSim state,
## with four reacting riders per car.

const RIDERS_PER_ROW := 2
const ROWS := 2

var cars: Array[Node3D] = []
var riders: Array[Rider] = []   # car-major order
var _num_cars := 0


func build(num_cars: int) -> void:
	for c in get_children():
		c.queue_free()
	cars.clear()
	riders.clear()
	_num_cars = num_cars
	var body_mat := StandardMaterial3D.new()
	body_mat.albedo_color = Color(0.95, 0.75, 0.1)
	body_mat.metallic = 0.3
	body_mat.roughness = 0.4
	var dark := StandardMaterial3D.new()
	dark.albedo_color = Color(0.12, 0.12, 0.14)
	var body := BoxMesh.new()
	body.size = Vector3(1.6, 0.5, 2.3)
	body.material = body_mat
	var seat := BoxMesh.new()
	seat.size = Vector3(1.4, 0.7, 0.18)
	seat.material = dark
	var bogie := BoxMesh.new()
	bogie.size = Vector3(1.3, 0.25, 0.6)
	bogie.material = dark
	var nose := PrismMesh.new()
	nose.size = Vector3(1.5, 0.7, 0.3)  # rotated below: y = length, z = height
	nose.material = dark
	var seed_value := 17
	for i in num_cars:
		var car := Node3D.new()
		add_child(car)
		cars.append(car)
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
				var r := Rider.new()
				car.add_child(r)
				r.position = Vector3(-0.36 + 0.72 * side, -0.5, z)
				r.setup(seed_value)
				seed_value += 31
				riders.append(r)


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
				riders[i * per_car + j].feel(g.x, g.y, absf(sim.v), dt)


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
