extends Node3D

# Постройки: что можно ставить, куда, за сколько - и как это строится, горит и
# рушится.
#
# Модели готовые (CC0, assets/kits): KayKit - здания, Kenney - природа, пирсы и
# мелочи. Новый тип добавляется ОДНОЙ записью в TYPES, без единой строки кода.
#
# Вынесено из мира отдельным узлом нарочно: мир отвечает за рельеф и не должен
# знать ни про запасы, ни про цены, ни про пожары.
#
# Правила размещения возвращают ПРИЧИНУ отказа строкой, а не false. Интерфейс
# показывает её человеку («нужно ровное место») - тот же принцип, что у ошибок
# остального проекта: сбой обязан подсказывать следующий шаг.

signal selection_changed(id: String)
signal stock_changed(stock: Dictionary)
signal placed(id: String, cell: Vector2i)
signal refused(reason: String)
signal notice(text: String)

const IslandMap := preload("res://scripts/islands/island_map.gd")
const Kit := preload("res://scripts/islands/kit.gd")

const KIT := "res://assets/kits/"
const BURN_SEC := 5.0              # столько горит перед обрушением

# Предельный уклон под застройку. Взят по замеру: на равнинах новых профилей
# уклон держится ниже 0.2, на подъёме от воды доходит до 0.6, на склонах горы
# выше единицы. 0.45 пропускает равнину и полку, но не склон.
const MAX_SLOPE := 0.45
const DEMOLISH := "demolish"       # не тип постройки, а режим сноса

const START_STOCK := {"wood": 260, "stone": 180, "food": 90, "gold": 60}

const RESOURCES: Array[Dictionary] = [
	{"id": "wood", "title": "дерево", "color": Color(0.55, 0.75, 0.35)},
	{"id": "stone", "title": "камень", "color": Color(0.66, 0.68, 0.72)},
	{"id": "food", "title": "еда", "color": Color(0.90, 0.62, 0.32)},
	{"id": "gold", "title": "золото", "color": Color(0.93, 0.80, 0.35)},
]

# Здание - ОДНА модель из набора KayKit (CC0), а не башенка, собранная из трёх
# кубиков замка. Разница видна сразу: раньше посёлок состоял из одинаковых
# квадратных вышек с синей крышей, потому что других частей в наборе не было.
#
# Здание встаёт МГНОВЕННО. Была стройка по шагам с полосой готовности на
# десять секунд - от неё отказались: в игре про застройку острова десять секунд
# ожидания на каждый дом это не «процесс», а простой. Вместо неё - облачко
# пыли: оно занимает те же полсекунды внимания и ничего не задерживает.
#
# ОБВЕС (extras) - половина работы. Голая модель из набора при приближении
# читается фишкой настольной игры: она стоит на пустой земле, и вокруг неё
# ничего не происходит. Бочки, поленница, забор, грядки и дорожка от двери
# стоят дёшево, а превращают фишку в двор. Ставятся они детерминированно от
# клетки, поэтому пересборка карты не «перемешивает» посёлок.
#
# Ключи типа:
#   body   - главная модель, scale - её масштаб в единицах набора;
#   cells  - сторона квадрата клеток, который здание занимает целиком;
#   extras - обвес; x/y/z В МЕТРАХ от середины здания (раньше были доли модели -
#            числа зависели от масштаба тела и не переносились между наборами),
#            s - масштаб самой модели куска, r - поворот в оборотах,
#            bob - качается на волне;
#   door   - вход в метрах от середины (по умолчанию перед фасадом, +Z);
#   water  - можно ли ставить на воду у берега;
#   work   - признаки работы: spin (имя узла, который крутится), smoke (откуда
#            идёт дым, В МЕТРАХ), rails (штольня с вагонеткой).

const TYPES: Array[Dictionary] = [
	{
		"id": "house", "title": "Дом", "hint": "жильё",
		"cost": {"wood": 40, "stone": 15}, "color": Color(0.85, 0.45, 0.36),
		"scale": 1.35, "cells": 2,
		"body": "kaykit/house.glb",
		"extras": [
			{"m": "village/well.glb", "x": 1.05, "z": 0.75, "s": 0.5},
			{"m": "village/barrel.glb", "x": -1.0, "z": 0.55, "s": 1.3},
			{"m": "village/crate.glb", "x": -1.05, "z": 0.15, "s": 1.4, "r": 0.11},
			{"m": "nature/log_stack.glb", "x": 0.95, "z": -0.85, "s": 0.9, "r": 0.25},
			{"m": "nature/flower_redB.glb", "x": -0.45, "z": 1.05, "s": 0.8},
			{"m": "nature/flower_yellowA.glb", "x": -0.15, "z": 1.1, "s": 0.8},
		],
		# Труба найдена ЗАМЕРОМ по вершинам модели, а не на глаз: верхушка дома
		# это компактный столбик на (0.38, 0.90, -0.40) в единицах модели, то
		# есть (0.51, 1.26, -0.54) метра при её масштабе. Раньше стояло
		# зеркально по Z, и дым шёл из конька крыши.
		"work": {"smoke": Vector3(0.51, 1.26, -0.54), "chance": 0.55},
	},
	{
		"id": "farm", "title": "Ферма", "hint": "еда с полей",
		"cost": {"wood": 25}, "color": Color(0.88, 0.74, 0.34),
		"scale": 1.55, "cells": 3,
		"body": "kaykit/farm_plot.glb",
		# Поле вокруг делянки: борозды, колосья, тыквы и забор с воротами. Одна
		# делянка из набора посреди луга читалась ковриком, а не хозяйством.
		"extras": [
			{"m": "nature/crops_dirtDoubleRow.glb", "x": 0.0, "z": 1.5, "s": 1.5},
			{"m": "nature/crops_wheatStageB.glb", "x": -0.5, "z": 1.35, "s": 0.85},
			{"m": "nature/crops_wheatStageB.glb", "x": 0.45, "z": 1.65, "s": 0.85},
			{"m": "nature/crops_wheatStageA.glb", "x": 0.0, "z": 1.5, "s": 0.85},
			{"m": "nature/crop_pumpkin.glb", "x": -1.5, "z": 0.9, "s": 0.9},
			{"m": "nature/crop_pumpkin.glb", "x": -1.25, "z": 1.35, "s": 0.75, "r": 0.3},
			{"m": "nature/fence_simple.glb", "x": -1.0, "z": -1.6, "s": 1.0},
			{"m": "nature/fence_gate.glb", "x": 0.35, "z": -1.6, "s": 1.0},
			{"m": "village/hay.glb", "x": 1.45, "z": -1.1, "s": 1.4},
			{"m": "village/cart.glb", "x": 1.5, "z": 0.5, "s": 0.6, "r": 0.25},
		],
	},
	{
		"id": "mill", "title": "Мельница", "hint": "мелет зерно",
		"cost": {"wood": 70, "stone": 25}, "color": Color(0.80, 0.66, 0.45),
		"scale": 1.2, "cells": 2,
		"body": "kaykit/mill.glb",
		"extras": [
			{"m": "village/bags.glb", "x": -0.95, "z": 0.85, "s": 1.5},
			{"m": "village/bag.glb", "x": -1.15, "z": 0.5, "s": 2.0, "r": 0.2},
			{"m": "village/package.glb", "x": 1.0, "z": 0.75, "s": 1.0},
			{"m": "nature/crops_wheatStageB.glb", "x": 1.15, "z": -0.75, "s": 0.8},
		],
		"work": {"spin": "mill_blades", "speed": 1.1},
	},
	{
		"id": "sawmill", "title": "Лесопилка", "hint": "рубит лес",
		"cost": {"wood": 55, "stone": 10}, "color": Color(0.50, 0.64, 0.36),
		"scale": 1.3, "cells": 3,
		"body": "kaykit/lumbermill.glb",
		"extras": [
			{"m": "nature/log_stackLarge.glb", "x": -1.5, "z": 0.9, "s": 1.0},
			{"m": "nature/log_stack.glb", "x": -1.45, "z": 0.15, "s": 1.0, "r": 0.02},
			{"m": "nature/log.glb", "x": 1.35, "z": 1.15, "s": 1.0, "r": 0.12},
			{"m": "nature/log.glb", "x": 1.5, "z": 0.75, "s": 1.0, "r": 0.16},
			{"m": "nature/stump_round.glb", "x": 1.4, "z": -0.85, "s": 1.1},
			{"m": "village/crate.glb", "x": -0.35, "z": -1.5, "s": 1.4, "r": 0.07},
		],
	},
	{
		"id": "quarry", "title": "Каменоломня", "hint": "камень из скалы",
		"cost": {"wood": 45, "stone": 20}, "color": Color(0.60, 0.60, 0.62),
		"scale": 1.3, "cells": 3,
		"body": "kaykit/mine.glb",
		"extras": [
			{"m": "nature/rock_smallA.glb", "x": 1.35, "z": -0.8, "s": 1.0},
			{"m": "nature/rock_smallC.glb", "x": 1.55, "z": -0.35, "s": 0.9, "r": 0.3},
			{"m": "nature/rock_tallC.glb", "x": -1.5, "z": -0.95, "s": 0.8},
			{"m": "village/crate.glb", "x": -1.35, "z": 0.9, "s": 1.4, "r": 0.18},
			{"m": "village/package_b.glb", "x": -1.3, "z": 0.5, "s": 1.2},
			{"m": "village/rocks.glb", "x": 1.4, "z": 1.15, "s": 1.4},
		],
		# Штольня: рельсы из шахты наружу, по ним ходит вагонетка. Ящик из
		# пиратского набора, стоявший тут раньше, читался коробкой на земле -
		# ни колёс, ни рельсов, ни смысла.
		"door": Vector3(0.0, 0.0, 1.6),
		"work": {"rails": {"a": Vector3(0.0, 0.08, -0.13), "b": Vector3(0.0, 0.08, 1.5),
			"sec": 7.0}},
	},
	{
		"id": "market", "title": "Рынок", "hint": "торговля",
		"cost": {"wood": 50, "gold": 20}, "color": Color(0.86, 0.52, 0.30),
		"scale": 1.4, "cells": 3,
		"body": "kaykit/market.glb",
		"extras": [
			{"m": "village/market_stand.glb", "x": -1.45, "z": 0.3, "s": 0.7, "r": 0.25},
			{"m": "village/market_stand_b.glb", "x": 1.45, "z": -0.4, "s": 0.7, "r": 0.75},
			{"m": "village/barrel.glb", "x": 0.95, "z": 1.2, "s": 1.3},
			{"m": "village/barrel.glb", "x": 1.3, "z": 1.05, "s": 1.1, "r": 0.2},
			{"m": "village/bags.glb", "x": -0.9, "z": 1.25, "s": 1.5},
			{"m": "village/bench.glb", "x": 0.0, "z": -1.5, "s": 0.8},
			{"m": "nature/pot_large.glb", "x": -1.4, "z": -1.15, "s": 1.0},
		],
	},
	{
		"id": "barracks", "title": "Казармы", "hint": "войско",
		"cost": {"wood": 60, "stone": 40}, "color": Color(0.66, 0.40, 0.40),
		"scale": 1.25, "cells": 3,
		"body": "kaykit/barracks.glb",
		"extras": [
			{"m": "village/bonfire.glb", "x": 1.35, "z": 1.15, "s": 1.1},
			{"m": "village/bench.glb", "x": 0.75, "z": 1.5, "s": 0.8, "r": 0.5},
			{"m": "village/crate.glb", "x": -1.4, "z": 0.95, "s": 1.4},
			{"m": "village/crate.glb", "x": -1.45, "z": 0.5, "s": 1.2, "r": 0.13},
			{"m": "village/barrel.glb", "x": -1.3, "z": -0.9, "s": 1.3},
			{"m": "nature/fence_planks.glb", "x": 0.4, "z": -1.55, "s": 1.0},
		],
	},
	{
		"id": "tower", "title": "Башня", "hint": "смотрит за морем",
		"cost": {"wood": 50, "stone": 60}, "color": Color(0.72, 0.57, 0.44),
		"scale": 1.25, "cells": 2,
		"body": "kaykit/watchtower.glb",
		"extras": [
			{"m": "village/bonfire.glb", "x": -0.95, "z": 0.9, "s": 1.0},
			{"m": "nature/rock_smallB.glb", "x": 1.0, "z": 0.75, "s": 1.0},
			{"m": "village/crate.glb", "x": 1.05, "z": -0.55, "s": 1.3, "r": 0.2},
		],
	},
	{
		"id": "dock", "title": "Верфь", "hint": "на кромке воды - с берега или с моря",
		"cost": {"wood": 60}, "color": Color(0.47, 0.62, 0.82),
		"water": true, "scale": 0.8, "cells": 3,
		"body": "pirate/structure-platform.glb",
		"extras": [
			{"m": "pirate/structure-platform-dock.glb", "x": 1.2, "s": 0.8},
			{"m": "pirate/boat-row-small.glb", "x": 2.0, "y": -0.4, "s": 0.56, "bob": true},
			{"m": "pirate/barrel.glb", "x": -0.5, "y": 0.72, "s": 0.4},
			{"m": "village/crate.glb", "x": -0.15, "y": 0.72, "z": 0.55, "s": 1.3, "r": 0.1},
			{"m": "village/package.glb", "x": 0.5, "y": 0.72, "z": -0.6, "s": 1.0},
		],
	},
]

# Мелочь, которую получает КАЖДОЕ здание: она разбрасывается по краю площадки
# броском от координат клетки. Ставится поверх именного обвеса и нужна ровно
# затем, чтобы два соседних дома не выглядели одной моделью, размноженной
# копией: у одного лежат дрова, у другого горшок и грядка.
const DECOR: Array[Dictionary] = [
	{"m": "nature/pot_small.glb", "s": 1.0},
	{"m": "nature/pot_large.glb", "s": 0.9},
	{"m": "nature/stump_squareDetailed.glb", "s": 1.0},
	{"m": "nature/log.glb", "s": 0.9},
	{"m": "nature/plant_bushSmall.glb", "s": 1.0},
	{"m": "nature/flower_purpleB.glb", "s": 0.8},
	{"m": "nature/mushroom_tanGroup.glb", "s": 0.9},
	{"m": "village/bag.glb", "s": 1.8},
	{"m": "village/package_b.glb", "s": 1.1},
	{"m": "village/rocks.glb", "s": 1.2},
	{"m": "nature/grass_large.glb", "s": 0.9},
]

# Камни дорожки от двери. Кладутся цепочкой наружу: тропа - самый дешёвый
# признак того, что домом пользуются, и она же связывает постройки между собой
# на общем плане.
#
# Взяты ПЛОСКИЕ КАМНИ, а не плитки path_* из того же набора. Плитки там
# размером в целую единицу - при нашем масштабе это плита два с половиной на
# полтора метра, и тропинка из четырёх таких выходила взлётной полосой. Плоский
# камень при том же назначении меньше метра.
const PATH_STONES: Array[String] = [
	"nature/rock_smallFlatA.glb", "nature/rock_smallFlatB.glb",
]

## Сколько готовых построек расставить вокруг старта при сборке карты.
## Ноль - обычная игра с чистого места. Больше нуля - посёлок для съёмки и
## проверок: ресурсы не списываются, стройка не анимируется.
@export var demo_village := 0

var stock := {}
var _map: IslandMap
var _selected := ""
var _sites := {}                   # Vector2i (угловая клетка) -> состояние постройки
var _taken := {}                   # каждая занятая клетка -> угловая клетка её здания
var _cache := {}                   # путь модели -> PackedScene
var _clock := 0.0                  # общее время: по нему ходят тележки и качка


func _ready() -> void:
	stock = START_STOCK.duplicate()


func _process(delta: float) -> void:
	_clock += delta
	for cell in _sites.keys():
		var s: Dictionary = _sites[cell]
		if String(s["state"]) == "burning":
			_advance_burn(s, delta)
		else:
			_work(s, delta)


# Карта сменилась - постройки сносятся вместе с землёй, на которой стояли.
func reset(map: IslandMap) -> void:
	_map = map
	for c in _sites:
		var node: Node3D = (_sites[c] as Dictionary)["root"]
		if is_instance_valid(node):
			node.queue_free()
	_sites.clear()
	_taken.clear()
	stock = START_STOCK.duplicate()
	select("")
	stock_changed.emit(stock)
	if demo_village > 0:
		_fill_demo()


# Готовый посёлок вокруг старта - для СЪЁМКИ и проверок, не для игры.
#
# Оценивать вид застроенного острова иначе нечем: инструмент съёмки мышкой не
# щёлкает, а без построек кадр показывает пустую траву и врёт о том, как игра
# выглядит на самом деле. Ресурсы при этом не списываются: это не партия.
func _fill_demo() -> void:
	var ids := ["house", "house", "farm", "house", "market", "house", "farm",
		"mill", "house", "sawmill", "house", "farm", "barracks", "house",
		"tower", "house", "quarry", "farm", "house", "dock"]
	var start := _map.start_cell
	var placed_count := 0
	# Запасы на время расстановки не ограничивают: посёлок для кадра, а не
	# партия. Без этого дома кончались на пятом - и кадр снова врал, показывая
	# пустой остров там, где игра к этому моменту застроена.
	for res in stock:
		stock[res] = 99999
	# Кольцами от старта, шагом в три клетки: посёлок растёт наружу, между домами
	# остаётся проход. Радиус до сорока клеток - ближние кольца бывает
	# отказывают целиком (склон, вода), и на восьми посёлок выходил из трёх домов.
	for radius in range(2, 41):
		for dy in range(-radius, radius + 1):
			for dx in range(-radius, radius + 1):
				if placed_count >= demo_village:
					_selected = ""
					stock = START_STOCK.duplicate()
					stock_changed.emit(stock)
					return
				if maxi(absi(dx), absi(dy)) != radius:
					continue
				if dx % 3 != 0 or dy % 3 != 0:
					continue
				var cell := Vector2i(start.x + dx, start.y + dy)
				_selected = ids[placed_count % ids.size()]
				if check(cell) != "":
					continue
				_place_now(cell)
				placed_count += 1
	_selected = ""
	stock = START_STOCK.duplicate()
	stock_changed.emit(stock)


func types() -> Array[Dictionary]:
	return TYPES


func type_by_id(id: String) -> Dictionary:
	for t in TYPES:
		if t["id"] == id:
			return t
	return {}


func selected() -> String:
	return _selected


func select(id: String) -> void:
	if _selected == id:
		return
	_selected = id
	selection_changed.emit(_selected)


func occupied_cells() -> Array:
	return _taken.keys()


# Сторона квадрата клеток, который занимает тип. Нужна и курсору: он обязан
# показывать ВСЮ площадку, а не одну клетку под мышью, иначе человек целится
# одним квадратом, а здание встаёт по другому.
func footprint(id: String) -> int:
	var t := type_by_id(id)
	return maxi(int(t.get("cells", 2)), 1) if not t.is_empty() else 1


# Входы - для горожан. Не просто точки: горожанину нужно знать, ЧТО это за
# здание, иначе он не отличит дом от каменоломни, а без этого «пошёл с работы
# домой» не отличается от «пошёл куда попало».
func entrances() -> Array:
	var out := []
	for c in _sites:
		var s: Dictionary = _sites[c]
		if String(s["state"]) == "ruin":
			continue
		out.append({"pos": s["door"], "type": String(s["type"]), "cell": c})
	return out


func count() -> int:
	return _sites.size()


# --------------------------------------------------------------------------- #
# Правила
# --------------------------------------------------------------------------- #

# Причина отказа или пустая строка, если действие возможно.
#
# Клетка под мышью - УГОЛ площадки, а не её середина: при чётной стороне
# середины у квадрата клеток попросту нет, и «округлить» её значит сдвигать
# здание на полклетки в непредсказуемую сторону.
func check(cell: Vector2i) -> String:
	if _selected == "":
		return "ничего не выбрано"
	if _map == null or not _map.inside(cell.x, cell.y):
		return "за краем карты"
	if _selected == DEMOLISH:
		if not _taken.has(cell):
			return "здесь нечего сносить"
		return ""
	var t := type_by_id(_selected)
	var n := footprint(_selected)
	var water := bool(t.get("water", false))
	# Для верфи считаем ОБА признака отдельно. Одного «есть суша» мало: площадка
	# целиком из суши его тоже даёт, и причал вставал бы посреди поля.
	var has_land := false
	var has_water := false
	for dy in n:
		for dx in n:
			var c := Vector2i(cell.x + dx, cell.y + dy)
			if not _map.inside(c.x, c.y):
				return "за краем карты"
			if _taken.has(c):
				return "место занято"
			if _map.is_land(c.x, c.y):
				has_land = true
			elif not water:
				return "здесь вода"
			else:
				has_water = true
	if water and not (has_land and has_water):
		# Верфь стоит НА КРОМКЕ: площадка обязана захватить и берег, и воду.
		# Отсюда и помост, уходящий в море, - иначе причал получался сараем в
		# двух метрах от прибоя.
		return "верфь ставится на кромке воды"
	if not water and _block_slope(cell, n) > MAX_SLOPE:
		# «Строить можно на равнине»: дом на склоне одним углом висит в воздухе,
		# другим уходит в землю, и никакой доводкой это не лечится.
		#
		# Уклон считается ПО ВСЕЙ ПЛОЩАДКЕ, а не по клетке: здание занимает
		# несколько клеток, и каждая по отдельности бывает ровной там, где
		# площадка целиком лежит на перегибе.
		return "слишком круто - нужно ровное место"
	for res in (t["cost"] as Dictionary):
		if int(stock.get(res, 0)) < int(t["cost"][res]):
			return "не хватает: %s" % _res_title(res)
	return ""


# Перепад высот на всей площадке, приведённый к её размеру. Та же величина, что
# cell_slope, но по квадрату клеток.
func _block_slope(cell: Vector2i, n: int) -> float:
	var lo := INF
	var hi := -INF
	for j in n + 1:
		for i in n + 1:
			var h := _map.node_height(cell.x + i, cell.y + j)
			lo = minf(lo, h)
			hi = maxf(hi, h)
	return (hi - lo) / (float(n) * IslandMap.CELL)


func act(cell: Vector2i) -> bool:
	var why := check(cell)
	if why != "":
		refused.emit(why)
		return false
	if _selected == DEMOLISH:
		_ignite(_sites[_taken[cell]])
		notice.emit("горит")
		return true
	return _place_now(cell)


func _res_title(id: String) -> String:
	for r in RESOURCES:
		if r["id"] == id:
			return String(r["title"])
	return id


# --------------------------------------------------------------------------- #
# Стройка
# --------------------------------------------------------------------------- #

# Здание садится на САМУЮ НИЗКУЮ вершину своей площадки, а не на среднюю
# высоту. По средней оно на любом уклоне повисает одним углом в воздухе -
# ровно та же беда, что была у камней подлеска. Вершины клеток это ровно те
# точки, из которых построен меш земли, так что промаха тут быть не может.
func _lowest_in_block(cell: Vector2i, n: int) -> float:
	var h := INF
	for j in n + 1:
		for i in n + 1:
			h = minf(h, _map.node_height(cell.x + i, cell.y + j))
	return h


# Середина площадки в мировых координатах.
func _block_center(cell: Vector2i, n: int) -> Vector3:
	var a := _map.cell_center(cell.x, cell.y)
	var b := _map.cell_center(cell.x + n - 1, cell.y + n - 1)
	return (a + b) * 0.5


func _place_now(cell: Vector2i) -> bool:
	var t := type_by_id(_selected)
	for res in (t["cost"] as Dictionary):
		stock[res] = int(stock.get(res, 0)) - int(t["cost"][res])

	var n := footprint(String(t["id"]))
	var half := float(n) * IslandMap.CELL * 0.5
	var root := Node3D.new()
	var c := _block_center(cell, n)
	# Причал стоит и на воде: там высота клетки отрицательная, и без нижней
	# границы помост ушёл бы под воду вместе с лодкой.
	var ground := _lowest_in_block(cell, n)
	var y := maxf(ground, 0.05) if bool(t.get("water", false)) else ground - 0.02
	root.position = Vector3(c.x, y, c.z)
	# Поворот от координат клетки, а не случайный: одна и та же клетка обязана
	# давать одно и то же здание, иначе перестройка карты «шевелит» посёлок.
	root.rotation.y = float((cell.x * 7 + cell.y * 13) % 4) * PI * 0.5
	add_child(root)

	var site := {
		"cell": cell, "cells": n, "type": String(t["id"]), "root": root,
		"state": "done", "t": 0.0,
		# Дымка кольцом ПО КРАЮ площадки, а не из середины дома. Клубы мелкие:
		# при размере в три метра дюжина построек подряд затягивала кадр
		# сплошным туманом, и посёлка не было видно вовсе.
		"dust": _make_particles(root, Color(0.88, 0.84, 0.74, 0.85), 1.1, 0.45,
			false, 0.6, half * 0.85, true, 0.5),
		"pieces": [], "bob": [], "body": null, "spin": {}, "cart": {},
	}

	var scale := float(t["scale"])
	if t.has("body"):
		var body := _spawn(String(t["body"]))
		if body != null:
			body.scale = Vector3.ONE * scale
			root.add_child(body)
			site["body"] = body
			(site["pieces"] as Array).append(body)
	# Смещения обвеса - В МЕТРАХ от середины здания, поэтому масштаб тела к ним
	# не примешивается: кусок из другого набора встаёт туда, куда сказано.
	for part in (t["extras"] as Array):
		var node := _spawn(String(part["m"]))
		if node == null:
			continue
		node.position = Vector3(float(part.get("x", 0.0)), float(part.get("y", 0.0)),
			float(part.get("z", 0.0)))
		node.rotation.y = float(part.get("r", 0.0)) * TAU
		node.scale = Vector3.ONE * float(part.get("s", 1.0))
		root.add_child(node)
		(site["pieces"] as Array).append(node)
		if bool(part.get("bob", false)):
			node.set_meta("y0", node.position.y)
			node.set_meta("ph", float(cell.x * 3 + cell.y * 7))
			(site["bob"] as Array).append(node)

	# Вход. Горожане ходят именно сюда, а не к середине здания: иначе они
	# «просачиваются» в стену с той стороны, с которой подошли. По умолчанию -
	# перед фасадом, чуть за краем площадки.
	var door: Vector3 = t.get("door", Vector3(0.0, 0.0, half + 0.25))
	site["door"] = root.transform * door

	_setup_work(site, t)
	if not bool(t.get("water", false)):
		_add_path(site, door, half)
		_add_decor(site, half)
		# Только на суше: у причала «рельеф» под досками - дно, и обвес ушёл бы
		# под воду вместе с лодкой.
		_sink_pieces(site)

	# Дымка. Единственное, что осталось от анимации стройки, и этого хватает:
	# без неё здание возникает подменой кадра, а с ней читается как поставленное.
	var dust: GPUParticles3D = site["dust"]
	if is_instance_valid(dust):
		dust.restart()
		dust.emitting = true

	_sites[cell] = site
	for dy in n:
		for dx in n:
			_taken[Vector2i(cell.x + dx, cell.y + dy)] = cell
	stock_changed.emit(stock)
	placed.emit(String(t["id"]), cell)
	notice.emit("готово: %s" % t["title"])
	return true


# Тропа от двери наружу. Три-четыре камня цепочкой: дальше тянуть некуда -
# соседнее здание может стоять с любой стороны, а дорога в никуда читается
# хуже, чем крыльцо.
func _add_path(site: Dictionary, door: Vector3, half: float) -> void:
	var cell: Vector2i = site["cell"]
	var rr := RandomNumberGenerator.new()
	rr.seed = cell.x * 4133 + cell.y * 911 + 17
	var dir := Vector3(door.x, 0.0, door.z)
	if dir.length() < 0.01:
		return
	dir = dir.normalized()
	var side := Vector3(dir.z, 0.0, -dir.x)
	for i in 5:
		var node := _spawn(PATH_STONES[rr.randi() % PATH_STONES.size()])
		if node == null:
			continue
		node.position = dir * (half * 0.5 + float(i) * 0.42) 			+ side * rr.randf_range(-0.16, 0.16)
		node.rotation.y = rr.randf() * TAU
		node.scale = Vector3.ONE * rr.randf_range(0.6, 0.85)
		(site["root"] as Node3D).add_child(node)
		(site["pieces"] as Array).append(node)


# Мелочь по углам площадки. Бросок от координат клетки: один и тот же дом на
# одном и том же месте обязан обрастать одинаково.
func _add_decor(site: Dictionary, half: float) -> void:
	var cell: Vector2i = site["cell"]
	var rr := RandomNumberGenerator.new()
	rr.seed = cell.x * 2657 + cell.y * 6151 + 43
	# Кольцо считается ОТ СТЕН, а не от доли площадки: у дома тело занимает
	# почти всю клетку, у башни - треть, и одна и та же доля ставила горшок то
	# во дворе, то внутрь стены.
	var lo := _body_radius(site) + 0.2
	var hi := maxf(half + 0.2, lo + 0.35)
	for i in 2 + (rr.randi() % 3):
		var spec: Dictionary = DECOR[rr.randi() % DECOR.size()]
		var node := _spawn(String(spec["m"]))
		if node == null:
			continue
		var a := rr.randf() * TAU
		var r := rr.randf_range(lo, hi)
		node.position = Vector3(cos(a) * r, 0.0, sin(a) * r)
		node.rotation.y = rr.randf() * TAU
		node.scale = Vector3.ONE * float(spec["s"]) * rr.randf_range(0.85, 1.15)
		(site["root"] as Node3D).add_child(node)
		(site["pieces"] as Array).append(node)


# Половина большей горизонтальной стороны тела - «где кончается стена».
func _body_radius(site: Dictionary) -> float:
	var body: Node3D = site.get("body")
	if body == null:
		return 0.6
	var box := AABB()
	var first := true
	for mi in body.find_children("*", "MeshInstance3D", true, false):
		var m := mi as MeshInstance3D
		if m.mesh == null:
			continue
		var b: AABB = body.transform * (m.transform * m.mesh.get_aabb())
		box = b if first else box.merge(b)
		first = false
	if first:
		return 0.6
	return 0.5 * maxf(box.size.x, box.size.z)


# Обвес садится на СВОЮ высоту рельефа, а не на высоту середины здания.
#
# Само здание стоит на самой низкой вершине площадки - оно жёсткое и должно
# лежать целиком. А бочка в двух метрах от стены на склоне при этом повисает в
# воздухе: она мелкая, и полметра просвета под ней видно сразу. Поэтому каждому
# куску обвеса высота ищется отдельно, уже после того, как всё расставлено.
func _sink_pieces(site: Dictionary) -> void:
	var root: Node3D = site["root"]
	var body: Node3D = site.get("body")
	for p in (site["pieces"] as Array):
		var node := p as Node3D
		if node == null or node == body:
			continue
		var w := root.transform * node.position
		node.position.y += _map.height_at(w.x, w.z) - root.position.y - 0.03


# Признаки работы: лопасти, дым из трубы, тележка на руднике.
#
# Ничего не считают и ни на что не влияют - и всё же без них посёлок выглядит
# макетом. Одно движение на здание отличает «стоит» от «работает» вернее, чем
# любая доводка света.
func _setup_work(site: Dictionary, t: Dictionary) -> void:
	var w: Dictionary = t.get("work", {})
	if w.is_empty():
		return
	var root: Node3D = site["root"]

	if w.has("spin"):
		var body: Node3D = site["body"]
		var part := body.find_child(String(w["spin"]), true, false) as Node3D 			if body != null else null
		if part != null:
			site["spin"] = {"node": part, "axis": _thin_axis(part),
				"speed": float(w.get("speed", 1.0))}
		else:
			push_warning("в модели нет узла %s - мельница не будет крутиться"
				% w["spin"])

	if w.has("smoke"):
		var cell: Vector2i = site["cell"]
		# Бросок ОТ КООРДИНАТ КЛЕТКИ, а не случайный: один и тот же дом обязан
		# дымить одинаково при каждой пересборке карты, иначе посёлок «мигает»
		# при каждом нажатии R.
		var rr := RandomNumberGenerator.new()
		rr.seed = cell.x * 7349 + cell.y * 1237 + 91
		if rr.randf() < float(w.get("chance", 1.0)):
			# Дым из трубы мелкий и полупрозрачный. При обычном размере частицы
			# он на общем плане выходил белым комом шире самого дома.
			# Радиус выброса КРОШЕЧНЫЙ (4 см): дым обязан выходить из устья
			# трубы, а не облаком вокруг неё. При 8 см на кадре казалось, что
			# он идёт из конька рядом.
			var puff := _make_particles(root, Color(0.82, 0.82, 0.84, 0.34), 2.4,
				0.30, true, 0.6, 0.04, false, 0.30)
			puff.position = w["smoke"] as Vector3
			# Трубы НЕ синхронны. Одинаковые струйки по всему посёлку сразу
			# выдают одну систему частиц, размноженную копией: у каждой свой
			# сдвиг фазы (preprocess), своя скорость и своя густота.
			puff.preprocess = rr.randf() * 4.0
			puff.speed_scale = rr.randf_range(0.7, 1.35)
			puff.lifetime = rr.randf_range(1.8, 3.2)
			puff.amount = 6 + (rr.randi() % 6)
			site["smoke"] = puff

	if w.has("rails"):
		site["cart"] = _make_mine(site, w["rails"])


# Штольня: две рельсы, шпалы и вагонетка на них.
#
# Собрано из примитивов, а не взято моделью: вагонетки в наборах нет, а нужна
# она размером с ладонь - на таком масштабе коробка на четырёх цилиндрах
# неотличима от честной модели, зато ничего не надо качать и подгонять.
func _make_mine(site: Dictionary, spec: Dictionary) -> Dictionary:
	var root: Node3D = site["root"]
	# Всё в МЕТРАХ, как и остальной обвес: числа ниже - это размеры вагонетки
	# (0.9 x 0.55 x 1.2 в игровых метрах при масштабе мира), а не доли модели.
	var scale := 1.3
	var a: Vector3 = spec["a"] as Vector3
	var b: Vector3 = spec["b"] as Vector3
	var dir := b - a
	var len_m := dir.length()
	if len_m < 0.01:
		return {}
	var yaw := atan2(dir.x, dir.z)

	var wood := _flat(Color(0.34, 0.24, 0.17))
	var iron := _flat(Color(0.32, 0.33, 0.36))
	var ore := _flat(Color(0.55, 0.56, 0.60))

	# Путь: две нитки рельсов и шпалы поперёк.
	var track := Node3D.new()
	track.position = (a + b) * 0.5
	track.rotation.y = yaw
	root.add_child(track)
	var gauge := 0.13 * scale
	for side in [-1.0, 1.0]:
		var rail := MeshInstance3D.new()
		var rm := BoxMesh.new()
		rm.size = Vector3(0.025 * scale, 0.02 * scale, len_m)
		rail.mesh = rm
		rail.material_override = iron
		rail.position = Vector3(side * gauge, 0.0, 0.0)
		track.add_child(rail)
	var ties := maxi(int(len_m / (0.16 * scale)), 2)
	for i in ties:
		var tie := MeshInstance3D.new()
		var tm := BoxMesh.new()
		tm.size = Vector3(gauge * 2.6, 0.015 * scale, 0.04 * scale)
		tie.mesh = tm
		tie.material_override = wood
		tie.position = Vector3(0.0, -0.012 * scale,
			-len_m * 0.5 + len_m * (float(i) + 0.5) / float(ties))
		track.add_child(tie)

	# Вагонетка: открытый ящик на четырёх колёсах.
	var cart := Node3D.new()
	cart.rotation.y = yaw
	root.add_child(cart)
	var box := MeshInstance3D.new()
	var bm := BoxMesh.new()
	bm.size = Vector3(0.20 * scale, 0.12 * scale, 0.26 * scale)
	box.mesh = bm
	box.material_override = wood
	box.position.y = 0.10 * scale
	cart.add_child(box)
	for sx in [-1.0, 1.0]:
		for sz in [-1.0, 1.0]:
			var wheel := MeshInstance3D.new()
			var cm := CylinderMesh.new()
			cm.top_radius = 0.035 * scale
			cm.bottom_radius = 0.035 * scale
			cm.height = 0.02 * scale
			cm.radial_segments = 8
			wheel.mesh = cm
			wheel.material_override = iron
			# Цилиндр стоит вдоль Y, колесу нужно вдоль X - кладём набок.
			wheel.rotation.z = PI * 0.5
			wheel.position = Vector3(sx * gauge, 0.035 * scale, sz * 0.09 * scale)
			cart.add_child(wheel)

	# Груз: горка руды в кузове. Появляется в шахте, вываливается снаружи.
	var load := MeshInstance3D.new()
	var lm := BoxMesh.new()
	lm.size = Vector3(0.16 * scale, 0.07 * scale, 0.22 * scale)
	load.mesh = lm
	load.material_override = ore
	load.position.y = 0.19 * scale
	cart.add_child(load)

	# Отвал: то, что вывалили. Растёт у конца путей.
	var heap := MeshInstance3D.new()
	var hm := SphereMesh.new()
	hm.radius = 0.16 * scale
	hm.height = 0.16 * scale
	hm.radial_segments = 8
	hm.rings = 3
	heap.mesh = hm
	heap.material_override = ore
	heap.position = b + Vector3(0.22 * scale, 0.0, 0.0)
	root.add_child(heap)

	for n in [track, cart, heap]:
		(site["pieces"] as Array).append(n)
	return {"node": cart, "load": load, "heap": heap, "a": a, "b": b,
		"sec": float(spec.get("sec", 7.0))}


# Общие для мелочей материалы не годятся: пожар красит копии на месте, и один
# материал на две постройки потемнел бы у обеих.
func _flat(col: Color) -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	m.albedo_color = col
	m.roughness = 0.9
	return m


# Ось вращения = САМАЯ ТОНКАЯ сторона меша. Лопасти мельницы и колесо водяной -
# плоские диски, и ось у них та, вдоль которой диск тоньше всего. Так не нужно
# помнить для каждой модели, вокруг чего её крутить.
func _thin_axis(node: Node3D) -> Vector3:
	for mi in node.find_children("*", "MeshInstance3D", true, false):
		var m := mi as MeshInstance3D
		if m.mesh == null:
			continue
		var sz := m.mesh.get_aabb().size
		if sz.x <= sz.y and sz.x <= sz.z:
			return Vector3.RIGHT
		return Vector3.UP if sz.y <= sz.z else Vector3.BACK
	return Vector3.BACK


func _work(site: Dictionary, delta: float) -> void:
	var spin: Dictionary = site.get("spin", {})
	if not spin.is_empty():
		var node: Node3D = spin["node"]
		if is_instance_valid(node):
			node.rotate(spin["axis"], float(spin["speed"]) * delta)

	var cart: Dictionary = site.get("cart", {})
	if not cart.is_empty():
		_roll_cart(cart)

	for n in (site.get("bob", []) as Array):
		var node := n as Node3D
		if is_instance_valid(node):
			node.position.y = float(node.get_meta("y0")) 				+ sin(_clock * 1.5 + float(node.get_meta("ph"))) * 0.07


# Круг вагонетки: выехать с рудой, вывалить её в отвал, вернуться пустой,
# загрузиться. Фазы взяты долями от периода, чтобы менять его одним числом.
#
# Простой челнок туда-сюда здесь не годится: он читается маятником. Работа
# видна ровно тогда, когда у движения есть НАЧАЛО и КОНЕЦ - гружёная поехала,
# пустая вернулась.
func _roll_cart(cart: Dictionary) -> void:
	var node: Node3D = cart["node"]
	if not is_instance_valid(node):
		return
	var k := fmod(_clock, float(cart["sec"])) / float(cart["sec"])
	var a: Vector3 = cart["a"]
	var b: Vector3 = cart["b"]
	var load: MeshInstance3D = cart["load"]
	var heap: MeshInstance3D = cart["heap"]
	var full := true
	var pos := a
	if k < 0.38:
		pos = a.lerp(b, smoothstep(0.0, 1.0, k / 0.38))
	elif k < 0.50:
		pos = b                                   # стоим, вываливаем
		full = k < 0.42
	elif k < 0.88:
		pos = b.lerp(a, smoothstep(0.0, 1.0, (k - 0.50) / 0.38))
		full = false
	else:
		full = k > 0.96                           # грузимся в забое
	node.position = pos
	if is_instance_valid(load):
		load.visible = full
	if is_instance_valid(heap):
		# Отвал растёт по мере разгрузки и опадает к следующему кругу: иначе
		# он либо всегда одинаков, либо копится до неба.
		var grow := clampf((k - 0.42) / 0.46, 0.0, 1.0)
		heap.scale = Vector3.ONE * (0.35 + 0.65 * grow)


# --------------------------------------------------------------------------- #
# Пожар и обрушение
# --------------------------------------------------------------------------- #

func _ignite(site: Dictionary) -> void:
	if String(site["state"]) == "burning":
		return
	site["state"] = "burning"
	site["t"] = 0.0
	var root: Node3D = site["root"]
	site["fire"] = _make_particles(root, Color(1.0, 0.5, 0.1, 1.0), 1.0, 1.8, true, 2.0)
	site["smoke"] = _make_particles(root, Color(0.22, 0.20, 0.20, 0.7), 2.8, 1.2, true, 3.0)


func _advance_burn(site: Dictionary, delta: float) -> void:
	site["t"] = float(site["t"]) + delta
	var k := clampf(float(site["t"]) / BURN_SEC, 0.0, 1.0)

	# Здание темнеет и оседает, пока горит. Материал у моделей общий на весь
	# набор, поэтому темнеет КОПИЯ - иначе почернел бы весь посёлок разом.
	for p in (site["pieces"] as Array):
		if not is_instance_valid(p):
			continue
		_tint(p, Color(1, 1, 1).lerp(Color(0.28, 0.24, 0.22), k))
		# Оседает ОТ СВОЕЙ высоты: обвес уже посажен на рельеф каждым куском
		# отдельно, и обнулять его высоту тут значит подбрасывать бочки на склоне.
		if not p.has_meta("y0_burn"):
			p.set_meta("y0_burn", (p as Node3D).position.y)
		(p as Node3D).position.y = float(p.get_meta("y0_burn")) - 0.35 * k * k
		(p as Node3D).rotation.z = deg_to_rad(4.0 * k) * (1.0 if int(site["cell"].x) % 2 == 0 else -1.0)

	if k < 1.0:
		return
	# Обрушилось: на месте здания остаётся щебень.
	for p in (site["pieces"] as Array):
		if is_instance_valid(p):
			(p as Node3D).queue_free()
	site["pieces"] = []
	var root: Node3D = site["root"]
	for i in 3:
		var r := _spawn("nature/rock_smallD.glb")
		if r == null:
			continue
		r.position = Vector3(0.35 * cos(float(i) * 2.1), 0.0, 0.35 * sin(float(i) * 2.1))
		r.rotation.y = float(i) * 1.3
		r.scale = Vector3.ONE * 1.1
		_tint(r, Color(0.45, 0.42, 0.40))
		root.add_child(r)
		(site["pieces"] as Array).append(r)
	var fire: GPUParticles3D = site.get("fire")
	if is_instance_valid(fire):
		fire.emitting = false
		fire.queue_free()
	site["state"] = "ruin"
	notice.emit("сгорело")


func damage(cell: Vector2i, amount: float) -> void:
	# Задел под бой: пока любой урон поджигает. Внутри уже всё для полосы
	# здоровья и стадий разрушения, менять придётся только это место.
	if _taken.has(cell):
		_ignite(_sites[_taken[cell]])


func demolish_all() -> void:
	for c in _sites:
		_ignite(_sites[c])


# --------------------------------------------------------------------------- #
# Мелочи сцены
# --------------------------------------------------------------------------- #

func _spawn(path: String) -> Node3D:
	var full := KIT + path
	if not _cache.has(full):
		if not ResourceLoader.exists(full):
			push_warning("нет модели %s - постройка встанет без этой части" % full)
			_cache[full] = null
		else:
			_cache[full] = load(full)
	var packed: PackedScene = _cache[full]
	if packed == null:
		return null
	var node := packed.instantiate() as Node3D
	Kit.recolor(node, path)
	return node


# Цвет накладывается через material_override на КОПИИ материала: у моделей
# набора он общий, и правка на месте перекрасила бы все дома сразу.
func _tint(node: Node, col: Color) -> void:
	for mi in node.find_children("*", "MeshInstance3D", true, false):
		var m := mi as MeshInstance3D
		if m.mesh == null:
			continue
		# Копия материала уже стоит поверх каждой поверхности (kit.gd), поэтому
		# правим её на месте: цвет умножается на исходный, и текстурные модели
		# темнеют так же, как крашеные.
		for i in m.mesh.get_surface_count():
			var mat := m.get_surface_override_material(i) as BaseMaterial3D
			if mat == null:
				continue
			if not mat.has_meta("base_color"):
				mat.set_meta("base_color", mat.albedo_color)
			mat.albedo_color = (mat.get_meta("base_color") as Color) * col


# Клякса частицы: белый круг, прозрачность падает от середины к краю.
#
# Рисуется кодом, а не берётся файлом: это тридцать строк против ещё одного
# ассета, который надо положить, импортировать и не потерять. Делается один раз
# на весь запуск - текстура у всех частиц общая.
static var _puff: ImageTexture = null


static func _puff_texture() -> ImageTexture:
	if _puff != null:
		return _puff
	var size := 64
	var img := Image.create(size, size, false, Image.FORMAT_RGBA8)
	var c := float(size - 1) * 0.5
	for y in size:
		for x in size:
			var d := Vector2(float(x) - c, float(y) - c).length() / c
			# Квадрат косинусного спада: у линейного край всё равно виден
			# кольцом, потому что глаз ловит излом производной.
			var a := clampf(1.0 - d, 0.0, 1.0)
			img.set_pixel(x, y, Color(1.0, 1.0, 1.0, a * a))
	_puff = ImageTexture.create_from_image(img)
	return _puff


func _make_particles(root: Node3D, col: Color, life: float, speed: float,
		loop := false, rise := 1.2, radius := 0.35, ring := false,
		quad := 0.9) -> GPUParticles3D:
	var p := GPUParticles3D.new()
	p.amount = 26
	p.lifetime = life
	p.one_shot = not loop
	p.emitting = loop
	p.explosiveness = 0.0 if loop else 0.85
	p.local_coords = false

	var pm := ParticleProcessMaterial.new()
	if ring:
		# Пыль поднимается ВОКРУГ дома, а не бьёт из его середины: из середины
		# она читается как дым из крыши, а стройка пылит по краю площадки.
		pm.emission_shape = ParticleProcessMaterial.EMISSION_SHAPE_RING
		pm.emission_ring_axis = Vector3.UP
		pm.emission_ring_radius = radius
		pm.emission_ring_inner_radius = radius * 0.72
		pm.emission_ring_height = 0.12
	else:
		pm.emission_shape = ParticleProcessMaterial.EMISSION_SHAPE_SPHERE
		pm.emission_sphere_radius = radius
	pm.direction = Vector3.UP
	pm.spread = 25.0
	pm.initial_velocity_min = speed * 0.5
	pm.initial_velocity_max = speed
	pm.gravity = Vector3(0.0, rise * 0.4, 0.0)
	pm.scale_min = 0.25
	pm.scale_max = 0.6
	pm.color = col
	p.process_material = pm

	var q := QuadMesh.new()
	q.size = Vector2(quad, quad)
	p.draw_pass_1 = q
	var m := StandardMaterial3D.new()
	m.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	m.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	# Биллборд именно ЧАСТИЦ, а не обычный: обычный разворачивает меш целиком
	# один раз, а тут каждая частица должна смотреть в камеру сама.
	m.billboard_mode = BaseMaterial3D.BILLBOARD_PARTICLES
	# Цвет берётся из albedo, а не из вершин: у QuadMesh вершинных цветов нет
	# вовсе, и с vertex_color_use_as_albedo частицы выходили белёсыми пятнами.
	m.vertex_color_use_as_albedo = false
	m.albedo_color = col
	# Круглая текстура с мягким краем ОБЯЗАТЕЛЬНА. Без неё частица остаётся
	# квадратом с резкой границей, и облако пыли выглядит горстью белых бумажек
	# - это было прямо видно на кадре.
	m.albedo_texture = _puff_texture()
	m.disable_receive_shadows = true
	p.material_override = m
	# Область видимости задаётся руками: со свободными координатами (local_coords
	# = false) движок считает её по узлу, и облако дыма пропадало, стоило зданию
	# уйти за край кадра.
	p.visibility_aabb = AABB(Vector3(-6, -2, -6), Vector3(12, 14, 12))
	root.add_child(p)
	return p
