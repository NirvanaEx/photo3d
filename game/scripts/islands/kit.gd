extends RefCounted

# Приведение моделей наборов (Kenney, KayKit, Quaternius - все CC0) к палитре
# игры. Правится ТОЛЬКО то, что негодно, и правится ПОИМЕННО.
#
# Здесь было правило по подстроке: «имя материала содержит leaf - красим в
# зелёный». Оно выглядело разумно ровно до тех пор, пока пород было три. Как
# только в наборе оказались осенние и тёмные варианты, правило съело именно то,
# ради чего их брали: leafsFall (рыжий, 1.00, 0.57, 0.26) и leafsDark попадали
# под ту же подстроку и становились одним и тем же зелёным. На кадре весь
# архипелаг был выкрашен в один цвет, и разницы между сухим поясом и влажным не
# было видно вовсе. Та же ловушка ждала бы KayKit: «Roof_Red_1» словил бы
# правило "roof", и все крыши стали бы одного цвета - ради которого набор и
# брали.
#
# Модели замка и пиратов не трогаем вовсе: у них цвет приходит
# текстурой-палитрой (colormap.png), и она в стиль попадает.

# Точечные замены ПО ПОЛНОМУ ИМЕНИ материала, для любого набора.
#
# GreenDark у KayKit - листва, и она бирюзовая по-настоящему: 0.021, 0.257,
# 0.267, синего больше, чем зелёного. Рядом с зелёной травой острова роща
# выходила бирюзовой. Это не ошибка импорта и не цветовое пространство -
# проверено чтением baseColorFactor прямо из GLB.
#
# У Kenney та же беда и по той же причине: leafsGreen там 0.16, 0.79, 0.67 -
# зелёного и синего поровну, то есть бирюза, а не листва. grass - 0.17, 0.85,
# 0.72, ещё ярче. Три оттенка листвы разведены нарочно: рыжий остаётся рыжим,
# тёмный тёмным, и по ним на карте читается пояс.
#
# Земля и кора у Kenney тоже не то, чем зовутся: «dirt» и «woodBark» там
# 0.95, 0.74, 0.62 - это не земля и не кора, а лосось. Из этого материала у них
# сделаны КАМНИ и стволы, поэтому на кадре по всему острову лежали розовые
# булыжники и стояли розовые деревья. «_defaultMat» - вообще забытый в наборе
# белый по умолчанию, и колосья с ним читались пластиковыми свечками.
const FIX := {
	"GreenDark": Color(0.24, 0.42, 0.18),
	"leafsGreen": Color(0.33, 0.58, 0.24),
	"leafsDark": Color(0.20, 0.40, 0.20),
	"leafsFall": Color(0.83, 0.50, 0.18),
	"grass": Color(0.45, 0.66, 0.28),
	"stone": Color(0.74, 0.74, 0.71),
	"stoneDark": Color(0.56, 0.57, 0.56),
	"dirt": Color(0.72, 0.56, 0.42),
	"dirtDark": Color(0.58, 0.44, 0.33),
	"woodBark": Color(0.62, 0.45, 0.31),
	"woodBarkDark": Color(0.50, 0.36, 0.26),
	"wood": Color(0.78, 0.58, 0.40),
	"woodDark": Color(0.62, 0.44, 0.30),
	"_defaultMat": Color(0.86, 0.80, 0.68),
	# Срез бревна и колосья - один материал, и в наборе он почти белый.
	# У бревна это сходит, у поля - нет: колосья читались пластиковыми свечками.
	"woodInner": Color(0.88, 0.79, 0.58),
}

static var _mesh_cache := {}


# Меш для мультимеша: материалы копируются и перекрашиваются один раз на породу.
# Копия обязательна - материал у загруженной модели общий, и правка на месте
# перекрасила бы все деревья карты разом, включая уже стоящие.
static func mesh_for(path: String) -> Mesh:
	if _mesh_cache.has(path):
		return _mesh_cache[path]
	var full := "res://assets/kits/" + path
	if not ResourceLoader.exists(full):
		push_warning("нет модели %s" % full)
		_mesh_cache[path] = null
		return null
	var inst := (load(full) as PackedScene).instantiate()
	var src: Mesh = null
	for mi in inst.find_children("*", "MeshInstance3D", true, false):
		src = (mi as MeshInstance3D).mesh
		break
	inst.queue_free()
	if src == null:
		_mesh_cache[path] = null
		return null
	var out := src.duplicate() as ArrayMesh
	for i in out.get_surface_count():
		out.surface_set_material(i, _fixed(out.surface_get_material(i)))
	_mesh_cache[path] = out
	return out


# Узел-постройка: материал ставится ПОВЕРХ каждой поверхности отдельно.
# material_override заменил бы собой все поверхности сразу, и у дома крыша
# стала бы цвета стен.
static func recolor(node: Node, _path: String) -> void:
	for mi in node.find_children("*", "MeshInstance3D", true, false):
		var m := mi as MeshInstance3D
		if m.mesh == null:
			continue
		for i in m.mesh.get_surface_count():
			m.set_surface_override_material(i, _fixed(m.mesh.surface_get_material(i)))


static func _fixed(mat: Material) -> Material:
	if mat == null:
		return null
	var out := mat.duplicate() as BaseMaterial3D
	if out == null:
		return mat
	# Текстура есть - цвет задан ей, трогать нечего.
	if FIX.has(out.resource_name) and out.albedo_texture == null:
		out.albedo_color = FIX[out.resource_name]
	out.roughness = 0.88
	out.metallic_specular = 0.15
	return out
