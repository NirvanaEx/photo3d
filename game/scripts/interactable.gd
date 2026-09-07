class_name Interactable
extends Area3D

# Предмет, на который можно посмотреть и что-то узнать.
#
# Зона, а не меш, и вот почему. Локация приезжает из Blender ОДНИМ GLB: парты,
# доска и окна внутри него - части единой сетки, отдельными узлами их там нет.
# Луч, пущенный в такую комнату, всегда упирается в «локацию целиком», и по
# попаданию невозможно понять, во что именно смотрит человек.
#
# Зоны решают это тем, что расставляются в сцене руками - там, где предмет
# стоит. Разметка живёт в .tscn текстом, рядом со светом и пылью, и правится
# так же. Когда локация начнёт собираться из отдельных ассетов, зоны заменятся
# на сами предметы без единой правки здесь: игрок ищет узел по типу, а не по
# тому, меш это или объём.

## Как предмет называется в подсказке. Пусто - подсказки не будет вовсе.
@export var title := ""

## Что человек узнаёт, нажав клавишу. Пусто - предмет только называется.
@export_multiline var detail := ""

## Дальше этого расстояния подсказка не показывается, даже если луч дотянулся.
## Иначе доска подписывается через весь класс, и надпись висит постоянно.
@export var reach := 2.6

const FRAME_SHADER := "res://shaders/zone_frame.gdshader"
const OUTLINE_SHADER := "res://shaders/outline.gdshader"

var _marker: MeshInstance3D = null
var _outlined: Array[MeshInstance3D] = []


func _ready() -> void:
	# Если внутри зоны лежит собственная геометрия (отдельный ассет, как бюст
	# в коридоре) - обводим её саму: это точнее любой рамки. Если геометрии
	# нет, а есть только форма столкновений - строим каркас по её габаритам.
	_outlined = _meshes(self, [])
	if _outlined.is_empty():
		_build_frame()
	else:
		_build_outlines()
	highlight(false)


func _meshes(node: Node, acc: Array[MeshInstance3D]) -> Array[MeshInstance3D]:
	for c in node.get_children():
		if c is MeshInstance3D:
			acc.append(c)
		_meshes(c, acc)
	return acc


func _build_outlines() -> void:
	var shader: Shader = load(OUTLINE_SHADER)
	if shader == null:
		push_warning("[interactable] нет %s — обводки не будет" % OUTLINE_SHADER)
		return
	for mi in _outlined:
		var mat := ShaderMaterial.new()
		mat.shader = shader
		# next_pass, а не подмена материала: свой вид предмета должен
		# остаться, кайма лишь дорисовывается вторым проходом поверх.
		var base: Material = mi.get_active_material(0)
		if base != null:
			var copy := base.duplicate()
			copy.next_pass = mat
			mi.material_override = copy
		else:
			mi.material_overlay = mat


func _build_frame() -> void:
	var shape := _box_shape()
	if shape == null:
		return
	var shader: Shader = load(FRAME_SHADER)
	if shader == null:
		push_warning("[interactable] нет %s — рамки не будет" % FRAME_SHADER)
		return
	var mesh := BoxMesh.new()
	# Чуть больше самой зоны: рамка вплотную к парте наполовину тонет в её
	# столешнице и читается обрывками.
	mesh.size = shape.size * 1.04
	var mat := ShaderMaterial.new()
	mat.shader = shader
	mesh.material = mat

	_marker = MeshInstance3D.new()
	_marker.mesh = mesh
	# Рамка — подсказка интерфейса, а не часть мира: она не должна ни
	# отбрасывать тень, ни попадать в расчёт глобального освещения, иначе
	# SDFGI подсветит ею потолок.
	_marker.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	_marker.gi_mode = GeometryInstance3D.GI_MODE_DISABLED
	add_child(_marker)


func _box_shape() -> BoxShape3D:
	for c in get_children():
		if c is CollisionShape3D and (c as CollisionShape3D).shape is BoxShape3D:
			return (c as CollisionShape3D).shape as BoxShape3D
	return null


func highlight(on: bool) -> void:
	if _marker != null:
		_marker.visible = on
	for mi in _outlined:
		var mat: Material = mi.material_override
		if mat != null and mat.next_pass is ShaderMaterial:
			# Толщина в ноль вместо снятия прохода: пересобирать материал на
			# каждый взгляд дороже, чем менять одно число.
			(mat.next_pass as ShaderMaterial).set_shader_parameter(
				"width", 0.012 if on else 0.0)
		elif mi.material_overlay is ShaderMaterial:
			(mi.material_overlay as ShaderMaterial).set_shader_parameter(
				"width", 0.012 if on else 0.0)


func label() -> String:
	return title


func look_text() -> String:
	# Подсказка про клавишу появляется только когда есть что рассказать:
	# обещать нажатие и ничего не показать - хуже, чем промолчать.
	return title if detail.is_empty() else "%s · [E] осмотреть" % title
