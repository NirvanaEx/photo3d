shader_type spatial;
render_mode blend_mix, depth_draw_never, cull_disabled, specular_schlick_ggx;

// Вода: волны Герстнера в вершинах, бегущий к берегу прибой, блики и рябь.
//
// Глубина берётся не из буфера глубины экрана, а из карты высот, которую и так
// построил генератор: она приезжает сюда текстурой (height_map). Так дешевле и
// честнее - подводный рельеф известен точно, а не восстанавливается из
// screen-space, где он зависит от того, что попало в кадр, и ломается на каждой
// смене проекции. Побочная выгода: пена у берега не мигает при движении камеры.
//
// Текстура читается ТЕМИ ЖЕ узлами, что и меш земли: сдвиг на полтексела
// заложен в формулу uv, иначе линия пены уезжает от берега на метр.

uniform sampler2D height_map : filter_linear, repeat_disable;
uniform float map_half = 102.4;      // половина стороны карты в метрах
uniform float cell_size = 1.6;       // шаг сетки высот
uniform float tex_size = 129.0;      // сторона текстуры в текселях

uniform vec3 shallow_color : source_color = vec3(0.35, 0.76, 0.78);
uniform vec3 deep_color : source_color = vec3(0.03, 0.19, 0.37);
uniform vec3 foam_color : source_color = vec3(0.95, 0.99, 1.0);
uniform vec3 sky_tint : source_color = vec3(0.62, 0.82, 0.95);
uniform float depth_scale = 4.5;     // на какой глубине цвет становится «дном»
uniform float wave_speed = 1.0;
uniform float wave_height = 0.30;
uniform float wave_steep = 0.55;     // острота гребней: 0 - синус, 1 - пик
uniform float ripple = 0.5;

// Прибой. edge - неподвижная кромка у самой воды, surf - полосы, бегущие к
// берегу: обе меряются в МЕТРАХ ПО ГОРИЗОНТАЛИ от уреза воды.
uniform float foam_edge = 1.2;
uniform float surf_reach = 12.0;     // как далеко от берега видны буруны
uniform float surf_length = 9.0;     // расстояние между гребнями прибоя
uniform float surf_speed = 3.0;

varying vec3 world_pos;


float ground_at(vec2 xz) {
	vec2 uv = ((xz + map_half) / cell_size + 0.5) / tex_size;
	return texture(height_map, uv).r;
}


// Расстояние по ГОРИЗОНТАЛИ до линии берега, метры.
//
// Считается как |высота| / |уклон| - первое приближение расстояния до нулевого
// уровня, точное для линейного склона. Нужно оно вот зачем: полоса прибоя
// шириной «полтора метра глубины» на пологом дне растягивается на пятьдесят
// метров по горизонтали, и остров получает белый ореол вместо кромки. В метрах
// по горизонтали ширина прибоя одинакова и у отмели, и у обрыва.
float shore_distance(vec2 xz, float h) {
	// Плечо шире одной клетки нарочно: билинейная фильтрация даёт производную,
	// постоянную внутри тексела, и по узкому плечу кромка пены получалась
	// ступенчатой - ровно по клеткам карты высот.
	float e = 2.5 * cell_size;
	float gx = ground_at(xz + vec2(e, 0.0)) - ground_at(xz - vec2(e, 0.0));
	float gz = ground_at(xz + vec2(0.0, e)) - ground_at(xz - vec2(0.0, e));
	float grad = length(vec2(gx, gz)) / (2.0 * e);
	return abs(h) / max(grad, 0.004);
}


// Волна Герстнера: точка ходит не вверх-вниз, а по окружности - вперёд на
// гребне и назад во впадине. Отсюда острые гребни и широкие ложбины, которых
// у суммы синусов не бывает: синус даёт одинаково круглую волну и читается
// как колышущаяся ткань.
//
// Возвращает смещение (x, y, z); складывать можно любое число волн.
vec3 gerstner(vec2 dir, float len, float amp, float steep, float speed,
		vec2 p, float t) {
	float k = TAU / len;
	vec2 d = normalize(dir);
	float phase = k * dot(d, p) - speed * k * t;
	float a = amp;
	// Крутизна делится на k*amp, иначе на длинных волнах гребень самопересекается.
	float q = steep / max(k * a * 3.0, 0.0001);
	return vec3(q * a * d.x * cos(phase), a * sin(phase), q * a * d.y * cos(phase));
}


vec3 waves(vec2 p, float t, float scale) {
	vec3 o = vec3(0.0);
	o += gerstner(vec2(1.0, 0.35), 27.0, 0.55 * scale, wave_steep, 1.00, p, t);
	o += gerstner(vec2(-0.4, 1.0), 17.0, 0.34 * scale, wave_steep, 1.25, p, t);
	o += gerstner(vec2(0.8, -0.7), 9.5, 0.19 * scale, wave_steep * 0.8, 1.6, p, t);
	o += gerstner(vec2(-0.9, -0.3), 5.5, 0.10 * scale, wave_steep * 0.6, 2.1, p, t);
	return o;
}


void vertex() {
	world_pos = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
	float t = TIME * wave_speed;

	// У самого берега волнение гасится: иначе кромка воды то заходит на песок,
	// то оголяет дно, и берег «дышит» на полметра.
	float shore = clamp(-ground_at(world_pos.xz) / 2.5, 0.0, 1.0);
	float amp = wave_height * shore;

	vec3 o = waves(world_pos.xz, t, amp);
	VERTEX += o;

	// Нормаль - по двум смещённым соседям, а не аналитически: производную
	// суммы Герстнеров пришлось бы держать в согласии с самой суммой при
	// каждой правке волн, а разностей хватает с запасом.
	float e = 1.2;
	vec3 px = vec3(e, 0.0, 0.0) + waves(world_pos.xz + vec2(e, 0.0), t, amp);
	vec3 pz = vec3(0.0, 0.0, e) + waves(world_pos.xz + vec2(0.0, e), t, amp);
	NORMAL = normalize(cross(pz - o, px - o));
}


void fragment() {
	float t = TIME * wave_speed;

	// Мелкая рябь живёт только в нормали: геометрию она бы не изменила
	// заметно, а блики от неё - половина вида воды. Вдали гасится: её период
	// меньше пикселя, и на горизонте она превращалась в мерцающую клетку.
	vec2 rp = world_pos.xz;
	float r1 = sin(rp.x * 1.30 + t * 3.0) * cos(rp.y * 1.10 - t * 2.4);
	float r2 = sin((rp.x + rp.y) * 0.90 - t * 2.0) * cos(rp.x * 0.70 + t * 1.7);
	float near_fade = 1.0 - smoothstep(60.0, 220.0, length(VERTEX));
	vec3 bump = vec3(r1, 0.0, r2) * ripple * near_fade * 0.06;
	vec3 n = normalize(NORMAL + (VIEW_MATRIX * vec4(bump, 0.0)).xyz);
	NORMAL = n;

	float ground = ground_at(world_pos.xz);
	float depth = max(0.0, -ground);
	float fade = clamp(depth / depth_scale, 0.0, 1.0);

	// Высота волны пересчитывается ЗДЕСЬ, а не приезжает varying-ом из вершины.
	// Через varying она интерполируется линейно, и порог «гребень» разрезал
	// треугольники по прямой: барашки выходили острыми белыми треугольниками
	// на четыре метра каждый - хорошо видно на кадре открытого моря.
	float amp = wave_height * clamp(-ground / 2.5, 0.0, 1.0);
	float crest = clamp(waves(world_pos.xz, t, amp).y / max(amp * 0.9, 0.001)
		* 0.5 + 0.5, 0.0, 1.0);
	float dist = shore_distance(world_pos.xz, ground);
	float wet = step(ground, 0.0);        // на суше воды нет, там своя геометрия

	// Кромка: неподвижная полоса у самого уреза.
	float edge = (1.0 - smoothstep(0.0, foam_edge, dist)) * wet;

	// Буруны: полосы, бегущие к берегу. Фаза зависит от расстояния до берега,
	// поэтому гребни повторяют изгибы бухт сами, без единой текстуры.
	float phase = dist / surf_length - t * surf_speed / surf_length;
	float rolls = sin(phase * TAU);
	// Гребень узкий, впадина широкая: у прибоя белая только верхушка вала.
	float surf = smoothstep(0.25, 0.9, rolls);
	surf *= 1.0 - smoothstep(surf_reach * 0.35, surf_reach, dist);
	surf *= smoothstep(0.0, foam_edge * 0.6, dist);   // у кромки своя пена
	// Прибой живёт на ОТМЕЛИ. Без этой строки полосы уходили в открытое море
	// и читались как горизонтали на топографической карте, а не как волны.
	surf *= 1.0 - smoothstep(1.5, 4.0, depth);
	surf *= wet;

	// Барашков на открытом море НЕТ, хотя они тут были.
	//
	// Сумма четырёх Герстнеров даёт широкие пологие гребни, и порог по высоте
	// белил не верхушки, а целые области в десятки метров: на кадре море
	// покрывалось мутными разводами, будто по нему возили тряпкой. У референса
	// (Dice Kingdoms) открытая вода - ровная насыщенная гладь, и белое там
	// только у берега. Волны никуда не делись: они живут в геометрии и в блике,
	// а не в пене.
	float foam = clamp(edge + surf * 0.7, 0.0, 1.0);

	vec3 col = mix(shallow_color, deep_color, fade);
	// Гребень чуть светлее подошвы: вода на просвет у вершины тоньше. Раньше
	// было вчетверо сильнее - и читалось как грязь, а не как объём.
	col = mix(col, shallow_color * 1.18, crest * 0.10 * (1.0 - fade * 0.6));
	col = mix(col, foam_color, foam);

	// Отблеск неба на пологом взгляде: без него вода читается как крашеный
	// пластик, сколько ни поднимай блик от солнца.
	float fresnel = pow(1.0 - clamp(dot(n, normalize(VIEW)), 0.0, 1.0), 3.0);
	ALBEDO = mix(col, sky_tint, fresnel * 0.4 * (1.0 - foam));

	// У берега вода прозрачная, вдали - непроглядная: за краем карты под ней
	// нет никакой геометрии, и щель до неба закрывать больше нечем.
	ALPHA = clamp(mix(0.42, 1.0, fade) + foam * 0.6, 0.0, 1.0);
	// Пена матовая, чистая вода зеркальная - иначе буруны блестят как лак.
	ROUGHNESS = mix(0.04, 0.55, foam);
	METALLIC = 0.0;
	SPECULAR = mix(0.85, 0.2, foam);
}
