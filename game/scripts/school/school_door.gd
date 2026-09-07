extends AnimatableBody3D

var title := "Дверь"
var closed_angle := 0.0
var open_angle := -1.693
var is_open := false
var desired_open := false
var exterior := false
var blocked_count := 0
var activation_count := 0
var _target := 0.0
var _shape := BoxShape3D.new()
var _sound: AudioStreamPlayer3D
var _finished := true

func _exit_tree() -> void:
	if is_instance_valid(_sound):
		_sound.stop()
		_sound.stream = null

func _ready() -> void:
	collision_layer = 1
	collision_mask = 2
	sync_to_physics = true
	rotation.y = closed_angle
	_target = closed_angle
	var visual: Node3D = load("res://assets/models/school_door.glb").instantiate()
	add_child(visual)
	for mi in visual.find_children("*", "MeshInstance3D", true, false):
		for s in mi.mesh.get_surface_count():
			var material: Material = mi.get_active_material(s)
			if material is BaseMaterial3D and material.transparency != BaseMaterial3D.TRANSPARENCY_DISABLED:
				mi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	_shape.size = Vector3(0.075,2.20,1.08)
	var collider := CollisionShape3D.new()
	collider.shape = _shape
	collider.position = Vector3(0,1.10,-0.54)
	add_child(collider)
	_sound = AudioStreamPlayer3D.new()
	_sound.position = Vector3(0,1.0,-0.9)
	_sound.bus = "SchoolFoley"
	_sound.max_distance = 16
	_sound.unit_size = 2
	_sound.volume_db = -12
	add_child(_sound)

func look_text() -> String:
	return title + (" · [E] закрыть" if desired_open else " · [E] открыть")

func interact(_player: Node) -> String:
	desired_open = not desired_open
	_target = open_angle if desired_open else closed_angle
	_finished = false
	activation_count += 1
	_play("door_open.ogg" if desired_open else "door_latch.ogg")
	return ""

func _play(file: String) -> void:
	_sound.stream = load("res://assets/audio/school/" + file)
	_sound.pitch_scale = 0.94 if exterior else 1.0
	_sound.play()

func _physics_process(delta: float) -> void:
	if _finished: return
	var next := move_toward(rotation.y, _target, delta*1.9)
	# Test the next actual leaf pose against the player; never close through them.
	var query := PhysicsShapeQueryParameters3D.new()
	query.shape = _shape
	query.collision_mask = 2
	query.margin = 0.001
	query.exclude = [get_rid()]
	query.transform = Transform3D(Basis(Vector3.UP,next),global_position) * Transform3D(Basis.IDENTITY,Vector3(0,1.10,-0.54))
	if not get_world_3d().direct_space_state.intersect_shape(query,1).is_empty():
		blocked_count += 1
		if not desired_open:
			desired_open = true
			_target = open_angle
		else:
			_finished = true
			desired_open = is_open
		return
	rotation.y = next
	if absf(next-_target) < 0.001:
		is_open = desired_open
		_finished = true
		if not is_open: _play("door_close.ogg")

func opening_fraction() -> float:
	return clampf(absf(rotation.y-closed_angle)/absf(open_angle-closed_angle),0,1)
