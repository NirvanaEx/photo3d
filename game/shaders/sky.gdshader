shader_type sky;

// Небо «Архипелага»: градиент купола, кучевые облака и солнечный диск.
//
// Зачем своё вместо ProceduralSkyMaterial: у встроенного неба нет облаков, а на
// общем плане небо занимает треть кадра. Пустой градиент там читается как
// заливка в графическом редакторе - облака дают и масштаб, и ощущение движения,
// а геометрии стоят ноль: всё считается по направлению взгляда.
//
// Облака проецируются на воображаемую плоскость на высоте: направление взгляда
// делится на свою вертикальную составляющую (dir.xz / dir.y). Отсюда честная
// перспектива - у горизонта облака сплющиваются и сходятся, как настоящий слой.

uniform vec3 top_color : source_color = vec3(0.11, 0.40, 0.84);
uniform vec3 mid_color : source_color = vec3(0.36, 0.67, 0.95);
uniform vec3 horizon_color : source_color = vec3(0.82, 0.92, 0.98);
uniform vec3 ground_color : source_color = vec3(0.30, 0.52, 0.70);
uniform vec3 cloud_lit : source_color = vec3(1.0, 0.99, 0.96);
uniform vec3 cloud_dark : source_color = vec3(0.55, 0.63, 0.78);
uniform float cloud_cover : hint_range(0.0, 1.0) = 0.44;
uniform float cloud_opacity : hint_range(0.0, 1.0) = 0.92;
uniform float cloud_scale = 1.25;
uniform float cloud_speed = 0.004;
uniform float sun_glow = 0.30;


float hash21(vec2 p) {
	p = fract(p * vec2(123.34, 456.21));
	p += dot(p, p + 45.32);
	return fract(p.x * p.y);
}


float vnoise(vec2 p) {
	vec2 i = floor(p);
	vec2 f = fract(p);
	f = f * f * (3.0 - 2.0 * f);
	float a = hash21(i);
	float b = hash21(i + vec2(1.0, 0.0));
	float c = hash21(i + vec2(0.0, 1.0));
	float d = hash21(i + vec2(1.0, 1.0));
	return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}


float fbm(vec2 p) {
	float s = 0.0;
	float a = 0.5;
	for (int i = 0; i < 5; i++) {
		s += a * vnoise(p);
		p = p * 2.07 + vec2(11.3, 7.9);
		a *= 0.5;
	}
	return s;
}


// Плотность облака, 0..1. Домен искажается сам собой: без этого fbm даёт
// ровный «ковёр» из пятен, а не кучевые облака с рваным краем и просветами.
float clouds(vec2 uv) {
	vec2 w = vec2(fbm(uv * 0.55), fbm(uv * 0.55 + 5.2));
	return smoothstep(cloud_cover, cloud_cover + 0.26, fbm(uv + w * 1.15));
}


void sky() {
	vec3 dir = normalize(EYEDIR);
	float up = dir.y;

	// Три полосы, а не две: над головой небо заметно глубже, чем на полпути к
	// горизонту, и один градиент на весь купол эту разницу съедает.
	vec3 col = mix(horizon_color, mid_color, smoothstep(0.0, 0.24, up));
	col = mix(col, top_color, smoothstep(0.20, 0.78, up));
	col = mix(ground_color, col, smoothstep(-0.07, 0.02, up));

	vec2 sun_flat = vec2(1.0, 0.0);
	if (LIGHT0_ENABLED) {
		sun_flat = normalize(LIGHT0_DIRECTION.xz + vec2(1e-4, 1e-4));
		float a = clamp(dot(dir, LIGHT0_DIRECTION), -1.0, 1.0);
		// Ореол: небо рядом с солнцем всегда светлее и теплее самого купола.
		col += LIGHT0_COLOR * sun_glow * pow(max(a, 0.0), 22.0);
		float ang = acos(a);
		col = mix(col, LIGHT0_COLOR * 2.6,
			1.0 - smoothstep(LIGHT0_SIZE * 0.6, LIGHT0_SIZE * 1.7, ang));
	}

	if (up > 0.004) {
		// max() в знаменателе обязателен: у самого горизонта dir.y стремится к
		// нулю, и без ограничителя координата улетает в бесконечность - слой
		// облаков рассыпается в мерцающую кашу из отдельных пикселей.
		vec2 uv = dir.xz / max(up, 0.055) * cloud_scale + vec2(TIME * cloud_speed, 0.0);
		float dens = clouds(uv);
		// Свет по-простому: пробуем плотность на шаг В СТОРОНУ солнца. Там
		// плотнее - значит мы в тени соседнего кома; там просвет - значит это
		// освещённый край. Дёшево и читается как объём.
		float lit = clouds(uv + sun_flat * 0.4);
		float shade = clamp(1.0 - (lit - dens) * 2.4, 0.0, 1.0);
		vec3 cc = mix(cloud_dark, cloud_lit, 0.18 + 0.82 * shade);
		dens *= smoothstep(0.004, 0.17, up);   // у горизонта слой уходит за край
		col = mix(col, cc, dens * cloud_opacity);
	}

	COLOR = col;
}
