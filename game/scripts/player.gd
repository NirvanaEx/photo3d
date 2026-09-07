extends CharacterBody3D

# Ходьба от первого лица. Числа те же, что в веб-прогулке (web/static/walk.js),
# и это не лень, а требование: одна и та же локация должна ощущаться одинаково
# в браузерном просмотре и в игре, иначе один из двух режимов врёт.
#
# Столкновений здесь НЕТ ни строчки: тело даёт CharacterBody3D, оболочку -
# сам ассет (меш с суффиксом -colonly, из которого импортёр Godot делает
# StaticBody3D). Своя физика была бы ровно тем случаем, о котором
# предупреждает CLAUDE.md.

# Было 4.2 м/с. Это не ходьба, а бег: у человека спокойный шаг 1.4 м/с,
# быстрый - около 2. На 4.2 походка физически честной уже не бывает - шаг
# растягивается до полутора метров, и звук читается как топот вне зависимости
# от того, какие взяты сэмплы. Замер: 13 метров коридора проходились за 6.5 с
# при девяти шагах, то есть по 1.46 м на шаг - поступь бегуна.
#
# 2.6 - верх быстрой ходьбы. Бег остался под Shift, там множитель.
# Вернуть прежнюю прыть: поставить обратно 4.2.
const SPEED := 2.6          # м/с, предельная скорость шага
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

# Поверхность задаётся сценой, а не определяется под ногами. Определять было
# бы честнее, но материал через столкновения не достать: тело приезжает из
# GLB одним StaticBody3D на всю локацию, и какой меш под ногой - физика уже
# не знает. У класса пол один, у коридора один, и пока это так, параметр
# сцены даёт тот же результат без единой проверки в кадре.
#
# Имена совпадают с папками в assets/audio/steps/ - это записи, не синтез
# (см. assets/audio/CREDITS.md, лицензия CC-BY требует упоминания авторов).
@export_enum("wood", "tile", "boots", "grass", "gravel", "metal", "water")
var footstep_surface := "wood"

# Через сколько метров пути - следующий шаг. 0.78 - длина шага взрослого при
# спокойной ходьбе; на глаз подбирать это нельзя, звук сразу разъезжается с
# движением и читается как чужой.
const STEP_DISTANCE := 0.85

# Но одного расстояния мало. SPEED здесь 4.2 м/с - это скорость бега, а не
# ходьбы (у человека около 1.4), и честный пересчёт даёт 5.4 шага в секунду:
# сплошная дробь, которую слышно как стук, а не как походку. Игровая скорость
# завышена намеренно ради отзывчивости, поэтому частоту шагов приходится
# ограничивать отдельно - по времени.
#
# 0.34 с ≈ 3 шага в секунду: верх нормального темпа быстрой ходьбы. При беге
# по Shift разрешаем чаще, но не намного.
const STEP_MIN_INTERVAL := 0.34
const STEP_MIN_INTERVAL_SPRINT := 0.26

@onready var cam: Camera3D = $Camera
@onready var hint: Label = get_node_or_null("../HUD/Hint")
@onready var look_label: Label = get_node_or_null("../HUD/Look")
@onready var detail_label: Label = get_node_or_null("../HUD/Detail")

var _ray: RayCast3D
var _looking: Interactable = null

# Поверхности для перебора клавишей F. Порядок от самой вероятной для
# помещения к самой дальней: подбирается на слух, а слух есть только у
# человека - отсюда и клавиша вместо параметра в файле.
const SURFACES := ["wood", "tile", "boots", "metal", "gravel", "grass", "water"]

# ПОПЫТКА, КОТОРАЯ НЕ СРАБОТАЛА, и это записано, чтобы её не повторяли.
#
# Рассуждение было такое: записи в наборе длятся 135 мс (плитка, ботинки) и
# 287 мс (дерево) - это удар, а не шаг; настоящий шаг длится 300-400 мс и
# состоит из двух фаз, пятка и перекат на носок. Отсюда родилась вторая фаза
# через 75-115 мс, тише и выше по тону.
#
# На слух вышло хуже исходного: слышны ДВА отдельных звука, а не один шаг.
# Причина в том, что перекат - не второй удар, а продолжение того же контакта,
# с общим затуханием; двумя срабатываниями одного сэмпла это не собирается,
# нужна запись, где обе фазы уже есть. Разбирать шаг на части имеет смысл,
# только если части записаны как части.
var _steps: Array[AudioStream] = []
var _step_audio: AudioStreamPlayer
var _walked := 0.0
var _was_on_floor := true
var _since_step := 0.0
var _last_sample := -1
# Счётчик для проверки из walk_probe: беззвучную ходьбу на слух не отличить
# от ходьбы с ненастроенным аудиодрайвером, а в --headless слушать некому.
var steps_played := 0
var _frames := 0
var _frames_on_floor := 0


func _ready() -> void:
	cam.position.y = EYE
	_setup_audio()
	_setup_ray()
	# Мышь НЕ захватывается на старте. Захват без спроса выглядит как зависание
	# машины: курсор исчезает, окно может быть даже не в фокусе, и человек не
	# понимает, что произошло. В вебе это уже решено приглашением «кликни,
	# чтобы взять управление» - здесь то же самое.
	_show_hint(true)


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
			_show_hint(true)
		else:
			get_tree().quit()
	elif event is InputEventKey and event.pressed \
			and event.physical_keycode == KEY_E:
		_interact()
	elif event is InputEventKey and event.pressed \
			and event.physical_keycode == KEY_F:
		_cycle_surface()
	elif event is InputEventMouseButton and event.pressed:
		Input.mouse_mode = Input.MOUSE_MODE_CAPTURED
		_show_hint(false)


func _show_hint(on: bool) -> void:
	if hint != null:
		hint.visible = on


func _setup_audio() -> void:
	# Шаги — НЕ AudioStreamPlayer3D: источник находится там же, где уши, и
	# позиционировать его не в чем. Трёхмерный игрок слышал бы собственные
	# шаги затухающими, потому что затухание считается от точки к камере, а
	# расстояние тут всегда нулевое.
	_step_audio = AudioStreamPlayer.new()
	# Шаги идут через ту же шину, что и фон: иначе они звучат снаружи
	# помещения, сухими, а комната вокруг — с эхом. Шину заводим сами, а не
	# ждём узел RoomAudio: порядок _ready между соседями по сцене не
	# гарантирован, а функция идемпотентна и второй раз ничего не создаст.
	RoomAudio.ensure_bus(0.5, 0.19)
	_step_audio.bus = RoomAudio.BUS
	add_child(_step_audio)
	_load_steps()


func _load_steps() -> void:
	# Файлы перебираются по папке, а не по жёсткому списку имён: в наборе их
	# то восемь, то десять на поверхность, и «от 1 до 4» молча отбрасывало бы
	# половину вариантов — а именно на разнообразии держится вся правдоподобность.
	var dir_path := "res://assets/audio/steps/%s" % footstep_surface
	var dir := DirAccess.open(dir_path)
	if dir == null:
		push_warning("[player] нет папки %s — ходьба будет беззвучной. "
			% dir_path + "Звуки шагов лежат в assets/audio/steps/<поверхность>/")
		return
	# Через словарь, а не списком: в проекте-исходнике рядом с 0.ogg лежит
	# 0.ogg.import, и оба после отсечения суффикса дают одно имя. Списком
	# каждый звук попадал бы в набор дважды - в редакторе 18 штук вместо 9, а
	# в экспортированной игре, где .import уже свёрнут, честные 9. Разное
	# поведение там и там - худший вид такой ошибки: на глаз не заметно.
	var unique := {}
	for file in dir.get_files():
		var name := file.trim_suffix(".import")
		if name.ends_with(".ogg") or name.ends_with(".wav"):
			unique[name] = true
	for file in unique:
		var s: AudioStream = load(dir_path + "/" + file)
		if s == null:
			continue
		# Зацикливание бывает включено импортёром по умолчанию; шаг,
		# повторяющийся вечно, - самый заметный вид этой ошибки.
		if s is AudioStreamOggVorbis:
			(s as AudioStreamOggVorbis).loop = false
		elif s is AudioStreamWAV:
			(s as AudioStreamWAV).loop_mode = AudioStreamWAV.LOOP_DISABLED
		_steps.append(s)
	if _steps.is_empty():
		push_warning("[player] в %s нет ни одного звука, ходьба беззвучна" % dir_path)


func _cycle_surface() -> void:
	# Перебор поверхностей прямо в игре. Нужен потому, что «подходит ли этот
	# шаг паркету» - вопрос к уху, а не к числам: спектр и длительность у
	# дерева и плитки различаются предсказуемо, а вот какой из них звучит
	# правдоподобнее В ЭТОЙ комнате, слышно только на месте.
	#
	# Выбранное надо перенести в .tscn руками (footstep_surface у Player) -
	# писать в сцену из игры нельзя: она открыта на чтение, и правка потерялась
	# бы при выходе, оставив ощущение, что настройка сохранилась.
	var i := SURFACES.find(footstep_surface)
	footstep_surface = SURFACES[(i + 1) % SURFACES.size()]
	_steps.clear()
	_load_steps()
	_footstep()          # сразу дать услышать, а не ждать следующего шага
	if detail_label != null:
		detail_label.text = "поверхность: %s (%d звуков) · F — следующая\nвыбрал — впиши footstep_surface = \"%s\" в сцену" \
			% [footstep_surface, _steps.size(), footstep_surface]


func _footstep(volume_db := 0.0) -> void:
	if _steps.is_empty():
		return

	# Не тот же сэмпл, что в прошлый раз. Случайный выбор из девяти повторяет
	# предыдущий примерно каждый девятый шаг, и повтор подряд слышен резко -
	# именно он читается как «зациклено» посреди живой в остальном ходьбы.
	var i := randi() % _steps.size()
	if _steps.size() > 1 and i == _last_sample:
		i = (i + 1) % _steps.size()
	_last_sample = i
	_step_audio.stream = _steps[i]

	# Разброс высоты был 0.92…1.08 - восемь процентов в обе стороны. На записи
	# настоящего шага это слышно как гуляющий тон: сэмплы и так отличаются друг
	# от друга, и добавленный разброс складывался с их собственным в хаос.
	# Синтезированным он был нужен, записанным - вреден.
	var pitch := randf_range(0.97, 1.04)
	_step_audio.pitch_scale = pitch
	# База -9 дБ. На нуле шаг равен по громкости всему остальному в сцене, и
	# собственная походка звучит как удары рядом с ухом.
	_step_audio.volume_db = volume_db - 9.0 + randf_range(-1.5, 0.5)
	_step_audio.play()
	steps_played += 1


func _setup_ray() -> void:
	_ray = RayCast3D.new()
	# Длина луча — с запасом над самым дальним reach: отсечка по расстоянию
	# делается ниже, у конкретного предмета, а не общей длиной. Так у доски
	# может быть свой радиус, а у мелочи на парте — свой.
	_ray.target_position = Vector3(0, 0, -6)
	# Ловим И зоны, И тела. Тела не для того, чтобы на них реагировать, а
	# наоборот: стена, оказавшаяся ближе зоны, должна перекрыть подсказку.
	# Иначе доска подписывается сквозь простенок.
	_ray.collide_with_areas = true
	_ray.collide_with_bodies = true
	# Себя не ловим: капсула игрока начинается там же, где камера.
	_ray.add_exception(self)
	cam.add_child(_ray)


func _update_look() -> void:
	var found: Interactable = null
	if _ray != null and _ray.is_colliding():
		var hit := _ray.get_collider()
		if hit is Interactable:
			var item := hit as Interactable
			# Расстояние меряется до точки попадания, а не до центра зоны:
			# у длинной парты центр может быть втрое дальше её края.
			if cam.global_position.distance_to(_ray.get_collision_point()) <= item.reach:
				found = item

	if found == _looking:
		return
	# Гасим прежнюю ДО того, как запомнили новую: иначе при переходе взгляда
	# с парты на доску подсвеченными окажутся обе.
	if _looking != null:
		_looking.highlight(false)
	if found != null:
		found.highlight(true)
	_looking = found
	if look_label != null:
		look_label.text = "" if found == null else found.look_text()
	# Рассказ гаснет, как только человек отвёл взгляд: иначе он висит поверх
	# следующего предмета и читается как подпись к нему.
	if detail_label != null:
		detail_label.text = ""


func _interact() -> void:
	if _looking == null or detail_label == null:
		return
	detail_label.text = _looking.detail


func audio_report() -> Dictionary:
	# Имена файлов, а не только их число: «звучит не то» проверяется именно
	# так. Счётчик показал бы девять и при девяти неправильных звуках.
	var paths: Array = []
	for s in _steps:
		paths.append(s.resource_path)
	return {
		"samples": _steps.size(),
		"surface": footstep_surface,
		"steps_played": steps_played,
		"bus": AudioServer.get_bus_index(RoomAudio.BUS),
		"files": paths,
		# Доля кадров на опоре. Шаги считаются только стоя на полу, и если
		# капсула дребезжит на стыках геометрии, путь просто не накапливается -
		# походка выходит вдвое реже задуманной без всякой ошибки в формуле.
		"frames": _frames,
		"frames_on_floor": _frames_on_floor,
	}


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
	_tick_footsteps(delta)
	_update_look()


func _tick_footsteps(delta: float) -> void:
	# Приземление после прыжка звучит всегда и громче обычного: тишина в этот
	# момент - первое, обо что спотыкается ощущение веса.
	var on_floor := is_on_floor()
	_frames += 1
	if on_floor:
		_frames_on_floor += 1
	if on_floor and not _was_on_floor:
		_footstep(2.0)
		_walked = 0.0
	_was_on_floor = on_floor
	if not on_floor:
		return

	# Считаем ГОРИЗОНТАЛЬНЫЙ путь, а не время: упёршись в стену, шаги должны
	# смолкать, хотя клавиша зажата и скорость по вектору не нулевая.
	var moved := Vector2(velocity.x, velocity.z).length() * delta
	_since_step += delta
	if moved < 0.001:
		return
	# Потолок накопления - полтора шага. Пока ждём разрешения по времени, путь
	# продолжает копиться, и без ограничения после паузы выстреливала бы
	# очередь «долгов». Полтора, а не ровно один: небольшой запас сохраняет
	# ритм на неровной скорости, когда игрок то упирается, то освобождается.
	_walked = minf(_walked + moved, STEP_DISTANCE * 1.5)
	if _walked < STEP_DISTANCE:
		return

	# Оба условия сразу: пройденный путь И прошедшее время. По одному пути на
	# игровой скорости выходила дробь; по одному времени шаги звучали бы и на
	# месте, стоило чуть покачнуться.
	var floor_gap := STEP_MIN_INTERVAL_SPRINT if \
		Input.is_physical_key_pressed(KEY_SHIFT) else STEP_MIN_INTERVAL
	if _since_step < floor_gap:
		return
	# Вычитаем, а не обнуляем: при обнулении терялся остаток пути, и замер
	# показывал шаг раз в 1.46 м вместо заданных 0.85 - походка выходила
	# вдвое реже задуманной.
	_walked -= STEP_DISTANCE
	_since_step = 0.0
	_footstep()


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
