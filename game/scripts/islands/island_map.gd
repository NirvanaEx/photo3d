extends RefCounted

# Карта архипелага: поле высот на квадратной сетке плюс биом каждой клетки.
#
# Высоты лежат в УЗЛАХ сетки (их на один больше, чем клеток по стороне), биомы -
# в КЛЕТКАХ. Разделение не формальность: рельеф должен быть непрерывным, иначе
# между клетками появятся ступеньки, а цвет и постройки привязаны именно к
# клетке. Высота в произвольной точке берётся билинейно из четырёх узлов.
#
# Данные отделены от отрисовки: генерацию можно прогнать и проверить
# счётчиками (stats()), не подняв ни одного меша. «Суши 3%» и «остров
# развалился на пять клякс» видно по числам раньше, чем по картинке.
#
# Всё детерминировано от seed: та же цифра - тот же архипелаг. Иначе баг
# «старт встал в воду» не воспроизвести.

# Клетка ПОД МЕЛОЧЬ, а здание занимает НЕСКОЛЬКО клеток.
#
# История такая. Сперва клетка была 1.6 м, и дом из набора (2.1 м) в неё не
# влезал - постройки въезжали друг в друга углами. Клетку укрупнили до 2.56 м,
# ровно под дом, и это чинило застройку, но ломало всё остальное: шаг сетки
# задаёт ТОЧНОСТЬ, с которой на карту вообще можно что-то поставить, а мелочи
# на карте больше, чем зданий. Куст, камень и цветок вставали по решётке в два
# с половиной метра и читались расставленными, а не выросшими.
#
# Теперь клетка мелкая, а здание занимает КВАДРАТ клеток - сколько ему надо
# (builder.gd, ключ "cells"). Мелочь получила шаг, на котором решётка не видна,
# а здания - прежний зазор.
const CELLS := 160                       # клеток по стороне
const CELL := 1.28                       # размер клетки, метры

const HALF := CELLS * CELL * 0.5
const SEA_LEVEL := 0.0

# Сглаживание считается по УЗЛАМ, поэтому его сила зависит от шага сетки: ядро
# 1-2-1 всегда захватывает одного соседа, а сосед теперь вдвое ближе. Радиус
# размытия растёт как корень из числа проходов, значит при вдвое мелкой клетке
# проходов нужно вчетверо больше - иначе рельеф остаётся вдвое острее прежнего,
# уклон подскакивает и половина суши уходит в «обрыв».
const SMOOTH_PASSES := 8

# DUNE дописан В КОНЕЦ нарочно: COLORS и BIOME_NAMES индексируются этим
# перечислением, и вставка в середину молча перекрасила бы половину карты.
enum Biome {SEABED, SAND, GRASS, FOREST, CLIFF, ROCK, SNOW, DUNE}

# Типы островов. Форма задаётся НЕ шумом, а ПРОФИЛЕМ: у каждого типа своя
# лестница уровней, и уровни эти ровные - плато, а не склон.
#
# Раньше профиль был один на всех: остров всегда выходил куполом, высота росла
# от берега к середине без остановки. Ровного места на таком куполе нет нигде,
# и здания приходилось ставить «куда пустят».
#
# Уровни разделены ПЛАВНО (smoothstep через заметную долю радиуса), а не
# ступенью: между плато выходит пологий подъём, а не отвес. Отвесы пробовали
# террасами - получилось плохо, вернулись к ровному рельефу.
#
#   MOUNTAIN - море, возвышенность, горы: три уровня
#   BEACH    - море, широкий пляж, равнина: два уровня, оба низкие
#   PLAIN    - море и сразу равнина: один уровень с заметным, но не резким
#              подъёмом от воды
enum Kind {MOUNTAIN, BEACH, PLAIN}

# Высота пляжной полки, метры. Она есть у ВСЕХ типов - между водой и землёй
# всегда лежит песок, а не обрывается зелень. У пляжного острова полка просто
# тянется в несколько раз дальше.
#
# Порог песка в _biome_for обязан быть ВЫШЕ этого числа, иначе пляж считается
# лугом и на кадре его нет вовсе - на этом уже споткнулись: полка стояла на
# 0.45 м при пороге 0.35, и «пляжный» остров выходил без единой песчинки.
const BEACH_H := 0.42

const NEIGHBORS: Array[Vector2i] = [
	Vector2i(1, 0), Vector2i(-1, 0), Vector2i(0, 1), Vector2i(0, -1),
]

# Цвета клеток. Лежат тут, а не в материале: цвет запекается в вершины меша,
# поэтому вся земля рисуется одним материалом и одним вызовом.
#
# Палитра снята с референса - Dice Kingdoms: плотные насыщенные цвета БЕЗ
# текстуры вообще. Богатство кадра там даётся не детализацией земли, а тенями и
# плотностью построек, поэтому земле полагается быть чистой заливкой.
#
# Приглушать цвета пришлось бы, если бы солнце и небо светили в полную силу
# вместе: песочный 0.94 под таким освещением выгорает в белый, и берег выглядит
# снегом. Лечится это не палитрой, а рассеянным светом - см. islands.tscn,
# ambient_light_sky_contribution. Смотреть надо на кадр, а не на числа.
const COLORS: Array[Color] = [
	Color(0.16, 0.44, 0.50),      # SEABED - дно, видно сквозь толщу воды
	Color(0.94, 0.87, 0.62),      # SAND
	Color(0.56, 0.70, 0.33),      # GRASS
	Color(0.35, 0.55, 0.26),      # FOREST
	Color(0.63, 0.42, 0.32),      # CLIFF  - обрыв, слишком крут для травы
	Color(0.72, 0.56, 0.45),      # ROCK
	Color(0.96, 0.96, 0.95),      # SNOW
	# DUNE - сухая земля. Заметно РЫЖЕЕ пляжа: первый вариант (0.86, 0.74, 0.47)
	# на кадре не отличался от песка, и пустошь посреди острова читалась вторым
	# пляжем неизвестно откуда.
	Color(0.84, 0.65, 0.38),      # DUNE
]

# Названия для интерфейса. Порядок тот же, что у Biome и COLORS - три массива
# рядом дешевле одного словаря: индекс биома и так уже посчитан.
const BIOME_NAMES: Array[String] = [
	"дно", "песок", "луг", "лес", "обрыв", "камень", "снег", "пустошь",
]

var seed := 0
var height := PackedFloat32Array()       # (CELLS+1)^2 узлов
var cell_biome := PackedByteArray()      # CELLS^2
var cell_tree := PackedByteArray()
var cell_land := PackedByteArray()
# Влажность: непрерывная величина от -1 (пустошь) до +1 (густой лес). Живёт
# отдельно от биома нарочно - биом это ступенька для логики и мини-карты, а
# растительность и цвет земли должны ПЕРЕТЕКАТЬ, а не переключаться.
var cell_moist := PackedFloat32Array()   # CELLS^2
var node_moist := PackedFloat32Array()   # (CELLS+1)^2
var node_climate := PackedFloat32Array() # (CELLS+1)^2, климат острова-хозяина
var cell_main := PackedByteArray()       # принадлежность главному острову
var islands: Array = []                  # {c: Vector2, r: float}
var main_size := 0
var start_cell := Vector2i.ZERO
var start_pos := Vector3.ZERO
var max_height := 0.0
var world_half := HALF


func generate(p_seed: int, island_count: int) -> void:
	seed = p_seed
	var rng := RandomNumberGenerator.new()
	rng.seed = p_seed

	_place_islands(rng, island_count)
	_raise_terrain()
	_smooth_terrain(SMOOTH_PASSES)
	_classify(rng)
	_find_main_island()
	_choose_start(rng)


# --------------------------------------------------------------------------- #
# Форма архипелага
# --------------------------------------------------------------------------- #

# Главный остров всегда в середине: старт игрока не должен зависеть от того,
# куда лёг случай. Остальные раскиданы по кольцу с неровным шагом - ровный шаг
# читается как узор, а не как архипелаг.
func _place_islands(rng: RandomNumberGenerator, count: int) -> void:
	islands.clear()
	# Главный - пляжный: на нём начинают, и ему полагается ровная равнина под
	# застройку и широкий берег под причалы. Гора на старте отняла бы половину
	# места и ничего не дала.
	# Радиусы выросли в полтора раза вместе со сменой маски: спад теперь идёт от
	# самого центра, суша кончается примерно на 0.6 радиуса, и при прежних
	# числах главный остров усох вдвое - 285 клеток вместо 564, посёлку тесно.
	# Климат главного острова умеренный: старт должен быть обычным лугом с
	# рощами, а не пустошью и не сплошным лесом.
	islands.append({"c": Vector2.ZERO, "r": HALF * 0.60, "kind": Kind.BEACH,
		"climate": 0.05})
	var rest := maxi(0, count - 1)
	if rest == 0:
		return
	# Типы РАЗДАЮТСЯ ПО ОЧЕРЕДИ, а не бросаются случайно: при случайном выборе
	# на пяти островах регулярно выпадали пять равнин, и архипелаг выходил
	# однообразным. Очередь гарантирует, что все три типа на карте есть.
	var order := [Kind.MOUNTAIN, Kind.PLAIN, Kind.BEACH]
	# То же и с климатом: очередь из трёх поясов, но со случайным сдвигом.
	# Именно отсюда берётся «на карте может не быть лесов или пустыни» - на
	# трёх островах достаётся не всё, а на пяти повторяется по кругу.
	var belts := [0.62, -0.58, 0.02]
	var b0 := rng.randi()
	var a0 := rng.randf() * TAU
	for i in rest:
		var a := a0 + TAU * (float(i) + rng.randf_range(-0.22, 0.22)) / float(rest)
		# Соседи отодвинуты и ужаты: при прежних числах (0.55..0.78 расстояния и
		# радиусы до 0.45) острова СРАСТАЛИСЬ - замер показывал, что вся суша
		# карты числится одним связным куском в четырёх случаях из пяти. Это уже
		# не архипелаг, а континент с заливами.
		var d := HALF * rng.randf_range(0.62, 0.82)
		var kind: int = order[i % order.size()]
		# Гора требует места: на островке в тридцать метров три уровня
		# накладываются друг на друга и читаются бугром, а не горой.
		var r := HALF * (rng.randf_range(0.28, 0.36) if kind == Kind.MOUNTAIN
			else rng.randf_range(0.19, 0.28))
		var climate: float = belts[(b0 + i) % belts.size()] + rng.randf_range(-0.16, 0.16)
		islands.append({"c": Vector2(cos(a), sin(a)) * d, "r": r, "kind": kind,
			"climate": climate})


# Высота по типу острова. vn: 0 у воды, 1 в середине.
#
# Каждое слагаемое - один уровень. smoothstep между двумя долями радиуса даёт
# подъём, а между подъёмами получается ПЛАТО: производная там нулевая, то есть
# место ровное и застраиваемое. Ширина подъёма (разница границ) и есть ответ на
# «не резко»: чем она больше, тем положе.
func _profile(kind: int, vn: float) -> float:
	match kind:
		Kind.MOUNTAIN:
			# Пляж, прибрежная полка (2.7 м), возвышенность (6.7 м), гора
			# (14.6 м). Верхний уровень начинается только за 0.70 радиуса -
			# иначе камень и снег накрывают весь остров, и зелени не остаётся.
			#
			# Уровни подняты в полтора раза против первой версии. Прежние 10.9
			# метра на острове шириной под сотню читались с общего плана бугром,
			# а не горой: глаз судит о высоте по ОТНОШЕНИЮ к ширине, и на такой
			# карте гора обязана быть заметно выше, чем требует здравый смысл.
			# Верхний уровень поднимается ДО САМОЙ СЕРЕДИНЫ (0.70..1.00), а не
			# выходит на плато к 0.90. Плато на вершине - это стол, и снег на
			# нём ложился белой скатертью в половину острова; при подъёме до
			# конца снег достаётся только макушке, как ему и положено.
			return (BEACH_H * smoothstep(0.00, 0.03, vn)
				+ 2.3 * smoothstep(0.16, 0.30, vn)
				+ 4.3 * smoothstep(0.40, 0.62, vn)
				+ 8.4 * smoothstep(0.70, 1.00, vn))
		Kind.BEACH:
			# Пляж ШИРОКИЙ: полка держится почти до трети радиуса, метров семь.
			# Ради него этот тип и заведён.
			return (BEACH_H * smoothstep(0.00, 0.03, vn)
				+ 1.90 * smoothstep(0.30, 0.48, vn))
		_:
			# Равнина: пляж узкий, дальше подъём заметный, но не обрыв, и
			# ровное плато до самой середины.
			return (BEACH_H * smoothstep(0.00, 0.03, vn)
				+ 2.30 * smoothstep(0.16, 0.30, vn))


func _raise_terrain() -> void:
	var elev := FastNoiseLite.new()
	elev.seed = seed
	elev.noise_type = FastNoiseLite.TYPE_SIMPLEX
	elev.frequency = 0.010
	# Октав четыре, а не пять, и затухание сильнее: пятая октава давала рябь с
	# длиной волны в четыре клетки, из-за которой уклон подскакивал на ровном
	# месте и половина острова числилась обрывом (замер: медиана уклона 0.63).
	elev.fractal_octaves = 4
	elev.fractal_gain = 0.42

	# Мелкий шум поверх крупного: без него склоны получаются вылизанными, как
	# у надувного матраса, - фактуры нет ни на глаз, ни в тенях.
	var detail := FastNoiseLite.new()
	detail.seed = seed + 5501
	detail.noise_type = FastNoiseLite.TYPE_SIMPLEX
	detail.frequency = 0.045
	detail.fractal_octaves = 3

	# Искажение координат перед расчётом маски. Без него острова остаются
	# ровными кругами: шум высот ломает только их край, а очертания задаёт
	# окружность, и сверху архипелаг выглядит набором монет. Смещение точки
	# двумя независимыми шумами превращает круг в кляксу с бухтами и мысами.
	var warp := FastNoiseLite.new()
	warp.seed = seed + 313
	warp.noise_type = FastNoiseLite.TYPE_SIMPLEX
	warp.frequency = 0.012
	warp.fractal_octaves = 2

	var side := CELLS + 1
	height.resize(side * side)
	node_climate.resize(side * side)
	max_height = -INF
	for j in side:
		for i in side:
			var p := Vector2(-HALF + float(i) * CELL, -HALF + float(j) * CELL)

			var wp := p + Vector2(
				warp.get_noise_2d(p.x, p.y),
				warp.get_noise_2d(p.y + 917.0, p.x - 431.0)) * 26.0

			# Маска суши: несколько островов, а не одна большая клякса. У каждого
			# своя окружность, плавно спадающая к краю, - но считается она по
			# искажённой точке wp, поэтому окружностью на карте не выглядит.
			var n := elev.get_noise_2d(p.x, p.y) * 0.5 + 0.5      # 0..1
			# Край карты обязан быть открытым морем, иначе остров срезается рамкой.
			var edge := 1.0 - smoothstep(0.88, 1.02, p.length() / HALF)

			# Побеждает тот остров, вглубь которого точка зашла ДАЛЬШЕ всех.
			# Берём максимум, а не сумму: на стыке двух островов сумма поднимала
			# перемычку выше обоих берегов, и они срастались горбом.
			var v := -INF
			var kind := Kind.PLAIN
			var climate := 0.0
			for isl in islands:
				var d: float = wp.distance_to(isl["c"]) / float(isl["r"])
				# Спад маски идёт от САМОГО ЦЕНТРА, а не от трети радиуса.
				#
				# Было smoothstep(0.30, ...): маска равна единице во всей
				# середине острова, а значит «глубина внутри» там постоянная -
				# и уровни профиля не могли разложиться по радиусу. Гора
				# выходила не горой, а сплошной каменной шапкой во весь остров.
				var m := (1.0 - smoothstep(0.02, 1.0, d)) * edge
				var vi := m * (0.72 + 0.66 * n) - 0.34
				if vi > v:
					v = vi
					kind = int(isl["kind"])
					climate = float(isl["climate"])

			var h := 0.0
			if v > 0.0:
				# vn - «насколько глубоко внутри острова»: 0 у самой воды, 1 в
				# середине. Береговая линия при этом остаётся рваной, потому что
				# в v уже вмешаны шум и искажение координат.
				# Делитель - это v в середине острова при среднем шуме
				# (1.05 - 0.34): так vn честно пробегает от 0 у воды до 1 в
				# сердцевине, и границы уровней в _profile означают доли радиуса.
				var vn := clampf(v / 0.71, 0.0, 1.0)
				h = _profile(kind, vn)
				# Шум СЛАБЫЙ и растёт с высотой: равнине положено быть ровной
				# (о том и просили), а вот голая гора без фактуры выглядит
				# леденцом. Отсюда и множитель от самой высоты.
				h += detail.get_noise_2d(p.x, p.y) * (0.06 + 0.05 * h)
			else:
				h = v * 13.0 - n * 1.5

			height[j * side + i] = h
			node_climate[j * side + i] = climate
			max_height = maxf(max_height, h)


# Сглаживание поля высот ядром 1-2-1 по обеим осям.
#
# Шум даёт рельеф с изломами в одну клетку: на кадре это читается как рябь и
# «квадратики», а не как холмы. Два прохода убирают её, оставляя крупные формы,
# - и заодно сажают медиану уклона, то есть добавляют места под постройки.
#
# Проходов ровно два: на четырёх остров начинает походить на каплю, теряя
# бухты и мысы, ради которых заводилось искажение маски.
func _smooth_terrain(passes: int) -> void:
	var side := CELLS + 1
	for _p in passes:
		var src := height.duplicate()
		for j in side:
			for i in side:
				var acc := 0.0
				var wsum := 0.0
				for dj in range(-1, 2):
					for di in range(-1, 2):
						var x := clampi(i + di, 0, side - 1)
						var y := clampi(j + dj, 0, side - 1)
						var w := (2.0 if di == 0 else 1.0) * (2.0 if dj == 0 else 1.0)
						acc += src[y * side + x] * w
						wsum += w
				height[j * side + i] = acc / wsum
	max_height = -INF
	for h in height:
		max_height = maxf(max_height, h)


# --------------------------------------------------------------------------- #
# Биомы
# --------------------------------------------------------------------------- #

func _classify(rng: RandomNumberGenerator) -> void:
	# Частота ВТРОЕ ниже прежней: пояс леса или пустоши должен быть размером с
	# кусок острова (метров семьдесят), а не с рощу в десять метров. При 0.03
	# лес и луг чередовались пятнами по три клетки, и «биома» на карте не
	# читалось - читался шум.
	var wet := FastNoiseLite.new()
	wet.seed = seed + 977
	wet.noise_type = FastNoiseLite.TYPE_SIMPLEX
	wet.frequency = 0.009
	wet.fractal_octaves = 3
	wet.fractal_gain = 0.45

	var side := CELLS + 1
	node_moist.resize(side * side)
	for j in side:
		for i in side:
			var p := Vector2(-HALF + float(i) * CELL, -HALF + float(j) * CELL)
			# Влажность = пояс острова (климат) + местная пестрота. Климат
			# решает, какой остров каким выйдет; шум - где внутри него роща, а
			# где поляна. Отсюда и «в равнине бывают деревья, а в лесу поляны»:
			# это одна непрерывная величина, а не два разных списка клеток.
			node_moist[j * side + i] = clampf(
				node_climate[j * side + i] + wet.get_noise_2d(p.x, p.y) * 0.72,
				-1.0, 1.0)

	cell_biome.resize(CELLS * CELLS)
	cell_tree.resize(CELLS * CELLS)
	cell_land.resize(CELLS * CELLS)
	cell_moist.resize(CELLS * CELLS)
	for cy in CELLS:
		for cx in CELLS:
			var idx := cy * CELLS + cx
			var h := cell_height(cx, cy)
			var s := cell_slope(cx, cy)
			var m := 0.25 * (node_moist[cy * side + cx] + node_moist[cy * side + cx + 1]
				+ node_moist[(cy + 1) * side + cx] + node_moist[(cy + 1) * side + cx + 1])
			cell_moist[idx] = m
			cell_land[idx] = 1 if h > SEA_LEVEL else 0
			cell_biome[idx] = _biome_for(h, s, m)
			# Дерево - ТОЛЬКО на суше, и проверка идёт по cell_land, а не по
			# биому. Мелководье у берега тоже числится песком (так оно и должно
			# выглядеть сквозь толщу воды), и без этой проверки пальмы вырастали
			# прямо в море - было видно на кадре.
			cell_tree[idx] = _tree_for(m, h, rng) if cell_land[idx] == 1 else 0


func _biome_for(h: float, slope: float, moisture: float) -> int:
	if h <= SEA_LEVEL:
		# Дно у берега песчаное, дальше уходит в темноту - под водой это и
		# читается как глубина.
		return Biome.SAND if h > -1.6 else Biome.SEABED
	# Порог ВЫШЕ пляжной полки (BEACH_H), иначе полка числится лугом и пляжа на
	# кадре нет. Запас нужен ещё и на подъём: песок должен захватывать начало
	# склона, чтобы граница песка и травы не совпадала с изломом рельефа.
	if h < BEACH_H + 0.33:
		return Biome.SAND
	# Обрыв определяется УКЛОНОМ, а не высотой: скала у воды бывает и на трёх
	# метрах, а плато на десяти остаётся лугом.
	#
	# Порог взят по ЗАМЕРУ, а не на глаз: медиана уклона суши 0.54, p90 - 1.06.
	# При 0.75 обрывом числилась половина суши. При 0.9 обрыв доставался каждой
	# шестой клетке - на кадре это ложилось не скалой, а бурой размазнёй по
	# зелёному склону: отдельные клетки обрыва тонули в усреднении цвета и
	# оставляли грязь. Порог 1.3 - примерно p95: обрыв достаётся только тому,
	# что действительно круто, и читается стеной.
	if slope > 1.3:
		return Biome.CLIFF
	# Снег только на самой макушке и только у высоких островов. Камень же
	# наоборот полезен: он размечает верхние площадки и не даёт острову стать
	# однородно зелёным.
	if h > 13.9:
		return Biome.SNOW
	if h > 7.6:
		return Biome.ROCK
	# Пояса. Пороги - середины тех же переходов, по которым красится земля
	# (ground_color): биом обязан совпадать с тем, что видно, иначе подсказка
	# под курсором спорит с картинкой.
	if moisture < -0.30:
		return Biome.DUNE
	if moisture > 0.22 or h > 6.0:
		return Biome.FOREST
	return Biome.GRASS


# Цвет земли в точке - НЕПРЕРЫВНЫЙ, а не «цвет биома клетки».
#
# Раньше цвет брался таблицей по номеру биома и усреднялся по четырём соседним
# клеткам. На стыке пояса это давало границу шириной в одну клетку: лес
# кончался, луг начинался, и линия шла по решётке. С мелкой клеткой стало
# только хуже - решётка мельче, а линия всё равно линия.
#
# Здесь вместо ступенек - смеси: каждый признак (влажность, высота, уклон)
# подмешивает свой цвет через smoothstep, и переход занимает столько, сколько
# ему положено по местности. Биом при этом никуда не делся: он остался для
# логики и мини-карты, где ступенька как раз нужна.
func ground_color(h: float, slope: float, moisture: float) -> Color:
	if h <= SEA_LEVEL:
		return COLORS[Biome.SEABED].lerp(COLORS[Biome.SAND],
			smoothstep(-1.9, -0.2, h))
	# Пояс: пустошь -> луг -> лес.
	var col: Color = COLORS[Biome.DUNE].lerp(COLORS[Biome.GRASS],
		smoothstep(-0.44, -0.10, moisture))
	col = col.lerp(COLORS[Biome.FOREST], smoothstep(0.06, 0.40, moisture))
	# Выше шести метров лес темнеет независимо от влажности: это уже склон.
	col = col.lerp(COLORS[Biome.FOREST], smoothstep(5.0, 6.8, h))
	# Пляж. Переход широкий - песок обязан заходить на начало подъёма, иначе
	# граница песка совпадает с изломом рельефа и читается ступенькой.
	col = COLORS[Biome.SAND].lerp(col, smoothstep(BEACH_H + 0.05, BEACH_H + 0.85, h))
	col = col.lerp(COLORS[Biome.ROCK], smoothstep(6.8, 8.6, h))
	col = col.lerp(COLORS[Biome.SNOW], smoothstep(13.1, 14.7, h))
	col = col.lerp(COLORS[Biome.CLIFF], smoothstep(1.05, 1.55, slope))
	return col


# Лес ГУСТОЙ, луг почти пустой - разница нарочно резкая.
#
# Было 0.42 и 0.05: деревья ложились редкой сыпью по всему острову и читались
# не как лес, а как шум. У референса (Dice Kingdoms) роща - плотное тёмное
# пятно, а поляна - чистая трава, и остров из-за этого читается как местность,
# а не как текстура.
#
# Числа пересчитаны под мелкую клетку. Считается ПЛОТНОСТЬ НА ПЛОЩАДЬ, а не
# «сколько выпадает на клетку»: клетка стала вчетверо меньше по площади, и
# прежние вероятности дали бы вчетверо гуще - остров зарос бы сплошняком.
# На отмеченной клетке теперь ровно одно дерево, поэтому вероятность и есть
# плотность.
#
# Дерево растёт от ВЛАЖНОСТИ, а не от «клетка числится лесом». Так на равнине
# оказываются отдельные деревья и рощицы, а в лесу - поляны: густота плавно
# идёт от нуля на пустоши до сплошного полога. Ступенька по биому давала ровно
# обратное - лес обрывался по линии, за которой не было ни куста.
func _tree_for(moisture: float, h: float, rng: RandomNumberGenerator) -> int:
	if h < BEACH_H + 0.33:
		# Пальмы на пляже. Редко: сплошная пальмовая роща на песке выглядит
		# посадкой, а не берегом.
		return 1 if rng.randf() < 0.03 else 0
	if h > 7.6:
		return 0                        # выше - камень, там растёт нечего
	# Переход НЕ пологий: между поляной и чащей должно быть видно разницу. При
	# ширине в целую единицу влажности густота менялась настолько плавно, что
	# весь остров выходил равномерно присыпан деревьями - ни леса, ни поляны.
	var p := lerpf(0.004, 0.46, smoothstep(-0.28, 0.28, moisture))
	# На верхних площадках лес гуще независимо от пояса: склон задерживает воду.
	p = maxf(p, 0.16 * smoothstep(5.2, 7.0, h))
	return 1 if rng.randf() < p else 0


# --------------------------------------------------------------------------- #
# Суша и точка старта
# --------------------------------------------------------------------------- #

# Заливка по связности: «главный остров» - не тот, что у середины карты, а
# самый крупный связный кусок суши. После шума они не всегда совпадают.
func _find_main_island() -> void:
	cell_main.resize(CELLS * CELLS)
	var seen := PackedByteArray()
	seen.resize(CELLS * CELLS)
	var best: PackedInt32Array = PackedInt32Array()
	for start in CELLS * CELLS:
		if seen[start] == 1 or cell_land[start] == 0:
			continue
		var group := PackedInt32Array()
		var queue := PackedInt32Array([start])
		seen[start] = 1
		while queue.size() > 0:
			var c := queue[queue.size() - 1]
			queue.remove_at(queue.size() - 1)
			group.append(c)
			var cx := c % CELLS
			var cy := c / CELLS
			for d: Vector2i in NEIGHBORS:
				var nx := cx + d.x
				var ny := cy + d.y
				if nx < 0 or ny < 0 or nx >= CELLS or ny >= CELLS:
					continue
				var ni := ny * CELLS + nx
				if seen[ni] == 0 and cell_land[ni] == 1:
					seen[ni] = 1
					queue.append(ni)
		if group.size() > best.size():
			best = group
	main_size = best.size()
	for i in best:
		cell_main[i] = 1


# Старт - ровное место у берега на главном острове. Ровное, чтобы было куда
# ставить постройки; у берега, чтобы было куда причалить.
#
# Не «первая подходящая клетка», а лучшая по сумме признаков: жёсткий фильтр
# на шумной карте иногда не находит ничего, и тогда старт улетает на вершину.
func _choose_start(rng: RandomNumberGenerator) -> void:
	var center := Vector2.ZERO
	var count := 0
	for i in CELLS * CELLS:
		if cell_main[i] == 1:
			center += Vector2(float(i % CELLS), float(i / CELLS))
			count += 1
	if count > 0:
		center /= float(count)

	var best := -1
	var best_score := -INF
	for i in CELLS * CELLS:
		if cell_main[i] != 1:
			continue
		var cx := i % CELLS
		var cy := i / CELLS
		var h := cell_height(cx, cy)
		if h < 0.8 or h > 5.0:
			continue
		# Ровность считается по окрестности РАДИУСОМ В ПЯТЬ МЕТРОВ, а не по одной
		# клетке: ставить посёлок на единственной горизонтальной клетке посреди
		# склона незачем. Радиус в клетках, поэтому зависит от шага сетки.
		var rough := _roughness(cx, cy, 4)
		var coast := _distance_to_water(cx, cy, 16)
		# Веса на расстояниях вдвое меньше прежних: сами расстояния считаются в
		# клетках, а клетка стала вдвое мельче.
		var score := -rough * 22.0 - float(coast) * 0.8
		score -= Vector2(float(cx), float(cy)).distance_to(center) * 0.025
		score += rng.randf() * 1.2
		if score > best_score:
			best_score = score
			best = i

	if best < 0:
		# Суши выше уровня моря нет вовсе - редкий случай, но молча ставить
		# флаг в воду нельзя.
		push_warning("суши на карте нет: старт поставлен в середину")
		start_cell = Vector2i(CELLS / 2, CELLS / 2)
	else:
		start_cell = Vector2i(best % CELLS, best / CELLS)
	var c := cell_center(start_cell.x, start_cell.y)
	start_pos = Vector3(c.x, height_at(c.x, c.z), c.z)


func _roughness(cx: int, cy: int, radius: int) -> float:
	var lo := INF
	var hi := -INF
	for y in range(cy - radius, cy + radius + 1):
		for x in range(cx - radius, cx + radius + 1):
			if x < 0 or y < 0 or x >= CELLS or y >= CELLS:
				return INF
			var h := cell_height(x, y)
			lo = minf(lo, h)
			hi = maxf(hi, h)
	return hi - lo


func _distance_to_water(cx: int, cy: int, limit: int) -> int:
	for r in range(1, limit + 1):
		for y in range(cy - r, cy + r + 1):
			for x in range(cx - r, cx + r + 1):
				if maxi(absi(x - cx), absi(y - cy)) != r:
					continue
				if x < 0 or y < 0 or x >= CELLS or y >= CELLS:
					return r
				if cell_land[y * CELLS + x] == 0:
					return r
	return limit + 1


# --------------------------------------------------------------------------- #
# Доступ
# --------------------------------------------------------------------------- #

func node_height(i: int, j: int) -> float:
	var side := CELLS + 1
	i = clampi(i, 0, side - 1)
	j = clampi(j, 0, side - 1)
	return height[j * side + i]


func cell_height(cx: int, cy: int) -> float:
	return 0.25 * (node_height(cx, cy) + node_height(cx + 1, cy)
		+ node_height(cx, cy + 1) + node_height(cx + 1, cy + 1))


func cell_slope(cx: int, cy: int) -> float:
	var a := node_height(cx, cy)
	var b := node_height(cx + 1, cy)
	var c := node_height(cx, cy + 1)
	var d := node_height(cx + 1, cy + 1)
	var lo: float = min(min(a, b), min(c, d))
	var hi: float = max(max(a, b), max(c, d))
	return (hi - lo) / CELL


# Влажность в узле - для покраски земли. Индексы зажимаются так же, как у
# высоты: у края карты соседа нет, а спрашивать его будут.
func node_moisture(i: int, j: int) -> float:
	var side := CELLS + 1
	i = clampi(i, 0, side - 1)
	j = clampi(j, 0, side - 1)
	return node_moist[j * side + i]


# Крутизна В УЗЛЕ: длина градиента поля высот по центральной разности. Та же
# величина, что cell_slope, но привязана к узлу - именно там красится земля.
func node_slope(i: int, j: int) -> float:
	var dx := (node_height(i + 1, j) - node_height(i - 1, j)) / (2.0 * CELL)
	var dz := (node_height(i, j + 1) - node_height(i, j - 1)) / (2.0 * CELL)
	return sqrt(dx * dx + dz * dz)


func cell_center(cx: int, cy: int) -> Vector3:
	return Vector3(-HALF + (float(cx) + 0.5) * CELL, 0.0, -HALF + (float(cy) + 0.5) * CELL)


func cell_at(x: float, z: float) -> Vector2i:
	return Vector2i(int(floor((x + HALF) / CELL)), int(floor((z + HALF) / CELL)))


func inside(cx: int, cy: int) -> bool:
	return cx >= 0 and cy >= 0 and cx < CELLS and cy < CELLS


func biome_at(cx: int, cy: int) -> int:
	return cell_biome[cy * CELLS + cx] if inside(cx, cy) else Biome.SEABED


func is_land(cx: int, cy: int) -> bool:
	return inside(cx, cy) and cell_land[cy * CELLS + cx] == 1


# Высота в произвольной точке - билинейно по четырём узлам. За краем карты
# отдаём глубину, а не ноль: иначе луч мыши «цепляется» за несуществующий берег.
func height_at(x: float, z: float) -> float:
	var fx := (x + HALF) / CELL
	var fz := (z + HALF) / CELL
	if fx < 0.0 or fz < 0.0 or fx > float(CELLS) or fz > float(CELLS):
		return -12.0
	var i := int(fx)
	var j := int(fz)
	var tx := fx - float(i)
	var tz := fz - float(j)
	var h0 := lerpf(node_height(i, j), node_height(i + 1, j), tx)
	var h1 := lerpf(node_height(i, j + 1), node_height(i + 1, j + 1), tx)
	return lerpf(h0, h1, tz)


func stats() -> Dictionary:
	var per := {}
	var land := 0
	var flat := 0
	var slopes := PackedFloat32Array()
	for i in CELLS * CELLS:
		var b := cell_biome[i]
		per[b] = int(per.get(b, 0)) + 1
		land += cell_land[i]
		if cell_land[i] == 1:
			var s := cell_slope(i % CELLS, i / CELLS)
			slopes.append(s)
			# «Ровное место» - по тому же порогу, по которому builder пускает
			# застройку. Без этого числа непонятно, есть ли на карте где строить:
			# суша бывает и вся склонами.
			if s <= 0.45 and cell_main[i] == 1:
				flat += 1
	slopes.sort()
	var median := 0.0
	var p90 := 0.0
	if slopes.size() > 0:
		median = slopes[slopes.size() / 2]
		p90 = slopes[int(float(slopes.size()) * 0.9)]
	return {
		"cells": CELLS * CELLS,
		"land": land,
		"flat": flat,
		"islands": islands.size(),
		"main": main_size,
		"max_height": max_height,
		"slope_median": median,
		"slope_p90": p90,
		"sand": int(per.get(Biome.SAND, 0)),
		"grass": int(per.get(Biome.GRASS, 0)),
		"forest": int(per.get(Biome.FOREST, 0)),
		"cliff": int(per.get(Biome.CLIFF, 0)),
		"rock": int(per.get(Biome.ROCK, 0)),
		"snow": int(per.get(Biome.SNOW, 0)),
		"dune": int(per.get(Biome.DUNE, 0)),
	}
