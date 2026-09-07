extends Node

# Кадр сцены ВМЕСТЕ с интерфейсом.
#
# Зачем отдельный инструмент: tools/shot.gd прячет CanvasLayer нарочно - агенту
# нужен мир, а подсказки «щёлкни, чтобы взять управление» только закрывают его.
# Но когда правишь сам интерфейс, смотреть надо именно на него, и другого
# способа увидеть HUD в кадре нет. Снимать вместо этого экран Windows - плохая
# замена: в кадр попадает чужой рабочий стол, а не игра.
#
# Запуск:
#   godot --path game res://tools/uishot.tscn -- --scene=res://scenes/islands.tscn --out=D:/путь/ui.png

const WARMUP := 45           # кадров на прогрев: свет, тени и небо считаются не сразу



func _ready() -> void:
	var scene_path := "res://scenes/islands.tscn"
	var out := "ui.png"
	var hud := true
	# Выдержка. Прогрева хватает для света, но не для того, что ИДЁТ во
	# времени: чтобы увидеть стройку на половине, ждать надо секунды, а не кадры.
	var frames := WARMUP
	for a in OS.get_cmdline_user_args():
		if a.begins_with("--frames="):
			frames = maxi(int(a.substr(9)), 1)
	for a in OS.get_cmdline_user_args():
		if a.begins_with("--scene="):
			scene_path = a.substr(8)
		elif a.begins_with("--out="):
			out = a.substr(6)
		elif a == "--nohud":
			hud = false

	if not ResourceLoader.exists(scene_path):
		printerr("нет сцены %s - проверь путь res:// или имя файла" % scene_path)
		get_tree().quit(1)
		return

	var world := (load(scene_path) as PackedScene).instantiate()
	# Настройки правятся ДО add_child: _ready сцены строит по ним мир, а после
	# добавления в дерево карта уже собрана и seed менять поздно.
	#
	# Нужно это затем, что снимать приходится не то, что в сцене, а то, что
	# проверяешь: пустой остров ничего не говорит о посёлке, а общий план - о
	# том, как здание выглядит вблизи. Раньше ради каждого кадра правился
	# islands.tscn и потом возвращался обратно - однажды это стоило испорченного
	# файла.
	_tune(world)
	add_child(world)

	# Слои гасятся ПОСЛЕ первого кадра: те, что сцена создаёт в своём _ready,
	# до него ещё не существуют. Нужно это для плиток лаунчера - там интерфейс
	# в размер ногтя превращается в грязь поверх картинки.
	if not hud:
		await get_tree().process_frame
		for n in world.find_children("*", "CanvasLayer", true, false):
			(n as CanvasLayer).visible = false

	for i in frames:
		await get_tree().process_frame
	await RenderingServer.frame_post_draw

	var img := get_viewport().get_texture().get_image()
	var err := img.save_png(out)
	if err != OK:
		printerr("не записать %s (код %d) - проверь, что папка существует" % [out, err])
		get_tree().quit(1)
		return
	print("снято %s, %dx%d" % [out, img.get_width(), img.get_height()])
	get_tree().quit()


# --demo=N   - поставить N готовых построек вокруг старта
# --seed=N   - повторяемый архипелаг
# --zoom=N   - расстояние камеры (в сцене 46; 12 это уже двор одного дома)
# --pitch=N  - наклон камеры в градусах (в сцене 52)
func _tune(world: Node) -> void:
	for a in OS.get_cmdline_user_args():
		if a.begins_with("--demo="):
			var b := world.get_node_or_null("Buildings")
			if b != null:
				b.set("demo_village", int(a.substr(7)))
		elif a.begins_with("--seed="):
			var w := world.get_node_or_null("Archipelago")
			if w != null:
				w.set("world_seed", int(a.substr(7)))
		elif a.begins_with("--zoom="):
			var cam := world.get_node_or_null("CameraRig/Arm/Camera3D") as Camera3D
			if cam != null:
				cam.position.z = float(a.substr(7))
		elif a.begins_with("--pitch="):
			var arm := world.get_node_or_null("CameraRig/Arm") as Node3D
			if arm != null:
				arm.rotation.x = -deg_to_rad(float(a.substr(8)))
