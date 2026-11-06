class_name ProceduralAudio
extends RefCounted
## Placeholder sounds synthesised at startup, so the project ships with no
## audio files: chain-lift clack, wind and track roar loops, and a scream.

const RATE := 22050


static func _to_wav(samples: PackedFloat32Array, loop: bool) -> AudioStreamWAV:
	var bytes := PackedByteArray()
	bytes.resize(samples.size() * 2)
	for i in samples.size():
		bytes.encode_s16(i * 2, int(clampf(samples[i], -1.0, 1.0) * 32000.0))
	var w := AudioStreamWAV.new()
	w.format = AudioStreamWAV.FORMAT_16_BITS
	w.mix_rate = RATE
	w.stereo = false
	w.data = bytes
	if loop:
		w.loop_mode = AudioStreamWAV.LOOP_FORWARD
		w.loop_begin = 0
		w.loop_end = samples.size()
	return w


## Seamless loop: crossfade the tail into the head.
static func _make_loopable(s: PackedFloat32Array, fade: int) -> PackedFloat32Array:
	var n := s.size() - fade
	var out := PackedFloat32Array()
	out.resize(n)
	for i in n:
		out[i] = s[i]
	for i in fade:
		var t := float(i) / float(fade)
		out[i] = s[i] * t + s[n + i] * (1.0 - t)
	return out


## Filtered noise: one-pole low-pass at `lp` Hz minus a low-pass at `hp` Hz.
static func _noise(seconds: float, lp: float, hp: float, seed_value: int) -> PackedFloat32Array:
	var rng := RandomNumberGenerator.new()
	rng.seed = seed_value
	var n := int(seconds * RATE)
	var out := PackedFloat32Array()
	out.resize(n)
	var a_lp := 1.0 - exp(-TAU * lp / RATE)
	var a_hp := 1.0 - exp(-TAU * hp / RATE)
	var y1 := 0.0
	var y2 := 0.0
	var peak := 1e-6
	for i in n:
		var x := rng.randf_range(-1.0, 1.0)
		y1 += a_lp * (x - y1)
		y2 += a_hp * (y1 - y2)
		out[i] = y1 - y2 if hp > 0.0 else y1
		peak = maxf(peak, absf(out[i]))
	for i in n:
		out[i] /= peak
	return out


static func wind() -> AudioStreamWAV:
	return _to_wav(_make_loopable(_noise(2.2, 1800.0, 250.0, 7), 2000), true)


static func roar() -> AudioStreamWAV:
	return _to_wav(_make_loopable(_noise(2.2, 140.0, 25.0, 11), 2000), true)


static func clack() -> AudioStreamWAV:
	var n := int(0.09 * RATE)
	var out := PackedFloat32Array()
	out.resize(n)
	var rng := RandomNumberGenerator.new()
	rng.seed = 3
	for i in n:
		var t := float(i) / RATE
		var env := exp(-t * 70.0)
		out[i] = (rng.randf_range(-1.0, 1.0) * 0.6 + sin(TAU * 190.0 * t) * 0.8) * env
	return _to_wav(out, false)


## A rough "aaah": a buzzy source at a wobbling pitch through two vowel-ish
## formant resonances, with breath noise and a rise-and-fall contour.
static func scream() -> AudioStreamWAV:
	var seconds := 1.5
	var n := int(seconds * RATE)
	var out := PackedFloat32Array()
	out.resize(n)
	var rng := RandomNumberGenerator.new()
	rng.seed = 5
	var phase := 0.0
	var f1 := _Resonator.new(850.0, 90.0)
	var f2 := _Resonator.new(1250.0, 120.0)
	var peak := 1e-6
	for i in n:
		var t := float(i) / RATE
		var contour := sin(PI * clampf(t / seconds, 0.0, 1.0))
		var f0 := 520.0 + 260.0 * contour + 35.0 * sin(TAU * 7.0 * t)
		phase = fmod(phase + f0 / RATE, 1.0)
		var src := (phase * 2.0 - 1.0) + rng.randf_range(-0.3, 0.3)
		var y := f1.process(src) + 0.6 * f2.process(src)
		var env := minf(t / 0.06, 1.0) * minf((seconds - t) / 0.45, 1.0)
		out[i] = y * env
		peak = maxf(peak, absf(out[i]))
	for i in n:
		out[i] = out[i] / peak * 0.8
	return _to_wav(out, false)


## Two-pole resonant band-pass filter.
class _Resonator:
	var b0: float
	var a1: float
	var a2: float
	var y1 := 0.0
	var y2 := 0.0

	func _init(freq: float, bandwidth: float) -> void:
		var r := exp(-PI * bandwidth / RATE)
		a1 = 2.0 * r * cos(TAU * freq / RATE)
		a2 = -r * r
		b0 = 1.0 - r

	func process(x: float) -> float:
		var y := b0 * x + a1 * y1 + a2 * y2
		y2 = y1
		y1 = y
		return y
