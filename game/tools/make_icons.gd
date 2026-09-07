extends Node

# Значки построек: модель из набора, снятая в PNG с прозрачным фоном.
#
# Зачем: в карточке постройки раньше стоял цветной прямоугольник. Он не говорит
# ничего - «оранжевое» и «серое» не выбирают, выбирают мельницу и причал. У
# референса (Dice Kingdoms) на карточках картинки самих зданий, и панель
# читается без единой подписи.
#
# Почему НЕ SubViewport в каждой карточке: десять живых трёхмерных вьюпортов
# рисуются каждый кадр вместе с миром. Значок же не меняется никогда - его
# место в файле, а не в кадровом бюджете.
#
# Запуск (после смены моделей или добавления типа):
#   godot --path game res://tools/make_icons.tscn
#   godot --path game --headless --import      # чтобы движок увидел новые PNG

const Builder := preload("res://scripts/islands/builder.gd")
const Kit := preload("res://scripts/islands/kit.gd")

const OUT_DIR := "res://assets/icons"

# Значки не для построек. «Снести» - не тип здания, а режим, и модели у него
# нет: берём щебень, потому что именно он остаётся после сноса.
const EXTRA := {
	"demolish": "kaykit/detail_rocks.glb",
}
const SIZE := 192
# Ракурс: три четверти сверху - тот же, каким игрок видит мир. Значок в другом
# ракурсе приходится сопоставлять с постройкой в уме.
const YAW := deg_to_rad(-35.0)
const PITCH := deg_to_rad(-28.0)


func _ready() -> void:
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(OUT_DIR))

	var view := SubViewport.new()
	view.size = Vector2i(SIZE, SIZE)
	view.transparent_bg = true
	view.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	view.msaa_3d = Viewport.MSAA_4X
	add_child(view)

	var cam := Camera3D.new()
	cam.projection = Camera3D.PROJECTION_ORTHOGONAL
	view.add_child(cam)

	# Свет тот же по смыслу, что в игре: солнце сбоку сверху плюс мягкая
	# подсветка снизу, иначе низ модели уходит в чёрное пятно.
	var sun := DirectionalLight3D.new()
	sun.light_energy = 1.5
	sun.rotation = Vector3(deg_to_rad(-42.0), deg_to_rad(38.0), 0.0)
	view.add_child(sun)
	var fill := DirectionalLight3D.new()
	fill.light_energy = 0.55
	fill.light_color = Color(0.78, 0.84, 0.95)
	fill.rotation = Vector3(deg_to_rad(28.0), deg_to_rad(-140.0), 0.0)
	view.add_child(fill)

	var env := WorldEnvironment.new()
	var e := Environment.new()
	e.background_mode = Environment.BG_CANVAS
	e.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	e.ambient_light_color = Color(0.62, 0.66, 0.72)
	e.ambient_light_energy = 0.9
	e.tonemap_mode = Environment.TONE_MAPPER_ACES
	env.environment = e
	view.add_child(env)

	var made := 0
	for t in Builder.TYPES:
		var path := String(t.get("body", ""))
		if path == "":
			continue
		if await _shoot(view, cam, path, String(t["id"])):
			made += 1
	for id in EXTRA:
		if await _shoot(view, cam, String(EXTRA[id]), String(id)):
			made += 1
	print("значков записано: %d в %s" % [made, OUT_DIR])
	get_tree().quit()


func _shoot(view: SubViewport, cam: Camera3D, model: String, id: String) -> bool:
	var full := "res://assets/kits/" + model
	if not ResourceLoader.exists(full):
		printerr("нет модели %s - значок для «%s» не сделан" % [full, id])
		return false
	var node := (load(full) as PackedScene).instantiate() as Node3D
	Kit.recolor(node, model)
	view.add_child(node)

	# Габариты берутся с УЖЕ ПОСТАВЛЕННОЙ модели: у части наборов начало
	# координат не в середине, и рамка, посчитанная «по размеру», срезала бы
	# крышу. Камера наводится на фактический охват.
	var box := _aabb(node)
	var centre := box.get_center()
	var reach := maxf(box.size.x, maxf(box.size.y, box.size.z))
	cam.size = reach * 1.28
	cam.near = 0.01
	cam.far = reach * 12.0
	var dir := Basis.from_euler(Vector3(PITCH, YAW, 0.0)) * Vector3(0, 0, 1)
	cam.position = centre + dir * reach * 4.0
	cam.look_at(centre, Vector3.UP)

	await RenderingServer.frame_post_draw
	await RenderingServer.frame_post_draw
	var img := view.get_texture().get_image()
	node.queue_free()

	var err := img.save_png("%s/%s.png" % [OUT_DIR, id])
	if err != OK:
		printerr("не записать значок «%s» (код %d)" % [id, err])
		return false
	return true


func _aabb(root: Node3D) -> AABB:
	var out := AABB()
	var first := true
	for mi in root.find_children("*", "MeshInstance3D", true, false):
		var m := mi as MeshInstance3D
		if m.mesh == null:
			continue
		var b := m.global_transform * m.mesh.get_aabb()
		if first:
			out = b
			first = false
		else:
			out = out.merge(b)
	return out
