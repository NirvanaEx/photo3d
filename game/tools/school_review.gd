extends SceneTree

func _initialize() -> void:
	call_deferred("_run")

func _run() -> void:
	var out: String = OS.get_cmdline_user_args()[0]
	var world: Node3D = load("res://scenes/classroom_v2.tscn").instantiate()
	root.add_child(world)
	var player: CharacterBody3D = world.get_node("Player")
	player.set_physics_process(false)
	player.set_process(false)
	player.collision_layer = 0
	world.get_node("HUD").visible = false
	var cam: Camera3D = player.get_node("Camera")
	cam.current = true
	cam.fov = 56
	var poses := [
		["school_game_classroom",Vector3(2.9,1.64,-.8),Vector3(-.55,1.35,-7.5)],
		["school_game_corridor",Vector3(4.8,1.64,-.05),Vector3(5.8,1.5,-10.5)],
		["school_game_garden",Vector3(4.0,1.64,-14.8),Vector3(-7.0,1.9,-17.0)],
		["school_game_doorway",Vector3(2.7,1.64,-1.25),Vector3(6.4,1.40,-2.0)]
	]
	var report := {}
	for pose in poses:
		if pose[0] == "school_game_doorway": world.doors.ClassDoor101.interact(player)
		player.global_position = pose[1]-Vector3.UP*1.64
		cam.position = Vector3.UP*1.64
		cam.look_at(pose[2])
		for frame in range(150): await process_frame
		await RenderingServer.frame_post_draw
		var img := root.get_texture().get_image()
		var target: String = out.path_join(pose[0]+".png")
		if img.save_png(target) != OK: quit(1);return
		report[pose[0]] = {"image":target,"fps":Engine.get_frames_per_second(),"draw_calls":Performance.get_monitor(Performance.RENDER_TOTAL_DRAW_CALLS_IN_FRAME),"primitives":Performance.get_monitor(Performance.RENDER_TOTAL_PRIMITIVES_IN_FRAME)}
	var file := FileAccess.open(out.path_join("school_game_review.json"),FileAccess.WRITE)
	file.store_string(JSON.stringify(report,"  "));file.close()
	print("SCHOOL_REVIEW "+JSON.stringify(report))
	world.queue_free()
	await create_timer(.3).timeout
	quit()
