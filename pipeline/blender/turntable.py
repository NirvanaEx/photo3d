"""Рендер турнтейбла — исполняется внутри Blender, не в venv проекта.

    blender -b --factory-startup -noaudio -P turntable.py -- \
        --glb model.glb --out views/ --views 24 --res 512 \
        --style clay --engine workbench

Тот же скрипт снимает и одиночный кадр с заданного ракурса — с --azimuth.
Сцена, свет и настройки движков у оборота и у одиночного кадра обязаны быть
одни и те же: иначе крупный план показывал бы не то, что видно на превью,
и сравнивать их было бы нельзя.

Три стиля, у каждого своя задача:

  clay   - Workbench, серая глина с подчёркиванием впадин, без единой лампы.
           Для оценки ФОРМЫ. Настоящий свет здесь мешает: блики и тени
           прячут дыры и складки, ради которых кадр и снимается.
  color  - тот же Workbench, но показывает материал и текстуру. Быстрый
           способ увидеть покраску, освещения по-прежнему нет.
  beauty - настоящая сцена: три источника света, подложка с мягкой тенью,
           нейтральный мир. Для показа результата, а не для инспекции.

Стиль и движок разведены: сцена собирается по стилю, а рисовать её может
и EEVEE, и Cycles. Вызывающая сторона перебирает движки по очереди —
см. STYLE_ENGINES в pipeline/render.py, там же измерения, почему для
постановочного стиля первым идёт Cycles.
"""
import argparse
import math
import sys

import bpy
from mathutils import Vector


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--glb", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--views", type=int, default=24)
    p.add_argument("--res", type=int, default=512)
    p.add_argument("--style", default="clay", choices=["clay", "color", "beauty"])
    p.add_argument("--engine", default="workbench",
                   choices=["workbench", "eevee", "cycles"])
    # Одиночный кадр. --azimuth задан - снимается он один, оборот не идёт.
    p.add_argument("--azimuth", type=float, default=None)
    p.add_argument("--elevation", type=float, default=None)
    p.add_argument("--zoom", type=float, default=1.0)
    p.add_argument("--focus", type=float, default=None)
    p.add_argument("--name", default="look")
    return p.parse_args(argv)


def world_bounds(objs):
    pts = []
    for o in objs:
        for corner in o.bound_box:
            pts.append(o.matrix_world @ Vector(corner))
    if not pts:
        raise SystemExit("BLENDER_ERROR: в сцене нет мешей после импорта GLB")
    lo = Vector((min(p[i] for p in pts) for i in range(3)))
    hi = Vector((max(p[i] for p in pts) for i in range(3)))
    center = (lo + hi) / 2.0
    radius = max((p - center).length for p in pts)
    return center, max(radius, 1e-4), lo, hi


# Ракурс турнтейбла: чуть справа, спереди и сверху. Наклон отсюда - около 20°,
# и именно его повторяет elevation по умолчанию, чтобы одиночный кадр без
# параметров совпадал с кадром оборота.
BASE_DIR = Vector((0.55, -1.0, 0.42))


def camera_direction(elevation_deg):
    """Единичный вектор от точки прицела к камере.

    Азимут не трогаем: он задаётся поворотом самой модели, как и в обороте.
    Иначе пришлось бы держать два независимых способа считать ракурс, и
    кадр 090 оборота перестал бы совпадать с azimuth=90 крупного плана.
    """
    if elevation_deg is None:
        return BASE_DIR.normalized()
    flat = Vector((BASE_DIR.x, BASE_DIR.y, 0.0)).normalized()
    e = math.radians(max(min(elevation_deg, 85.0), -85.0))
    return (flat * math.cos(e) + Vector((0.0, 0.0, 1.0)) * math.sin(e)).normalized()


def setup_workbench(scene, style):
    scene.render.engine = "BLENDER_WORKBENCH"
    sh = scene.display.shading
    sh.light = "STUDIO"
    if style == "color":
        sh.color_type = "TEXTURE"      # показать материал и текстуру
    else:
        sh.color_type = "SINGLE"
        sh.single_color = (0.82, 0.80, 0.78)
    sh.show_shadows = True
    sh.show_object_outline = True
    sh.object_outline_color = (0.05, 0.05, 0.05)
    # Cavity подсвечивает складки и вмятины — без неё дефекты геометрии
    # сливаются в ровное пятно и их не разглядеть.
    sh.show_cavity = style != "color"
    sh.cavity_type = "BOTH"
    sh.curvature_ridge_factor = 1.2
    sh.curvature_valley_factor = 1.2
    try:
        sh.background_type = "VIEWPORT"
        sh.background_color = (0.12, 0.12, 0.14)
    except AttributeError:
        pass  # на старых сборках свойства нет — останется тема по умолчанию
    scene.display.render_aa = "8"


def build_studio(scene, center, radius, floor_z):
    """Три источника света и подложка. Размеры привязаны к габариту модели,
    чтобы кадр выглядел одинаково независимо от её масштаба."""
    r = radius

    world = bpy.data.worlds.new("studio")
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (0.05, 0.055, 0.065, 1.0)
    bg.inputs[1].default_value = 0.6
    scene.world = world

    def area(name, loc, energy, size, color=(1, 1, 1)):
        d = bpy.data.lights.new(name, type="AREA")
        d.energy = energy
        d.size = size
        d.color = color
        o = bpy.data.objects.new(name, d)
        o.location = center + Vector(loc) * r
        o.rotation_euler = (center - o.location).to_track_quat("-Z", "Y").to_euler()
        scene.collection.objects.link(o)
        return o

    # Ключевой спереди-сверху-слева, заполняющий справа послабее и холоднее,
    # контровой сзади для отделения силуэта от фона.
    area("key", (-1.6, -2.2, 2.0), 240 * r * r, 3.2 * r)
    area("fill", (2.4, -1.2, 0.4), 70 * r * r, 4.0 * r, (0.85, 0.9, 1.0))
    area("rim", (0.6, 2.6, 1.4), 150 * r * r, 2.2 * r, (1.0, 0.96, 0.9))

    mesh = bpy.data.meshes.new("floor")
    floor = bpy.data.objects.new("floor", mesh)
    scene.collection.objects.link(floor)
    import bmesh
    bm = bmesh.new()
    # Подложка намеренно огромная: при размере в полтора десятка радиусов
    # её дальний край попадал в кадр заметной линией горизонта.
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=r * 120)
    bm.to_mesh(mesh)
    bm.free()
    floor.location = (center.x, center.y, floor_z - r * 0.02)

    mat = bpy.data.materials.new("floor")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.22, 0.22, 0.24, 1)
    bsdf.inputs["Roughness"].default_value = 0.75
    mesh.materials.append(mat)


def setup_eevee(scene):
    ids = [i.identifier for i in
           bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items]
    scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in ids else "BLENDER_EEVEE"
    ee = getattr(scene, "eevee", None)
    if ee:
        for attr, val in (("taa_render_samples", 64), ("use_shadows", True),
                          ("use_raytracing", True), ("use_gtao", True)):
            if hasattr(ee, attr):
                setattr(ee, attr, val)


def setup_cycles(scene):
    """Cycles с попыткой считать на видеокарте.

    На CPU постановочный кадр 512 px занимает секунд восемнадцать, то есть
    полный оборот - больше семи минут. На GPU это десятки секунд. OptiX
    быстрее CUDA на картах RTX, поэтому пробуется первым.
    """
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 32
    scene.cycles.use_denoising = True
    scene.cycles.device = "CPU"

    device = "CPU"
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        for backend in ("OPTIX", "CUDA"):
            try:
                prefs.compute_device_type = backend
            except TypeError:
                continue          # эта сборка Blender такого бэкенда не знает
            for refresh in ("get_devices", "refresh_devices"):
                if hasattr(prefs, refresh):
                    try:
                        getattr(prefs, refresh)()
                    except Exception:  # noqa: BLE001, S110
                        pass
            gpus = [d for d in prefs.devices if d.type == backend]
            if gpus:
                for d in prefs.devices:
                    d.use = d.type == backend
                scene.cycles.device = "GPU"
                device = f"{backend} / {gpus[0].name}"
                break
    except Exception as exc:  # noqa: BLE001
        print(f"CYCLES_GPU_UNAVAILABLE {type(exc).__name__}: {exc}")
    print(f"CYCLES_DEVICE {device}")


def main():
    args = parse_args()

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=args.glb)

    scene = bpy.context.scene
    meshes = [o for o in scene.objects if o.type == "MESH"]
    center, radius, lo, hi = world_bounds(meshes)

    # Крутим объект вокруг пивота, а не камеру: свет остаётся на месте,
    # и кадры отличаются только ракурсом.
    pivot = bpy.data.objects.new("pivot", None)
    pivot.location = center
    scene.collection.objects.link(pivot)
    for o in meshes:
        o.parent = pivot
        o.matrix_parent_inverse = pivot.matrix_world.inverted()

    cam_data = bpy.data.cameras.new("cam")
    cam = bpy.data.objects.new("cam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam

    # Точка прицела. По умолчанию центр габарита; focus поднимает её по
    # высоте модели (0 - низ, 1 - верх), чтобы снять голову, а не пупок.
    target = center.copy()
    if args.focus is not None:
        target.z = lo.z + (hi.z - lo.z) * max(min(args.focus, 1.0), 0.0)

    half_fov = cam_data.angle / 2.0
    # Расстояние считается по ПОЛНОМУ габариту и от zoom не зависит: приближает
    # не подъезд камеры, а сужение объектива. Подъезд к голове фигуры требует
    # зайти внутрь описанной сферы - оттуда лезет и отсечение ближней
    # плоскостью, и перспективная карикатура вместо портрета. Длинный фокус с
    # прежнего места даёт ровно то, что нужно: тот же ракурс, только крупнее.
    dist = radius / math.sin(half_fov) * 1.15  # запас, чтобы не подрезать край
    direction = camera_direction(args.elevation)
    cam.location = target + direction * dist
    cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
    cam_data.clip_start = max(dist - radius * 3, 0.001)
    cam_data.clip_end = dist + radius * 20
    if args.zoom and abs(args.zoom - 1.0) > 1e-6:
        cam_data.angle = 2.0 * math.atan(math.tan(half_fov) / max(args.zoom, 0.05))

    if args.style == "beauty":
        build_studio(scene, center, radius, lo.z)
        # Standard вместо AgX по умолчанию. AgX даёт красивую киношную
        # картинку, но заметно гасит насыщенные цвета - заказанная терракота
        # выходила блёклым лососевым. Здесь важнее показать ту краску,
        # которую действительно задали.
        try:
            scene.view_settings.view_transform = "Standard"
            scene.view_settings.look = "None"
        except (AttributeError, TypeError):
            pass

    if args.engine == "workbench":
        setup_workbench(scene, args.style)
    elif args.engine == "eevee":
        setup_eevee(scene)
    else:
        setup_cycles(scene)

    scene.render.resolution_x = args.res
    scene.render.resolution_y = args.res
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"

    out = args.out.rstrip("/")
    if args.azimuth is None:
        for i in range(args.views):
            angle = 2 * math.pi * i / args.views
            pivot.rotation_euler = (0, 0, angle)
            deg = round(math.degrees(angle))
            scene.render.filepath = f"{out}/{deg:03d}"
            bpy.ops.render.render(write_still=True)
            print(f"BLENDER_VIEW_OK {deg:03d}")
    else:
        pivot.rotation_euler = (0, 0, math.radians(args.azimuth))
        scene.render.filepath = f"{out}/{args.name}"
        bpy.ops.render.render(write_still=True)
        print(f"BLENDER_VIEW_OK {args.name}")

    print("BLENDER_DONE")


if __name__ == "__main__":
    main()
