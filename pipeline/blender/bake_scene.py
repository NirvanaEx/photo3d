"""Запекание процедурных материалов сцены в текстуры — внутри Blender, не в venv.

    blender -b СЦЕНА.blend --factory-startup -noaudio \
        -P bake_scene.py -- --out СЦЕНА_baked.blend [--px-per-m 256] [--max-px 2048]

Зачем. glTF знает только Principled BSDF с константами и картинками, а доски
пола и штукатурка коридора нарисованы шумами прямо в шейдере. Экспортёр их не
сворачивает в цвет, а выбрасывает: в `m_corridor/model.glb` восемь материалов
из одиннадцати уехали вообще без `baseColorFactor`, то есть белыми. Запекание
переводит шум в картинку, после чего вид в прогулке совпадает с рендером.

Чем отличается от `bake.py`: тот переносит внешний вид С ОДНОЙ модели НА
ДРУГУЮ (запекание «выделенное на активное» после ретопологии). Здесь сетка
остаётся своей, переводится сам материал — задача другая, и общего кода у них
только настройка Cycles.

Устройство, и каждый пункт стоил бы отладки, если сделать иначе:

  * **развёртка строится на материал, а не на объект.** Материал у нескольких
    объектов общий — если каждый развернуть в свои 0..1, они запекутся друг
    поверх друга в одну картинку. Поэтому в правку берутся все объекты с этим
    материалом сразу, и Smart UV Project раскладывает их в общий атлас;

  * **разрешение считается от площади.** Пол 40 м² и дверная ручка в ладонь
    не заслуживают одинаковых 2048²: у первого не хватит текселей на волокно,
    у второй мегабайты уйдут в пустоту. Пиксели на метр задаются одним числом;

  * **узел-приёмник во время запекания не подключён к шейдеру.** Подключённый
    даёт обратную связь: Cycles читает Base Color, там пустая картинка, и
    запекается пустота в пустоту. Провода перекидываются ПОСЛЕ запекания;

  * **объёмные материалы пропускаются.** У дымки коридора нет поверхности
    вовсе (Volume Scatter в Material Output), запекать там нечего;

  * **результат проверяется по разбросу пикселей.** `bpy.ops.object.bake`
    возвращает FINISHED и запекая ровную пустоту — это общее правило проекта
    для операторов Blender.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys

import bmesh
import bpy

# Пиксели на метр поверхности. 256 -> 4 мм на тексель: волокно доски и потёки
# штукатурки читаются, а атлас пола укладывается в 2048².
PX_PER_M = 256
MIN_PX = 128
MAX_PX = 2048

# Входы Principled BSDF, которые умеет запекать Cycles. Metallic в списке нет:
# отдельного прохода под него не существует, и если он окажется процедурным —
# скажем об этом вслух, а не подсунем молча константу.
BAKEABLE = {
    "Base Color": ("DIFFUSE", "sRGB"),
    "Roughness": ("ROUGHNESS", "Non-Color"),
    # Рельеф. Раньше его не было вовсе, и все поверхности уезжали в игру
    # геометрически идеально плоскими - при скользящем солнце это половина
    # картинки: доски пола, потёки штукатурки, вмятины на металле.
    # Bump в glTF не существует, а карта нормалей - существует, и запекание
    # переводит одно в другое.
    "Normal": ("NORMAL", "Non-Color"),
}


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True, help="куда сохранить .blend с текстурами")
    p.add_argument("--px-per-m", type=int, default=PX_PER_M)
    p.add_argument("--max-px", type=int, default=MAX_PX)
    return p.parse_args(argv)


# --------------------------------------------------------------------------- #
# Разбор материала
# --------------------------------------------------------------------------- #

def surface_bsdf(mat):
    """Principled BSDF, подключённый к выходу материала. None у объёмных."""
    if not mat or not mat.use_nodes:
        return None
    out = next((n for n in mat.node_tree.nodes if n.type == "OUTPUT_MATERIAL"), None)
    if out is None or not out.inputs["Surface"].is_linked:
        return None
    node = out.inputs["Surface"].links[0].from_node
    return node if node.type == "BSDF_PRINCIPLED" else None


def linked_inputs(bsdf):
    """Какие запекаемые входы заданы узлами, а не числом."""
    return [name for name in BAKEABLE
            if bsdf.inputs[name].is_linked]


def pow2_clamped(value, lo, hi):
    px = 1 << max(0, int(value - 1)).bit_length()
    return max(lo, min(hi, px))


# --------------------------------------------------------------------------- #
# Площадь и развёртка
# --------------------------------------------------------------------------- #

def material_faces(obj, mat):
    """Индексы граней объекта, которым назначен этот материал."""
    slots = [i for i, s in enumerate(obj.material_slots) if s.material == mat]
    if not slots:
        return []
    if len(obj.material_slots) == 1:
        return list(range(len(obj.data.polygons)))
    return [p.index for p in obj.data.polygons if p.material_index in slots]


def world_area(obj, face_indices):
    """Площадь граней в метрах: считается по мировым координатам.

    Через `polygon.area` считать нельзя — она в локальных единицах и врёт на
    любом объекте с масштабом.
    """
    m = obj.matrix_world
    total = 0.0
    me = obj.data
    for i in face_indices:
        poly = me.polygons[i]
        verts = [m @ me.vertices[v].co for v in poly.vertices]
        for a, b in zip(verts[1:-1], verts[2:]):
            total += (b - verts[0]).cross(a - verts[0]).length / 2
    return total


def unwrap_material(objs_faces, margin=0.004):
    """Общая развёртка для всех объектов одного материала.

    Правка ведётся сразу над всеми объектами (multi-object edit) — только так
    Smart UV Project раскладывает их в один атлас, а не каждого в свои 0..1.
    """
    bpy.ops.object.select_all(action="DESELECT")
    for obj, _ in objs_faces:
        if not obj.data.uv_layers:
            obj.data.uv_layers.new(name="bake")
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objs_faces[0][0]

    bpy.context.scene.tool_settings.mesh_select_mode = (False, False, True)
    bpy.ops.object.mode_set(mode="EDIT")
    for obj, faces in objs_faces:
        bm = bmesh.from_edit_mesh(obj.data)
        wanted = set(faces)
        for f in bm.faces:
            f.select_set(f.index in wanted)
        bmesh.update_edit_mesh(obj.data)
    bpy.ops.uv.smart_project(angle_limit=1.15, island_margin=margin)
    bpy.ops.object.mode_set(mode="OBJECT")


# --------------------------------------------------------------------------- #
# Запекание
# --------------------------------------------------------------------------- #

def setup_cycles_gpu():
    """Тот же подбор устройства, что в bake.py: OPTIX, иначе CUDA, иначе CPU."""
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 8          # цвет и шероховатость — не свет, хватит
    scene.cycles.use_denoising = False
    device = "CPU"
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        for backend in ("OPTIX", "CUDA"):
            try:
                prefs.compute_device_type = backend
            except TypeError:
                continue
            try:
                prefs.get_devices()
            except AttributeError:
                pass
            gpus = [d for d in prefs.devices if d.type == backend]
            if gpus:
                for d in prefs.devices:
                    d.use = (d.type == backend)
                scene.cycles.device = "GPU"
                device = f"{backend}/{gpus[0].name}"
                break
    except Exception as exc:  # noqa: BLE001
        print("BAKE_GPU_FAIL", exc)
    return device


def target_node(mat):
    """Узел-приёмник запекания. Один на материал, создаётся один раз."""
    nt = mat.node_tree
    node = next((n for n in nt.nodes if n.label == "bake-target"), None)
    if node is None:
        node = nt.nodes.new("ShaderNodeTexImage")
        node.label = "bake-target"
        node.location = (400, 400)
    nt.nodes.active = node
    return node


def spread_of(img):
    """Разброс пикселей: bake возвращает FINISHED и запекая пустоту."""
    px = list(img.pixels)
    step = max(len(px) // 30000, 1)
    sample = px[0:len(px):step]
    mean = sum(sample) / len(sample)
    dev = statistics.pstdev(sample) if len(sample) > 1 else 0.0
    return round(mean, 4), round(dev, 5)


def main():
    a = parse_args()
    scene = bpy.context.scene
    report = {"materials": {}, "skipped": {}}

    meshes = [o for o in scene.objects if o.type == "MESH" and o.visible_get()]

    # 1. кто чего требует
    plan = {}          # material -> {"objs": [(obj, faces)], "inputs": [...], "area": м²}
    for obj in meshes:
        for slot in obj.material_slots:
            mat = slot.material
            if mat is None:
                continue
            bsdf = surface_bsdf(mat)
            if bsdf is None:
                report["skipped"][mat.name] = "объёмный материал, поверхности нет"
                continue
            inputs = linked_inputs(bsdf)
            if bsdf.inputs["Metallic"].is_linked:
                report["skipped"][mat.name + ":Metallic"] = (
                    "процедурная металличность: прохода запекания под неё нет, "
                    "в GLB уедет константа")
            if not inputs:
                report["skipped"][mat.name] = "все входы константы, запекать нечего"
                continue
            faces = material_faces(obj, mat)
            if not faces:
                continue
            entry = plan.setdefault(mat, {"objs": [], "inputs": inputs, "area": 0.0})
            entry["objs"].append((obj, faces))
            entry["area"] += world_area(obj, faces)

    if not plan:
        raise SystemExit("BAKE_ERROR: процедурных материалов в сцене не нашлось")

    device = setup_cycles_gpu()

    # 2. развёртка и картинки
    images = {}        # material -> {input_name: image}
    for mat, entry in plan.items():
        px = pow2_clamped((entry["area"] ** 0.5) * a.px_per_m, MIN_PX, a.max_px)
        unwrap_material(entry["objs"])
        images[mat] = {}
        for name in entry["inputs"]:
            _, colorspace = BAKEABLE[name]
            img = bpy.data.images.new(
                f"{mat.name}_{name.replace(' ', '').lower()}", px, px, alpha=False)
            img.colorspace_settings.name = colorspace
            images[mat][name] = img
        report["materials"][mat.name] = {
            "объектов": len(entry["objs"]),
            "площадь_м2": round(entry["area"], 2),
            "текстура_px": px,
            "запекается": entry["inputs"],
        }

    # Материалы, которые не запекаются, тоже обязаны иметь приёмник: запекание
    # идёт одним проходом по всей сцене, и объект с материалом без активной
    # картинки роняет оператор целиком.
    stub = bpy.data.images.new("bake_stub", 4, 4, alpha=False)
    all_mats = {s.material for o in meshes for s in o.material_slots if s.material}
    bakeable_objs = [o for o in meshes
                     if any(s.material in plan for s in o.material_slots)
                     and all(surface_bsdf(s.material) for s in o.material_slots
                             if s.material)]

    # 3. проходы. Один вызов bake на тип: Cycles сам разложит каждую грань в
    #    картинку её материала.
    for name, (bake_type, _) in BAKEABLE.items():
        users = [m for m in plan if name in plan[m]["inputs"]]
        if not users:
            continue
        for mat in all_mats:
            if surface_bsdf(mat) is None:
                continue
            target_node(mat).image = images.get(mat, {}).get(name, stub)

        bpy.ops.object.select_all(action="DESELECT")
        for obj in bakeable_objs:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = bakeable_objs[0]

        kwargs = {"type": bake_type, "margin": 8, "use_clear": True}
        if bake_type == "DIFFUSE":
            # Только цвет: свет в текстуре запёк бы тени намертво, а в прогулке
            # сцену освещает своё солнце из GLB.
            kwargs["pass_filter"] = {"COLOR"}
        bpy.ops.object.bake(**kwargs)

    # 4. провода перекидываются только теперь — см. шапку про обратную связь
    for mat, per_input in images.items():
        nt = mat.node_tree
        bsdf = surface_bsdf(mat)
        for name, img in per_input.items():
            node = nt.nodes.new("ShaderNodeTexImage")
            node.image = img
            node.location = (-300, 300 if name == "Base Color" else -100)
            if name == "Normal":
                # Карта нормалей подключается ЧЕРЕЗ узел Normal Map, а не
                # напрямую: вход Normal ждёт вектор, а не цвет. Подключённая
                # напрямую картинка даёт правдоподобный, но неверный рельеф -
                # и экспортёр glTF такой материал нормалью не считает вовсе.
                nm = nt.nodes.new("ShaderNodeNormalMap")
                nm.location = (-120, -420)
                nt.links.new(nm.inputs["Color"], node.outputs["Color"])
                nt.links.new(bsdf.inputs["Normal"], nm.outputs["Normal"])
            else:
                nt.links.new(bsdf.inputs[name], node.outputs["Color"])
            mean, dev = spread_of(img)
            info = report["materials"][mat.name].setdefault("проверка", {})
            # У карты нормалей «непустая» проверка по среднему не работает:
            # ровная карта это сплошной (0.5, 0.5, 1.0), среднее у неё большое
            # при полном отсутствии рельефа. Судим только по разбросу.
            ok = dev > 1e-3 if name == "Normal" else (dev > 1e-4 or mean > 1e-3)
            info[name] = {"среднее": mean, "разброс": dev, "запеклось": ok}
            img.pack()

    # Узел-приёмник больше не нужен: он остался бы активным и следующее
    # запекание писало бы в него вместо новой картинки.
    for mat in all_mats:
        if not mat.use_nodes:
            continue
        node = next((n for n in mat.node_tree.nodes if n.label == "bake-target"), None)
        if node:
            mat.node_tree.nodes.remove(node)
    bpy.data.images.remove(stub)

    report["device"] = device
    empty = [f"{m}:{i}" for m, d in report["materials"].items()
             for i, v in d.get("проверка", {}).items() if not v["запеклось"]]
    if empty:
        report["пустые"] = empty

    bpy.ops.wm.save_as_mainfile(filepath=a.out)
    print("BAKE_SCENE " + json.dumps(report, ensure_ascii=False))
    print("BAKE_SCENE_DONE")


if __name__ == "__main__":
    main()
