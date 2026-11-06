class_name GLimits
extends RefCounted
## Comfort zones used for the colour overlay, rider reactions and problem spots.
## Numbers follow the spirit of ride-design guidance (e.g. ASTM F2291): brief
## +5 g is the practical ceiling, -1.5 g is very harsh, and over ~1.5 g lateral
## is painful in a normal coaster seat.

enum Zone { SAFE, INTENSE, DANGER }

const VERT_SAFE_MIN := -0.5
const VERT_SAFE_MAX := 3.5
const VERT_INTENSE_MIN := -1.2
const VERT_INTENSE_MAX := 5.0
const LAT_SAFE := 0.8
const LAT_INTENSE := 1.5

const COLOR_SAFE := Color(0.25, 0.85, 0.35)
const COLOR_INTENSE := Color(1.0, 0.82, 0.15)
const COLOR_DANGER := Color(0.95, 0.2, 0.2)


## `scale` shrinks the limits for coaster types whose riders tolerate less
## (flying riders lie in a harness: scale 0.82). 1 g itself is always safe.
static func vertical_zone(g: float, scale: float = 1.0) -> int:
	if g < VERT_INTENSE_MIN * scale or g > 1.0 + (VERT_INTENSE_MAX - 1.0) * scale:
		return Zone.DANGER
	if g < VERT_SAFE_MIN * scale or g > 1.0 + (VERT_SAFE_MAX - 1.0) * scale:
		return Zone.INTENSE
	return Zone.SAFE


static func lateral_zone(g: float, scale: float = 1.0) -> int:
	var a := absf(g)
	if a > LAT_INTENSE * scale:
		return Zone.DANGER
	if a > LAT_SAFE * scale:
		return Zone.INTENSE
	return Zone.SAFE


static func combined_zone(vert: float, lat: float, scale: float = 1.0) -> int:
	return maxi(vertical_zone(vert, scale), lateral_zone(lat, scale))


static func zone_color(zone: int) -> Color:
	match zone:
		Zone.DANGER: return COLOR_DANGER
		Zone.INTENSE: return COLOR_INTENSE
	return COLOR_SAFE


## Smooth colour for speed overlays: blue (slow) -> green -> yellow -> red (fast).
static func speed_color(v: float, v_max: float = 35.0) -> Color:
	var t := clampf(absf(v) / v_max, 0.0, 1.0)
	if t < 0.33:
		return Color(0.2, 0.45, 0.95).lerp(COLOR_SAFE, t / 0.33)
	if t < 0.66:
		return COLOR_SAFE.lerp(COLOR_INTENSE, (t - 0.33) / 0.33)
	return COLOR_INTENSE.lerp(COLOR_DANGER, (t - 0.66) / 0.34)
