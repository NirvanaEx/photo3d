extends CharacterBody3D

# Ходьба от первого лица. Числа те же, что в веб-прогулке (web/static/walk.js),
# и это не лень, а требование: одна и та же локация должна ощущаться одинаково
# в браузерном просмотре и в игре, иначе один из двух режимов врёт.
#
# Столкновений здесь НЕТ ни строчки: тело даёт CharacterBody3D, оболочку -
# сам ассет (меш с суффиксом -colonly, из которого импортёр Godot делает
# StaticBody3D). Своя физика была бы ровно тем случаем, о котором
# предупреждает CLAUDE.md.

const SPEED := 4.2          # м/с, предельная скорость шага
const SPRINT := 2.2         # множитель по Shift
const JUMP := 7.2
const GRAVITY := 24.0       # не 9.8: игровая тяжесть читается как отзывчивая
const EYE := 1.65

# Отладочная ручка: пошаговый прогон физики без клавиатуры. Ею проверяется,
# что игрок действительно упирается в стену, а не проходит сквозь. Тот же
# приём, что window.walk.debug в вебе - «побегал и вроде нормально» проверкой
# не является.
var debug_drive := false
var debug_move := Vector2.ZERO

@export var mouse_sensitivity := 0.0022

@onready var cam: Camera3D = $Camera


func _ready() -> void:
	cam.position.y = EYE
	if not debug_drive:
		Input.mouse_mode = Input.MOUSE_MODE_CAPTURED


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseMotion and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
		rotate_y(-event.relative.x * mouse_sensitivity)
		cam.rotate_x(-event.relative.y * mouse_sensitivity)
		# Под ноги и в потолок заглядывать можно, кувыркаться - нет.
		cam.rotation.x = clampf(cam.rotation.x, -1.4, 1.4)
	elif event is InputEventKey and event.pressed \
			and event.physical_keycode == KEY_ESCAPE:
		# Первый Esc отпускает мышь, второй закрывает окно. Без второго шага
		# человек оказывается заперт: мышь свободна, а выйти нечем, кроме
		# Alt+F4. Порядок именно такой, чтобы случайный Esc не выбрасывал из
		# игры целиком.
		if Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
			Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
		else:
			get_tree().quit()
	elif event is InputEventMouseButton and event.pressed:
		Input.mouse_mode = Input.MOUSE_MODE_CAPTURED


func _physics_process(delta: float) -> void:
	if not is_on_floor():
		velocity.y -= GRAVITY * delta

	var move := debug_move if debug_drive else _keys()
	if not debug_drive and Input.is_physical_key_pressed(KEY_SPACE) and is_on_floor():
		velocity.y = JUMP

	var dir := (transform.basis * Vector3(move.x, 0, move.y)).normalized()
	var speed := SPEED
	if not debug_drive and Input.is_physical_key_pressed(KEY_SHIFT):
		speed *= SPRINT

	if dir:
		velocity.x = dir.x * speed
		velocity.z = dir.z * speed
	else:
		velocity.x = move_toward(velocity.x, 0, speed)
		velocity.z = move_toward(velocity.z, 0, speed)

	move_and_slide()


func _keys() -> Vector2:
	# Клавиши читаются ФИЗИЧЕСКИЕ, а не по символу. При русской раскладке
	# W/A/S/D дают «ц», «ф», «ы», «в», и управление молча перестало бы
	# работать - в вебе на это уже наступали (web/static/walk.js).
	var v := Vector2.ZERO
	if Input.is_physical_key_pressed(KEY_W): v.y -= 1
	if Input.is_physical_key_pressed(KEY_S): v.y += 1
	if Input.is_physical_key_pressed(KEY_A): v.x -= 1
	if Input.is_physical_key_pressed(KEY_D): v.x += 1
	return v
