extends Control

# Лаунчер: список сцен проекта карточками, запуск одним нажатием.
#
# Появился по простой причине: сцен стало пять, у каждой была своя командная
# строка с --path и res://-путём, и запуск превратился в поиск нужной строки.
# Теперь вход один - главная сцена проекта, - а что запускать, выбирается
# внутри.
#
# Список НЕ зашит в код. Сцены находятся сканированием scenes/, а подписи к ним
# лежат рядом в games.json. Новая сцена появляется в лаунчере сама, как только
# лёг файл; забыли подпись - будет имя файла, но из списка сцена не пропадёт.
# Молча потерянная сцена хуже некрасивой подписи.
#
# Превью - обычные PNG в assets/previews/<имя сцены>.png, их делает
# scripts/make-previews.py тем же движком. Нет картинки - карточка остаётся,
# на месте превью надпись.

const SCENES_DIR := "res://scenes/"
const MANIFEST := "res://scenes/games.json"
const PREVIEW_DIR := "res://assets/previews/"
const COLUMNS := 3

# Палитра взята из веб-интерфейса (web/static/theme.css): один проект - один
# набор цветов, чтобы лаунчер и библиотека моделей не выглядели чужими.
const C_CARD := Color("272b32")
const C_CARD_HI := Color("30353d")
const C_LINE := Color("33383f")
const C_ACCENT := Color("4a9eff")
const C_TEXT := Color("d6d9df")
const C_TEXT_2 := Color("98a0ac")
const C_TEXT_3 := Color("6c737e")

@onready var _grid: GridContainer = $Margin/Column/Scroll/Grid
@onready var _hint: Label = $Margin/Column/Hint

var _entries: Array = []
var _cards: Array[PanelContainer] = []
var _index := 0
var _busy := false


func _ready() -> void:
	_grid.columns = COLUMNS
	_entries = _collect()
	for e in _entries:
		var card := _make_card(e)
		_grid.add_child(card)
		_cards.append(card)
	if _entries.is_empty():
		_hint.text = "в %s нет ни одной сцены" % SCENES_DIR
		return
	_select(0)
	_update_hint()


# --------------------------------------------------------------------------- #
# Сбор списка
# --------------------------------------------------------------------------- #

func _collect() -> Array:
	var meta := _load_manifest()
	var out: Array = []
	var dir := DirAccess.open(SCENES_DIR)
	if dir == null:
		push_warning("не открылась папка сцен %s" % SCENES_DIR)
		return out
	var files := dir.get_files()
	files.sort()
	for f in files:
		# В экспортированной сборке ресурсы лежат под .remap - имя сцены надо
		# брать до него, иначе собранная игра покажет пустой список.
		var name := f
		if name.ends_with(".remap"):
			name = name.trim_suffix(".remap")
		if not name.ends_with(".tscn"):
			continue
		var id := name.get_basename()
		var m: Dictionary = meta.get(id, {})
		if bool(m.get("hide", false)):
			continue
		out.append({
			"id": id,
			"path": SCENES_DIR + name,
			"title": String(m.get("title", id)),
			"subtitle": String(m.get("subtitle", "")),
			"keys": String(m.get("keys", "")),
			"order": int(m.get("order", 50)),
		})
	out.sort_custom(func(a, b):
		if a["order"] != b["order"]:
			return a["order"] < b["order"]
		return a["title"] < b["title"])
	return out


func _load_manifest() -> Dictionary:
	if not FileAccess.file_exists(MANIFEST):
		return {}
	var text := FileAccess.get_file_as_string(MANIFEST)
	var parsed = JSON.parse_string(text)
	if typeof(parsed) != TYPE_DICTIONARY:
		# Ошибка несёт, что делать (CLAUDE.md): без подписи лаунчер работает,
		# поэтому падать тут нельзя - но и молчать нельзя тоже.
		push_warning("%s не разобрался как JSON - сцены останутся без подписей" % MANIFEST)
		return {}
	var out := {}
	for k in parsed:
		# Ключи с подчёркиванием - комментарии внутри JSON, у которого своих нет.
		if not String(k).begins_with("_"):
			out[k] = parsed[k]
	return out


# --------------------------------------------------------------------------- #
# Карточки
# --------------------------------------------------------------------------- #

func _make_card(e: Dictionary) -> PanelContainer:
	var panel := PanelContainer.new()
	panel.custom_minimum_size = Vector2(340, 0)
	panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	panel.add_theme_stylebox_override("panel", _card_style(false))
	panel.mouse_filter = Control.MOUSE_FILTER_STOP

	var pad := MarginContainer.new()
	for side in ["left", "right", "top", "bottom"]:
		pad.add_theme_constant_override("margin_" + side, 10)
	panel.add_child(pad)

	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 7)
	box.mouse_filter = Control.MOUSE_FILTER_IGNORE
	pad.add_child(box)

	box.add_child(_preview_node(e))
	box.add_child(_label(e["title"], 20, C_TEXT))
	box.add_child(_label(e["subtitle"], 13, C_TEXT_2))
	box.add_child(_label(e["keys"], 11, C_TEXT_3))

	var idx := _cards.size()
	panel.mouse_entered.connect(func(): _select(idx))
	panel.gui_input.connect(func(ev: InputEvent):
		if ev is InputEventMouseButton and ev.pressed \
				and (ev as InputEventMouseButton).button_index == MOUSE_BUTTON_LEFT:
			_select(idx)
			_launch(idx))
	return panel


func _preview_node(e: Dictionary) -> Control:
	var path: String = PREVIEW_DIR + String(e["id"]) + ".png"
	if ResourceLoader.exists(path):
		var shot := TextureRect.new()
		shot.texture = load(path)
		shot.custom_minimum_size = Vector2(0, 175)
		shot.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
		shot.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_COVERED
		shot.mouse_filter = Control.MOUSE_FILTER_IGNORE
		return shot

	var stub := PanelContainer.new()
	stub.custom_minimum_size = Vector2(0, 175)
	stub.mouse_filter = Control.MOUSE_FILTER_IGNORE
	var style := StyleBoxFlat.new()
	style.bg_color = Color("1c2027")
	style.set_corner_radius_all(4)
	stub.add_theme_stylebox_override("panel", style)
	var text := _label("превью нет\nscripts/make-previews.py", 12, C_TEXT_3)
	text.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	text.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	stub.add_child(text)
	return stub


func _label(text: String, size: int, color: Color) -> Label:
	var l := Label.new()
	l.text = text
	l.add_theme_font_size_override("font_size", size)
	l.add_theme_color_override("font_color", color)
	l.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	l.mouse_filter = Control.MOUSE_FILTER_IGNORE
	return l


func _card_style(active: bool) -> StyleBoxFlat:
	var s := StyleBoxFlat.new()
	s.bg_color = C_CARD_HI if active else C_CARD
	s.border_color = C_ACCENT if active else C_LINE
	s.set_border_width_all(2 if active else 1)
	s.set_corner_radius_all(6)
	return s


# --------------------------------------------------------------------------- #
# Выбор и запуск
# --------------------------------------------------------------------------- #

func _select(i: int) -> void:
	if _cards.is_empty():
		return
	_index = clampi(i, 0, _cards.size() - 1)
	for k in _cards.size():
		_cards[k].add_theme_stylebox_override("panel", _card_style(k == _index))
	_update_hint()


func _update_hint() -> void:
	if _busy or _entries.is_empty():
		return
	_hint.text = "стрелки — выбор · Enter или щелчок — запустить · Esc — выход        %d из %d" % [
		_index + 1, _entries.size()]


func _launch(i: int) -> void:
	if _busy or i < 0 or i >= _entries.size():
		return
	_busy = true
	var e: Dictionary = _entries[i]
	# Надпись до смены сцены, а не после: тяжёлая сцена собирается секунду и
	# больше, и без неё нажатие выглядит как «ничего не произошло».
	_hint.text = "запускаю: %s…" % e["title"]
	var err := get_tree().change_scene_to_file(String(e["path"]))
	if err != OK:
		_busy = false
		_hint.text = "не запустилась %s (код %d) — смотри вывод движка" % [e["path"], err]


func _unhandled_input(event: InputEvent) -> void:
	if not (event is InputEventKey) or not event.pressed or event.echo:
		return
	match (event as InputEventKey).keycode:
		KEY_RIGHT, KEY_D:
			_select(_index + 1)
		KEY_LEFT, KEY_A:
			_select(_index - 1)
		KEY_DOWN, KEY_S:
			_select(_index + COLUMNS)
		KEY_UP, KEY_W:
			_select(_index - COLUMNS)
		KEY_ENTER, KEY_KP_ENTER, KEY_SPACE:
			_launch(_index)
		KEY_ESCAPE:
			get_tree().quit()
