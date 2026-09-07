extends Node3D

# Кадры из сцены для агента. Запускается обвязкой bridge/shot_scene.py.
#
# Запускается С ОКНОМ, и это не небрежность: в --headless драйвер отрисовки
# пустой, кадров не рисуется вовсе и ожидание отрисовки не разрешается никогда
# (docs/PITFALLS.md). Окно живёт 2-4 секунды и закрывается само.
#
# Аргументы приходят одной строкой JSON - разбирать позиционные было бы
# гаданием, а полей тут восемь:
#   scene      res://... - что снимаем
#   out        куда класть PNG (абсолютный путь виндовой стороны)
#   views      сколько кадров по кругу
#   azimuth    с какого угла начинать; пусто - камера самой сцены
#   elevation  наклон, градусы (для предмета; локация смотрит горизонтально)
#   distance   множитель габарита сцены; пусто - подобрать
#   fov        угол объектива
#   unshaded   снять ещё кадр без света: только альбедо

const PREFIX := "RESULT "
const EYE := 1.65          # рост камеры в локации - тот же, что в прогулке
const WARMUP := 10         # кадров на прогрев: текстуры доезжают не к первому
# Со включённым SDFGI прогрев другой. Глобальное освещение считается не за
# кадр: каскады заполняются постепенно, и на десятом кадре сцена ещё тёмная.
# Замер на classroom.tscn: при 10 кадрах правая половина класса уходила в
# черноту, и по такому снимку GI выглядел ошибкой, хотя просто не досчитался.
const WARMUP_GI := 90


var _cfg := {}
var _shots: Array = []
var _stats := {}


func _ready() -> void:
	var raw := "{}"
	var args := OS.get_cmdline_user_args()
	if args.size() > 0:
		raw = args[0]
	var parsed = JSON.parse_string(raw)
	if typeof(parsed) != TYPE_DICTIONARY:
		_emit({"ok": false, "error": "аргументы не разобрались как JSON: %s" % raw})
		return
	_cfg = parsed
	_run()


func _run() -> void:
	var scene_path: String = _cfg.get("scene", "")
	if not ResourceLoader.exists(scene_path):
		_emit({"ok": false, "error": "нет сцены %s" % scene_path})
		return
	var packed: PackedScene = load(scene_path)
	if packed == null:
		_emit({"ok": false, "error": "сцена %s не загрузилась" % scene_path})
		return

	var world: Node = packed.instantiate()
	add_child(world)
	await get_tree().process_frame       # дать _ready сцены отработать

	# highlight=true подсвечивает ВСЕ зоны осмотра разом. В игре так не бывает
	# - подсветка идёт за взглядом, - но проверить её иначе нечем: камера
	# съёмки не игрок и ни на что не смотрит. Отладочный режим, назван так же.
	if _cfg.get("highlight", false):
		for node in world.find_children("*", "Area3D", true, false):
			if node.has_method("highlight"):
				node.highlight(true)

	# HUD гасится целиком: подсказки «кликни, чтобы взять управление»
	# адресованы человеку с мышью, а в кадре для агента и в склейке с
	# референсом они просто закрывают сцену. Прячется ПОСЛЕ process_frame -
	# слой, который сцена создаёт в _ready, до него ещё не существует.
	_hide_canvas(world)

	var aabb := _bounds(world)
	_stats = _describe(world, aabb)

	var cam: Camera3D = _camera(world)
	var views: int = maxi(int(_cfg.get("views", 1)), 1)
	var base = _cfg.get("azimuth", null)
	# Тип указан явно: base приходит из JSON и потому Variant, а от Variant
	# вывод типа не работает - парсер отказывается собирать файл целиком.
	var own: bool = base == null and int(_stats["cameras"]) > 0

	var out: String = _cfg.get("out", "")
	if own:
		# Камера сцены одна, кружить нечем: снимаем оттуда, откуда смотрел
		# автор сцены. Нужен облёт - задай azimuth, и заведётся своя.
		await _settle()
		_save(out, "scene")
	else:
		var start: float = 0.0 if base == null else float(base)
		for i in views:
			var az: float = start + 360.0 * i / views
			_aim(cam, aabb, az)
			await _settle()
			_save(out, "%03d" % (int(round(az)) % 360))

	if bool(_cfg.get("unshaded", false)):
		# Второй кадр без единой лампы. Отделяет «текстура не доехала» от
		# «сцена пересвечена»: по обычному кадру эти два случая не различить,
		# и первый же разбор коридора на этом споткнулся.
		get_viewport().debug_draw = Viewport.DEBUG_DRAW_UNSHADED
		await _settle()
		_save(out, "unshaded")

	_emit({"ok": _shots.size() > 0, "shots": _shots, "stats": _stats,
		   "error": "" if _shots.size() > 0 else "не снято ни одного кадра"})


func _settle() -> void:
	for i in (WARMUP_GI if _has_gi() else WARMUP):
		await get_tree().process_frame
	await RenderingServer.frame_post_draw


func _has_gi() -> bool:
	# Ищем среди WorldEnvironment сцены: ждать девяносто кадров там, где GI
	# нет, значит вчетверо удлинить каждую съёмку без всякой пользы.
	for node in get_tree().root.find_children("*", "WorldEnvironment", true, false):
		var env: Environment = (node as WorldEnvironment).environment
		if env != null and env.sdfgi_enabled:
			return true
	return false


func _save(dir_path: String, name: String) -> void:
	var img := get_viewport().get_texture().get_image()
	var path := dir_path.path_join(name + ".png")
	var err := img.save_png(path)
	if err != OK:
		_shots.append({"name": name, "error": "не записать %s (код %d)" % [path, err]})
		return
	_shots.append({"name": name, "file": path, "spread": _spread(img)})


func _camera(world: Node) -> Camera3D:
	# Камера сцены важнее нашей: её поставил тот, кто сцену писал, и снимать
	# надо оттуда, откуда он смотрел. Своя заводится, только если её нет
	# или если явно попросили ракурс.
	var found: Array[Camera3D] = []
	_walk_cam(world, found)
	if found.size() > 0 and _cfg.get("azimuth", null) == null:
		found[0].current = true
		found[0].fov = float(_cfg.get("fov", found[0].fov))
		return found[0]
	var cam := Camera3D.new()
	cam.fov = float(_cfg.get("fov", 65.0))
	add_child(cam)
	cam.current = true
	return cam


func _aim(cam: Camera3D, aabb: AABB, azimuth: float) -> void:
	var c := aabb.get_center()
	var a := deg_to_rad(azimuth)
	if _is_location(aabb):
		# В локации камера стоит ВНУТРИ, в середине пола, и поворачивается на
		# месте - то же правило, что в прогулке. Облёт снаружи показал бы
		# изнанку стен, а не помещение.
		var eye := Vector3(c.x, aabb.position.y + EYE, c.z)
		cam.global_position = eye
		cam.look_at(eye + Vector3(sin(a), -0.08, cos(a)))
		return
	var elev := deg_to_rad(float(_cfg.get("elevation", 15.0)))
	var dist: float = maxf(aabb.size.length(), 0.001) \
		* float(_cfg.get("distance", 1.1))
	cam.global_position = c + Vector3(
		sin(a) * cos(elev), sin(elev), cos(a) * cos(elev)) * dist
	cam.look_at(c)


func _is_location(aabb: AABB) -> bool:
	return aabb.size.y > 2.2 and maxf(aabb.size.x, aabb.size.z) > 4.0


func _bounds(root: Node) -> AABB:
	var meshes: Array[MeshInstance3D] = []
	_walk_mesh(root, meshes)
	var aabb := AABB()
	var first := true
	for mi in meshes:
		if mi.mesh == null:
			continue
		var box: AABB = mi.global_transform * mi.mesh.get_aabb()
		aabb = box if first else aabb.merge(box)
		first = false
	return aabb


func _describe(root: Node, aabb: AABB) -> Dictionary:
	var meshes: Array[MeshInstance3D] = []
	_walk_mesh(root, meshes)
	var cams: Array[Camera3D] = []
	_walk_cam(root, cams)
	var tris := 0
	for mi in meshes:
		if mi.mesh == null:
			continue
		for s in mi.mesh.get_surface_count():
			var arrays: Array = mi.mesh.surface_get_arrays(s)
			# Индексов может не быть ВОВСЕ: у меша, собранного в коде из
			# отдельных треугольников, вершины идут подряд, и Godot кладёт в
			# ARRAY_INDEX null. Присваивание в типизированную переменную на
			# этом падало, и съёмка любой процедурной сцены обрывалась молча.
			var idx = arrays[Mesh.ARRAY_INDEX]
			if idx is PackedInt32Array and (idx as PackedInt32Array).size() > 0:
				tris += (idx as PackedInt32Array).size() / 3
			else:
				tris += (arrays[Mesh.ARRAY_VERTEX] as PackedVector3Array).size() / 3
	# Яркость источников, а не только их число. Пересвеченный кадр и кадр с
	# потерянной текстурой выглядят одинаково белыми, и первым делом хочется
	# знать, чем именно сцену залило - особенно когда свет приехал внутри GLB
	# и в тексте сцены его не видно вовсе.
	var lights: Array[Light3D] = []
	_walk_light(root, lights)
	var energy: Array = []
	for l in lights:
		energy.append({"node": l.name, "class": l.get_class(),
					   "energy": snappedf(l.light_energy, 0.01)})

	return {
		"meshes": meshes.size(),
		"triangles": tris,
		"lights": lights.size(),
		"light_energy": energy,
		"cameras": cams.size(),
		"kind": "локация" if _is_location(aabb) else "предмет",
		"size": [snappedf(aabb.size.x, 0.01), snappedf(aabb.size.y, 0.01),
				 snappedf(aabb.size.z, 0.01)],
	}


func _count(node: Node, cls: String) -> int:
	var n := 1 if node.is_class(cls) else 0
	for c in node.get_children():
		n += _count(c, cls)
	return n


func _hide_canvas(node: Node) -> void:
	if node is CanvasLayer:
		node.visible = false
	for c in node.get_children():
		_hide_canvas(c)


func _walk_mesh(node: Node, out: Array[MeshInstance3D]) -> void:
	if node is MeshInstance3D:
		out.append(node)
	for c in node.get_children():
		_walk_mesh(c, out)


func _walk_light(node: Node, out: Array[Light3D]) -> void:
	if node is Light3D:
		out.append(node)
	for c in node.get_children():
		_walk_light(c, out)


func _walk_cam(node: Node, out: Array[Camera3D]) -> void:
	if node is Camera3D:
		out.append(node)
	for c in node.get_children():
		_walk_cam(c, out)


func _spread(img: Image) -> float:
	# Тот же приём, что при проверке запекания: пустой кадр отличается от
	# снятого не кодом возврата, а разбросом яркости.
	var lo := 2.0
	var hi := -1.0
	var step := maxi(img.get_width() / 48, 1)
	for y in range(0, img.get_height(), step):
		for x in range(0, img.get_width(), step):
			var l := img.get_pixel(x, y).get_luminance()
			lo = minf(lo, l)
			hi = maxf(hi, l)
	return snappedf(hi - lo, 0.001)


func _emit(data: Dictionary) -> void:
	print(PREFIX + JSON.stringify(data))
	get_tree().quit(0 if data.get("ok", false) else 1)
