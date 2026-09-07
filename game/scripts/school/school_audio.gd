extends Node

const BASE := "res://assets/audio/school/"
const FOLEY_BUS := "SchoolFoley"
const NATURE_BUS := "SchoolNature"
var _pools := {}
var _last := {}
var _players: Array[AudioStreamPlayer] = []
var _voice := 0
var _verb: AudioEffectReverb
var _filter: AudioEffectLowPassFilter
var _birds: AudioStreamPlayer
var _room: AudioStreamPlayer
var _elapsed := 0.0
var _events: Array[Dictionary] = []
var current_zone := "classroom"
var _missing: Array[String] = []

func _exit_tree() -> void:
	for voice in _players + [_birds,_room]:
		if is_instance_valid(voice):
			voice.stop()
			voice.stream = null
	_pools.clear()

func _bus(name: String) -> int:
	var index := AudioServer.get_bus_index(name)
	if index < 0:
		index = AudioServer.bus_count
		AudioServer.add_bus(index)
		AudioServer.set_bus_name(index, name)
		AudioServer.set_bus_send(index, "Master")
	return index

func _ready() -> void:
	var foley := _bus(FOLEY_BUS)
	if AudioServer.get_bus_effect_count(foley) == 0:
		AudioServer.add_bus_effect(foley, AudioEffectReverb.new())
	_verb = AudioServer.get_bus_effect(foley, 0) as AudioEffectReverb
	_verb.room_size = 0.45
	_verb.wet = 0.12
	_verb.dry = 1
	_verb.damping = 0.64
	_verb.predelay_msec = 14
	var nature := _bus(NATURE_BUS)
	if AudioServer.get_bus_effect_count(nature) == 0:
		AudioServer.add_bus_effect(nature, AudioEffectLowPassFilter.new())
	_filter = AudioServer.get_bus_effect(nature, 0) as AudioEffectLowPassFilter
	_filter.cutoff_hz = 2200
	for surface in ["wood", "tile", "grass", "gravel"]:
		for gait in ["walk", "run"]:
			var key: String = surface + "/" + gait
			var clips: Array[AudioStream] = []
			var path: String = BASE + "steps/" + key
			var dir := DirAccess.open(path)
			if dir != null:
				var seen := {}
				for filename in dir.get_files():
					var file: String = filename.trim_suffix(".import").trim_suffix(".remap")
					if not file.ends_with(".ogg") or seen.has(file): continue
					seen[file] = true
					var stream: AudioStream = load(path.path_join(file))
					if stream != null:
						(stream as AudioStreamOggVorbis).loop = false
						clips.append(stream)
			if clips.is_empty():
				_missing.append(key)
				push_error("No school footsteps: " + path + ". Run scripts/build_school_audio.py")
			_pools[key] = clips
	for i in range(6):
		var player := AudioStreamPlayer.new()
		player.bus = FOLEY_BUS
		add_child(player)
		_players.append(player)
	_birds = _loop("garden.ogg", NATURE_BUS, -34)
	_room = _loop("room.ogg", FOLEY_BUS, -27)

func _loop(file: String, bus: String, db: float) -> AudioStreamPlayer:
	var player := AudioStreamPlayer.new()
	var stream := load(BASE + file) as AudioStreamOggVorbis
	if stream != null:
		stream.loop = true
		player.stream = stream
	player.bus = bus
	player.volume_db = db
	add_child(player)
	player.play()
	return player

func play_step(surface: String, gait: String, landing := false, extra_db := 0.0) -> void:
	var key := surface + "/" + gait
	var clips: Array = _pools.get(key, [])
	if clips.is_empty(): return
	var pick := randi_range(0, clips.size()-1)
	if clips.size() > 1 and pick == int(_last.get(key, -1)): pick = (pick+1) % clips.size()
	_last[key] = pick
	var player := _players[_voice]
	_voice = (_voice+1) % _players.size()
	player.stream = clips[pick]
	player.pitch_scale = randf_range(0.985, 1.018) * (0.92 if landing else 1.0)
	player.volume_db = (-8.0 if gait == "run" else -12.0) + (3.0 if landing else 0.0) + extra_db + randf_range(-0.7,0.3)
	player.play()
	_events.append({"time":snappedf(_elapsed,0.001),"surface":surface,"gait":gait,"landing":landing,"sample":pick,"zone":current_zone})
	if _events.size() > 256: _events.pop_front()

func _process(delta: float) -> void:
	_elapsed += delta
	var player: Node3D = get_node_or_null("../Player")
	if player == null: return
	current_zone = get_parent().zone_at(player.global_position)
	var outdoors := current_zone == "garden"
	var hallway := current_zone == "corridor"
	var door_open: bool = get_parent().garden_door_open()
	var blend := 1.0-exp(-delta*2.0)
	_verb.wet = lerpf(_verb.wet, 0.012 if outdoors else (0.27 if hallway else 0.12), blend)
	_verb.room_size = lerpf(_verb.room_size, 0.12 if outdoors else (0.79 if hallway else 0.46), blend)
	_filter.cutoff_hz = lerpf(_filter.cutoff_hz, 12500.0 if outdoors else (5300.0 if hallway and door_open else 2300.0), blend)
	_birds.volume_db = lerpf(_birds.volume_db, -17.0 if outdoors else (-26.0 if hallway and door_open else -35.0), blend)
	_room.volume_db = lerpf(_room.volume_db, -65.0 if outdoors else (-27.0 if hallway else -30.0), blend)

func report() -> Dictionary:
	var counts := {}
	for key in _pools: counts[key] = _pools[key].size()
	return {"pools":counts,"missing":_missing,"events":_events,"zone":current_zone,"reverb_wet":_verb.wet,"nature_cutoff_hz":_filter.cutoff_hz,"birds_playing":_birds.playing,"room_playing":_room.playing}
