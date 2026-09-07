"""Сборка школьного класса по референсу — исполняется внутри Blender.

    blender -b --factory-startup -noaudio -P classroom.py -- \
        --out data/output/loc_classroom --res 1366x768 --samples 96

Референс: японский класс на закате (data/input/ref_classroom.jpg) — парты с
трубчатыми ножками рядами, зелёная доска, стенды с бумажками, большие окна
слева, низкое тёплое солнце, блестящий паркет.

Здесь НЕТ голых боксов в роли предметов: ножки парт и стульев — кривые с
круглым сечением, столешницы и корпуса — с фасками (Bevel), шторы — сетка с
синусоидальными складками. Боксы остались только там, где им место: стены.

Общие с corridor.py приёмы (box_uv, mat_scanned, подбор устройства Cycles)
скопированы, а не импортированы: corridor.py прямо сейчас ведёт параллельная
сессия, и зависеть от файла в движении — плодить гонки. Когда осядет —
общее место обоих скриптов: pipeline/blender/matlib.py (план в README).

Геометрия в мировых координатах, начала объектов в нуле — причина та же,
что в коридоре: процедурные текстуры и проекционная развёртка идут единым
полотном через стыки.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

import bpy
from mathutils import Vector

# --------------------------------------------------------------------------- #
# Размеры. Японский типовой класс: 7.4 x 9.0, потолок 3.0.
# --------------------------------------------------------------------------- #

WIDTH = 7.4            # x: от оконной стены (слева) до дверной (справа)
LENGTH = 9.0           # y: от задней стены (за камерой) до доски
HEIGHT = 3.0
WALL_T = 0.30

# Окна левой стены: четыре пролёта раздвижных рам, как на референсе.
WIN_SILL = 0.85
WIN_TOP = 2.55
WIN_SPLIT = 1.75       # горизонтальный импост: снизу большие створки, сверху фрамуги
WIN_BAYS = ((0.7, 2.6), (2.8, 4.7), (4.9, 6.8), (7.0, 8.6))   # (y0, y1)

# Доска на передней стене.
BOARD_W, BOARD_Z0, BOARD_Z1 = 3.6, 0.90, 2.10

# Парты: японская школьная, столешница 65x45 на высоте 73 см.
DESK_W, DESK_D, DESK_H = 0.65, 0.45, 0.73
COLS = (-2.35, -0.85, 0.65, 2.15)      # x колонн
ROWS = (2.1, 3.25, 4.4, 5.55)          # y рядов

TEX_DIR = Path("/mnt/d/Develop/photo3d/data/textures")

rng = random.Random(7)   # фиксированный сид: пересборка даёт тот же класс


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--res", default="1366x768")
    p.add_argument("--samples", type=int, default=96)
    # Солнце низкое: длинные полосы света через парты — половина настроения
    # референса. Азимут отсчитан от нормали окон в сторону доски.
    p.add_argument("--sun-elev", type=float, default=9.0)
    p.add_argument("--sun-azim", type=float, default=28.0)
    p.add_argument("--sun-energy", type=float, default=38.0)
    p.add_argument("--sky", type=float, default=2.3)
    p.add_argument("--haze", type=float, default=0.006)
    p.add_argument("--lens", type=float, default=23.0)
    p.add_argument("--cam", default="2.55,1.30,1.45")
    p.add_argument("--look", default="-2.4,8.6,0.95")
    p.add_argument("--view-transform", default="AgX")
    p.add_argument("--exposure", type=float, default=0.0)
    p.add_argument("--blend", default="")
    return p.parse_args(argv)


# --------------------------------------------------------------------------- #
# Примитивы
# --------------------------------------------------------------------------- #

def link(obj):
    bpy.context.scene.collection.objects.link(obj)
    return obj


def make_box(name, x0, x1, y0, y1, z0, z1, mat=None, bevel=0.0):
    """Бокс по границам; bevel>0 снимает остроту рёбер — мебель, а не ящик."""
    mesh = bpy.data.meshes.new(name)
    verts = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
             (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    faces = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
             (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    if mat:
        mesh.materials.append(mat)
    obj = link(bpy.data.objects.new(name, mesh))
    if bevel > 0:
        mod = obj.modifiers.new("bevel", "BEVEL")
        mod.width = bevel
        mod.segments = 2
    return obj


def make_plane(name, mat, w, h):
    """Вертикальная плоскость w x h с центром в нуле, нормаль +X.

    Ставится на место поворотом/сдвигом объекта — бумажки и плакаты
    развешиваются как в жизни, штучно.
    """
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(
        [(0, -w / 2, -h / 2), (0, w / 2, -h / 2), (0, w / 2, h / 2), (0, -w / 2, h / 2)],
        [], [(0, 1, 2, 3)])
    mesh.update()
    mesh.materials.append(mat)
    return link(bpy.data.objects.new(name, mesh))


def tube(name, points, radius, mat):
    """Труба по ломаной: кривая с круглым сечением. Это и есть «не бокс».

    Кривая конвертируется в меш сразу: glTF-экспортёру и запеканию нужны
    полигоны, а держать в сцене два представления — путать счётчики.
    """
    curve = bpy.data.curves.new(name, "CURVE")
    curve.dimensions = "3D"
    curve.bevel_depth = radius
    curve.bevel_resolution = 3
    curve.resolution_u = 6
    spline = curve.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for pt, (x, y, z) in zip(spline.points, points):
        pt.co = (x, y, z, 1)
    obj = link(bpy.data.objects.new(name, curve))
    obj.data.materials.append(mat)

    bpy.context.view_layer.objects.active = obj
    for o in bpy.context.selected_objects:
        o.select_set(False)
    obj.select_set(True)
    bpy.ops.object.convert(target="MESH")
    converted = bpy.context.view_layer.objects.active
    if len(converted.data.polygons) == 0:
        raise SystemExit(f"CLASSROOM_ERROR труба {name} не дала граней")
    return converted


# --------------------------------------------------------------------------- #
# Материалы
# --------------------------------------------------------------------------- #

def _mat(name):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    coord = nt.nodes.new("ShaderNodeTexCoord")
    coord.location = (-1400, 0)
    return mat, nt, bsdf, coord


def _noise(nt, coord, scale, detail=6.0, loc=(-1100, 0), stretch=None):
    src = coord.outputs["Object"]
    if stretch:
        mapping = nt.nodes.new("ShaderNodeMapping")
        mapping.location = (loc[0] - 200, loc[1])
        mapping.inputs["Scale"].default_value = stretch
        nt.links.new(mapping.inputs["Vector"], src)
        src = mapping.outputs["Vector"]
    n = nt.nodes.new("ShaderNodeTexNoise")
    n.location = loc
    n.inputs["Scale"].default_value = scale
    n.inputs["Detail"].default_value = detail
    nt.links.new(n.inputs["Vector"], src)
    return n


def box_uv(obj, tile_m):
    """Проекционная развёртка по осям в мировых координатах (см. corridor.py)."""
    me = obj.data
    uvl = me.uv_layers.get("scan") or me.uv_layers.new(name="scan")
    mw = obj.matrix_world
    for poly in me.polygons:
        n = poly.normal
        axis = max(range(3), key=lambda i: abs(n[i]))
        for li in poly.loop_indices:
            co = mw @ me.vertices[me.loops[li].vertex_index].co
            if axis == 0:
                u, v = co.y, co.z
            elif axis == 1:
                u, v = co.x, co.z
            else:
                u, v = co.x, co.y
            uvl.data[li].uv = (u / tile_m, v / tile_m)


def _tex(nt, mat_dir, short, colorspace, loc):
    path = mat_dir / f"{short}.jpg"
    if not path.exists():
        return None
    node = nt.nodes.new("ShaderNodeTexImage")
    node.image = bpy.data.images.load(str(path), check_existing=True)
    node.image.colorspace_settings.name = colorspace
    node.location = loc
    return node


def mat_scanned(name, asset, tile_m, tint=None, rough_range=None):
    """Фотоскан: цвет+нормаль+шероховатость картинками, тайлинг через UV.

    bake_scene такой материал узнаёт и НЕ запекает — уезжает как есть.
    """
    mat, nt, bsdf, coord = _mat(name)
    mat["tile_m"] = tile_m
    d = TEX_DIR / asset
    if not d.is_dir():
        raise SystemExit(f"CLASSROOM_ERROR нет текстур {d}. "
                         f"Прогони scripts/fetch_textures.py {asset}")

    diff = _tex(nt, d, "diff", "sRGB", (-800, 300))
    if tint is not None:
        mul = nt.nodes.new("ShaderNodeMixRGB")
        mul.location = (-450, 300)
        mul.blend_type = "MULTIPLY"
        mul.inputs["Fac"].default_value = 1.0
        mul.inputs["Color2"].default_value = (*tint, 1)
        nt.links.new(mul.inputs["Color1"], diff.outputs["Color"])
        nt.links.new(bsdf.inputs["Base Color"], mul.outputs["Color"])
    else:
        nt.links.new(bsdf.inputs["Base Color"], diff.outputs["Color"])

    rough = _tex(nt, d, "rough", "Non-Color", (-800, 0))
    if rough is not None:
        if rough_range is not None:
            rng_n = nt.nodes.new("ShaderNodeMapRange")
            rng_n.location = (-450, 0)
            rng_n.inputs["To Min"].default_value = rough_range[0]
            rng_n.inputs["To Max"].default_value = rough_range[1]
            nt.links.new(rng_n.inputs["Value"], rough.outputs["Color"])
            nt.links.new(bsdf.inputs["Roughness"], rng_n.outputs["Result"])
        else:
            nt.links.new(bsdf.inputs["Roughness"], rough.outputs["Color"])

    nor = _tex(nt, d, "nor", "Non-Color", (-800, -300))
    if nor is not None:
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nm.location = (-450, -300)
        nt.links.new(nm.inputs["Color"], nor.outputs["Color"])
        nt.links.new(bsdf.inputs["Normal"], nm.outputs["Normal"])
    return mat


def mat_flat(name, color, rough=0.55, metallic=0.0):
    mat, nt, bsdf, _ = _mat(name)
    bsdf.inputs["Base Color"].default_value = (*color, 1)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metallic
    return mat


def mat_desk_wood():
    """Лакированная столешница: тёплое дерево, продольная свиль, блеск."""
    mat, nt, bsdf, coord = _mat("desk_wood")
    grain = _noise(nt, coord, 30.0, 8.0, (-900, -200), stretch=(1.0, 0.08, 1.0))
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.location = (-650, -200)
    ramp.color_ramp.elements[0].color = (0.32, 0.175, 0.075, 1)
    ramp.color_ramp.elements[1].color = (0.52, 0.31, 0.14, 1)
    nt.links.new(ramp.inputs["Fac"], grain.outputs["Fac"])
    nt.links.new(bsdf.inputs["Base Color"], ramp.outputs["Color"])
    # Лак:低кая шероховатость — закат должен бликовать на столешницах,
    # как на референсе.
    bsdf.inputs["Roughness"].default_value = 0.22
    return mat


def mat_board():
    """Зелёная доска: тёмная, с горизонтальной дымкой от мела."""
    mat, nt, bsdf, coord = _mat("board_green")
    base = nt.nodes.new("ShaderNodeRGB")
    base.location = (-700, 200)
    base.outputs[0].default_value = (0.045, 0.115, 0.075, 1)
    chalk = _noise(nt, coord, 2.5, 3.0, (-950, -200), stretch=(1.0, 0.05, 1.0))
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.location = (-650, -200)
    ramp.color_ramp.elements[0].position = 0.55
    ramp.color_ramp.elements[1].position = 0.98
    nt.links.new(ramp.inputs["Fac"], chalk.outputs["Fac"])
    mix = nt.nodes.new("ShaderNodeMixRGB")
    mix.location = (-400, 100)
    mix.inputs["Fac"].default_value = 0.05       # мел еле заметен
    mix.inputs["Color2"].default_value = (0.55, 0.6, 0.55, 1)
    nt.links.new(mix.inputs["Color1"], base.outputs[0])
    nt.links.new(mix.inputs["Fac"], ramp.outputs["Color"])
    nt.links.new(bsdf.inputs["Base Color"], mix.outputs["Color"])
    bsdf.inputs["Roughness"].default_value = 0.55
    return mat


def mat_metal(name, color, rough=0.35, metallic=0.9):
    mat, nt, bsdf, coord = _mat(name)
    n = _noise(nt, coord, 40.0, 3.0, (-900, -200))
    rr = nt.nodes.new("ShaderNodeMapRange")
    rr.location = (-650, -400)
    rr.inputs["To Min"].default_value = rough - 0.08
    rr.inputs["To Max"].default_value = rough + 0.10
    nt.links.new(rr.inputs["Value"], n.outputs["Fac"])
    nt.links.new(bsdf.inputs["Roughness"], rr.outputs["Result"])
    bsdf.inputs["Base Color"].default_value = (*color, 1)
    bsdf.inputs["Metallic"].default_value = metallic
    return mat


def mat_glass():
    mat, nt, bsdf, _ = _mat("glass")
    bsdf.inputs["Base Color"].default_value = (0.88, 0.92, 0.96, 1)
    bsdf.inputs["Roughness"].default_value = 0.03
    bsdf.inputs["IOR"].default_value = 1.02
    for socket in ("Transmission Weight", "Transmission"):
        if socket in bsdf.inputs:
            bsdf.inputs[socket].default_value = 1.0
            break
    return mat


# --------------------------------------------------------------------------- #
# Оболочка и окна
# --------------------------------------------------------------------------- #

def build_shell(m):
    x0, x1 = -WIDTH / 2, WIDTH / 2
    make_box("floor", x0 - WALL_T, x1 + WALL_T, -WALL_T, LENGTH + WALL_T,
             -0.2, 0.0, m["floor"])
    make_box("ceiling", x0 - WALL_T, x1 + WALL_T, -WALL_T, LENGTH + WALL_T,
             HEIGHT, HEIGHT + 0.2, m["ceil"])
    make_box("wall_front", x0, x1, LENGTH, LENGTH + WALL_T, 0, HEIGHT, m["wall"])
    make_box("wall_back", x0, x1, -WALL_T, 0.0, 0, HEIGHT, m["wall"])
    make_box("wall_right", x1, x1 + WALL_T, -WALL_T, LENGTH + WALL_T, 0, HEIGHT,
             m["wall"])
    left = make_box("wall_left", x0 - WALL_T, x0, -WALL_T, LENGTH + WALL_T,
                    0, HEIGHT, m["wall"])
    # Плинтус тёмного дерева по трём глухим стенам.
    for name, xa, xb, ya, yb in (
        ("sk_r", x1 - 0.02, x1, 0, LENGTH),
        ("sk_f", x0, x1, LENGTH - 0.02, LENGTH),
        ("sk_b", x0, x1, 0, 0.02),
    ):
        make_box(f"skirt_{name}", xa, xb, ya, yb, 0, 0.10, m["trim"])
    return left


def build_windows(left_wall, m):
    """Раздвижные окна во всю левую стену: алюминий, две полосы створок."""
    x0 = -WIDTH / 2
    glass_objs = []
    for i, (y0, y1) in enumerate(WIN_BAYS):
        # Проём.
        cutter = make_box(f"wcut{i}", x0 - WALL_T - 0.05, x0 + 0.05,
                          y0, y1, WIN_SILL, WIN_TOP)
        before = len(left_wall.data.polygons)
        mod = left_wall.modifiers.new("cut", "BOOLEAN")
        mod.object = cutter
        mod.operation = "DIFFERENCE"
        mod.solver = "EXACT"
        bpy.context.view_layer.objects.active = left_wall
        for o in bpy.context.selected_objects:
            o.select_set(False)
        left_wall.select_set(True)
        bpy.ops.object.modifier_apply(modifier=mod.name)
        if len(left_wall.data.polygons) == before:
            raise SystemExit(f"CLASSROOM_ERROR окно {i} не вырезалось")
        bpy.data.objects.remove(cutter, do_unlink=True)

        # Стекло одним листом на пролёт, ближе к улице.
        gx = x0 - WALL_T + 0.10
        glass_objs.append(make_box(f"glass{i}", gx, gx + 0.02, y0 + 0.02,
                                   y1 - 0.02, WIN_SILL, WIN_TOP, m["glass"]))

        # Алюминиевая обвязка: рама по периметру, импост, вертикальные
        # перемычки створок — раздвижные окна из референса.
        fx0, fx1 = x0 - WALL_T + 0.06, x0 - 0.02
        fr = m["alu"]
        make_box(f"wf{i}_b", fx0, fx1, y0, y1, WIN_SILL, WIN_SILL + 0.05, fr)
        make_box(f"wf{i}_t", fx0, fx1, y0, y1, WIN_TOP - 0.05, WIN_TOP, fr)
        make_box(f"wf{i}_l", fx0, fx1, y0, y0 + 0.04, WIN_SILL, WIN_TOP, fr)
        make_box(f"wf{i}_r", fx0, fx1, y1 - 0.04, y1, WIN_SILL, WIN_TOP, fr)
        make_box(f"wf{i}_m", fx0, fx1, y0, y1, WIN_SPLIT - 0.025,
                 WIN_SPLIT + 0.025, fr)
        n_mull = 3
        for k in range(1, n_mull + 1):
            y = y0 + (y1 - y0) * k / (n_mull + 1)
            make_box(f"wm{i}_{k}", fx0, fx1, y - 0.015, y + 0.015,
                     WIN_SILL, WIN_TOP, fr)

        # Подоконник внутрь.
        make_box(f"sill{i}", x0 - 0.02, x0 + 0.14, y0 - 0.06, y1 + 0.06,
                 WIN_SILL - 0.05, WIN_SILL, m["trim"])
    return glass_objs


def build_backdrop(m):
    """Задник за окнами: тёплая стена заката и тёмная полоса деревьев.

    Не город 1 в 1 — но окно перестаёт быть дырой в пустоту: появляется
    глубина и силуэт горизонта. Настоящая панорама - следующий слой.
    """
    x = -WIDTH / 2 - 6.0
    make_box("horizon", x - 0.2, x, -8, LENGTH + 12, -2, 2.1, m["trees"])


# --------------------------------------------------------------------------- #
# Мебель
# --------------------------------------------------------------------------- #

def build_desk(cx, cy, angle_deg, m):
    """Парта: столешница с фаской + трубчатый каркас. Ножки — кривые."""
    r = 0.012
    hw, hd = DESK_W / 2, DESK_D / 2
    top = make_box("desk_top", cx - hw, cx + hw, cy - hd, cy + hd,
                   DESK_H - 0.022, DESK_H, m["desk"], bevel=0.006)
    # Полка под столешницей.
    make_box("desk_shelf", cx - hw + 0.05, cx + hw - 0.05,
             cy - hd + 0.06, cy + hd - 0.02,
             DESK_H - 0.17, DESK_H - 0.155, m["metal"])
    legs = []
    for sx in (-1, 1):
        x = cx + sx * (hw - 0.04)
        # ⊓-образная боковина: перед-низ-зад, с полозом по полу.
        legs.append(tube(f"desk_leg", [
            (x, cy - hd + 0.02, DESK_H - 0.02),
            (x, cy - hd + 0.02, 0.02),
            (x, cy + hd - 0.02, 0.02),
            (x, cy + hd - 0.02, DESK_H - 0.02),
        ], r, m["metal"]))
    # Поперечина сзади.
    legs.append(tube("desk_bar", [
        (cx - hw + 0.04, cy + hd - 0.02, DESK_H - 0.30),
        (cx + hw - 0.04, cy + hd - 0.02, DESK_H - 0.30),
    ], r, m["metal"]))

    objs = [top] + legs
    _spin_group(objs, cx, cy, angle_deg)
    return objs


def build_chair(cx, cy, angle_deg, m):
    """Стул: сиденье, спинка, каркас из двух труб с высокими задними ножками."""
    r = 0.010
    hw, hd = 0.19, 0.185
    seat_h = 0.42
    seat = make_box("chair_seat", cx - hw, cx + hw, cy - hd, cy + hd,
                    seat_h - 0.016, seat_h, m["desk"], bevel=0.005)
    back = make_box("chair_back", cx - hw + 0.02, cx + hw - 0.02,
                    cy + hd - 0.014, cy + hd,
                    seat_h + 0.26, seat_h + 0.40, m["desk"], bevel=0.005)
    legs = []
    for sx in (-1, 1):
        x = cx + sx * (hw - 0.025)
        legs.append(tube("chair_leg", [
            (x, cy - hd + 0.015, seat_h - 0.01),
            (x, cy - hd + 0.015, 0.015),
            (x, cy + hd - 0.015, 0.015),
            (x, cy + hd - 0.015, seat_h + 0.42),   # задняя ножка уходит в спинку
        ], r, m["metal"]))
    objs = [seat, back] + legs
    _spin_group(objs, cx, cy, angle_deg)
    return objs


def _spin_group(objs, cx, cy, angle_deg):
    """Повернуть группу вокруг вертикали в точке (cx, cy).

    Лёгкий разнобой поворотов — то, что отличает обжитый класс от
    выставочного: идеально ровные ряды читаются макетом.
    """
    # Меши построены в мировых координатах с началом объекта в нуле, поэтому
    # честный способ повернуть группу — повернуть сами вершины вокруг (cx, cy).
    a = math.radians(angle_deg)
    ca, sa = math.cos(a), math.sin(a)
    for o in objs:
        me = o.data
        for v in me.vertices:
            px, py = v.co.x - cx, v.co.y - cy
            v.co.x = cx + px * ca - py * sa
            v.co.y = cy + px * sa + py * ca


def build_teacher_desk(m):
    """Кафедра у доски: корпус с фасками и врезной передней панелью."""
    cx, cy = 1.3, LENGTH - 1.15
    w, d, h = 1.05, 0.60, 0.85
    make_box("lectern_top", cx - w / 2 - 0.03, cx + w / 2 + 0.03,
             cy - d / 2 - 0.03, cy + d / 2 + 0.03, h - 0.03, h,
             m["desk"], bevel=0.008)
    make_box("lectern_body", cx - w / 2, cx + w / 2, cy - d / 2, cy + d / 2,
             0.06, h - 0.03, m["cabinet"], bevel=0.006)
    make_box("lectern_panel", cx - w / 2 + 0.08, cx + w / 2 - 0.08,
             cy - d / 2 - 0.012, cy - d / 2,
             0.16, h - 0.14, m["cabinet_dark"])


def build_board_wall(m):
    """Передняя стена: доска, лоток мела, стенды с бумажками, часы, табличка."""
    y = LENGTH - 0.001
    bx0, bx1 = -BOARD_W / 2 - 0.4, BOARD_W / 2 - 0.4

    # Доска с алюминиевой рамкой.
    make_box("board", bx0, bx1, y - 0.02, y, BOARD_Z0, BOARD_Z1, m["board"])
    fr = m["alu"]
    make_box("bfr_t", bx0 - 0.03, bx1 + 0.03, y - 0.03, y, BOARD_Z1, BOARD_Z1 + 0.03, fr)
    make_box("bfr_b", bx0 - 0.03, bx1 + 0.03, y - 0.03, y, BOARD_Z0 - 0.03, BOARD_Z0, fr)
    make_box("bfr_l", bx0 - 0.03, bx0, y - 0.03, y, BOARD_Z0, BOARD_Z1, fr)
    make_box("bfr_r", bx1, bx1 + 0.03, y - 0.03, y, BOARD_Z0, BOARD_Z1, fr)
    # Лоток и мел.
    make_box("tray", bx0, bx1, y - 0.07, y - 0.02, BOARD_Z0 - 0.05, BOARD_Z0 - 0.03, fr)
    for k in range(3):
        x = bx0 + 0.5 + k * 0.9 + rng.uniform(-0.1, 0.1)
        make_box(f"chalk{k}", x, x + 0.07, y - 0.055, y - 0.04,
                 BOARD_Z0 - 0.03, BOARD_Z0 - 0.018, m["paper"], bevel=0.004)

    # Зелёные стенды справа от доски, с приколотыми листами.
    for j, (px0, px1) in enumerate(((bx1 + 0.25, bx1 + 1.05),
                                    (bx1 + 1.2, bx1 + 2.0))):
        make_box(f"pin{j}", px0, px1, y - 0.015, y, 1.05, 2.25, m["pinboard"])
        for k in range(5):
            w, h = 0.21, 0.29
            px = rng.uniform(px0 + 0.14, px1 - 0.14)
            pz = rng.uniform(1.3, 2.0)
            paper = make_plane(f"paper{j}{k}", m["paper"], w, h)
            paper.location = (px, y - 0.02, pz)
            paper.rotation_euler = (math.radians(90), rng.uniform(-0.06, 0.06),
                                    math.radians(180))

    # Часы: два цилиндра — корпус и белый циферблат.
    _clock(0.0, y - 0.02, 2.62, m)
    # Табличка с изречением над доской (как на референсе) и динамик.
    make_box("plaque", -0.95, -0.15, y - 0.025, y, 2.55, 2.78, m["cabinet_dark"])
    make_box("plaque_in", -0.9, -0.2, y - 0.032, y - 0.025, 2.59, 2.74, m["paper"])
    make_box("speaker", 0.45, 0.95, y - 0.14, y, 2.5, 2.82, m["paper"], bevel=0.01)


def _clock(cx, cy, cz, m):
    for name, r, depth, mat in (("clock_rim", 0.17, 0.045, m["metal"]),
                                ("clock_face", 0.145, 0.05, m["paper"])):
        mesh = bpy.data.meshes.new(name)
        n = 24
        verts, faces = [], []
        for i in range(n):
            a = 2 * math.pi * i / n
            verts.append((cx + r * math.cos(a), cy, cz + r * math.sin(a)))
            verts.append((cx + r * math.cos(a), cy - depth, cz + r * math.sin(a)))
        for i in range(n):
            j = (i + 1) % n
            faces.append((2 * i, 2 * j, 2 * j + 1, 2 * i + 1))
        faces.append(tuple(2 * i + 1 for i in range(n)))
        mesh.from_pydata(verts, [], faces)
        mesh.update()
        mesh.materials.append(mat)
        link(bpy.data.objects.new(name, mesh))
    # Стрелки.
    make_box("hand_h", cx - 0.006, cx + 0.006, cy - 0.052, cy - 0.05,
             cz, cz + 0.08, m["cabinet_dark"])
    make_box("hand_m", cx - 0.004, cx + 0.004, cy - 0.052, cy - 0.05,
             cz - 0.11, cz, m["cabinet_dark"])


def build_cabinet(m):
    """Шкаф и книжная полка у окна, слева от доски, книги разнобоем."""
    x0 = -WIDTH / 2 + 0.15
    y0, y1 = LENGTH - 1.9, LENGTH - 0.25
    make_box("cabinet", x0, x0 + 0.45, y0, y0 + 0.8, 0.05, 1.85,
             m["cabinet"], bevel=0.008)
    make_box("cab_door_l", x0 + 0.44, x0 + 0.455, y0 + 0.04, y0 + 0.38,
             0.12, 1.78, m["cabinet_dark"])
    make_box("cab_door_r", x0 + 0.44, x0 + 0.455, y0 + 0.42, y0 + 0.76,
             0.12, 1.78, m["cabinet_dark"])
    # Полка с книгами.
    sx0, sy0 = x0, y0 + 0.95
    make_box("shelf", sx0, sx0 + 0.35, sy0, sy0 + 0.7, 0.05, 1.25,
             m["cabinet"], bevel=0.006)
    palette = ((0.55, 0.3, 0.2), (0.25, 0.35, 0.5), (0.6, 0.55, 0.35),
               (0.3, 0.45, 0.3), (0.5, 0.25, 0.3), (0.75, 0.7, 0.6))
    for level_z in (0.45, 0.86):
        yy = sy0 + 0.05
        while yy < sy0 + 0.62:
            t = rng.uniform(0.02, 0.045)
            h = rng.uniform(0.18, 0.30)
            c = palette[rng.randrange(len(palette))]
            mat = m.setdefault(f"book_{c}", mat_flat(f"book{len(m)}", c, 0.7))
            make_box("book", sx0 + 0.04, sx0 + 0.30, yy, yy + t,
                     level_z, level_z + h, mat)
            yy += t + 0.004


def build_curtains(m):
    """Шторы: сетка с синусоидальными складками, собраны к краям окон."""
    x = -WIDTH / 2 + 0.05
    for i, (y0, y1) in enumerate(WIN_BAYS):
        for side, ya in ((0, y0 - 0.05), (1, y1 - 0.35)):
            w = 0.40
            mesh = bpy.data.meshes.new(f"curtain{i}{side}")
            cols, rows_n = 14, 2
            verts = []
            for c in range(cols):
                t = c / (cols - 1)
                yy = ya + t * w
                xx = x + 0.05 * math.sin(t * math.pi * 6) + 0.02 * math.sin(t * 17)
                for z in (WIN_SILL - 0.25, WIN_TOP + 0.12):
                    verts.append((xx, yy, z))
            faces = []
            for c in range(cols - 1):
                a = c * rows_n
                faces.append((a, a + rows_n, a + rows_n + 1, a + 1))
            mesh.from_pydata(verts, [], faces)
            mesh.update()
            mesh.materials.append(m["curtain"])
            link(bpy.data.objects.new(f"curtain{i}{side}", mesh))


def build_ceiling_lights(m):
    """Подвесные люминесцентные светильники — выключены: класс на закате."""
    for (cx, cy) in ((-1.4, 2.6), (-1.4, 5.8), (1.6, 2.6), (1.6, 5.8)):
        make_box("lamp_house", cx - 0.62, cx + 0.62, cy - 0.10, cy + 0.10,
                 HEIGHT - 0.55, HEIGHT - 0.47, m["paper"], bevel=0.01)
        for dy in (-0.045, 0.045):
            make_box("lamp_tube", cx - 0.55, cx + 0.55, cy + dy - 0.014,
                     cy + dy + 0.014, HEIGHT - 0.47, HEIGHT - 0.445, m["alu"])
        for dx in (-0.45, 0.45):
            tube("lamp_rod", [(cx + dx, cy, HEIGHT - 0.55),
                              (cx + dx, cy, HEIGHT)], 0.006, m["alu"])


def build_radiator(m):
    """Белый ребристый радиатор под передним окном."""
    y0, y1 = WIN_BAYS[3][0] + 0.1, WIN_BAYS[3][1] - 0.1
    x = -WIDTH / 2 + 0.06
    yy = y0
    while yy < y1:
        make_box("fin", x, x + 0.10, yy, yy + 0.02, 0.12, 0.72, m["paper"])
        yy += 0.055
    make_box("rad_top", x - 0.01, x + 0.12, y0 - 0.03, y1 + 0.03,
             0.72, 0.75, m["paper"], bevel=0.006)


# --------------------------------------------------------------------------- #
# Свет, камера, рендер
# --------------------------------------------------------------------------- #

def setup_light(scene, args, glass_objs):
    e, a = math.radians(args.sun_elev), math.radians(args.sun_azim)
    # Окна на -X: свет летит в +X, со сдвигом к доске (+Y).
    d = Vector((math.cos(a) * math.cos(e), math.sin(a) * math.cos(e),
                -math.sin(e)))
    data = bpy.data.lights.new("sun", type="SUN")
    data.energy = args.sun_energy
    data.color = (1.0, 0.72, 0.45)      # у горизонта: почти оранжевое
    data.angle = math.radians(1.5)
    sun = link(bpy.data.objects.new("sun", data))
    sun.location = Vector((-WIDTH, LENGTH * 0.4, HEIGHT)) - d * 12
    sun.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()

    for g in glass_objs:
        g.visible_shadow = False

    world = bpy.data.worlds.new("sky")
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    # Насыщеннее, чем кажется нужным: AgX гасит цвет, и «оранжевый» в
    # числах выходит белёсым в кадре. Первый рендер дал белые окна.
    bg.inputs[0].default_value = (0.98, 0.48, 0.20, 1)
    bg.inputs[1].default_value = args.sky
    scene.world = world

    if args.haze > 0:
        box = make_box("haze", -WIDTH / 2, WIDTH / 2, 0.0, LENGTH, 0.0, HEIGHT)
        mat = bpy.data.materials.new("haze")
        mat.use_nodes = True
        nt = mat.node_tree
        nt.nodes.remove(nt.nodes["Principled BSDF"])
        sc = nt.nodes.new("ShaderNodeVolumeScatter")
        sc.inputs["Density"].default_value = args.haze
        sc.inputs["Anisotropy"].default_value = 0.4
        nt.links.new(nt.nodes["Material Output"].inputs["Volume"],
                     sc.outputs["Volume"])
        box.data.materials.append(mat)
        scene.cycles.volume_bounces = 2
    return d


def setup_cycles(scene, samples):
    scene.render.engine = "CYCLES"
    scene.cycles.samples = samples
    scene.cycles.use_denoising = True
    scene.cycles.max_bounces = 10
    scene.cycles.diffuse_bounces = 8
    scene.cycles.device = "CPU"
    device = "CPU"
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        for backend in ("OPTIX", "CUDA"):
            try:
                prefs.compute_device_type = backend
            except TypeError:
                continue
            for refresh in ("get_devices", "refresh_devices"):
                if hasattr(prefs, refresh):
                    try:
                        getattr(prefs, refresh)()
                    except Exception:  # noqa: BLE001, S110
                        pass
            gpus = [dv for dv in prefs.devices if dv.type == backend]
            if gpus:
                for dv in prefs.devices:
                    dv.use = dv.type == backend
                scene.cycles.device = "GPU"
                device = f"{backend} / {gpus[0].name}"
                break
    except Exception as exc:  # noqa: BLE001
        print(f"CYCLES_GPU_UNAVAILABLE {type(exc).__name__}: {exc}")
    print(f"CYCLES_DEVICE {device}")
    return device


def main():
    args = parse_args()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene

    m = {
        # Паркет глянцевый: диапазон шероховатости опущен вниз, чтобы закат
        # бликовал на полу — на референсе отражения окон в паркете.
        "floor": mat_scanned("floor_parquet", "rectangular_parquet", 1.6,
                             tint=(0.95, 0.82, 0.62), rough_range=(0.10, 0.32)),
        "wall": mat_scanned("wall_plaster", "beige_wall_001", 3.0,
                            tint=(0.97, 0.90, 0.74), rough_range=(0.75, 0.95)),
        "ceil": mat_scanned("ceiling_tiles", "ceiling_interior", 1.2,
                            tint=(1.0, 0.97, 0.92)),
        "desk": mat_desk_wood(),
        "board": mat_board(),
        "metal": mat_metal("frame_metal", (0.62, 0.63, 0.65), 0.32, 0.9),
        "alu": mat_metal("alu", (0.80, 0.81, 0.82), 0.38, 0.85),
        "glass": mat_glass(),
        "trim": mat_flat("trim_wood", (0.42, 0.30, 0.18), 0.5),
        "pinboard": mat_flat("pinboard", (0.38, 0.47, 0.33), 0.9),
        "paper": mat_flat("paper", (0.93, 0.90, 0.84), 0.7),
        "cabinet": mat_flat("cabinet_wood", (0.55, 0.40, 0.24), 0.45),
        "cabinet_dark": mat_flat("cabinet_dark", (0.30, 0.21, 0.13), 0.5),
        "curtain": mat_flat("curtain", (0.93, 0.88, 0.76), 0.85),
        "trees": mat_flat("trees_far", (0.14, 0.12, 0.10), 0.9),
    }

    left = build_shell(m)
    glass = build_windows(left, m)
    build_backdrop(m)
    build_board_wall(m)
    build_cabinet(m)
    build_teacher_desk(m)
    build_curtains(m)
    build_ceiling_lights(m)
    build_radiator(m)

    n_desks = 0
    for cy in ROWS:
        for cx in COLS:
            jx = rng.uniform(-0.05, 0.05)
            jy = rng.uniform(-0.04, 0.04)
            ja = rng.uniform(-4.0, 4.0)
            build_desk(cx + jx, cy + jy, ja, m)
            # Стул СО СТОРОНЫ ЗАДНЕЙ стены и развёрнут на 180: ученик сидит
            # лицом к доске. Первый рендер посадил весь класс спиной к ней.
            build_chair(cx + jx, cy + jy - DESK_D / 2 - 0.16,
                        ja + 180 + rng.uniform(-6, 6), m)
            n_desks += 1

    # Развёртка под фотосканы — после всей геометрии (булевы меняют сетку).
    scanned = 0
    for obj in scene.objects:
        if obj.type != "MESH":
            continue
        tiles = [sl.material["tile_m"] for sl in obj.material_slots
                 if sl.material is not None and "tile_m" in sl.material]
        if tiles:
            box_uv(obj, tiles[0])
            scanned += 1
    print(f"CLASSROOM_UV объектов с фотосканной развёрткой: {scanned}")

    d = setup_light(scene, args, glass)
    cam_data = bpy.data.cameras.new("cam")
    cam_data.lens = args.lens
    cam_data.clip_start = 0.02
    cam_data.clip_end = 200
    cam = link(bpy.data.objects.new("cam", cam_data))
    loc = Vector([float(v) for v in args.cam.split(",")])
    look = Vector([float(v) for v in args.look.split(",")])
    cam.location = loc
    cam.rotation_euler = (look - loc).to_track_quat("-Z", "Y").to_euler()
    scene.camera = cam

    device = setup_cycles(scene, args.samples)

    w, h = (int(v) for v in args.res.lower().split("x"))
    scene.render.resolution_x = w
    scene.render.resolution_y = h
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.view_settings.view_transform = args.view_transform
    scene.view_settings.exposure = args.exposure
    try:
        scene.view_settings.look = "None"
    except TypeError:
        pass

    out = args.out.rstrip("/")
    scene.render.filepath = f"{out}/classroom"
    bpy.ops.render.render(write_still=True)
    print("CLASSROOM_VIEW_OK classroom")

    if args.blend:
        bpy.ops.wm.save_as_mainfile(filepath=args.blend)

    faces = sum(len(o.data.polygons) for o in scene.objects if o.type == "MESH")
    stats = {
        "объектов": len([o for o in scene.objects if o.type == "MESH"]),
        "граней": faces,
        "парт": n_desks,
        "окон": len(WIN_BAYS),
        "устройство": device,
        "солнце_летит": [round(v, 3) for v in d],
        "габариты_м": [WIDTH, LENGTH, HEIGHT],
    }
    print("CLASSROOM_STATS " + json.dumps(stats, ensure_ascii=False))
    print("CLASSROOM_DONE")


if __name__ == "__main__":
    main()
