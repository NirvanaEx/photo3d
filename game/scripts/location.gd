extends Node3D

# Стекло не должно отбрасывать тень.
#
# Симптом был такой: солнце направлено в окна, а внутри темно, будто окон нет
# вовсе. Замер: с тенями разброс яркости кадра 0.459, без теней - 0.979.
# То есть свет в помещение попадает, но всё внутри стоит в тени - потому что
# оконные стёкла для теневой карты остаются обычной геометрией и работают как
# заложенные проёмы.
#
# В glTF признака «не отбрасывать тень» нет, поэтому проставляется он здесь, в
# сцене: формат довезти это не может, а решение принадлежит уровню.

func _ready() -> void:
	var off := 0
	for mi in _meshes(self):
		if _transparent(mi):
			mi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
			off += 1
	if off > 0:
		# Вслух: молча изменившаяся сцена - худший вид «магии».
		print("[location] тень снята с прозрачных мешей: %d" % off)


func _transparent(mi: MeshInstance3D) -> bool:
	var mesh: Mesh = mi.mesh
	if mesh == null:
		return false
	for s in mesh.get_surface_count():
		var m := mi.get_active_material(s)
		if m is BaseMaterial3D:
			if m.transparency != BaseMaterial3D.TRANSPARENCY_DISABLED:
				return true
			if m.albedo_color.a < 0.99:
				return true
	return false


func _meshes(node: Node, acc: Array = []) -> Array:
	if node is MeshInstance3D:
		acc.append(node)
	for c in node.get_children():
		_meshes(c, acc)
	return acc
