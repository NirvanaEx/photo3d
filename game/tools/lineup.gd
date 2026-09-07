extends Node

# Линейка пропорций: модели в ряд на одной земле, с метровой шкалой позади.
#
# Зачем отдельный инструмент. Сводить масштабы наборов на глаз по игровому кадру
# невозможно: там всё далеко, перекрывает друг друга и стоит на разной высоте.
# Ошибка «трава ростом с человека» в кадре читается как «что-то не так», а тут
# видна сразу и с числом. Проект уже споткнулся об это дважды - камни в полдома
# и кусты по пояс, - поэтому линейка живёт рядом с игрой, а не в черновиках.
#
# Позади ряда стоит СЕТКА в один метр: без неё картинка отвечает на «что больше»,
# но не на «сколько это в метрах», а вопрос всегда второй.
#
# Запуск:
#   godot --path game res://tools/lineup.tscn --
#       --items=kaykit/house.glb@1.35,nature/tree_oak.glb@2.0
#       --out=D:/путь/lineup.png [--span=12] [--folk=folk/man_a.glb@0.0055]
#
# @ - масштаб. Модели ставятся подошвой на ноль и разносятся по X по их
# фактической ширине, поэтому число в аргументе - единственное, что надо крутить.

const KIT := "res://assets/kits/"
const WARMUP := 12


func _ready() -> void:
	var items: Array[String] = []
	var out := "lineup.png"
	var span := 0.0            # 0 - подобрать по ширине ряда
	for a in OS.get_cmdline_user_args():
		if a.begins_with("--items="):
			for piece in a.substr(8).split(",", false):
				items.append(piece)
		elif a.begins_with("--out="):
			out = a.substr(6)
		elif a.begins_with("--span="):
			span = float(a.substr(7))
	if items.is_empty():
		printerr("нечего показывать: передай --items=путь@масштаб,...")
		get_tree().quit(1)
		return

	var row := $Row as Node3D
	var x := 0.0
	var top := 0.0
	for piece in items:
		var parts := piece.split("@")
		var path := parts[0]
		var s := float(parts[1]) if parts.size() > 1 else 1.0
		var node := _spawn(path)
		if node == null:
			continue
		node.scale = Vector3.ONE * s
		row.add_child(node)
		# Габарит считается ПОСЛЕ добавления в дерево: у скинов (горожане) он
		# берётся из AABB скелета, а тот считается только внутри сцены.
		# _aabb отдаёт габарит В СОБСТВЕННЫХ единицах модели - масштаб узла в нём
		# сокращается, - поэтому домножаем сами. Иначе линейка отчитывается о
		# размерах до масштабирования и ряд расставляется вплотную.
		var box := _aabb(node)
		box.position *= s
		box.size *= s
		node.position = Vector3(x - (box.position.x + box.size.x * 0.5), -box.position.y, 0.0)
		x += box.size.x + 0.5
		top = maxf(top, box.size.y)
		print("%-38s масштаб %.4f -> %.2f x %.2f x %.2f м"
			% [path, s, box.size.x, box.size.y, box.size.z])

	# Ряд центрируется, камера отодвигается ровно настолько, чтобы он влез.
	row.position.x = -x * 0.5
	var width: float = span if span > 0.0 else maxf(x, top * 1.6) * 1.12
	var cam := $Camera3D as Camera3D
	cam.position = Vector3(0.0, top * 0.42, width * 0.5 / tan(deg_to_rad(cam.fov * 0.5)) * 0.62)
	cam.look_at(Vector3(0.0, top * 0.42, 0.0), Vector3.UP)

	_draw_grid(top, x)

	for i in WARMUP:
		await get_tree().process_frame
	await RenderingServer.frame_post_draw
	var img := get_viewport().get_texture().get_image()
	if img.save_png(out) != OK:
		printerr("не записать %s" % out)
		get_tree().quit(1)
		return
	print("снято %s" % out)
	get_tree().quit()


func _spawn(path: String) -> Node3D:
	var full := KIT + path
	if not ResourceLoader.exists(full):
		printerr("нет модели %s" % full)
		return null
	return (load(full) as PackedScene).instantiate() as Node3D


# Габарит узла в его собственных координатах, с учётом трансформаций детей.
func _aabb(node: Node3D) -> AABB:
	var box := AABB()
	var first := true
	for child in node.find_children("*", "VisualInstance3D", true, false):
		var vi := child as VisualInstance3D
		var b: AABB = node.global_transform.affine_inverse() * (vi.global_transform * vi.get_aabb())
		box = b if first else box.merge(b)
		first = false
	return box


# Метровая сетка позади ряда: горизонтали через метр, вертикали через метр.
func _draw_grid(top: float, width: float) -> void:
	var m := ImmediateMesh.new()
	var mi := $Grid as MeshInstance3D
	mi.mesh = m
	var mat := StandardMaterial3D.new()
	mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	mat.albedo_color = Color(0.25, 0.28, 0.32, 1.0)
	mat.vertex_color_use_as_albedo = true
	mi.material_override = mat
	var w := width * 0.5 + 1.0
	var h := ceilf(top) + 1.0
	m.surface_begin(Mesh.PRIMITIVE_LINES)
	for i in range(0, int(h) + 1):
		# Каждый пятый метр ярче: считать полосы глазами дальше третьей нельзя.
		var c := Color(0.55, 0.60, 0.66) if i % 5 == 0 else Color(0.30, 0.34, 0.38)
		m.surface_set_color(c)
		m.surface_add_vertex(Vector3(-w, float(i), -1.2))
		m.surface_set_color(c)
		m.surface_add_vertex(Vector3(w, float(i), -1.2))
	for i in range(-int(w), int(w) + 1):
		m.surface_set_color(Color(0.30, 0.34, 0.38))
		m.surface_add_vertex(Vector3(float(i), 0.0, -1.2))
		m.surface_set_color(Color(0.30, 0.34, 0.38))
		m.surface_add_vertex(Vector3(float(i), h, -1.2))
	m.surface_end()
