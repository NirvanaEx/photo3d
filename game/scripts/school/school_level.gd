extends Node3D

const DoorScript = preload("res://scripts/school/school_door.gd")
const LeafShader = preload("res://shaders/school_leaves.gdshader")
var doors: Dictionary = {}
var _zone := ""
var _zone_label: Label
var _zone_tween: Tween

func _ready() -> void:
	for body in $Location.find_children("*", "StaticBody3D", true, false):
		var surface: String = String(body.name).trim_prefix("Surface").to_lower()
		if surface in ["wood","tile","grass","gravel"]:
			body.set_meta("footstep_surface",surface)
	var raw := FileAccess.get_file_as_string("res://assets/school_layout.json")
	var layout: Dictionary = JSON.parse_string(raw)
	var tree_scene: PackedScene = load("res://assets/models/school_tree.glb")
	for config in layout.get("trees",[]):
		var tree: Node3D = tree_scene.instantiate()
		var p: Array = config.position
		tree.position = Vector3(float(p[0]),float(p[1]),float(p[2]))
		tree.scale = Vector3.ONE * float(config.height)
		tree.rotation.y = float(config.rotation)
		add_child(tree)
	for config in layout.get("doors",[]):
		var door := AnimatableBody3D.new()
		door.set_script(DoorScript)
		door.name = str(config.id)
		door.title = str(config.label)
		door.closed_angle = deg_to_rad(float(config.closed_deg))
		door.open_angle = deg_to_rad(float(config.open_deg))
		door.exterior = bool(config.exterior)
		var p: Array = config.hinge
		door.position = Vector3(float(p[0]),float(p[1]),float(p[2]))
		add_child(door)
		doors[door.name] = door
	for z in [-1.1,-4.9,-8.6]:
		var light := OmniLight3D.new()
		light.position = Vector3(5.6,2.79,z)
		light.light_color = Color(1,0.88,0.72)
		light.light_energy = 0.82
		light.light_specular = 0.25
		light.omni_range = 4.6
		light.omni_attenuation = 1.1
		light.shadow_enabled = true
		add_child(light)
	for mi in $Location.find_children("*", "MeshInstance3D", true, false):
		for s in mi.mesh.get_surface_count():
			var material: Material = mi.get_active_material(s)
			if material is StandardMaterial3D and ("oak foliage" in material.resource_name or "autumn foliage" in material.resource_name):
				var leaves := ShaderMaterial.new()
				leaves.shader = LeafShader
				leaves.set_shader_parameter("leaf_color",material.albedo_color)
				mi.set_surface_override_material(s,leaves)
	_zone_label = Label.new()
	_zone_label.position = Vector2(26,23)
	_zone_label.add_theme_font_size_override("font_size",18)
	_zone_label.add_theme_color_override("font_color",Color(0.94,0.90,0.81))
	$HUD.add_child(_zone_label)
	var crosshair := Label.new()
	crosshair.text = "·"
	crosshair.set_anchors_preset(Control.PRESET_CENTER)
	crosshair.position = Vector2(-5,-13)
	crosshair.add_theme_font_size_override("font_size",23)
	crosshair.modulate.a = 0.65
	$HUD.add_child(crosshair)

func zone_at(p: Vector3) -> String:
	if p.x > 3.72 and p.x < 7.5 and p.z > -10.85 and p.z < 0.83:
		return "corridor"
	if p.x >= -4.01 and p.x <= 3.72 and p.z >= -9.35 and p.z <= 0.32:
		return "classroom"
	return "garden"

func garden_door_open() -> bool:
	return doors.has("GardenDoor") and doors.GardenDoor.opening_fraction() > 0.3

func _process(_delta: float) -> void:
	if _zone_label == null: return
	var current := zone_at($Player.global_position)
	if current == _zone: return
	_zone = current
	_zone_label.text = {"classroom":"Класс · 17:42","corridor":"Школьный коридор","garden":"Задний двор"}[current]
	if _zone_tween != null: _zone_tween.kill()
	_zone_label.modulate.a = 1
	_zone_tween = create_tween()
	_zone_tween.tween_interval(3.0)
	_zone_tween.tween_property(_zone_label,"modulate:a",0.0,1.0)
