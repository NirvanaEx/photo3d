extends Node3D

# Горожане: жители посёлка, у которых есть дом, работа и распорядок.
#
# Зачем: посёлок без людей читается макетом. Одно движение делает место
# обжитым вернее, чем любая доводка света.
#
# Модель ГОТОВАЯ - Quaternius, Animated Men/Women Pack (CC0, по полмегабайта,
# одиннадцать анимаций: ходьба, стойка, сидение, хлопки). Здесь уже стояли две
# предыдущие: сперва капсула с шаром вместо головы, потом фигурка KayKit. Обе
# выброшены по одной причине - ПРОПОРЦИИ. У капсулы их нет вовсе, у KayKit
# голова размером с туловище: набор рисован под свой стиль, и рядом с домами
# такой человечек читается игрушкой, а не жителем. У этих моделей сложение
# обычное, семь голов в росте, и походка сделана скелетной анимацией, а не
# покачиванием узла.
#
# Ходят они ПО ДЕЛУ, а не куда попало. У каждого свой дом и своё рабочее место,
# и порядок обхода один и тот же: из дома на работу, с работы на площадь, с
# площади домой. Случайный выбор двери, который был раньше, на кадре выглядел
# ровно тем, чем был, - броуновским движением. Экономики за этим по-прежнему
# нет: появится - сюда придёт задание «отнести с фермы в амбар», и менять
# придётся только выбор цели.

const IslandMap := preload("res://scripts/islands/island_map.gd")

# Модели. Несколько нарочно: один и тот же силуэт, размноженный тридцать раз,
# читается копипастой даже при разной одежде.
const MODELS: Array[String] = [
	"res://assets/kits/folk/man_a.glb",
	"res://assets/kits/folk/man_b.glb",
	"res://assets/kits/folk/man_c.glb",
	"res://assets/kits/folk/woman_a.glb",
	"res://assets/kits/folk/woman_b.glb",
]

# Рост горожанина в метрах игры и рост модели в её собственных единицах.
#
# Мир этой игры считается в единицах, где дом из набора KayKit шириной 2.3 - то
# есть примерно семиметровый. Тогда человек ростом 1.75 м занимает полединицы,
# и это же значение получается из ДВЕРИ: у модели дома проём высотой около 0.52
# единицы, человек обязан в него проходить с запасом.
const HEIGHT := 0.50
const MODEL_HEIGHT := 4.84

## Сколько горожан на одну постройку.
@export var per_building := 0.8
## Потолок: на большом посёлке толпа съедает кадр и ничего не добавляет.
@export var max_count := 34
## Скорость шага, единиц в секунду. Считается ОТ РОСТА: полторы единицы в
## секунду для фигурки в полметра это три роста в секунду, то есть спринт.
@export var speed := 0.42
@export var world_path: NodePath
@export var builder_path: NodePath

# Одежда. Тёплая приглушённая гамма под стать домам: у моделей рубаха, штаны и
# волосы - отдельные материалы, поэтому красится именно одежда, а не человек
# целиком (у прежней модели материал был один на всё, и горожанин выходил
# монохромным).
const SHIRTS: Array[Color] = [
	Color(0.72, 0.36, 0.28), Color(0.38, 0.46, 0.62), Color(0.44, 0.54, 0.34),
	Color(0.76, 0.62, 0.32), Color(0.52, 0.40, 0.56), Color(0.80, 0.76, 0.66),
	Color(0.62, 0.44, 0.30), Color(0.34, 0.52, 0.50),
]
const PANTS: Array[Color] = [
	Color(0.34, 0.28, 0.23), Color(0.28, 0.30, 0.36), Color(0.45, 0.38, 0.28),
	Color(0.24, 0.24, 0.26), Color(0.40, 0.32, 0.30),
]
const HAIRS: Array[Color] = [
	Color(0.16, 0.12, 0.09), Color(0.32, 0.20, 0.11), Color(0.52, 0.36, 0.18),
	Color(0.68, 0.56, 0.36), Color(0.46, 0.45, 0.44),
]
# Материалы, которые НЕ красим: кожа и глаза. Красить их - верный способ
# получить зелёных людей.
const KEEP: Array[String] = ["Skin", "Eyes"]

# Где жильё, а где работа. Разделение нужно только распорядку: горожанин должен
# уходить из дома в одно место, а возвращаться в другое.
const HOMES: Array[String] = ["house"]

# Насколько близко к зданию горожанин подходить не должен - половина стороны
# площадки самого мелкого здания.
const SOLID := IslandMap.CELL * 0.96

var _world: Node3D
var _builder: Node3D
var _map: IslandMap
var _folk: Array = []
var _doors: Array = []           # {pos, type, cell} - обновляется на постройке
var _homes: Array = []
var _jobs: Array = []
var _solid := {}                 # Vector2i занятых клеток - для обхода
var _rng := RandomNumberGenerator.new()
var _scenes := {}


func _ready() -> void:
	_world = get_node_or_null(world_path)
	_builder = get_node_or_null(builder_path)
	_rng.seed = 20260803
	for path in MODELS:
		if ResourceLoader.exists(path):
			_scenes[path] = load(path)
		else:
			push_warning("нет модели %s - горожан станет меньше. Проверь импорт" % path)
	if _scenes.is_empty():
		push_warning("моделей горожан нет вовсе - посёлок останется пустым")

	if _world != null:
		_world.connect("world_ready", _on_world_ready)
		if _world.get("map") != null:
			_on_world_ready(_world.get("map"))
	if _builder != null and _builder.has_signal("placed"):
		_builder.connect("placed", func(_id, _cell): _sync())


func _on_world_ready(map) -> void:
	_map = map
	for f in _folk:
		var n: Node3D = f["node"]
		if is_instance_valid(n):
			n.queue_free()
	_folk.clear()
	_sync()


# --------------------------------------------------------------------------- #
# Население
# --------------------------------------------------------------------------- #

func _sync() -> void:
	if _map == null or _builder == null or _scenes.is_empty():
		return
	_doors = []
	_solid = {}
	if _builder.has_method("entrances"):
		_doors = _builder.call("entrances")
	if _builder.has_method("occupied_cells"):
		for cell in _builder.call("occupied_cells"):
			_solid[cell] = true
	_homes = []
	_jobs = []
	for d in _doors:
		if String(d["type"]) in HOMES:
			_homes.append(d)
		else:
			_jobs.append(d)
	if _doors.is_empty():
		return

	var want := mini(int(round(float(_doors.size()) * per_building)), max_count)
	while _folk.size() > want:
		var f: Dictionary = _folk.pop_back()
		var n: Node3D = f["node"]
		if is_instance_valid(n):
			n.queue_free()
	while _folk.size() < want:
		_folk.append(_spawn())
	# Дом или работа могли сгореть - тогда прежняя цель ведёт в пустоту.
	for f in _folk:
		_reassign(f)


func _spawn() -> Dictionary:
	var keys := _scenes.keys()
	var node := (_scenes[keys[_rng.randi() % keys.size()]] as PackedScene).instantiate() as Node3D
	node.scale = Vector3.ONE * (HEIGHT / MODEL_HEIGHT)
	_dress(node)

	var f := {
		"node": node,
		"home": _homes[_rng.randi() % _homes.size()] if not _homes.is_empty() else null,
		"job": _jobs[_rng.randi() % _jobs.size()] if not _jobs.is_empty() else null,
		"anim": node.find_child("AnimationPlayer", true, false) as AnimationPlayer,
		"names": {},
		"state": "wait", "t": 0.0, "dur": 1.0, "wait": _rng.randf_range(0.2, 4.0),
		"stage": _rng.randi() % 3,
		"speed": speed * _rng.randf_range(0.85, 1.15),
		"from": Vector3.ZERO, "to": Vector3.ZERO,
	}
	var ap: AnimationPlayer = f["anim"]
	if ap != null:
		for want in ["Walk", "Idle", "Standing", "Sitting", "Clapping"]:
			var found := _find_anim(ap, want)
			if found != "":
				(f["names"] as Dictionary)[want] = found
		# Сдвиг фазы у каждого свой: шеренга людей, шагающих в ногу, сразу
		# выдаёт одну анимацию на всех.
		ap.speed_scale = _rng.randf_range(0.9, 1.15)

	var start: Vector3 = _doors[_rng.randi() % _doors.size()]["pos"]
	node.position = start
	f["from"] = start
	f["to"] = start
	add_child(node)
	_play(f, "Idle")
	if ap != null:
		ap.advance(_rng.randf() * 1.5)
	return f


# Одежда: рубаха, штаны и волосы - каждому свои. Материал КОПИРУЕТСЯ на каждого
# отдельно, иначе перекрасился бы весь посёлок разом: у загруженной модели
# материал общий.
func _dress(node: Node3D) -> void:
	var shirt := SHIRTS[_rng.randi() % SHIRTS.size()]
	var pants := PANTS[_rng.randi() % PANTS.size()]
	var hair := HAIRS[_rng.randi() % HAIRS.size()]
	for mi in node.find_children("*", "MeshInstance3D", true, false):
		var m := mi as MeshInstance3D
		if m.mesh == null:
			continue
		for i in m.mesh.get_surface_count():
			var src := m.mesh.surface_get_material(i) as BaseMaterial3D
			if src == null:
				continue
			var name := src.resource_name
			if name in KEEP:
				continue
			var mat := src.duplicate() as BaseMaterial3D
			if name.begins_with("Shirt") or name == "Details" or name == "TieTexture":
				mat.albedo_color = shirt
			elif name.begins_with("Pants") or name == "Shoes" or name == "Socks":
				mat.albedo_color = pants
			elif name.begins_with("Hair"):
				mat.albedo_color = hair
			else:
				continue
			mat.roughness = 0.94
			m.set_surface_override_material(i, mat)


func _find_anim(ap: AnimationPlayer, want: String) -> String:
	for name in ap.get_animation_list():
		var s := String(name)
		if s == want or s.ends_with(want):
			return s
	return ""


func _play(f: Dictionary, want: String) -> void:
	var ap: AnimationPlayer = f["anim"]
	if ap == null:
		return
	var names: Dictionary = f["names"]
	var pick := String(names.get(want, names.get("Idle", "")))
	if pick != "" and ap.current_animation != pick:
		ap.play(pick)


# Дом или работа сгорели - выдаём новые. Без этого горожанин ходил бы к двери,
# которой больше нет, и стоял бы там до конца партии.
func _reassign(f: Dictionary) -> void:
	if not _alive(f["home"]):
		f["home"] = _homes[_rng.randi() % _homes.size()] if not _homes.is_empty() else null
	if not _alive(f["job"]):
		f["job"] = _jobs[_rng.randi() % _jobs.size()] if not _jobs.is_empty() else null


func _alive(door) -> bool:
	if door == null:
		return false
	for d in _doors:
		if d["cell"] == door["cell"]:
			return true
	return false


# --------------------------------------------------------------------------- #
# Распорядок
# --------------------------------------------------------------------------- #

func _process(delta: float) -> void:
	if _map == null or _folk.is_empty():
		return
	for f in _folk:
		_step(f, delta)


func _step(f: Dictionary, delta: float) -> void:
	var node: Node3D = f["node"]
	if not is_instance_valid(node):
		return

	match String(f["state"]):
		"inside":
			# Внутри здания: фигурка спрятана, идёт отсчёт до выхода.
			node.visible = false
			f["wait"] = float(f["wait"]) - delta
			if float(f["wait"]) <= 0.0:
				_depart(f)
		"wait":
			# Стоит снаружи: у двери, на площади, у костра. Именно эти паузы и
			# отличают «идёт по делу» от «мечется»: без них горожанин движется
			# непрерывно и читается заводной игрушкой.
			node.visible = true
			f["wait"] = float(f["wait"]) - delta
			if float(f["wait"]) <= 0.0:
				_depart(f)
		_:
			node.visible = true
			_walk(f, delta)


func _walk(f: Dictionary, delta: float) -> void:
	var node: Node3D = f["node"]
	f["t"] = float(f["t"]) + delta / maxf(float(f["dur"]), 0.01)
	if float(f["t"]) >= 1.0:
		node.position = f["to"]
		_arrive(f)
		return

	var p: Vector3 = (f["from"] as Vector3).lerp(f["to"], float(f["t"]))
	p = _push_out(p, f["to"])
	p.y = _map.height_at(p.x, p.z)
	var dir := p - node.position
	node.position = p
	# Модель смотрит вдоль своего -Z, как принято в Godot: look_at разворачивает
	# именно эту ось. Порог проверяется по ГОРИЗОНТАЛЬНОЙ части: на крутом
	# подъёме шаг бывает почти отвесным, и тогда цель look_at совпадает с самой
	# фигуркой - движок на это ругается и разворот пропадает.
	var flat := Vector2(dir.x, dir.z)
	if flat.length_squared() > 1e-8:
		node.look_at(p + Vector3(flat.x, 0.0, flat.y), Vector3.UP)


# Пришли. Если цель - дверь, заходим внутрь; если площадь или поле, стоим.
func _arrive(f: Dictionary) -> void:
	if bool(f.get("enter", false)):
		f["state"] = "inside"
		f["wait"] = _rng.randf_range(3.0, 12.0)
		(f["node"] as Node3D).visible = false
		_play(f, "Idle")
	else:
		f["state"] = "wait"
		f["wait"] = _rng.randf_range(2.0, 9.0)
		# У стояния три вида: просто стоять, сидеть, хлопать. Три разных позы на
		# площади читаются людьми, одна - манекенами.
		_play(f, ["Standing", "Sitting", "Clapping", "Idle"][_rng.randi() % 4])


# Выбор следующей цели. Порядок один и тот же: дом -> работа -> площадь -> дом.
#
# Это и есть «осознанность»: маршрут повторяется, у каждого свои дом и работа,
# и по посёлку видно, куда человек идёт. Полноценного поиска пути тут нет и не
# нужно - здания стоят на равнине, а стены обходятся выталкиванием.
func _depart(f: Dictionary) -> void:
	var node: Node3D = f["node"]
	var stage := int(f["stage"])
	var goal = null
	var enter := true
	match stage:
		0:
			goal = f["job"]
			if goal == null:
				goal = _near(node.position, _doors)
		1:
			# Между работой и домом - прогулка: площадь, чужое крыльцо или
			# просто открытое место неподалёку.
			if _rng.randf() < 0.45:
				goal = _stroll(node.position)
				enter = false
			else:
				goal = _near(node.position, _doors)
		_:
			goal = f["home"]
			if goal == null:
				goal = _near(node.position, _homes if not _homes.is_empty() else _doors)
	f["stage"] = (stage + 1) % 3

	var to: Vector3 = node.position
	if goal is Dictionary:
		to = goal["pos"]
	elif goal is Vector3:
		to = goal
	else:
		enter = false
	# Цель за морем или слишком далеко - идти туда по прямой значило бы шагать
	# по волнам. Проверяется и САМА ЦЕЛЬ: у верфи дверь выходит на помост, то
	# есть стоит над водой, и без этой проверки горожанин уходил бы в море.
	if to.distance_to(node.position) > 34.0 or _map.height_at(to.x, to.z) <= 0.05 \
			or not _dry_path(node.position, to):
		to = _stroll(node.position)
		enter = false

	f["from"] = node.position
	f["to"] = to
	f["enter"] = enter
	f["dur"] = maxf(to.distance_to(node.position) / float(f["speed"]), 0.5)
	f["t"] = 0.0
	f["state"] = "walk"
	_play(f, "Walk")


# Ближайшая из дверей, но не та, у которой стоим.
func _near(from: Vector3, list: Array):
	var best = null
	var best_d := INF
	for d in list:
		var v: Vector3 = d["pos"]
		var dist := v.distance_to(from)
		if dist < 1.2 or dist > 34.0:
			continue
		if dist < best_d:
			best_d = dist
			best = d
	return best


# Точка для прогулки: открытое место в нескольких шагах, обязательно на суше и
# не внутри чужого дома.
func _stroll(from: Vector3) -> Vector3:
	for tries in 12:
		var a := _rng.randf() * TAU
		var r := _rng.randf_range(2.5, 9.0)
		var p := from + Vector3(cos(a) * r, 0.0, sin(a) * r)
		if _map.height_at(p.x, p.z) <= 0.15:
			continue
		var cell := _map.cell_at(p.x, p.z)
		if _solid.has(cell):
			continue
		return Vector3(p.x, _map.height_at(p.x, p.z), p.z)
	return from


# Не проходит ли прямая через воду. Пять проб хватает: бухты у этих островов
# шире десяти метров, а точнее считать - это уже поиск пути.
func _dry_path(a: Vector3, b: Vector3) -> bool:
	for i in range(1, 6):
		var p := a.lerp(b, float(i) / 6.0)
		if _map.height_at(p.x, p.z) <= 0.05:
			return false
	return true


# Обход построек: горожанин не проходит сквозь стены.
#
# Полноценный поиск пути здесь не нужен и вреден - он потянул бы за собой
# сетку проходимости и её пересборку на каждую постройку. Хватает
# ВЫТАЛКИВАНИЯ: точка, попавшая внутрь занятой клетки, сдвигается наружу по
# кратчайшей стороне. Горожанин обходит дом по стенке, а не сквозь него.
#
# Клетка, к двери которой он идёт, из проверки исключается: иначе до цели он
# бы никогда не добрался.
func _push_out(p: Vector3, target: Vector3) -> Vector3:
	var goal := _map.cell_at(target.x, target.z)
	var here := _map.cell_at(p.x, p.z)
	var reach := int(ceil(SOLID / IslandMap.CELL))
	for dy in range(-reach, reach + 1):
		for dx in range(-reach, reach + 1):
			var cell := Vector2i(here.x + dx, here.y + dy)
			if cell == goal or not _solid.has(cell):
				continue
			var c := _map.cell_center(cell.x, cell.y)
			var ox := p.x - c.x
			var oz := p.z - c.z
			var half := IslandMap.CELL * 0.5
			if absf(ox) >= half or absf(oz) >= half:
				continue
			# Выталкиваем по той оси, по которой ближе к краю: так фигурка
			# скользит вдоль стены, а не отскакивает по диагонали.
			if half - absf(ox) < half - absf(oz):
				p.x = c.x + signf(ox) * half
			else:
				p.z = c.z + signf(oz) * half
	return p
