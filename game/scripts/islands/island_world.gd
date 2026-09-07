extends Node3D

# Сборка мира из карты: меш земли, карта высот для воды, деревья, курсор клетки,
# точка старта, наведение камеры.
#
# Земля - ОДИН меш с запечённым в вершины цветом: разбивать её на клетки-узлы
# значило бы шесть тысяч узлов и столько же вызовов отрисовки.
#
# Наружу мир говорит СИГНАЛАМИ, а не тянет за собой интерфейс: он не знает ни
# про мини-карту, ни про панель построек. Появится второй интерфейс - подпишется
# на те же сигналы.

signal world_ready(map)
signal hover_changed(cell: Vector2i, info: Dictionary)

const IslandMap := preload("res://scripts/islands/island_map.gd")
const Kit := preload("res://scripts/islands/kit.gd")

const LAUNCHER := "res://scenes/launcher.tscn"

# Цвет вытоптанной земли у построек. Тёплая земля, а не серая грязь: рядом с
# оранжевыми крышами серое читается как пятно сырости.
#
# Тёмная нарочно. Первый вариант (0.52, 0.42, 0.29) по числам был явно бурым, а
# на кадре не читался вовсе: под ярким солнцем, с подмешанным зелёным от SSIL и
# поднятой насыщенностью пятно выходило чуть более тусклой травой. Проверено
# подстановкой красного - геометрия пятна была верной с самого начала, негодным
# был контраст.
const DIRT := Color(0.40, 0.29, 0.17)

@export var island_count := 5
## 0 - выбрать случайно при запуске. Любое другое число повторяет архипелаг.
@export var world_seed := 0

@export var camera_path: NodePath
@export var sea_path: NodePath
@export var start_point_path: NodePath
@export var builder_path: NodePath

var map: IslandMap

@onready var _ground: MeshInstance3D = $Ground
@onready var _trees: Node3D = $Trees
@onready var _props: Node3D = $Props
@onready var _cursor: MeshInstance3D = $CellCursor

var _camera_rig: Node3D
var _sea: MeshInstance3D
var _start_point: Node3D
var _builder: Node3D
var _ground_mat: StandardMaterial3D
var _cursor_mat: StandardMaterial3D
var _hover := Vector2i(-1, -1)
var _cursor_n := 1


func _ready() -> void:
	_camera_rig = get_node_or_null(camera_path)
	_sea = get_node_or_null(sea_path)
	_start_point = get_node_or_null(start_point_path)
	_builder = get_node_or_null(builder_path)

	if _builder != null and _builder.has_signal("placed"):
		_builder.connect("placed", func(id, cell):
			var n: int = _builder.call("footprint", id)
			clear_cell(cell, n)
			stomp_cell(cell, n))

	_ground_mat = _ground_material()
	_cursor_mat = _cursor_material()
	_cursor.mesh = ImmediateMesh.new()
	_cursor.material_override = _cursor_mat
	_cursor.visible = false

	if world_seed == 0:
		world_seed = randi() % 100000
	rebuild(world_seed)


func rebuild(new_seed: int) -> void:
	var t0 := Time.get_ticks_msec()
	world_seed = new_seed
	map = IslandMap.new()
	map.generate(world_seed, island_count)

	_build_ground()
	_feed_water()
	_plant_trees()
	_scatter_props()
	_place_start()
	if _builder != null and _builder.has_method("reset"):
		_builder.call("reset", map)
	if _camera_rig != null and _camera_rig.has_method("focus_on"):
		_camera_rig.call("focus_on", map.start_pos)
		_camera_rig.call("set_bounds", IslandMap.HALF * 1.02)
	_hover = Vector2i(-1, -1)
	world_ready.emit(map)

	var s := map.stats()
	print("архипелаг seed=%d: суша %d из %d клеток, островов %d (главный %d, ровных %d), пик %.1f м, сборка %d мс"
		% [world_seed, s["land"], s["cells"], s["islands"], s["main"], s["flat"],
			s["max_height"], Time.get_ticks_msec() - t0])
	# Разбор суши по биомам печатается всегда: «остров вышел каменным куполом»
	# видно по этой строке раньше, чем по кадру.
	print("  песок %d, луг %d, лес %d, пустошь %d, обрыв %d, камень %d, снег %d; уклон медиана %.2f, p90 %.2f"
		% [s["sand"], s["grass"], s["forest"], s["dune"], s["cliff"], s["rock"], s["snow"],
			s["slope_median"], s["slope_p90"]])
	var mm := 0
	for parent in [_trees, _props]:
		for child in parent.get_children():
			var node := child as MultiMeshInstance3D
			if node != null and node.multimesh != null:
				mm += node.multimesh.instance_count
	print("  растительности %d штук в %d мультимешах"
		% [mm, _trees.get_child_count() + _props.get_child_count()])


# --------------------------------------------------------------------------- #
# Ввод
# --------------------------------------------------------------------------- #

func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseButton:
		var mb := event as InputEventMouseButton
		if mb.button_index == MOUSE_BUTTON_LEFT:
			# Здание ставится на ОТПУСКАНИИ, а не на нажатии: левой кнопкой ещё и
			# тянут карту, и на нажатии невозможно знать, чем движение окажется.
			# Камера считает пройденный путь и отвечает на dragged().
			if not mb.pressed and not _camera_dragged():
				_try_place()
			return
		# Правая кнопка возвращает В РЕЖИМ ОСМОТРА: щелчок ею снимает выбранную
		# постройку. Она же и крутит камеру, поэтому решает то же правило, что и
		# у левой, - щелчок это тот случай, когда мышь никуда не уехала.
		if mb.button_index == MOUSE_BUTTON_RIGHT and not mb.pressed:
			if not _camera_turned() and _builder != null \
					and String(_builder.call("selected")) != "":
				_builder.call("select", "")
			return
		return
	if not (event is InputEventKey) or not event.pressed or event.echo:
		return
	match (event as InputEventKey).keycode:
		KEY_R:
			rebuild(randi() % 100000)
		KEY_F:
			focus_start()
		KEY_HOME:
			reset_view()
		KEY_ESCAPE:
			# Первый Esc отменяет выбранную постройку, второй уводит в лаунчер.
			# Иначе случайное нажатие в режиме стройки выбрасывает из игры.
			if _builder != null and String(_builder.call("selected")) != "":
				_builder.call("select", "")
			else:
				_leave()


func reset_view() -> void:
	if _camera_rig != null and _camera_rig.has_method("reset_view"):
		_camera_rig.call("reset_view")


func focus_start() -> void:
	if _camera_rig != null and _camera_rig.has_method("focus_on") and map != null:
		_camera_rig.call("focus_on", map.start_pos)


func _camera_dragged() -> bool:
	return _camera_rig != null and _camera_rig.has_method("dragged") \
		and bool(_camera_rig.call("dragged"))


func _camera_turned() -> bool:
	return _camera_rig != null and _camera_rig.has_method("turned") \
		and bool(_camera_rig.call("turned"))


func _try_place() -> void:
	if _builder == null or map == null:
		return
	if String(_builder.call("selected")) == "":
		return
	if not map.inside(_hover.x, _hover.y):
		return
	_builder.call("act", _hover)


# Выход - В ЛАУНЧЕР, а не из приложения: он главная сцена проекта, и человек
# пришёл в игру оттуда. Второй Esc, уже в лаунчере, закрывает окно.
func _leave() -> void:
	if ResourceLoader.exists(LAUNCHER):
		get_tree().change_scene_to_file(LAUNCHER)
	else:
		get_tree().quit()


func _process(_dt: float) -> void:
	_update_cursor()


# --------------------------------------------------------------------------- #
# Земля
# --------------------------------------------------------------------------- #

# Меш строится на ОБЩИХ вершинах со сглаженными нормалями.
#
# Пробовали террасы - плоские площадки с отвесными уступами. Они и правда дают
# ровное место под здание, но остров превращается в лестницу, и от этого
# отказались. Здесь снова гладкий рельеф, а ровные места берутся не из
# геометрии, а из ПРОФИЛЯ острова: у каждого типа между уровнями есть плато,
# см. island_map.gd, _profile.
#
# Общие вершины дают вшестеро меньше геометрии, чем отдельные треугольники с
# плоскими нормалями, и сразу читаются холмами, а не набором квадратов.
func _build_ground() -> void:
	var cells := IslandMap.CELLS
	var cell := IslandMap.CELL
	var half := IslandMap.HALF
	var side := cells + 1

	var verts := PackedVector3Array()
	var norms := PackedVector3Array()
	var colors := PackedColorArray()
	var index := PackedInt32Array()
	verts.resize(side * side)
	norms.resize(side * side)
	colors.resize(side * side)
	index.resize(cells * cells * 6)

	var ncol := _node_colors()
	for j in side:
		for i in side:
			var k := j * side + i
			verts[k] = Vector3(-half + float(i) * cell, map.node_height(i, j),
				-half + float(j) * cell)
			# Нормаль - из наклона поля высот в узле (центральная разность), а
			# не из соседних граней: то же самое, но без обхода треугольников.
			var dx := (map.node_height(i + 1, j) - map.node_height(i - 1, j)) / (2.0 * cell)
			var dz := (map.node_height(i, j + 1) - map.node_height(i, j - 1)) / (2.0 * cell)
			norms[k] = Vector3(-dx, 1.0, -dz).normalized()
			colors[k] = ncol[k]

	var t := 0
	for cy in cells:
		for cx in cells:
			var a := cy * side + cx
			var b := cy * side + cx + 1
			var c := (cy + 1) * side + cx + 1
			var d := (cy + 1) * side + cx
			# Обход по часовой стрелке - у Godot это лицевая сторона.
			index[t] = a; index[t + 1] = b; index[t + 2] = c
			index[t + 3] = a; index[t + 4] = c; index[t + 5] = d
			t += 6

	_g_arrays = []
	_g_arrays.resize(Mesh.ARRAY_MAX)
	_g_arrays[Mesh.ARRAY_VERTEX] = verts
	_g_arrays[Mesh.ARRAY_NORMAL] = norms
	_g_arrays[Mesh.ARRAY_COLOR] = colors
	_g_arrays[Mesh.ARRAY_INDEX] = index
	_refresh_ground()


# Цвет считается В УЗЛАХ и НЕПРЕРЫВНОЙ функцией от высоты, уклона и влажности
# (map.ground_color), а не таблицей по номеру биома.
#
# Раньше здесь усреднялись цвета четырёх соседних клеток. Это сглаживало
# границу ровно на одну клетку: берег переставал быть лесенкой, но стык леса и
# пустоши всё равно шёл по решётке. Теперь ступенек нет вовсе - каждый признак
# подмешивается плавно, и ширину перехода задаёт местность, а не сетка.
#
# Перевод в ЛИНЕЙНОЕ пространство остаётся обязательным. Цвет вершины уходит в
# шейдер как есть и присваивается ALBEDO, а ALBEDO движок считает линейным.
# Палитра же подбиралась глазами, то есть в sRGB. Без перевода зелёный 0.38
# попадает в кадр как 0.65 - именно поэтому острова выглядели пастельными,
# сколько ни убавляй солнце и рассеянный свет.
func _node_colors() -> PackedColorArray:
	var side := IslandMap.CELLS + 1
	var out := PackedColorArray()
	out.resize(side * side)
	for j in side:
		for i in side:
			var col := map.ground_color(map.node_height(i, j), map.node_slope(i, j),
				map.node_moisture(i, j)).srgb_to_linear()
			col.a = 1.0
			out[j * side + i] = col
	return out


# Вода читает рельеф из текстуры высот - той же, что построил генератор.
# FORMAT_RF это 32 бита с плавающей точкой на тексел: высота кладётся как есть,
# без упаковки в байты и обратной распаковки в шейдере.
func _feed_water() -> void:
	if _sea == null:
		return
	var mat := _sea.get_active_material(0)
	if mat == null or not (mat is ShaderMaterial):
		push_warning("на воде нет ShaderMaterial - глубина и пена работать не будут")
		return
	var side := IslandMap.CELLS + 1
	var img := Image.create_from_data(side, side, false, Image.FORMAT_RF,
		map.height.to_byte_array())
	var tex := ImageTexture.create_from_image(img)
	var sm := mat as ShaderMaterial
	sm.set_shader_parameter("height_map", tex)
	sm.set_shader_parameter("map_half", IslandMap.HALF)
	sm.set_shader_parameter("cell_size", IslandMap.CELL)
	sm.set_shader_parameter("tex_size", float(side))


# Лес из моделей набора (Kenney, CC0). На каждую породу свой мультимеш: одна
# геометрия, сотни инстансов, один вызов отрисовки на породу.
#
# Пальмы растут на песке у воды, хвойные и лиственные - выше и дальше от
# берега. Порода выбирается детерминированно от seed, поэтому одна и та же
# карта каждый раз зарастает одинаково.
# Растительность. Породы ОДНОГО набора (Kenney Nature Kit, CC0) - у него уже
# сведён внутренний масштаб, и деревья не спорят друг с другом по высоте.
# Прежний список из трёх пород KayKit заменён потому, что три дерева на весь
# архипелаг читаются одной моделью, размноженной копией, - какой бы хорошей она
# ни была.
#
# Порода выбирается НЕ по биому, а весом от влажности и высоты:
#   "wc"/"ww" - середина и ширина пояса влажности (-1 пустошь ... +1 лес);
#   "hc"/"hw" - то же по высоте над морем, метры;
#   "s"       - масштаб, "j" - разброс масштаба (от него и берутся разные
#               высоты деревьев одной породы).
# Гауссовы веса дают ПЕРЕТЕКАНИЕ: у границы пояса встречаются обе породы, и
# линии на карте не возникает. Со списком «биом -> порода» лес обрывался ровно
# по клетке.
const TREES: Array[Dictionary] = [
	# Пляж: пальмы. Узкий пояс по высоте - им положено стоять у самой воды.
	{"m": "nature/tree_palmDetailedTall.glb", "s": 1.30, "j": 0.22, "wc": 0.0, "ww": 3.0,
		"hc": 0.45, "hw": 0.42},
	{"m": "nature/tree_palmDetailedShort.glb", "s": 1.25, "j": 0.20, "wc": 0.0, "ww": 3.0,
		"hc": 0.45, "hw": 0.42},
	{"m": "nature/tree_palmTall.glb", "s": 1.20, "j": 0.22, "wc": 0.0, "ww": 3.0,
		"hc": 0.50, "hw": 0.45},
	{"m": "nature/tree_palmBend.glb", "s": 1.20, "j": 0.20, "wc": 0.0, "ww": 3.0,
		"hc": 0.42, "hw": 0.40},
	# Сухой пояс: редкие деревца с рыжей листвой. Цвет тут не украшение, а
	# ЧИТАЕМОСТЬ пояса: сухая часть острова обязана отличаться от влажной
	# издалека, а разница в густоте на общем плане не видна.
	{"m": "nature/tree_small_fall.glb", "s": 0.95, "j": 0.28, "wc": -0.56, "ww": 0.26,
		"hc": 2.2, "hw": 2.8},
	{"m": "nature/tree_blocks_fall.glb", "s": 0.95, "j": 0.24, "wc": -0.48, "ww": 0.25,
		"hc": 2.4, "hw": 2.8},
	{"m": "nature/tree_fat_fall.glb", "s": 1.00, "j": 0.24, "wc": -0.42, "ww": 0.25,
		"hc": 2.2, "hw": 2.8},
	{"m": "nature/tree_plateau_fall.glb", "s": 1.00, "j": 0.24, "wc": -0.36, "ww": 0.24,
		"hc": 2.6, "hw": 2.8},
	{"m": "nature/tree_oak_fall.glb", "s": 1.15, "j": 0.26, "wc": -0.30, "ww": 0.24,
		"hc": 2.4, "hw": 2.8},
	{"m": "nature/tree_cone_fall.glb", "s": 0.95, "j": 0.24, "wc": -0.38, "ww": 0.24,
		"hc": 2.8, "hw": 2.8},
	# Умеренный пояс: то, из чего состоит обычная равнина с рощами.
	{"m": "nature/tree_oak.glb", "s": 1.20, "j": 0.30, "wc": 0.02, "ww": 0.40,
		"hc": 2.6, "hw": 3.2},
	{"m": "nature/tree_default.glb", "s": 0.95, "j": 0.28, "wc": 0.10, "ww": 0.42,
		"hc": 2.6, "hw": 3.2},
	{"m": "nature/tree_fat.glb", "s": 1.10, "j": 0.26, "wc": -0.05, "ww": 0.38,
		"hc": 2.4, "hw": 3.0},
	{"m": "nature/tree_small.glb", "s": 1.05, "j": 0.30, "wc": 0.00, "ww": 0.45,
		"hc": 2.4, "hw": 3.2},
	{"m": "nature/tree_plateau.glb", "s": 1.05, "j": 0.24, "wc": 0.06, "ww": 0.36,
		"hc": 3.0, "hw": 3.0},
	{"m": "nature/tree_detailed_fall.glb", "s": 1.00, "j": 0.26, "wc": -0.10, "ww": 0.30,
		"hc": 2.6, "hw": 3.0},
	# Влажный пояс: высокий густой лес тёмной листвой.
	{"m": "nature/tree_tall.glb", "s": 1.05, "j": 0.32, "wc": 0.40, "ww": 0.40,
		"hc": 2.8, "hw": 3.4},
	{"m": "nature/tree_detailed_dark.glb", "s": 1.10, "j": 0.30, "wc": 0.48, "ww": 0.38,
		"hc": 2.6, "hw": 3.2},
	{"m": "nature/tree_simple_dark.glb", "s": 1.00, "j": 0.32, "wc": 0.44, "ww": 0.40,
		"hc": 2.8, "hw": 3.4},
	{"m": "nature/tree_default_dark.glb", "s": 1.00, "j": 0.30, "wc": 0.58, "ww": 0.38,
		"hc": 3.0, "hw": 3.4},
	{"m": "nature/tree_small_dark.glb", "s": 1.05, "j": 0.32, "wc": 0.52, "ww": 0.40,
		"hc": 2.4, "hw": 3.2},
	{"m": "nature/tree_thin_dark.glb", "s": 0.95, "j": 0.30, "wc": 0.62, "ww": 0.36,
		"hc": 2.8, "hw": 3.2},
	{"m": "nature/tree_cone.glb", "s": 1.00, "j": 0.26, "wc": 0.30, "ww": 0.40,
		"hc": 3.4, "hw": 3.0},
	# Верхний пояс: хвойные. Разной высоты нарочно - ровный ельник читается
	# щёткой, а разнокалиберный лесом.
	{"m": "nature/tree_pineTallB.glb", "s": 1.00, "j": 0.32, "wc": 0.20, "ww": 0.70,
		"hc": 7.4, "hw": 3.0},
	{"m": "nature/tree_pineTallA.glb", "s": 1.00, "j": 0.32, "wc": 0.15, "ww": 0.70,
		"hc": 6.9, "hw": 3.0},
	{"m": "nature/tree_pineRoundA.glb", "s": 1.00, "j": 0.30, "wc": 0.10, "ww": 0.70,
		"hc": 6.4, "hw": 2.8},
	{"m": "nature/tree_pineDefaultA.glb", "s": 1.00, "j": 0.30, "wc": 0.10, "ww": 0.70,
		"hc": 6.6, "hw": 3.0},
	{"m": "nature/tree_pineSmallA.glb", "s": 1.00, "j": 0.34, "wc": 0.05, "ww": 0.80,
		"hc": 7.1, "hw": 3.2},
	{"m": "nature/tree_pineGroundA.glb", "s": 1.00, "j": 0.30, "wc": 0.05, "ww": 0.80,
		"hc": 8.2, "hw": 3.0},
]

# Подлесок: кусты, камни, коряги, грибы, кактусы. Ставится НЕ по карте деревьев,
# а своим броском на каждую клетку - потому и ложится в промежутки между рощами.
#
# Зачем вообще: на референсе (Dice Kingdoms) остров богат не детализацией земли,
# а тем, что на ней стоит. Пустая трава между рощами читается как незакрашенное
# место, сколько ни улучшай её оттенок. Здесь это дёшево: один мультимеш на
# породу, геометрия у всех крошечная.
#
# Ключи те же, что у деревьев. "sand" - вещь встречается и на пляже (иначе
# песчаная полоса из выборки исключается: на песке не растёт почти ничего).
const PROPS: Array[Dictionary] = [
	{"m": "nature/plant_bushDetailed.glb", "s": 1.00, "j": 0.28, "wc": 0.35, "ww": 0.50,
		"hc": 2.6, "hw": 3.4},
	{"m": "nature/plant_bush.glb", "s": 1.00, "j": 0.28, "wc": 0.20, "ww": 0.55,
		"hc": 2.6, "hw": 3.4},
	{"m": "nature/plant_bushLarge.glb", "s": 1.00, "j": 0.26, "wc": 0.30, "ww": 0.50,
		"hc": 2.6, "hw": 3.4},
	{"m": "nature/plant_bushSmall.glb", "s": 1.00, "j": 0.30, "wc": 0.05, "ww": 0.60,
		"hc": 2.4, "hw": 3.4},
	{"m": "nature/plant_bushTriangle.glb", "s": 1.00, "j": 0.26, "wc": 0.25, "ww": 0.50,
		"hc": 3.0, "hw": 3.2},
	{"m": "nature/plant_flatShort.glb", "s": 1.00, "j": 0.30, "wc": -0.15, "ww": 0.45,
		"hc": 2.2, "hw": 3.0},
	{"m": "nature/plant_flatTall.glb", "s": 1.00, "j": 0.30, "wc": -0.05, "ww": 0.45,
		"hc": 2.4, "hw": 3.0},
	{"m": "nature/mushroom_redGroup.glb", "s": 1.00, "j": 0.25, "wc": 0.60, "ww": 0.35,
		"hc": 2.6, "hw": 2.6},
	{"m": "nature/mushroom_tanGroup.glb", "s": 1.00, "j": 0.25, "wc": 0.55, "ww": 0.35,
		"hc": 2.6, "hw": 2.6},
	{"m": "nature/log_large.glb", "s": 1.00, "j": 0.20, "wc": 0.45, "ww": 0.45,
		"hc": 2.8, "hw": 3.0},
	{"m": "nature/log.glb", "s": 1.00, "j": 0.22, "wc": 0.35, "ww": 0.50,
		"hc": 2.8, "hw": 3.0},
	{"m": "nature/stump_round.glb", "s": 1.00, "j": 0.22, "wc": 0.30, "ww": 0.55,
		"hc": 2.6, "hw": 3.0},
	{"m": "nature/stump_old.glb", "s": 1.00, "j": 0.22, "wc": 0.10, "ww": 0.55,
		"hc": 2.6, "hw": 3.0},
	# Пустошь: кактусы и голые камни. Без них сухой пояс выходит просто жёлтым
	# пятном, а он должен читаться как местность.
	{"m": "nature/cactus_tall.glb", "s": 1.00, "j": 0.30, "wc": -0.70, "ww": 0.34,
		"hc": 2.2, "hw": 2.8},
	{"m": "nature/cactus_short.glb", "s": 1.00, "j": 0.30, "wc": -0.60, "ww": 0.36,
		"hc": 2.0, "hw": 2.8},
	{"m": "nature/rock_smallFlatA.glb", "s": 1.00, "j": 0.30, "wc": -0.45, "ww": 0.55,
		"hc": 2.2, "hw": 3.4, "sand": true},
	{"m": "nature/rock_smallA.glb", "s": 1.00, "j": 0.30, "wc": -0.20, "ww": 0.80,
		"hc": 3.0, "hw": 4.0, "sand": true},
	{"m": "nature/rock_smallD.glb", "s": 1.00, "j": 0.30, "wc": -0.10, "ww": 0.85,
		"hc": 3.2, "hw": 4.0, "sand": true},
	{"m": "nature/rock_smallG.glb", "s": 1.00, "j": 0.30, "wc": 0.00, "ww": 0.90,
		"hc": 4.0, "hw": 4.0},
	{"m": "nature/rock_largeA.glb", "s": 1.00, "j": 0.25, "wc": -0.10, "ww": 0.90,
		"hc": 7.1, "hw": 3.6},
	{"m": "nature/rock_largeC.glb", "s": 1.00, "j": 0.25, "wc": 0.00, "ww": 0.90,
		"hc": 7.6, "hw": 3.6},
	{"m": "nature/rock_tallA.glb", "s": 1.00, "j": 0.28, "wc": 0.00, "ww": 0.90,
		"hc": 8.4, "hw": 3.6},
	{"m": "nature/rock_tallC.glb", "s": 1.00, "j": 0.28, "wc": 0.00, "ww": 0.90,
		"hc": 7.9, "hw": 3.6},
	{"m": "nature/stone_tallB.glb", "s": 1.00, "j": 0.28, "wc": 0.00, "ww": 0.90,
		"hc": 9.4, "hw": 3.6},
]

# Мелочь под ногами: трава, клевер, цветы. Отдельный список и отдельный,
# гораздо более частый бросок - именно она отвечает за то, что земля не выглядит
# крашеной плоскостью. Раньше трава была в общем списке и в одном экземпляре на
# клетку в два с половиной метра: на кадре это читалось редкими кустиками
# посреди пустоты, а сами кустики были ростом с человека.
const COVER: Array[Dictionary] = [
	{"m": "nature/grass.glb", "s": 0.80, "j": 0.30, "wc": 0.25, "ww": 0.65, "hc": 2.6, "hw": 3.6},
	{"m": "nature/grass_large.glb", "s": 0.75, "j": 0.30, "wc": 0.35, "ww": 0.60, "hc": 2.6, "hw": 3.6},
	{"m": "nature/grass_leafs.glb", "s": 0.85, "j": 0.30, "wc": 0.10, "ww": 0.70, "hc": 2.4, "hw": 3.6},
	{"m": "nature/grass_leafsLarge.glb", "s": 0.80, "j": 0.30, "wc": 0.20, "ww": 0.65, "hc": 2.4, "hw": 3.6},
	{"m": "nature/flower_redA.glb", "s": 0.70, "j": 0.25, "wc": 0.15, "ww": 0.50, "hc": 2.2, "hw": 3.0},
	{"m": "nature/flower_yellowB.glb", "s": 0.70, "j": 0.25, "wc": 0.05, "ww": 0.55, "hc": 2.2, "hw": 3.0},
	{"m": "nature/flower_purpleA.glb", "s": 0.70, "j": 0.25, "wc": 0.20, "ww": 0.50, "hc": 2.4, "hw": 3.0},
	{"m": "nature/flower_purpleB.glb", "s": 0.70, "j": 0.25, "wc": 0.30, "ww": 0.50, "hc": 2.4, "hw": 3.0},
]


# Вес породы в точке: два гауссовых колокола - по влажности и по высоте.
#
# Колокол, а не отрезок: у отрезка есть край, и на этом краю порода исчезает
# разом. У колокола хвост, поэтому одиночная сосна встречается и ниже своего
# пояса - ровно так, как это выглядит в природе.
func _weight(spec: Dictionary, moist: float, h: float) -> float:
	var a := (moist - float(spec["wc"])) / float(spec["ww"])
	var b := (h - float(spec["hc"])) / float(spec["hw"])
	return exp(-a * a - b * b)


func _pick(list: Array, moist: float, h: float, sand: bool, rng: RandomNumberGenerator) -> int:
	var total := 0.0
	var w := PackedFloat32Array()
	w.resize(list.size())
	for i in list.size():
		var spec: Dictionary = list[i]
		# На песке растёт только то, что прямо помечено: остальному там не место,
		# и без этой отсечки пляж зарастал кустами.
		var ok := bool(spec.get("sand", false)) if sand else true
		w[i] = _weight(spec, moist, h) if ok else 0.0
		total += w[i]
	if total <= 0.0:
		return -1
	var r := rng.randf() * total
	for i in list.size():
		r -= w[i]
		if r <= 0.0:
			return i
	return list.size() - 1


func _plant_trees() -> void:
	for c in _trees.get_children():
		c.queue_free()
	var cells := IslandMap.CELLS
	var rng := RandomNumberGenerator.new()
	rng.seed = world_seed + 31

	# Сначала раскладка по породам, потом мультимеши: заполнять их по одному
	# инстансу нельзя - размер задаётся до записи.
	var spots := {}
	for i in TREES.size():
		spots[i] = []
		_footprint(String(TREES[i]["m"]))
	var jitter := IslandMap.CELL * 0.45
	for cy in cells:
		for cx in cells:
			var idx := cy * cells + cx
			if map.cell_tree[idx] == 0:
				continue
			var h := map.cell_height(cx, cy)
			var sand := map.cell_biome[idx] == IslandMap.Biome.SAND
			var choice := _pick(TREES, map.cell_moist[idx], h, false, rng)
			if choice < 0:
				continue
			# На песке - только пальмы, и наоборот: пальма посреди луга читается
			# ошибкой раньше, чем успеваешь понять, какой именно.
			var palm := String(TREES[choice]["m"]).contains("palm")
			if palm != sand:
				continue
			var c := map.cell_center(cx, cy)
			var x := c.x + rng.randf_range(-jitter, jitter)
			var z := c.z + rng.randf_range(-jitter, jitter)
			var j := float(TREES[choice]["j"])
			var s := float(TREES[choice]["s"]) * rng.randf_range(1.0 - j, 1.0 + j)
			(spots[choice] as Array).append(Transform3D(
				Basis(Vector3.UP, rng.randf() * TAU).scaled(Vector3.ONE * s),
				Vector3(x, _ground_under(x, z, _foot[String(TREES[choice]["m"])] * s), z)))

	for i in TREES.size():
		_add_multimesh(_trees, String(TREES[i]["m"]), spots[i])


# Подлесок и трава. Бросок независимый от деревьев, поэтому кусты и камни
# попадают и в рощу, и на открытую поляну - в отличие от версии, где всё росло
# из одной карты и промежутки оставались стерильными.
func _scatter_props() -> void:
	for c in _props.get_children():
		c.queue_free()
	var cells := IslandMap.CELLS
	var rng := RandomNumberGenerator.new()
	rng.seed = world_seed + 5171

	var spots := {}
	for src in [PROPS, COVER]:
		for spec in src:
			spots[String(spec["m"])] = []
			_footprint(String(spec["m"]))
	var jitter := IslandMap.CELL * 0.48
	for cy in cells:
		for cx in cells:
			var idx := cy * cells + cx
			if map.cell_land[idx] == 0:
				continue
			var h := map.cell_height(cx, cy)
			var moist: float = map.cell_moist[idx]
			var biome := int(map.cell_biome[idx])
			var sand := biome == IslandMap.Biome.SAND
			# Обрыв и снег оставляем голыми: на отвесе ничего не держится, а
			# кусты на снегу читаются мусором.
			if biome == IslandMap.Biome.CLIFF or biome == IslandMap.Biome.SNOW:
				continue
			var c := map.cell_center(cx, cy)
			# Крупная мелочь - редко, трава - часто. Густота травы идёт от
			# влажности: на пустоши её почти нет, в лесу сплошной ковёр.
			for pass_i in 2:
				var list: Array = PROPS if pass_i == 0 else COVER
				var p := 0.09 if pass_i == 0 else lerpf(0.02, 0.42,
					smoothstep(-0.5, 0.45, moist))
				if sand:
					p *= 0.22
				if rng.randf() >= p:
					continue
				var k := _pick(list, moist, h, sand, rng)
				if k < 0:
					continue
				var spec: Dictionary = list[k]
				var path := String(spec["m"])
				var x := c.x + rng.randf_range(-jitter, jitter)
				var z := c.z + rng.randf_range(-jitter, jitter)
				var j := float(spec["j"])
				var s := float(spec["s"]) * rng.randf_range(1.0 - j, 1.0 + j)
				(spots[path] as Array).append(Transform3D(
					Basis(Vector3.UP, rng.randf() * TAU).scaled(Vector3.ONE * s),
					Vector3(x, _ground_under(x, z, _foot[path] * s), z)))

	for src in [PROPS, COVER]:
		for spec in src:
			var path := String(spec["m"])
			_add_multimesh(_props, path, spots[path])


# Массивы земли держатся в памяти: цвет вершин меняется при каждой постройке
# (вытоптанная земля вокруг неё), и пересчитывать ради этого весь рельеф с
# нуля незачем.
var _g_arrays: Array = []


func _refresh_ground() -> void:
	var mesh := ArrayMesh.new()
	mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, _g_arrays)
	mesh.surface_set_material(0, _ground_mat)
	_ground.mesh = mesh


# Вытоптанная земля вокруг постройки.
#
# Дом, поставленный на нетронутый луг, выглядит вырезанным и наклеенным: у
# жилья не бывает травы впритык к стене. Здесь земля не подкладывается отдельной
# плашкой (её пришлось бы подгонять к рельефу и она бы дрожала на склоне), а
# ЗАПЕКАЕТСЯ В ЦВЕТ ВЕРШИН той же земли - то есть повторяет рельеф точно и
# ничего не стоит при отрисовке.
func stomp_cell(cell: Vector2i, n := 2) -> void:
	if map == null or _g_arrays.is_empty():
		return
	var side := IslandMap.CELLS + 1
	var colors: PackedColorArray = _g_arrays[Mesh.ARRAY_COLOR]
	var dirt := DIRT.srgb_to_linear()
	# Узлы площадки - это (cx, cy)..(cx+n, cy+n). Берём с запасом в два узла:
	# пятно должно выходить за стены, иначе получается коврик ровно по дому.
	# Сила падает от середины к краю - у пятна мягкий кант, а не квадратная
	# заплата. С мелкой клеткой это стало заметно: узлов на здание вчетверо
	# больше, и ступенька из двух уровней читалась рамкой.
	var pad := 2
	var mid := Vector2(float(cell.x) + float(n) * 0.5, float(cell.y) + float(n) * 0.5)
	var edge := float(n) * 0.5
	for dj in range(-pad, n + pad + 1):
		for di in range(-pad, n + pad + 1):
			var i := cell.x + di
			var j := cell.y + dj
			if i < 0 or j < 0 or i >= side or j >= side:
				continue
			var d := Vector2(float(i), float(j)).distance_to(mid)
			var k := 0.92 * (1.0 - smoothstep(edge * 0.5, edge + float(pad) * 0.8, d))
			if k <= 0.01:
				continue
			var idx := j * side + i
			colors[idx] = (colors[idx] as Color).lerp(dirt, k)
	_g_arrays[Mesh.ARRAY_COLOR] = colors
	_refresh_ground()


# Растительность под зданием убирается: дерево, растущее сквозь крышу, портит
# посёлок вернее, чем любая недоделка освещения.
#
# Инстансы не удаляются - у мультимеша нельзя выкинуть один, не пересобрав
# весь, - а схлопываются в точку нулевым масштабом. Перебор всех инстансов на
# каждую постройку выглядит расточительно, но это ЩЕЛЧОК, а не кадр: четыре
# тысячи сравнений разово не стоят ничего, зато не нужен указатель «клетка ->
# инстансы», который пришлось бы держать в согласии с пересборкой карты.
func clear_cell(cell: Vector2i, n := 2) -> void:
	if map == null:
		return
	var a := map.cell_center(cell.x, cell.y)
	var b := map.cell_center(cell.x + n - 1, cell.y + n - 1)
	var c := (a + b) * 0.5
	# Чуть шире площадки: здание её перекрывает, и куст у самой межи торчит
	# из-под стены.
	var half := float(n) * IslandMap.CELL * 0.62
	for parent in [_trees, _props]:
		for child in parent.get_children():
			var mmi := child as MultiMeshInstance3D
			if mmi == null or mmi.multimesh == null:
				continue
			var mm := mmi.multimesh
			for k in mm.instance_count:
				var tr := mm.get_instance_transform(k)
				if absf(tr.origin.x - c.x) > half or absf(tr.origin.z - c.z) > half:
					continue
				mm.set_instance_transform(k,
					Transform3D(Basis().scaled(Vector3.ZERO), tr.origin))


# Радиус подошвы модели в её собственных единицах: половина большей стороны по
# горизонтали. Считается один раз на породу - меш всё равно уже загружен и
# закэширован в Kit.
var _foot := {}


func _footprint(path: String) -> float:
	if _foot.has(path):
		return _foot[path]
	var mesh := Kit.mesh_for(path)
	var r := 0.0
	if mesh != null:
		var box := mesh.get_aabb()
		r = 0.5 * maxf(box.size.x, box.size.z)
	_foot[path] = r
	return r


# Высота, на которую садится предмет с подошвой радиуса r: САМАЯ НИЗКАЯ точка
# под ней, а не высота середины.
#
# Ставить по одной точке нельзя. На склоне середина ложится на землю, а нижний
# край повисает в воздухе: у камня шириной два метра на уклоне 0.6 это полметра
# просвета, и на кадре камни висят над берегом. Утопить не жалко - зарытый край
# не читается вовсе, а висящий виден сразу.
func _ground_under(x: float, z: float, r: float) -> float:
	var h := map.height_at(x, z)
	if r > 0.05:
		h = minf(h, map.height_at(x - r, z))
		h = minf(h, map.height_at(x + r, z))
		h = minf(h, map.height_at(x, z - r))
		h = minf(h, map.height_at(x, z + r))
	return h - 0.04


# Один мультимеш на породу: одна геометрия, сотни расстановок, один вызов
# отрисовки. custom_aabb задаётся вручную на всю карту - иначе движок считает
# охват по мешу-образцу (полтора метра) и отсекает весь мультимеш, стоит
# образцу уйти за край экрана.
func _add_multimesh(parent: Node3D, path: String, list: Array) -> void:
	if list.is_empty():
		return
	var mesh := Kit.mesh_for(path)
	if mesh == null:
		return
	var mm := MultiMesh.new()
	mm.transform_format = MultiMesh.TRANSFORM_3D
	mm.mesh = mesh
	mm.instance_count = list.size()
	for k in list.size():
		mm.set_instance_transform(k, list[k])
	var node := MultiMeshInstance3D.new()
	node.multimesh = mm
	node.custom_aabb = AABB(
		Vector3(-IslandMap.HALF, -2.0, -IslandMap.HALF),
		Vector3(IslandMap.HALF * 2.0, map.max_height + 12.0, IslandMap.HALF * 2.0))
	parent.add_child(node)


func _place_start() -> void:
	if _start_point == null:
		return
	_start_point.position = map.start_pos
	_start_point.visible = true


# --------------------------------------------------------------------------- #
# Курсор клетки
# --------------------------------------------------------------------------- #

# Клетка под мышью ищется маршем по лучу, а не физикой: коллизий у меша земли
# нет и заводить их ради подсветки было бы дорого. Марш начинается не от
# камеры, а с высоты самой высокой точки карты - до неё пересечения быть не
# может, и полсотни шагов экономятся на пустом небе.
func pick_cell(cam: Camera3D, screen: Vector2) -> Vector2i:
	if cam == null or map == null:
		return Vector2i(-1, -1)
	var o := cam.project_ray_origin(screen)
	var d := cam.project_ray_normal(screen)
	if d.y > -0.001:
		return Vector2i(-1, -1)          # взгляд вверх: земли впереди нет

	var t := (map.max_height - o.y) / d.y
	t = maxf(t, 0.0)
	# Шаг марша не мельче метра: он задаёт не точность (её даёт уточнение
	# делением ниже), а длину луча - девятьсот шагов по полклетки не достают до
	# горизонта с дальнего приближения.
	var step := maxf(IslandMap.CELL * 0.5, 1.0)
	var prev := o + d * t
	for i in 900:
		t += step
		var p := o + d * t
		if p.y < -14.0:
			return Vector2i(-1, -1)
		if p.y <= map.height_at(p.x, p.z):
			# Уточнение делением отрезка: без него курсор дрожит на полклетки.
			var lo := prev
			var hi := p
			for j in 8:
				var mid := (lo + hi) * 0.5
				if mid.y <= map.height_at(mid.x, mid.z):
					hi = mid
				else:
					lo = mid
			var hit := (lo + hi) * 0.5
			return map.cell_at(hit.x, hit.z)
		prev = p
	return Vector2i(-1, -1)


func _update_cursor() -> void:
	if map == null:
		return
	# Во время осмотра мышь захвачена и её экранная позиция стоит на месте -
	# подсвечивать под ней клетку бессмысленно.
	if _camera_rig != null and _camera_rig.has_method("looking") and _camera_rig.call("looking"):
		_cursor.visible = false
		return
	var cell := pick_cell(get_viewport().get_camera_3d(), get_viewport().get_mouse_position())
	if not map.inside(cell.x, cell.y) or not map.is_land(cell.x, cell.y):
		_cursor.visible = false
		if _hover != Vector2i(-1, -1):
			_hover = Vector2i(-1, -1)
			hover_changed.emit(_hover, {})
		return
	# Перерисовываем и когда сменилась ВЫБРАННАЯ ПОСТРОЙКА: у другого типа
	# другая площадка, а курсор обязан показывать её сразу, не дожидаясь, пока
	# мышь переедет на соседнюю клетку.
	var span := _cursor_span()
	if cell != _hover or span != _cursor_n:
		_hover = cell
		_cursor_n = span
		_draw_cursor(cell)
		hover_changed.emit(cell, cell_info(cell))
	_cursor_mat.albedo_color = _cursor_color()
	_cursor.visible = true


# Цвет курсора - это ответ на вопрос «можно ли тут строить», а не украшение.
# В обычном режиме он нейтральный, в режиме постройки зелёный или красный.
func _cursor_color() -> Color:
	if _builder == null or String(_builder.call("selected")) == "":
		return Color(1.0, 0.97, 0.65, 0.30)
	var why := String(_builder.call("check", _hover))
	return Color(0.45, 0.95, 0.5, 0.42) if why == "" else Color(0.95, 0.35, 0.32, 0.42)


func cell_info(cell: Vector2i) -> Dictionary:
	if map == null or not map.inside(cell.x, cell.y):
		return {}
	return {
		"cell": cell,
		"biome": IslandMap.BIOME_NAMES[map.biome_at(cell.x, cell.y)],
		"height": map.cell_height(cell.x, cell.y),
		"slope": map.cell_slope(cell.x, cell.y),
		"land": map.is_land(cell.x, cell.y),
	}


# Курсор повторяет рельеф ПЛОЩАДКИ по её клеткам: плоский квадрат на склоне
# наполовину уходил бы в землю.
#
# Показывается именно площадка целиком, а не клетка под мышью. Здание занимает
# несколько клеток, и если подсвечивать одну, человек целится одним квадратом,
# а постройка встаёт по другому - промах на два метра при каждой попытке.
func _draw_cursor(cell: Vector2i) -> void:
	var m := _cursor.mesh as ImmediateMesh
	m.clear_surfaces()
	var n := _cursor_span()
	var cs := IslandMap.CELL
	var lift := Vector3(0.0, 0.05, 0.0)
	m.surface_begin(Mesh.PRIMITIVE_TRIANGLES)
	for dy in n:
		for dx in n:
			var i := cell.x + dx
			var j := cell.y + dy
			var x0 := -IslandMap.HALF + float(i) * cs
			var z0 := -IslandMap.HALF + float(j) * cs
			var a := Vector3(x0, map.node_height(i, j), z0) + lift
			var b := Vector3(x0 + cs, map.node_height(i + 1, j), z0) + lift
			var c := Vector3(x0 + cs, map.node_height(i + 1, j + 1), z0 + cs) + lift
			var d := Vector3(x0, map.node_height(i, j + 1), z0 + cs) + lift
			for v in [a, b, c, a, c, d]:
				m.surface_add_vertex(v)
	m.surface_end()


func _cursor_span() -> int:
	if _builder == null:
		return 1
	var id := String(_builder.call("selected"))
	if id == "" or id == "demolish":
		return 1
	return int(_builder.call("footprint", id))


func hovered_cell() -> Vector2i:
	return _hover


# --------------------------------------------------------------------------- #
# Меши и материалы
# --------------------------------------------------------------------------- #

func _ground_material() -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	m.vertex_color_use_as_albedo = true
	m.roughness = 0.94
	m.metallic_specular = 0.12
	return m


func _cursor_material() -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	m.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	m.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	m.albedo_color = Color(1.0, 0.97, 0.65, 0.30)
	m.cull_mode = BaseMaterial3D.CULL_DISABLED
	return m
