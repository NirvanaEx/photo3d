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
	var glassed := 0
	for mi in _meshes(self):
		if _transparent(mi):
			mi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
			off += 1
		elif _named_glass(mi):
			# Заплатка, и названа заплаткой. Настоящее лечение - в экспорте
			# локации: стекло должно уезжать в GLB с alphaMode=BLEND. Пока оно
			# приезжает OPAQUE, распознать его можно только по имени материала,
			# и это работает ровно до первого материала, названного иначе.
			mi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
			_make_glass(mi)
			glassed += 1
	# Вслух: молча изменившаяся сцена - худший вид «магии».
	if off > 0:
		print("[location] тень снята с прозрачных мешей: %d" % off)
	if glassed > 0:
		# Строка одной длинной, а не двумя рядом: GDScript не склеивает соседние
		# строковые литералы переносом, как это делает Python, - получается
		# Parse Error на всём файле.
		print("[location] ЗАПЛАТКА: стекло опознано по имени материала (%d шт.), в GLB оно приехало непрозрачным - чинить надо экспорт" % glassed)


func _named_glass(mi: MeshInstance3D) -> bool:
	var mesh: Mesh = mi.mesh
	if mesh == null:
		return false
	for s in mesh.get_surface_count():
		var m := mi.get_active_material(s)
		if m != null and "glass" in m.resource_name.to_lower():
			return true
	return false


func _make_glass(mi: MeshInstance3D) -> void:
	for s in mi.mesh.get_surface_count():
		var m := mi.get_active_material(s)
		if m is BaseMaterial3D:
			var g: BaseMaterial3D = m.duplicate()
			g.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
			g.albedo_color.a = 0.12
			g.roughness = 0.05
			mi.set_surface_override_material(s, g)


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
