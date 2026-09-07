extends SceneTree

# Материалы модели ГЛАЗАМИ ДВИЖКА: имя, цвет, есть ли текстура.
#
# Читать те же числа прямо из GLB недостаточно. Правки палитры (kit.gd, FIX)
# ищут материал ПО ИМЕНИ, а имя после импорта задаёт Godot, а не файл: если оно
# не совпало, правка молча не срабатывает - именно так набор и остаётся
# бирюзовым, хотя в словаре всё написано верно.
#
#   godot --headless --path game --script res://tools/mats.gd -- nature/path_stone.glb ...

const KIT := "res://assets/kits/"
const Kit := preload("res://scripts/islands/kit.gd")


func _initialize() -> void:
	for name in OS.get_cmdline_user_args():
		var path := KIT + name
		if not ResourceLoader.exists(path):
			print("НЕТ %s" % path)
			continue
		var node := (load(path) as PackedScene).instantiate()
		print("=== %s" % name)
		for mi in node.find_children("*", "MeshInstance3D", true, false):
			var m := mi as MeshInstance3D
			if m.mesh == null:
				continue
			for i in m.mesh.get_surface_count():
				var mat := m.mesh.surface_get_material(i) as BaseMaterial3D
				if mat == null:
					print("    поверхность %d: материала нет" % i)
					continue
				var fixed := Kit._fixed(mat) as BaseMaterial3D
				print("    «%s»  %s -> %s%s" % [mat.resource_name,
					_c(mat.albedo_color), _c(fixed.albedo_color),
					"  (текстура)" if mat.albedo_texture != null else ""])
		node.queue_free()
	quit()


func _c(c: Color) -> String:
	return "%.2f,%.2f,%.2f" % [c.r, c.g, c.b]
