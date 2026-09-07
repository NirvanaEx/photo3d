extends SceneTree

# Проверка импортированного ассета: сколько мешей, треугольников, материалов,
# какие карты доехали, каковы габариты.
#
# Нужна потому, что импорт Godot сообщает об успехе и тогда, когда сцена пустая:
# то же правило, что и с операторами Blender - результат проверяется по
# счётчикам, а не по коду возврата.
#
# Работает в --headless: отрисовки здесь нет, только чтение ресурсов. Снять
# кадр так нельзя (см. docs/PITFALLS.md), а пересчитать геометрию - можно.
#
#   godot --headless --path <game> --script res://tools/inspect_asset.gd -- <имя>

const PREFIX := "RESULT "


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.is_empty():
		_emit({"ok": false, "error": "не передано имя ассета"})
		return

	var name: String = args[0]
	var path := "res://assets/models/%s.glb" % name
	if not ResourceLoader.exists(path):
		_emit({"ok": false, "error": "нет ресурса %s" % path})
		return

	var packed: PackedScene = load(path)
	if packed == null:
		_emit({"ok": false, "error": "ресурс %s не загрузился" % path})
		return

	var root: Node = packed.instantiate()
	var meshes: Array[MeshInstance3D] = []
	_walk(root, meshes)
	# Габариты считаются от КОРНЯ сцены, а не по собственной трансформации
	# каждого меша: масштаб может стоять на узле-родителе (так его вписывает
	# pipeline/glb_scale.py), и mi.transform о нём ничего не знает. Симптом
	# был бы тихий и обидный - модель в сцене девятиметровая, а отчёт уверяет,
	# что метровая, и по нему считается высота, на которой её ставить.

	var tris := 0
	var surfaces := 0
	var materials := {}
	var maps := {"albedo": 0, "roughness": 0, "metallic": 0, "normal": 0, "emission": 0}
	var aabb := AABB()
	var first := true

	for mi in meshes:
		var mesh: Mesh = mi.mesh
		if mesh == null:
			continue
		var box: AABB = _xform_to_root(mi, root) * mesh.get_aabb()
		aabb = box if first else aabb.merge(box)
		first = false
		for s in mesh.get_surface_count():
			surfaces += 1
			var arrays: Array = mesh.surface_get_arrays(s)
			var idx: PackedInt32Array = arrays[Mesh.ARRAY_INDEX]
			if idx.size() > 0:
				tris += idx.size() / 3
			else:
				tris += (arrays[Mesh.ARRAY_VERTEX] as PackedVector3Array).size() / 3
			var m: Material = mesh.surface_get_material(s)
			if m == null:
				continue
			materials[m.get_instance_id()] = true
			if m is BaseMaterial3D:
				if m.albedo_texture != null: maps["albedo"] += 1
				if m.roughness_texture != null: maps["roughness"] += 1
				if m.metallic_texture != null: maps["metallic"] += 1
				if m.normal_texture != null: maps["normal"] += 1
				if m.emission_texture != null: maps["emission"] += 1

	# Тела столкновений считаются отдельно, потому что ради них всё и затевалось.
	# Меш с суффиксом -colonly импортёр поглощает: в списке мешей его уже нет,
	# и по одному их числу нельзя понять, приехали столкновения или потерялись.
	var bodies := _count(root, "StaticBody3D")
	var shapes := _count(root, "CollisionShape3D")

	root.free()
	_emit({
		"ok": tris > 0,
		"bodies": bodies,
		"shapes": shapes,
		"error": "" if tris > 0 else "сцена импортировалась пустой: ноль треугольников",
		"meshes": meshes.size(),
		"surfaces": surfaces,
		"triangles": tris,
		"materials": materials.size(),
		"maps": maps,
		"size": [
			snappedf(aabb.size.x, 0.001),
			snappedf(aabb.size.y, 0.001),
			snappedf(aabb.size.z, 0.001)],
		"center": [
			snappedf(aabb.get_center().x, 0.001),
			snappedf(aabb.get_center().y, 0.001),
			snappedf(aabb.get_center().z, 0.001)],
	})


func _count(node: Node, cls: String) -> int:
	var n := 1 if node.is_class(cls) else 0
	for c in node.get_children():
		n += _count(c, cls)
	return n


func _walk(node: Node, out: Array[MeshInstance3D]) -> void:
	if node is MeshInstance3D:
		out.append(node)
	for c in node.get_children():
		_walk(c, out)


func _xform_to_root(node: Node3D, root: Node) -> Transform3D:
	# Своя сборка вместо global_transform: сцена здесь только инстанцирована и
	# в дерево не добавлена, а полагаться на глобальные координаты вне дерева
	# не стоит. Поднимаемся до корня включительно - у него тоже может быть
	# собственная трансформация.
	var t := Transform3D.IDENTITY
	var n: Node = node
	while n != null:
		if n is Node3D:
			t = (n as Node3D).transform * t
		if n == root:
			break
		n = n.get_parent()
	return t


func _emit(data: Dictionary) -> void:
	# Одной строкой с меткой: Godot печатает вокруг много своего, и разбирать
	# вывод построчным угадыванием - способ поймать чужую строку.
	print(PREFIX + JSON.stringify(data))
	quit(0 if data.get("ok", false) else 1)
