class_name RideRecord
extends RefCounted
## Time series captured during a simulated ride, consumed by RideScorer.
## Arrays are pre-sized once (no growth during the ride) and `size` says how
## many entries are valid.

var size := 0
var interval := 1.0 / 60.0   # seconds between entries

var s := PackedFloat32Array()        # unwrapped distance travelled (m) of the middle car
var speed := PackedFloat32Array()    # m/s (signed: negative = rolling back)
var g_vert := PackedFloat32Array()   # vertical G
var g_lat := PackedFloat32Array()    # lateral G
var g_long := PackedFloat32Array()   # longitudinal G
var height := PackedFloat32Array()   # m
var roll := PackedFloat32Array()     # track roll (radians) under the middle car

## Per track sample (indexed like TrackSpline arrays): what the middle car felt
## the last time it passed that sample. Drives the colour overlay in the editor.
var sample_speed := PackedFloat32Array()
var sample_g_vert := PackedFloat32Array()
var sample_g_lat := PackedFloat32Array()
var sample_visited := PackedByteArray()

var completed := false
var stalled := false
var stall_s := -1.0          # where the train first started rolling back (m, wrapped)
var rollbacks := 0
var duration := 0.0


func allocate(capacity: int, track_samples: int) -> void:
	for arr in [s, speed, g_vert, g_lat, g_long, height, roll]:
		arr.resize(capacity)
	sample_speed.resize(track_samples)
	sample_g_vert.resize(track_samples)
	sample_g_lat.resize(track_samples)
	sample_visited.resize(track_samples)
	sample_speed.fill(0.0)
	sample_g_vert.fill(1.0)
	sample_g_lat.fill(0.0)
	sample_visited.fill(0)
	size = 0


func capacity() -> int:
	return s.size()
