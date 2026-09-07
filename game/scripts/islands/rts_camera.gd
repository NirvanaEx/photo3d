extends Node3D

# Камера вида сверху: узел-подвес (эта нода) поворачивается по горизонтали,
# дочерний Arm задаёт наклон, камера сидит на конце руки и всегда смотрит в
# подвес. Такая тройка - стандартная схема стратегической камеры: перемещение,
# поворот и приближение не мешают друг другу и не требуют матричной математики.
#
# Управление читается напрямую с клавиш, а не через InputMap: проект уже
# существует, лезть в project.godot ради WASD значило бы менять общий файл
# ради одной сцены.

signal moved                       # для мини-карты: рамка обзора едет за камерой

@export var pan_speed := 22.0
@export var rotate_speed := 1.8
@export var zoom_min := 14.0
@export var zoom_max := 165.0
@export var zoom_step := 0.12
@export var pitch_min := 18.0
@export var pitch_max := 82.0
## Сглаживание: 0 - рывками, 1 - без задержки. Всё между - инерция.
@export var smooth := 12.0
## Панорама от края экрана - как в любой стратегии.
@export var edge_pan := true
@export var edge_margin := 6.0

@onready var _arm: Node3D = $Arm
@onready var _camera: Camera3D = $Arm/Camera3D

var _focus := Vector3.ZERO
var _yaw := 0.0
var _pitch := deg_to_rad(52.0)
var _dist := 42.0
var _bounds := 60.0
var _looking := false               # осмотр: ПКМ зажата, мышь захвачена
var _dragging := false              # СКМ: тянем карту
var _focus_set := false

# Панорама левой кнопкой. Она же ставит здания, поэтому нажатие само по себе
# ничего не решает: пока мышь не прошла CLICK_SLOP точек, это ещё щелчок, и
# карта стоит. Прошла - началось перетаскивание, и щелчка уже не будет.
# Без порога здание ставилось бы при каждой попытке подвинуть карту.
const CLICK_SLOP := 6.0
var _pan_button := false
var _pan_moved := 0.0
# То же для правой кнопки: она крутит камеру, но щелчком по ней выходят из
# режима стройки. Отличить одно от другого можно только по пройденному пути.
var _look_moved := 0.0

# Вид по умолчанию: то, что стоит в сцене. Запоминается на старте, чтобы
# «вернуть как было» не требовало помнить числа в двух местах.
var _home_yaw := 0.0
var _home_pitch := 0.0
var _home_dist := 0.0


func _ready() -> void:
	_yaw = rotation.y
	_pitch = -_arm.rotation.x
	_dist = _camera.position.z
	_home_yaw = _yaw
	_home_pitch = _pitch
	_home_dist = _dist
	if not _focus_set:
		_focus = position


# Мир готовится раньше камеры (в дереве он выше), поэтому focus_on прилетает
# до _ready. Флаг нужен, чтобы _ready потом не вернул камеру в начало координат.
func focus_on(target: Vector3) -> void:
	_focus = _clamped(target)
	if not _focus_set:
		_focus_set = true
		position = _focus       # первый раз - без перелёта через всю карту


func set_bounds(radius: float) -> void:
	_bounds = radius


# Вид по умолчанию одной кнопкой: угол, наклон и приближение возвращаются к
# тем, что записаны в сцене. Точка обзора остаётся - «сбросить вид» это про
# ракурс, а не про «улететь на старт»: для этого есть отдельная кнопка.
func reset_view() -> void:
	_yaw = _home_yaw
	_pitch = _home_pitch
	_dist = _home_dist


func focus_point() -> Vector3:
	return _focus


func yaw() -> float:
	return _yaw


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseButton:
		var mb := event as InputEventMouseButton
		match mb.button_index:
			MOUSE_BUTTON_WHEEL_UP:
				_dist = clampf(_dist * (1.0 - zoom_step), zoom_min, zoom_max)
			MOUSE_BUTTON_WHEEL_DOWN:
				_dist = clampf(_dist * (1.0 + zoom_step), zoom_min, zoom_max)
			MOUSE_BUTTON_RIGHT:
				if mb.pressed:
					_look_moved = 0.0
				_set_looking(mb.pressed)
			MOUSE_BUTTON_MIDDLE:
				_dragging = mb.pressed
			MOUSE_BUTTON_LEFT:
				_pan_button = mb.pressed
				# Счётчик пути обнуляется ТОЛЬКО при нажатии: на отпускании он
				# ещё нужен - по нему мир решает, был это щелчок или протяжка.
				if mb.pressed:
					_pan_moved = 0.0
	elif event is InputEventMouseMotion:
		var mm := event as InputEventMouseMotion
		if _looking:
			_look_moved += mm.relative.length()
			_yaw -= mm.relative.x * 0.006
			_pitch = clampf(_pitch + mm.relative.y * 0.005,
				deg_to_rad(pitch_min), deg_to_rad(pitch_max))
		elif _dragging or _pan_button:
			if _pan_button and not _dragging:
				_pan_moved += mm.relative.length()
				if _pan_moved < CLICK_SLOP:
					return
			# Тянем карту под курсором: смещение экрана переводится в плоскость
			# земли с учётом текущего поворота и высоты - иначе на приближении
			# карта уезжает медленнее курсора, и хват «проскальзывает».
			var k := _dist * 0.0016
			_move(Vector3(-mm.relative.x * k, 0.0, -mm.relative.y * k))


# Мышь на время осмотра ЗАХВАТЫВАЕТСЯ, а не просто скрывается: иначе курсор
# упирается в край экрана, и поворот обрывается на середине движения. При
# отпускании система возвращает указатель туда, где его взяли.
func _set_looking(on: bool) -> void:
	if _looking == on:
		return
	_looking = on
	Input.mouse_mode = Input.MOUSE_MODE_CAPTURED if on else Input.MOUSE_MODE_VISIBLE


func looking() -> bool:
	return _looking


# Было ли последнее нажатие левой кнопки протяжкой, а не щелчком. Спрашивает
# мир на ОТПУСКАНИИ кнопки: ставить здание нужно только там, где карту не
# тащили.
func dragged() -> bool:
	return _pan_moved >= CLICK_SLOP


# То же про правую кнопку: крутили камеру или щёлкнули. Мир спрашивает это,
# чтобы решить, снимать ли выбранную постройку.
func turned() -> bool:
	return _look_moved >= CLICK_SLOP


func _process(delta: float) -> void:
	var dir := Vector3.ZERO
	if Input.is_key_pressed(KEY_W) or Input.is_key_pressed(KEY_UP):
		dir.z -= 1.0
	if Input.is_key_pressed(KEY_S) or Input.is_key_pressed(KEY_DOWN):
		dir.z += 1.0
	if Input.is_key_pressed(KEY_A) or Input.is_key_pressed(KEY_LEFT):
		dir.x -= 1.0
	if Input.is_key_pressed(KEY_D) or Input.is_key_pressed(KEY_RIGHT):
		dir.x += 1.0
	dir += _edge_push()
	if dir != Vector3.ZERO:
		# Скорость растёт с высотой: на общем плане карта пролистывается за
		# те же секунды, что и вблизи, иначе перелёт через архипелаг занимает
		# полминуты.
		_move(dir.normalized() * pan_speed * delta * (_dist / 30.0))

	if Input.is_key_pressed(KEY_Q):
		_yaw += rotate_speed * delta
	if Input.is_key_pressed(KEY_E):
		_yaw -= rotate_speed * delta

	var t := clampf(delta * smooth, 0.0, 1.0)
	var before := position
	position = position.lerp(_focus, t)
	rotation.y = lerp_angle(rotation.y, _yaw, t)
	_arm.rotation.x = lerpf(_arm.rotation.x, -_pitch, t)
	_camera.position.z = lerpf(_camera.position.z, _dist, t)
	if not before.is_equal_approx(position):
		moved.emit()


# Панорама от края экрана. Не работает во время осмотра (мышь захвачена и
# «край» перестаёт быть краем) и когда окно не в фокусе - иначе карта уезжает,
# пока человек смотрит в другое приложение.
func _edge_push() -> Vector3:
	if not edge_pan or _looking or _dragging or _pan_button:
		return Vector3.ZERO
	if not DisplayServer.window_is_focused():
		return Vector3.ZERO
	var size := get_viewport().get_visible_rect().size
	var m := get_viewport().get_mouse_position()
	if m.x < 0.0 or m.y < 0.0 or m.x > size.x or m.y > size.y:
		return Vector3.ZERO
	var push := Vector3.ZERO
	if m.x < edge_margin:
		push.x -= 1.0
	elif m.x > size.x - edge_margin:
		push.x += 1.0
	if m.y < edge_margin:
		push.z -= 1.0
	elif m.y > size.y - edge_margin:
		push.z += 1.0
	return push


func _move(local: Vector3) -> void:
	_focus = _clamped(_focus + Basis(Vector3.UP, _yaw) * local)


# Держим взгляд над картой: за краем видно только пустое море, и вернуться
# оттуда бывает нечем - ориентиров нет.
func _clamped(p: Vector3) -> Vector3:
	var flat := Vector2(p.x, p.z)
	if flat.length() > _bounds:
		flat = flat.normalized() * _bounds
	return Vector3(flat.x, p.y, flat.y)
