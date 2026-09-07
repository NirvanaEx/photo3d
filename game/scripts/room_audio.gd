class_name RoomAudio
extends Node

# Звук помещения: постоянный фон и общая шина с ревербом.
#
# Полной тишины в комнате не бывает, и её отсутствие слышно сразу — сцена
# начинает казаться записью, поставленной на паузу. Фон стоит копейки и
# держит ощущение места лучше, чем любая деталь геометрии.
#
# Шина создаётся кодом, а не файлом раскладки (default_bus_layout.tres):
# ресурс двоичный по умолчанию и в текстовом виде правится плохо, а весь
# проект здесь намеренно правится текстом.

const BUS := "Room"

@export_file("*.wav") var ambience_path := "res://assets/audio/room_tone.wav"
# -22 дБ: фон должен быть на границе слышимости. Громче — и он превращается
# в гудение, которое замечают и от которого устают за минуту.
@export var ambience_db := -22.0
# Размер помещения для реверба. 0.5 — класс, 0.8 — коридор: там хвост длиннее
# и разборчивее, звук уходит вдоль стен.
@export_range(0.0, 1.0) var room_size := 0.5
@export_range(0.0, 1.0) var wet := 0.14

var _player: AudioStreamPlayer


static func ensure_bus(size: float, wet_mix: float) -> int:
	# Идемпотентно: сцена может перезапускаться, а шина с тем же именем,
	# добавленная второй раз, дала бы удвоенный реверб на всё сразу.
	var idx := AudioServer.get_bus_index(BUS)
	if idx != -1:
		return idx
	idx = AudioServer.bus_count
	AudioServer.add_bus(idx)
	AudioServer.set_bus_name(idx, BUS)
	AudioServer.set_bus_send(idx, "Master")

	var verb := AudioEffectReverb.new()
	verb.room_size = size
	verb.wet = wet_mix
	verb.dry = 1.0
	# Затухание высоких: голый реверб звенит жестью. У помещения с мебелью,
	# шторами и людьми верх съедается первым.
	verb.damping = 0.45
	verb.predelay_msec = 18.0
	AudioServer.add_bus_effect(idx, verb)
	return idx


func _ready() -> void:
	ensure_bus(room_size, wet)

	var stream: AudioStream = load(ambience_path)
	if stream == null:
		push_warning("[room_audio] нет фона %s — прогони scripts/make_sounds.py"
			% ambience_path)
		return
	# Петля обязана быть включена явно: импортёр Godot решает это сам по
	# длине и типу файла, и восьмисекундный фон он зацикливать не станет —
	# комната зазвучит один раз и замолчит навсегда.
	if stream is AudioStreamWAV:
		var wav := stream as AudioStreamWAV
		wav.loop_mode = AudioStreamWAV.LOOP_FORWARD
		wav.loop_begin = 0
		wav.loop_end = 0

	_player = AudioStreamPlayer.new()
	_player.stream = stream
	_player.volume_db = ambience_db
	_player.bus = BUS
	_player.autoplay = true
	add_child(_player)
	_player.play()
