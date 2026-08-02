extends Node3D

# Пошаговый прогон физики: игрок идёт вперёд заданное число шагов, положение
# записывается. Так проверяется, что он стоит на полу и упирается в стену, -
# «побегал, вроде нормально» проверкой не является, и в вебе это правило уже
# оправдалось (там же измерены и скорость шага, и место упора в модель).
#
# Работает в --headless, и это не противоречит грабле про снятие кадров:
# физика идёт в своём цикле и отрисовки не требует. Не рисуется только
# картинка - шаги считаются честно.
#
#   godot --headless --path <game> res://tools/walk_probe.tscn -- '{...}'
#
# Аргументы: scene (что грузим), steps (сколько шагов физики), move (куда
# идти: [x, z], -1 по z это вперёд).

const PREFIX := "RESULT "

var _player: CharacterBody3D
var _track: Array = []
var _steps := 0
var _limit := 240
var _start := Vector3.ZERO
var _floor_at := -1
var _collision: Array = []


func _ready() -> void:
	var raw := "{}"
	var args := OS.get_cmdline_user_args()
	if args.size() > 0:
		raw = args[0]
	var cfg = JSON.parse_string(raw)
	if typeof(cfg) != TYPE_DICTIONARY:
		_emit({"ok": false, "error": "аргументы не разобрались: %s" % raw})
		return

	var path: String = cfg.get("scene", "res://scenes/walk.tscn")
	if not ResourceLoader.exists(path):
		_emit({"ok": false, "error": "нет сцены %s" % path})
		return
	var world: Node = (load(path) as PackedScene).instantiate()
	add_child(world)

	_player = _find(world)
	if _player == null:
		_emit({"ok": false, "error": "в сцене нет CharacterBody3D - ходить некому"})
		return

	# Точку старта можно задать: тем же прогоном проверяются и «упёрся в
	# предмет», и «дошёл до торца», а это разные дорожки в одном коридоре.
	if cfg.has("start"):
		var st: Array = cfg["start"]
		_player.global_position = Vector3(float(st[0]), float(st[1]), float(st[2]))

	_collision = _collisions(world)
	_limit = int(cfg.get("steps", 240))
	var mv: Array = cfg.get("move", [0, -1])
	_player.debug_drive = true
	_player.debug_move = Vector2(float(mv[0]), float(mv[1]))
	_start = _player.global_position


func _physics_process(_delta: float) -> void:
	if _player == null:
		return
	_steps += 1
	if _floor_at < 0 and _player.is_on_floor():
		_floor_at = _steps
	if _steps % 30 == 0 or _steps == _limit:
		var p := _player.global_position
		_track.append({"step": _steps,
					   "pos": [snappedf(p.x, 0.01), snappedf(p.y, 0.01),
							   snappedf(p.z, 0.01)],
					   "floor": _player.is_on_floor(),
					   "walls": _player.get_slide_collision_count()})
	if _steps >= _limit:
		var p := _player.global_position
		var walked := Vector2(p.x - _start.x, p.z - _start.z).length()
		_emit({
			"ok": _floor_at > 0,
			"error": "" if _floor_at > 0 else
				"игрок так и не встал на опору - провалился сквозь пол",
			"start": [snappedf(_start.x, 0.01), snappedf(_start.y, 0.01),
					  snappedf(_start.z, 0.01)],
			"end": [snappedf(p.x, 0.01), snappedf(p.y, 0.01), snappedf(p.z, 0.01)],
			"walked_m": snappedf(walked, 0.01),
			"floor_at_step": _floor_at,
			"steps": _steps,
			"track": _track,
			"collision": _collision,
		})


func _collisions(root: Node) -> Array:
	# Что вообще есть в сцене по части столкновений. Когда игрок проваливается,
	# первый вопрос - существует ли пол как тело и там ли он, где нарисован;
	# по одному факту падения этого не понять.
	var out: Array = []
	for body in _bodies(root, []):
		for c in body.get_children():
			if not (c is CollisionShape3D) or c.shape == null:
				continue
			var e := {"body": body.name, "shape": c.shape.get_class(),
					  "layer": body.collision_layer}
			if c.shape is ConcavePolygonShape3D:
				var f: PackedVector3Array = c.shape.get_faces()
				e["faces"] = f.size() / 3
				var lo := Vector3.INF
				var hi := -Vector3.INF
				for v in f:
					var w: Vector3 = c.global_transform * v
					lo = lo.min(w)
					hi = hi.max(w)
				e["low"] = [snappedf(lo.x, 0.01), snappedf(lo.y, 0.01), snappedf(lo.z, 0.01)]
				e["high"] = [snappedf(hi.x, 0.01), snappedf(hi.y, 0.01), snappedf(hi.z, 0.01)]
			out.append(e)
	return out


func _bodies(node: Node, acc: Array) -> Array:
	if node is StaticBody3D:
		acc.append(node)
	for c in node.get_children():
		_bodies(c, acc)
	return acc


func _find(node: Node) -> CharacterBody3D:
	if node is CharacterBody3D:
		return node
	for c in node.get_children():
		var r := _find(c)
		if r != null:
			return r
	return null


func _emit(data: Dictionary) -> void:
	print(PREFIX + JSON.stringify(data))
	get_tree().quit(0 if data.get("ok", false) else 1)
