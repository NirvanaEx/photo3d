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
		var box: AABB = mi.transform * mesh.get_aabb()
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

	root.free()
	_emit({
		"ok": tris > 0,
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


func _walk(node: Node, out: Array[MeshInstance3D]) -> void:
	if node is MeshInstance3D:
		out.append(node)
	for c in node.get_children():
		_walk(c, out)


func _emit(data: Dictionary) -> void:
	# Одной строкой с меткой: Godot печатает вокруг много своего, и разбирать
	# вывод построчным угадыванием - способ поймать чужую строку.
	print(PREFIX + JSON.stringify(data))
	quit(0 if data.get("ok", false) else 1)
