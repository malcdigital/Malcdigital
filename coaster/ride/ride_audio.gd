class_name RideAudio
extends Node
## Drives the placeholder ride sounds from the train state.

var _wind: AudioStreamPlayer
var _roar: AudioStreamPlayer
var _clack: AudioStreamPlayer
var _scream: AudioStreamPlayer
var _clack_dist := 0.0
var _scream_cooldown := 0.0
var _last_s := 0.0
var _rng := RandomNumberGenerator.new()


func _ready() -> void:
	_wind = _player(ProceduralAudio.wind(), 1)
	_roar = _player(ProceduralAudio.roar(), 1)
	_clack = _player(ProceduralAudio.clack(), 2)
	_scream = _player(ProceduralAudio.scream(), 4)


func _player(stream: AudioStream, polyphony: int) -> AudioStreamPlayer:
	var p := AudioStreamPlayer.new()
	p.stream = stream
	p.max_polyphony = polyphony
	p.volume_db = -80.0
	add_child(p)
	return p


func start(sim: TrainSim) -> void:
	_last_s = sim.s
	_clack_dist = 0.0
	_wind.volume_db = -80.0
	_roar.volume_db = -80.0
	_wind.play()
	_roar.play()


func stop() -> void:
	_wind.stop()
	_roar.stop()


func update(sim: TrainSim, screams: int, dt: float) -> void:
	var speed := absf(sim.v)
	# Wind rises with speed (roughly v² aerodynamic noise, in dB).
	var w := clampf(speed / 30.0, 0.0, 1.2)
	_wind.volume_db = lerpf(_wind.volume_db, linear_to_db(maxf(w * w, 0.0001)) - 4.0, 1.0 - exp(-6.0 * dt))
	_wind.pitch_scale = 0.7 + w * 0.6
	var r := clampf(speed / 25.0, 0.0, 1.0)
	_roar.volume_db = lerpf(_roar.volume_db, linear_to_db(maxf(r, 0.0001)) - 6.0, 1.0 - exp(-6.0 * dt))
	_roar.pitch_scale = 0.6 + r * 0.8

	# Chain dog clack every ~0.5 m while any part of the train is on a lift.
	var moved := absf(sim.s - _last_s)
	_last_s = sim.s
	if sim.spline.segment_at(sim.middle_s()) == TrackPoint.Segment.LIFT:
		_clack_dist += moved
		if _clack_dist > 0.5:
			_clack_dist = 0.0
			_clack.volume_db = -6.0
			_clack.pitch_scale = _rng.randf_range(0.95, 1.05)
			_clack.play()

	_scream_cooldown -= dt
	if screams > 0 and _scream_cooldown <= 0.0:
		_scream_cooldown = 0.35
		_scream.volume_db = -8.0 + minf(screams, 4) * 1.5
		_scream.pitch_scale = _rng.randf_range(0.85, 1.35)
		_scream.play()
