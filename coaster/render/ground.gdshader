shader_type spatial;
// Grass-coloured ground with a faint 10 m grid for judging size and height.

uniform vec3 grass_a : source_color = vec3(0.24, 0.42, 0.19);
uniform vec3 grass_b : source_color = vec3(0.21, 0.38, 0.17);
uniform vec3 line_color : source_color = vec3(0.32, 0.5, 0.26);

varying vec3 world_pos;

void vertex() {
	world_pos = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
}

float grid(vec2 p, float spacing, float width) {
	vec2 fw = fwidth(p / spacing);
	vec2 g = abs(fract(p / spacing - 0.5) - 0.5) / fw;
	float line = 1.0 - clamp(min(g.x, g.y) - width, 0.0, 1.0);
	// Fade out once grid cells are only a few pixels wide (avoids a solid sheen).
	return line * (1.0 - smoothstep(0.05, 0.25, max(fw.x, fw.y)));
}

void fragment() {
	vec2 p = world_pos.xz;
	// Large checker patches break up the flat colour.
	float checker = mod(floor(p.x / 40.0) + floor(p.y / 40.0), 2.0);
	vec3 col = mix(grass_a, grass_b, checker);
	float fade = clamp(1.0 - length(p) / 900.0, 0.0, 1.0);
	col = mix(col, line_color, grid(p, 10.0, 0.5) * 0.6 * fade);
	ALBEDO = col;
	ROUGHNESS = 0.95;
}
