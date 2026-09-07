extends SceneTree

var world: Node3D
var player: CharacterBody3D
var checks: Array[Dictionary] = []
var failed := false

func _initialize() -> void:
	call_deferred("_run")

func verify(name: String, condition: bool, detail: Variant = null) -> void:
	checks.append({"name":name,"passed":condition,"detail":detail})
	if not condition:
		failed = true
		push_error("SCHOOL CHECK FAILED: " + name + " " + str(detail))

func frames(count: int) -> void:
	for i in count: await physics_frame

func place(pos: Vector3) -> void:
	player.global_position = pos
	player.velocity = Vector3.ZERO
	player.debug_move = Vector2.ZERO
	player.debug_sprint = false
	await frames(12)

func go_to(target: Vector3, sprint := false, limit := 400) -> bool:
	player.debug_sprint = sprint
	var reached := false
	for i in range(limit):
		var difference := Vector2(target.x-player.global_position.x,target.z-player.global_position.z)
		if difference.length() < 0.10:
			reached = true
			break
		player.debug_move = difference.normalized()
		await physics_frame
	player.debug_move = Vector2.ZERO
	player.debug_sprint = false
	await frames(14)
	return reached

func use_door(id: String) -> void:
	var door: Node3D = world.doors[id]
	var target := door.global_position + door.global_basis * Vector3(0,1.15,-0.54)
	player.cam.look_at(target)
	await frames(2)
	player._update_look()
	verify(id+" targeted by view ray",player._looking == door)
	player._interact()
	await frames(90)
	verify(id+" opens via E interaction",door.is_open and door.opening_fraction()>.95,{"degrees":door.rotation_degrees.y,"blocked":door.blocked_count,"activations":door.activation_count})

func _run() -> void:
	world = load("res://scenes/classroom_v2.tscn").instantiate()
	root.add_child(world)
	player = world.get_node("Player")
	player.debug_drive = true
	await frames(35)
	verify("adult eye height",absf(player.cam.global_position.y-1.64)<.05,player.cam.global_position.y)
	verify("natural field of view",absf(player.cam.fov-56)<.05,player.cam.fov)
	verify("three physical doors",world.doors.size()==3)
	verify("all gait recordings loaded",player.audio_report().missing.is_empty(),player.audio_report().pools)
	await place(Vector3(2.15,.03,-.9))
	player.debug_move=Vector2(0,-1)
	await frames(100)
	verify("chair blocks player",player.global_position.z > -1.6 and player.is_on_floor(),player.global_position)
	await place(Vector3(-.1,.03,-.9))
	var start: Vector3 = player.global_position
	player.debug_move=Vector2(0,-1)
	await frames(180)
	var walked := start.distance_to(player.global_position)
	verify("walking covers human-scale distance",walked>4.1 and walked<5.1,walked)
	verify("wood detected automatically",player.footstep_surface=="wood")
	await place(Vector3(-.1,.03,-.9))
	start=player.global_position
	player.debug_sprint=true;player.debug_move=Vector2(0,-1)
	await frames(105)
	var ran := start.distance_to(player.global_position)
	verify("running faster with distinct gait",ran>5.3 and ran<6.6,ran)
	await place(Vector3(-.1,.03,-8.72))
	player.debug_move=Vector2(0,-1)
	await frames(25)
	var count: int = player.steps_played
	await frames(65)
	verify("no footsteps when blocked",player.steps_played==count)
	await place(Vector3(2.9,.03,-1.25))
	player.debug_move=Vector2(1,0)
	await frames(80)
	verify("closed class door blocks exit",player.global_position.x<3.65,player.global_position)
	player.debug_move=Vector2.ZERO
	await use_door("ClassDoor101")
	verify("walk through class doorway",await go_to(Vector3(5.6,0,-1.25)))
	verify("corridor floor and zone",player.footstep_surface=="tile" and world.zone_at(player.global_position)=="corridor",player.global_position)
	verify("corridor route to garden door",await go_to(Vector3(5.65,0,-10.1),true))
	await use_door("GardenDoor")
	verify("walk out into garden",await go_to(Vector3(5.65,0,-12.2)))
	await frames(110)
	var report: Dictionary = player.audio_report()
	verify("garden paving sounds",player.footstep_surface=="gravel",player.footstep_surface)
	verify("outdoor ambience and reduced echo",report.zone=="garden" and report.reverb_wet<.05 and report.nature_cutoff_hz>10000,report.reverb_wet)
	verify("walk on grass",await go_to(Vector3(3.6,0,-15.65)))
	verify("grass sounds automatic",player.footstep_surface=="grass",player.footstep_surface)
	player.debug_jump=true
	var base_y := player.global_position.y
	var high := base_y
	for i in 60:
		await physics_frame
		high=maxf(high,player.global_position.y)
	verify("jump and land",high-base_y>.30 and player.is_on_floor(),high-base_y)
	verify("return to garden doorway",await go_to(Vector3(5.65,0,-12.2),true))
	verify("enter open door threshold",await go_to(Vector3(5.65,0,-10.69)))
	var exit_door: Node3D=world.doors.GardenDoor
	exit_door.interact(player)
	await frames(120)
	verify("door does not close through player",exit_door.blocked_count>0 and exit_door.opening_fraction()>.6,{"blocked":exit_door.blocked_count,"fraction":exit_door.opening_fraction()})
	verify("return along corridor",await go_to(Vector3(5.65,0,-7.65),true))
	await use_door("ClassDoor101B")
	verify("re-enter classroom",await go_to(Vector3(2.9,0,-7.65)))
	verify("classroom acoustic zone restored",world.zone_at(player.global_position)=="classroom")
	world.doors.ClassDoor101B.interact(player)
	await frames(90)
	verify("door closes when doorway clear",not world.doors.ClassDoor101B.is_open and world.doors.ClassDoor101B.opening_fraction()<.01)
	var events: Array=player.audio_report().events
	var heard: Dictionary={}
	var landings:=0
	for event in events:
		heard[event.surface+"/"+event.gait]=true
		if event.landing:landings+=1
	verify("walk run and landing sounds exercised",heard.has("wood/walk") and heard.has("wood/run") and heard.has("tile/run") and heard.has("grass/walk") and landings>0,heard)
	var result: Dictionary={"passed":not failed,"checks":checks,"audio":player.audio_report()}
	var path: String=OS.get_cmdline_user_args()[0] if not OS.get_cmdline_user_args().is_empty() else "user://school_probe.json"
	var file:=FileAccess.open(path,FileAccess.WRITE);file.store_string(JSON.stringify(result,"  "));file.close()
	print("SCHOOL_PROBE "+JSON.stringify({"passed":not failed,"checks":checks.size(),"path":path}))
	world.queue_free()
	await frames(3)
	# Fixed-fps headless runs advance much faster than the native audio mixer.
	OS.delay_msec(120)
	await frames(3)
	quit(1 if failed else 0)
