extends SceneTree

# Почему сцена с SDFGI выглядит не так, как ожидалось.
#
# Кандидатов два, и глазами они неразличимы: либо глобальное освещение не
# видит геометрию (у мешей выключен режим GI), либо видит, но светит слабо.
# Скрипт отвечает числами: сколько мешей в каком режиме и какие параметры
# у окружения на самом деле.
#
#   godot --path <game> --script res://tools/gi_probe.gd -- res://scenes/X.tscn

const PREFIX := "RESULT "


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	var path: String = args[0] if args.size() > 0 else "res://scenes/classroom.tscn"
	var packed: PackedScene = load(path)
	if packed == null:
		print(PREFIX + JSON.stringify({"error": "не загрузилась сцена " + path}))
		quit()
		return

	var scene: Node = packed.instantiate()
	root.add_child(scene)

	var modes := {"disabled": 0, "static": 0, "dynamic": 0, "прочее": 0}
	var no_uv2 := 0
	for node in scene.find_children("*", "MeshInstance3D", true, false):
		var mi := node as MeshInstance3D
		match mi.gi_mode:
			GeometryInstance3D.GI_MODE_DISABLED: modes["disabled"] += 1
			GeometryInstance3D.GI_MODE_STATIC: modes["static"] += 1
			GeometryInstance3D.GI_MODE_DYNAMIC: modes["dynamic"] += 1
			_: modes["прочее"] += 1
		# UV2 нужен лайтмапам, а не SDFGI, но спросить дешевле сейчас:
		# это следующий шаг, если GI решим запекать.
		if mi.mesh != null and mi.mesh.get_surface_count() > 0:
			var fmt: int = mi.mesh.surface_get_format(0)
			if not (fmt & Mesh.ARRAY_FORMAT_TEX_UV2):
				no_uv2 += 1

	var env: Environment = null
	for node in scene.find_children("*", "WorldEnvironment", true, false):
		env = (node as WorldEnvironment).environment
		break

	var out := {"meshes_by_gi_mode": modes, "meshes_without_uv2": no_uv2}
	if env != null:
		out["env"] = {
			"sdfgi_enabled": env.sdfgi_enabled,
			"sdfgi_energy": env.sdfgi_energy,
			"sdfgi_cascades": env.sdfgi_cascades,
			"sdfgi_min_cell_size": env.sdfgi_min_cell_size,
			"sdfgi_bounce_feedback": env.sdfgi_bounce_feedback,
			"ambient_source": env.ambient_light_source,
			"ambient_energy": env.ambient_light_energy,
			"tonemap": env.tonemap_mode,
			"exposure": env.tonemap_exposure,
		}
	print(PREFIX + JSON.stringify(out))
	quit()
