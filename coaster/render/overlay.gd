class_name TrackOverlay
extends RefCounted
## Colours for the track spine in the editor: the live readout of speed and
## G-forces painted directly onto the track.

enum Mode { ZONES, SPEED, VERTICAL, LATERAL, PAINT }

const NAMES := ["Comfort zones", "Speed", "Vertical G", "Lateral G", "Plain paint"]
const PAINT := Color(0.9, 0.35, 0.12)
const UNVISITED := Color(0.35, 0.35, 0.38)


static func colors(mode: int, spline: TrackSpline, record: RideRecord, g_scale: float = 1.0, paint_color: Color = PAINT) -> PackedColorArray:
	var out := PackedColorArray()
	if spline == null:
		return out
	out.resize(spline.count)
	var paint := paint_color
	for k in spline.count:
		if mode == Mode.PAINT or record == null:
			out[k] = paint
			continue
		if record.sample_visited[k] == 0:
			out[k] = UNVISITED
			continue
		var vg := record.sample_g_vert[k]
		var lg := record.sample_g_lat[k]
		match mode:
			Mode.ZONES:
				out[k] = GLimits.zone_color(GLimits.combined_zone(vg, lg, g_scale))
			Mode.SPEED:
				out[k] = GLimits.speed_color(record.sample_speed[k])
			Mode.VERTICAL:
				out[k] = GLimits.zone_color(GLimits.vertical_zone(vg, g_scale))
			Mode.LATERAL:
				out[k] = GLimits.zone_color(GLimits.lateral_zone(lg, g_scale))
	return out
