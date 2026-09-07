extends CharacterBody3D

# Metres and seconds: an adult 1.75 m tall, with eyes at 1.64 m.
@export var eye_height := 1.64
@export var walk_speed := 1.6
@export var run_speed := 3.65
@export var base_fov := 56.0
@export var mouse_sensitivity := 0.0018
var debug_drive := false
var debug_move := Vector2.ZERO
var debug_sprint := false
var debug_jump := false
var footstep_surface := "wood"
var steps_played := 0
var _distance := 0.0
var _step_time := 0.0
var _bob_phase := 0.0
var _age := 0.0
var _detail_age := 0.0
var _on_floor_before := false
var _looking: Object
var _ray: RayCast3D
var _crouched := false
var _frames := 0
var _floor_frames := 0
var _standing_shape := CapsuleShape3D.new()
@onready var cam: Camera3D = $Camera
@onready var body_shape: CollisionShape3D = $Shape
@onready var sound: Node = get_node("../Audio")
@onready var hint: Label = get_node("../HUD/Hint")
@onready var look_label: Label = get_node("../HUD/Look")
@onready var detail_label: Label = get_node("../HUD/Detail")

func _ready() -> void:
	collision_layer = 2
	collision_mask = 1
	floor_snap_length = 0.22
	floor_stop_on_slope = true
	cam.position.y = eye_height
	cam.fov = base_fov
	cam.near = 0.035
	cam.far = 180.0
	_standing_shape.height = 1.75
	_standing_shape.radius = 0.27
	body_shape.shape = _standing_shape.duplicate()
	body_shape.position.y = 0.875
	_ray = RayCast3D.new()
	_ray.target_position = Vector3(0, 0, -3.0)
	_ray.collision_mask = 1
	_ray.collide_with_areas = true
	_ray.add_exception(self)
	cam.add_child(_ray)
	hint.text = "Кликните, чтобы начать прогулку\n\nWASD — идти · Shift — бежать · мышь — смотреть\nE — открыть дверь / осмотреть · Space — прыжок · Ctrl — присесть\nEsc — отпустить мышь · Esc ещё раз — выйти"
	hint.visible = true
	Input.mouse_mode = Input.MOUSE_MODE_VISIBLE

func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseMotion and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
		rotate_y(-event.relative.x * mouse_sensitivity)
		cam.rotation.x = clampf(cam.rotation.x - event.relative.y * mouse_sensitivity, -1.35, 1.35)
	elif event is InputEventMouseButton and event.pressed and event.button_index == MOUSE_BUTTON_LEFT:
		Input.mouse_mode = Input.MOUSE_MODE_CAPTURED
		hint.visible = false
	elif event is InputEventKey and event.pressed and not event.echo:
		if event.physical_keycode == KEY_ESCAPE:
			if Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
				Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
				hint.visible = true
			else:
				get_tree().quit()
		elif event.physical_keycode == KEY_E and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
			_interact()

func _keys() -> Vector2:
	if Input.mouse_mode != Input.MOUSE_MODE_CAPTURED:
		return Vector2.ZERO
	var result := Vector2.ZERO
	if Input.is_physical_key_pressed(KEY_W): result.y -= 1
	if Input.is_physical_key_pressed(KEY_S): result.y += 1
	if Input.is_physical_key_pressed(KEY_A): result.x -= 1
	if Input.is_physical_key_pressed(KEY_D): result.x += 1
	return result.limit_length()

func _can_stand() -> bool:
	var query := PhysicsShapeQueryParameters3D.new()
	query.shape = _standing_shape
	query.collision_mask = 1
	query.margin = 0.005
	query.transform = Transform3D(Basis.IDENTITY, global_position + Vector3(0, 0.895, 0))
	query.exclude = [get_rid()]
	return get_world_3d().direct_space_state.intersect_shape(query, 1).is_empty()

func _physics_process(delta: float) -> void:
	_age += delta
	_frames += 1
	var move: Vector2 = debug_move.limit_length() if debug_drive else _keys()
	var sprint: bool = debug_sprint if debug_drive else Input.is_physical_key_pressed(KEY_SHIFT)
	var crouch: bool = not debug_drive and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED and Input.is_physical_key_pressed(KEY_CTRL)
	if _crouched and not crouch and not _can_stand(): crouch = true
	if crouch != _crouched:
		_crouched = crouch
		var capsule := body_shape.shape as CapsuleShape3D
		capsule.height = 1.15 if crouch else 1.75
		body_shape.position.y = capsule.height * 0.5
	var speed: float = 0.86 if crouch else (run_speed if sprint else walk_speed)
	var direction := (global_basis * Vector3(move.x, 0, move.y)).normalized()
	velocity.x = move_toward(velocity.x, direction.x * speed, delta * 8.0)
	velocity.z = move_toward(velocity.z, direction.z * speed, delta * 8.0)
	if not is_on_floor(): velocity.y -= 9.81 * delta
	var jump: bool = debug_jump if debug_drive else (Input.mouse_mode == Input.MOUSE_MODE_CAPTURED and Input.is_physical_key_pressed(KEY_SPACE))
	if jump and is_on_floor() and not crouch: velocity.y = 2.9
	debug_jump = false
	var before := global_position
	var fall_speed := velocity.y
	move_and_slide()
	var actual_distance := Vector2(global_position.x - before.x, global_position.z - before.z).length()
	var grounded := is_on_floor()
	if grounded:
		_floor_frames += 1
		_update_surface()
	if grounded and not _on_floor_before and fall_speed < -2.2 and _age > 0.5:
		sound.play_step(footstep_surface, "run" if sprint else "walk", true)
		_distance = 0
	_on_floor_before = grounded
	_step_time += delta
	var moving := grounded and actual_distance > 0.001
	var gait: String = "run" if sprint and not crouch else "walk"
	var stride: float = 1.02 if gait == "run" else (0.57 if crouch else 0.73)
	if moving:
		_distance += actual_distance
		if _distance >= stride and _step_time >= (0.23 if gait == "run" else 0.36):
			_distance = fmod(_distance, stride)
			_step_time = 0
			sound.play_step(footstep_surface, gait, false, -5.0 if crouch else 0.0)
			steps_played += 1
	else:
		_distance = minf(_distance, stride * 0.35)
	_bob_phase += actual_distance / stride * PI
	var bob: float = sin(_bob_phase * 2.0) * (0.019 if gait == "run" else 0.009) if moving else 0.0
	cam.position.y = lerpf(cam.position.y, (1.05 if crouch else eye_height) + bob, 1.0-exp(-delta*13.0))
	cam.position.x = lerpf(cam.position.x, cos(_bob_phase) * 0.005 if moving else 0.0, 1.0-exp(-delta*10.0))
	cam.fov = lerpf(cam.fov, base_fov + (2.0 if sprint and moving else 0.0), 1.0-exp(-delta*4.0))
	_update_look()
	_detail_age -= delta
	if _detail_age <= 0: detail_label.text = ""
	if global_position.y < -8:
		global_position = Vector3(-0.1, 0.1, -0.9)
		velocity = Vector3.ZERO

func _update_surface() -> void:
	var query := PhysicsRayQueryParameters3D.create(global_position + Vector3.UP * 0.16, global_position - Vector3.UP * 0.34, 1, [get_rid()])
	var hit := get_world_3d().direct_space_state.intersect_ray(query)
	if not hit.is_empty():
		var body: Object = hit["collider"]
		if body.has_meta("footstep_surface"):
			footstep_surface = str(body.get_meta("footstep_surface"))
		else:
			var zone: String = get_parent().zone_at(global_position)
			footstep_surface = "tile" if zone == "corridor" else ("grass" if zone == "garden" else "wood")

func _update_look() -> void:
	_ray.force_raycast_update()
	_looking = null
	if _ray.is_colliding():
		var hit: Object = _ray.get_collider()
		var distance := cam.global_position.distance_to(_ray.get_collision_point())
		if hit.has_method("interact") and distance <= 2.2:
			_looking = hit
		elif hit is Interactable and distance <= hit.reach:
			_looking = hit
	look_label.text = "" if _looking == null else str(_looking.look_text())

func _interact() -> void:
	_update_look()
	if _looking == null: return
	if _looking.has_method("interact"):
		detail_label.text = str(_looking.interact(self))
	else:
		detail_label.text = str(_looking.detail)
	_detail_age = 4.0

func audio_report() -> Dictionary:
	var report: Dictionary = sound.report()
	report.merge({"surface":footstep_surface,"steps_played":steps_played,"frames":_frames,"frames_on_floor":_floor_frames})
	return report
