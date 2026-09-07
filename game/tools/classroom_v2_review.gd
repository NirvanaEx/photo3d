extends SceneTree

# Fixed interior camera positions are needed because this location includes
# a courtyard: a camera fitted to the total mesh bounds would be outdoors.
func _initialize() -> void:
	call_deferred("_run")

func _run() -> void:
	var args := OS.get_cmdline_user_args()
	if args.is_empty():
		push_error("Pass an output directory after --")
		quit(1)
		return
	var out: String = args[0]
	DirAccess.make_dir_recursive_absolute(out)
	var world: Node3D = load("res://scenes/classroom_v2.tscn").instantiate()
	root.add_child(world)
	var player := world.get_node("Player") as CharacterBody3D
	player.set_physics_process(false)
	player.set_process(false)
	world.get_node("HUD").visible = false
	var cam := player.get_node("Camera") as Camera3D
	cam.current = true
	cam.fov = 50.0
	var poses := [
		["game_hero", Vector3(2.86, 1.65, -0.79), Vector3(-0.58, 1.22, -7.5)],
		["game_detail", Vector3(-1.55, 1.21, -1.06), Vector3(-2.51, 0.92, -3.1)],
		["game_reverse", Vector3(0.1, 1.65, -7.1), Vector3(-0.8, 1.15, -0.5)]
	]
	var report := {}
	for pose in poses:
		cam.global_position = pose[1]
		cam.look_at(pose[2])
		for frame in range(120):
			await process_frame
		await RenderingServer.frame_post_draw
		var img := root.get_texture().get_image()
		var target: String = out.path_join(pose[0] + ".png")
		var error := img.save_png(target)
		if error != OK:
			push_error("Could not save review image: " + target)
			quit(1)
			return
		report[pose[0]] = {"image": target, "fps": Engine.get_frames_per_second(),
			"draw_calls": Performance.get_monitor(Performance.RENDER_TOTAL_DRAW_CALLS_IN_FRAME),
			"primitives": Performance.get_monitor(Performance.RENDER_TOTAL_PRIMITIVES_IN_FRAME)}
	var file := FileAccess.open(out.path_join("game_review.json"), FileAccess.WRITE)
	file.store_string(JSON.stringify(report, "  "))
	print("CLASSROOM_V2_REVIEW " + JSON.stringify(report))
	quit()
