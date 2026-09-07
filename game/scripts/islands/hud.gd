extends Control

# Интерфейс игры: запасы, мини-карта, панель построек, сведения о клетке.
#
# Живёт отдельной сценой и знает о мире только через сигналы (world_ready,
# hover_changed, stock_changed, refused, notice). Обратно ходит через открытые
# методы. Интерфейс можно переписать целиком, не тронув генерацию карты.
#
# Вид - ТЁПЛЫЙ МУЛЬТЯШНЫЙ, под стать яркому дневному миру: пергаментные панели
# с коричневой обводкой и мягкой тенью, крупные цифры, карточки построек с
# цветным значком. Серые кнопки движка по умолчанию рядом с таким миром
# выглядят чужой программой, поэтому здесь не используется ни одна из них -
# всё собрано из панелей со своими стилями.
#
# Карточки построек НЕ перечислены руками: они собираются из builder.TYPES.
# Новый тип появляется в панели сам.

const Builder := preload("res://scripts/islands/builder.gd")
const IslandMap := preload("res://scripts/islands/island_map.gd")

@export var world_path: NodePath
@export var camera_path: NodePath
@export var builder_path: NodePath

# Палитра: тёмное дерево с золотой каймой.
#
# Был светлый пергамент. Он проигрывал ровно там, где интерфейс и живёт - НА
# КАРТЕ: светлая панель поверх светлого песка и бликующей воды сливалась с
# ними, и глазу приходилось искать край панели. Тёмная не спорит с миром ни на
# одном биоме, а золотая кайма отделяет её от картинки одной линией. Проверено
# по референсу (Dice Kingdoms): там ровно та же пара - тёмное поле, светлый
# кант, тёплые цифры.
const C_PANEL := Color("2e2119")
const C_PANEL_2 := Color("3a2a1e")
const C_LINE := Color("c9a24a")
const C_TEXT := Color("f4e6c8")
const C_TEXT_2 := Color("b39a76")
const C_ACCENT := Color("f0bc55")
const C_OK := Color("8cc94e")
const C_DANGER := Color("e2694a")
const C_SHADOW := Color(0.0, 0.0, 0.0, 0.5)

const TOAST_SEC := 2.6

@onready var _res_row: HBoxContainer = $Top/Pad/Resources
@onready var _minimap: TextureRect = $MapPanel/Pad/Column/MapBox/Minimap
@onready var _overlay: Control = $MapPanel/Pad/Column/MapBox/Overlay
@onready var _seed: Label = $MapPanel/Pad/Column/Seed
@onready var _tools: HBoxContainer = $MapPanel/Pad/Column/Tools
@onready var _keys: Label = $MapPanel/Pad/Column/Keys
@onready var _build_row: HBoxContainer = $Build/Pad/Column/Buttons
@onready var _build_hint: Label = $Build/Pad/Column/Hint
@onready var _info: Label = $Info/Pad/Text
@onready var _toast: Label = $Toast/Pad/Text

var _world: Node3D
var _camera: Node3D
var _builder: Builder
var _map: IslandMap
var _values := {}                    # id ресурса -> Label
var _costs := {}                     # id постройки -> Label
var _cards := {}                     # id постройки -> PanelContainer
var _hovered_card := ""
var _toast_left := 0.0


func _ready() -> void:
	_world = get_node_or_null(world_path)
	_camera = get_node_or_null(camera_path)
	_builder = get_node_or_null(builder_path)

	_apply_panel_styles()
	_build_resources()
	_build_tools()
	_build_cards()
	_overlay.draw.connect(_draw_overlay)
	_overlay.gui_input.connect(_minimap_input)
	$Toast.modulate.a = 0.0
	_info.text = "наведи на клетку"
	_keys.text = ("ЛКМ — тянуть карту, щелчок — поставить. ПКМ — крутить вид, "
		+ "щелчок ПКМ — выйти из стройки. Колесо — приблизить, "
		+ "WASD и край экрана — двигаться. "
		+ "Home — вид по умолчанию, F — к старту, R — новая карта, Esc — выход.")

	if _world != null:
		_world.connect("world_ready", _on_world_ready)
		_world.connect("hover_changed", _on_hover)
		# Мир готовится РАНЬШЕ интерфейса (в дереве он выше), поэтому первый
		# world_ready уже прошёл мимо. Забираем состояние сами.
		if _world.get("map") != null:
			_on_world_ready(_world.get("map"))
	if _camera != null:
		_camera.connect("moved", func(): _overlay.queue_redraw())
	if _builder != null:
		_builder.stock_changed.connect(_on_stock)
		_builder.selection_changed.connect(_on_selection)
		_builder.refused.connect(func(why): toast(why, C_DANGER))
		_builder.notice.connect(func(text): toast(text, C_OK))
		_builder.placed.connect(func(_id, _cell): _overlay.queue_redraw())
		_on_stock(_builder.stock)
		_on_selection("")


func _process(delta: float) -> void:
	if _toast_left > 0.0:
		_toast_left -= delta
		$Toast.modulate.a = clampf(_toast_left / 0.5, 0.0, 1.0)


# --------------------------------------------------------------------------- #
# Оформление
# --------------------------------------------------------------------------- #

# Стиль панелей задаётся кодом, а не в сцене: их пять, стиль один, и держать
# его в пяти местах значит однажды поправить четыре.
func _apply_panel_styles() -> void:
	for n in [$Top, $MapPanel, $Build, $Info, $Toast]:
		(n as PanelContainer).add_theme_stylebox_override("panel", _panel_style())
	($MapPanel/Pad/Column/MapBox as PanelContainer).add_theme_stylebox_override(
		"panel", _frame_style())


func _panel_style() -> StyleBoxFlat:
	var s := StyleBoxFlat.new()
	s.bg_color = C_PANEL
	s.border_color = C_LINE
	s.set_border_width_all(2)
	s.set_corner_radius_all(9)
	s.shadow_color = C_SHADOW
	s.shadow_size = 8
	s.shadow_offset = Vector2(0, 3)
	return s


# Рамка мини-карты. Внутри почти чёрное: карта - светлая вставка, и подложка
# обязана быть темнее её, иначе рамка не читается как рамка.
func _frame_style() -> StyleBoxFlat:
	var s := StyleBoxFlat.new()
	s.bg_color = Color("1a120c")
	s.border_color = Color("8a6a34")
	s.set_border_width_all(2)
	s.set_corner_radius_all(5)
	return s


# 0 - обычная, 1 - под курсором, 2 - выбранная.
func _card_style(state: int) -> StyleBoxFlat:
	var s := StyleBoxFlat.new()
	s.bg_color = [C_PANEL_2, Color("4c3724"), Color("60452a")][state]
	s.border_color = [Color("6b5330"), C_LINE, C_ACCENT][state]
	s.set_border_width_all(2 if state < 2 else 3)
	s.set_corner_radius_all(7)
	if state == 2:
		s.shadow_color = Color(0.94, 0.74, 0.33, 0.45)
		s.shadow_size = 7
	return s


# Значок постройки: картинка самого здания на тёмной плитке.
#
# Картинки лежат готовыми в assets/icons (их делает tools/make_icons.gd). Если
# значка нет - у «Снести» его и не будет, - плитка просто заливается цветом
# типа. Молчать в этом случае нельзя только по-крупному: карточка без картинки
# остаётся рабочей, а не исчезает.
func _icon_of(id: String, col: Color) -> Control:
	var box := PanelContainer.new()
	box.custom_minimum_size = Vector2(0, 52)
	var tile := StyleBoxFlat.new()
	tile.bg_color = Color("241a12")
	tile.border_color = col.darkened(0.35)
	tile.set_border_width_all(2)
	tile.set_corner_radius_all(6)
	box.add_theme_stylebox_override("panel", tile)

	var path := "res://assets/icons/%s.png" % id
	if ResourceLoader.exists(path):
		var pic := TextureRect.new()
		pic.texture = load(path)
		pic.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
		pic.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
		pic.mouse_filter = Control.MOUSE_FILTER_IGNORE
		box.add_child(pic)
	else:
		tile.bg_color = col.darkened(0.15)
	return box


func _pill_style(col: Color) -> StyleBoxFlat:
	var s := StyleBoxFlat.new()
	s.bg_color = col
	s.border_color = C_LINE
	s.set_border_width_all(2)
	s.set_corner_radius_all(10)
	return s


func _text(s: String, size: int, color: Color) -> Label:
	var l := Label.new()
	l.text = s
	l.add_theme_font_size_override("font_size", size)
	l.add_theme_color_override("font_color", color)
	l.mouse_filter = Control.MOUSE_FILTER_IGNORE
	return l


# --------------------------------------------------------------------------- #
# Панели
# --------------------------------------------------------------------------- #

func _build_resources() -> void:
	for r in Builder.RESOURCES:
		var chip := HBoxContainer.new()
		chip.add_theme_constant_override("separation", 7)

		var dot := Panel.new()
		dot.custom_minimum_size = Vector2(16, 16)
		dot.size_flags_vertical = Control.SIZE_SHRINK_CENTER
		dot.add_theme_stylebox_override("panel", _pill_style(r["color"]))
		chip.add_child(dot)

		var value := _text("0", 21, C_TEXT)
		_values[r["id"]] = value
		chip.add_child(value)
		chip.add_child(_text(String(r["title"]), 13, C_TEXT_2))
		_res_row.add_child(chip)


func _build_tools() -> void:
	# Те же действия, что и с клавиатуры. Кнопка нужна не вместо клавиши, а
	# затем, что клавишу ещё надо знать: подпись сама себя объясняет.
	var items := [
		{"t": "Вид", "tip": "вид по умолчанию (Home)", "act": func(): _world.call("reset_view")},
		{"t": "Старт", "tip": "к точке старта (F)", "act": func(): _world.call("focus_start")},
		{"t": "Новая", "tip": "другой архипелаг (R)",
			"act": func(): _world.call("rebuild", randi() % 100000)},
	]
	for it in items:
		var b := PanelContainer.new()
		b.tooltip_text = String(it["tip"])
		b.add_theme_stylebox_override("panel", _card_style(0))
		var pad := MarginContainer.new()
		pad.add_theme_constant_override("margin_left", 12)
		pad.add_theme_constant_override("margin_right", 12)
		pad.add_theme_constant_override("margin_top", 6)
		pad.add_theme_constant_override("margin_bottom", 6)
		b.add_child(pad)
		pad.add_child(_text(String(it["t"]), 14, C_TEXT))
		b.mouse_entered.connect(func(): b.add_theme_stylebox_override("panel", _card_style(1)))
		b.mouse_exited.connect(func(): b.add_theme_stylebox_override("panel", _card_style(0)))
		var act: Callable = it["act"]
		b.gui_input.connect(func(ev):
			if _clicked(ev):
				act.call())
		_tools.add_child(b)


# Карточка постройки: цветной значок, название, цена. Кнопки движка тут не
# годятся - у них своя рамка, свой отступ и свой серый фон, и с пергаментом
# они не сходятся.
func _build_cards() -> void:
	if _builder == null:
		return
	var items: Array = _builder.types().duplicate()
	items.append({"id": Builder.DEMOLISH, "title": "Снести", "hint": "поджечь постройку",
		"cost": {}, "color": C_DANGER})
	for t in items:
		var id := String(t["id"])
		var card := PanelContainer.new()
		card.custom_minimum_size = Vector2(96, 0)
		card.tooltip_text = String(t["hint"])
		card.add_theme_stylebox_override("panel", _card_style(0))

		var pad := MarginContainer.new()
		for side in ["left", "right", "top", "bottom"]:
			pad.add_theme_constant_override("margin_" + side, 8)
		card.add_child(pad)

		var col := VBoxContainer.new()
		col.add_theme_constant_override("separation", 5)
		pad.add_child(col)

		col.add_child(_icon_of(id, t["color"]))

		var name := _text(String(t["title"]), 15, C_TEXT)
		name.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		col.add_child(name)

		var cost := _text(_cost_text(t["cost"]), 11, C_TEXT_2)
		cost.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		cost.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		col.add_child(cost)

		card.mouse_entered.connect(func():
			_hovered_card = id
			_restyle_cards())
		card.mouse_exited.connect(func():
			if _hovered_card == id:
				_hovered_card = ""
			_restyle_cards())
		card.gui_input.connect(func(ev):
			if _clicked(ev):
				# Повторный щелчок по выбранной карточке снимает выбор: иначе
				# из режима стройки выходят только через Esc, а его ещё надо знать.
				_builder.select("" if _builder.selected() == id else id))

		_cards[id] = card
		_costs[id] = cost
		_build_row.add_child(card)


func _clicked(ev: InputEvent) -> bool:
	return ev is InputEventMouseButton and ev.pressed \
		and (ev as InputEventMouseButton).button_index == MOUSE_BUTTON_LEFT


func _restyle_cards() -> void:
	var sel: String = _builder.selected() if _builder != null else ""
	for id in _cards:
		var state := 0
		if id == sel:
			state = 2
		elif id == _hovered_card:
			state = 1
		(_cards[id] as PanelContainer).add_theme_stylebox_override("panel", _card_style(state))


# Цена в СОКРАЩЁННОМ виде: «40 дер · 15 кам».
#
# Полные слова переносились на вторую строку, и карточка вырастала вдвое - при
# десяти карточках это отъедало у мира лишние сорок точек по высоте. Что значит
# «дер», видно из значка ресурса наверху, а точная цена всё равно проверяется
# по счётчику: карточка краснеет, когда не хватает.
func _cost_text(cost: Dictionary) -> String:
	if cost.is_empty():
		return "бесплатно"
	var parts := []
	for res in cost:
		var title := _res_title(String(res))
		parts.append("%d %s" % [int(cost[res]), title.substr(0, 3)])
	return " · ".join(parts)


func _res_title(id: String) -> String:
	for r in Builder.RESOURCES:
		if r["id"] == id:
			return String(r["title"])
	return id


# --------------------------------------------------------------------------- #
# Реакция на мир
# --------------------------------------------------------------------------- #

func _on_world_ready(map) -> void:
	_map = map
	_minimap.texture = _make_minimap(map)
	var s: Dictionary = map.stats()
	_seed.text = "seed %d · суша %d%%" % [_world.get("world_seed"),
		roundi(100.0 * float(s["land"]) / float(s["cells"]))]
	_overlay.queue_redraw()


func _on_hover(cell: Vector2i, info: Dictionary) -> void:
	if info.is_empty():
		_info.text = "наведи на клетку"
		return
	# Уклон показывается нарочно: именно он решает, встанет ли здание («строить
	# можно на равнине»). Число, по которому игра принимает решение, человек
	# должен видеть до щелчка, а не узнавать из отказа.
	_info.text = "%s · высота %.1f м · уклон %.2f" % [info["biome"], info["height"], info["slope"]]


func _on_stock(stock: Dictionary) -> void:
	for id in _values:
		(_values[id] as Label).text = str(int(stock.get(id, 0)))
	# Цена красным, если не по карману: отказ должен быть виден до нажатия.
	for id in _costs:
		var t := _builder.type_by_id(id)
		if t.is_empty():
			continue
		var ok := true
		for res in (t["cost"] as Dictionary):
			if int(stock.get(res, 0)) < int(t["cost"][res]):
				ok = false
		(_costs[id] as Label).add_theme_color_override("font_color", C_TEXT_2 if ok else C_DANGER)


func _on_selection(id: String) -> void:
	_restyle_cards()
	if id == "":
		_build_hint.text = "выбери постройку и щёлкни по клетке"
	elif id == Builder.DEMOLISH:
		_build_hint.text = "снос: щёлкни по постройке — она загорится. Esc отменяет"
	else:
		var t := _builder.type_by_id(id)
		# Размер площадки в подсказке не для красоты: курсор подсвечивает
		# несколько клеток, и человек должен понимать, почему именно столько.
		var n: int = _builder.footprint(id)
		_build_hint.text = "%s: %s — щёлкни по клетке, займёт %d×%d. ПКМ или Esc отменяет" % [
			t["title"], t["hint"], n, n]


func toast(text: String, color: Color) -> void:
	_toast.text = text
	_toast.add_theme_color_override("font_color", color)
	$Toast.modulate.a = 1.0
	_toast_left = TOAST_SEC


# --------------------------------------------------------------------------- #
# Мини-карта
# --------------------------------------------------------------------------- #

# Карта рисуется ОДИН раз при генерации: это те же данные, что у меша земли,
# и перерисовывать их каждый кадр незачем. Всё подвижное - рамка обзора,
# старт, постройки - живёт в накладке поверх и перерисовывается по событию.
func _make_minimap(map) -> ImageTexture:
	var n: int = IslandMap.CELLS
	var img := Image.create(n, n, false, Image.FORMAT_RGB8)
	for cy in n:
		for cx in n:
			var col: Color
			if map.is_land(cx, cy):
				col = IslandMap.COLORS[map.biome_at(cx, cy)]
			else:
				# Вода на мини-карте - по глубине, а не биомом: так читается
				# отмель вокруг островов и виден проход между ними.
				var d := clampf(-map.cell_height(cx, cy) / 6.0, 0.0, 1.0)
				col = Color(0.35, 0.68, 0.76).lerp(Color(0.07, 0.22, 0.40), d)
			img.set_pixel(cx, cy, col)
	return ImageTexture.create_from_image(img)


func _draw_overlay() -> void:
	if _map == null:
		return
	var size := _overlay.size
	var s := _cell_to_map(_map.start_cell, size)
	_overlay.draw_circle(s, 4.0, Color(0.85, 0.25, 0.22, 0.95))
	_overlay.draw_arc(s, 7.0, 0.0, TAU, 18, Color(1, 1, 1, 0.55), 1.5)

	if _builder != null:
		for cell in _builder.occupied_cells():
			_overlay.draw_rect(Rect2(_cell_to_map(cell, size) - Vector2(2, 2),
				Vector2(4, 4)), Color(0.98, 0.82, 0.35, 0.95))

	if _camera != null and _camera.has_method("focus_point"):
		var f: Vector3 = _camera.call("focus_point")
		var p := _world_to_map(Vector2(f.x, f.z), size)
		var yaw: float = _camera.call("yaw")
		var dir := Vector2(sin(yaw), cos(yaw)) * 12.0
		_overlay.draw_line(p, p - dir, Color(1, 1, 1, 0.8), 2.0)
		_overlay.draw_circle(p, 3.5, Color(1, 1, 1, 0.95))


func _cell_to_map(cell: Vector2i, size: Vector2) -> Vector2:
	var n := float(IslandMap.CELLS)
	return Vector2((float(cell.x) + 0.5) / n * size.x, (float(cell.y) + 0.5) / n * size.y)


func _world_to_map(p: Vector2, size: Vector2) -> Vector2:
	var h := IslandMap.HALF
	return Vector2((p.x + h) / (2.0 * h) * size.x, (p.y + h) / (2.0 * h) * size.y)


# Щелчок по мини-карте переносит взгляд: это самый быстрый способ попасть на
# соседний остров, и он ожидается в любой стратегии.
func _minimap_input(event: InputEvent) -> void:
	if not _clicked(event) or _camera == null or _map == null:
		return
	var local := (event as InputEventMouseButton).position
	var h := IslandMap.HALF
	var x := local.x / _overlay.size.x * 2.0 * h - h
	var z := local.y / _overlay.size.y * 2.0 * h - h
	_camera.call("focus_on", Vector3(x, _map.height_at(x, z), z))
	_overlay.queue_redraw()
