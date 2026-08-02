"""Сборка школьного коридора — исполняется внутри Blender, не в venv проекта.

    blender -b --factory-startup -noaudio -P corridor.py -- \
        --out data/output/loc_corridor --res 1366x768 --samples 128

Локация замкнутая: пол, потолок, четыре стены, включая стену за спиной у
камеры. Это не педантизм, а условие освещения — единственный источник света
здесь солнце СНАРУЖИ правой стены, и весь свет попадает внутрь только через
оконные проёмы. Стоит оставить коробку открытой, и мимо стен затечёт заливка
из мира: пропадут и контраст, и тёмный дальний конец, ради которых кадр и
собирается.

Геометрия строится сразу в мировых координатах, у всех объектов начало в
нуле. Тогда Object-координаты совпадают с мировыми, и процедурные текстуры
(доски пола, штукатурка) идут единым непрерывным полотном через все куски
стены, а не начинаются заново на каждом боксе.
"""
from __future__ import annotations

import argparse
import json
import math
import sys

from pathlib import Path

import bpy
from mathutils import Vector

# --------------------------------------------------------------------------- #
# Размеры. Метры, как и принято в Blender по умолчанию.
# --------------------------------------------------------------------------- #

WIDTH = 2.7           # чистая ширина коридора
LENGTH = 15.0         # от ближней стены (y=0) до дальней (y=LENGTH)
HEIGHT = 3.5          # до потолка; старое здание, потолки высокие
WALL_T = 0.35         # толщина стен: даёт глубокие оконные откосы, как на референсе

# Окна правой стены. Числа сняты с референса по двери в торце: у неё
# стандартные 2.05 м, и всё остальное меряется в её высотах. Окно там выходит
# заметно выше и шире нашего прежнего, а простенки - уже.
WIN_Y = (1.9, 4.3, 6.7, 9.1, 11.5)   # пять проёмов с шагом 2.4 вместо четырёх
WIN_W = 1.20                   # ширина проёма
WIN_SILL = 0.85                # низ проёма: на референсе подоконник ниже пояса
WIN_SPRING = 2.35              # пята арки: выше неё проём полукруглый
WIN_R = WIN_W / 2              # радиус арки

# Левая стена
LOCKER_RUNS = ((0.35, 4.60), (9.40, 11.10))   # участки со шкафчиками
LOCKER_W = 0.34                                # ширина одной дверцы
LOCKER_H = 1.92
LOCKER_D = 0.42
DOOR_Y = (5.55, 7.75)                          # двери в левой стене

DOOR_W = 0.95
DOOR_H = 2.15


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--res", default="1366x768")
    p.add_argument("--samples", type=int, default=128)
    p.add_argument("--width", type=float, default=3.10)
    # Ширина сама по себе ощущения простора не даёт: коридор читается
    # широким или узким по ОТНОШЕНИЮ ширины к высоте. Поэтому потолок
    # тоже параметр, а не константа.
    p.add_argument("--height", type=float, default=3.5)
    # Умолчания подобраны прогонами, а не взяты из головы, и связаны между
    # собой: высота солнца решает, сколько окна кладут на ПОЛ, а сколько на
    # левую стену. На 20° почти всё уходило на шкафчики, на 34° по полу идёт
    # цепочка пятен с читаемым переплётом - как на референсе.
    p.add_argument("--sun-elev", type=float, default=34.0,
                   help="высота солнца над горизонтом, градусы")
    p.add_argument("--sun-azim", type=float, default=68.0,
                   help="отклонение от оси коридора; 0 - строго вдоль, "
                        "90 - строго поперёк сквозь окна")
    p.add_argument("--sun-energy", type=float, default=42.0)
    p.add_argument("--sky", type=float, default=2.2,
                   help="заливка неба; она же цвет теней. Выше 4 - контраст "
                        "съедается и дальний конец перестаёт быть тёмным")
    p.add_argument("--haze", type=float, default=0.010,
                   help="плотность дымки; 0 - выключить объёмный свет")
    p.add_argument("--lens", type=float, default=26.0)
    p.add_argument("--cam", default="-0.20,0.80,1.55")
    p.add_argument("--look", default="0.05,15.0,0.95")
    p.add_argument("--view-transform", default="AgX")
    p.add_argument("--exposure", type=float, default=0.0)
    p.add_argument("--blend", default="")
    p.add_argument("--extra-views", action="store_true",
                   help="дополнительно снять пару ракурсов для проверки")
    p.add_argument("--walk", type=int, default=0,
                   help="снять проход по коридору: N кадров вдоль оси. "
                        "Веб-интерфейс листает такую последовательность "
                        "перетаскиванием - получается ход вперёд и назад")
    # Дальше 7-8 метров окна кончаются и коридор уходит в темноту. Для
    # неподвижного кадра это выразительно, для прохода - нет: треть кадров
    # получалась чёрной. Маршрут держим в освещённой части.
    p.add_argument("--walk-span", default="1.0,7.2",
                   help="от какого y до какого идти при --walk")
    p.add_argument("--walk-z", type=float, default=1.60,
                   help="высота глаз при --walk")
    p.add_argument("--plan", action="store_true",
                   help="диагностика: ортокамера сверху со снятым потолком. "
                        "В перспективе дальние световые пятна сжимаются в "
                        "несколько пикселей, и на глаз не отличить «пятна нет» "
                        "от «пятно мелкое». План показывает раскладку как есть")
    return p.parse_args(argv)


# --------------------------------------------------------------------------- #
# Примитивы
# --------------------------------------------------------------------------- #

def link(obj):
    bpy.context.scene.collection.objects.link(obj)
    return obj


def make_box(name, x0, x1, y0, y1, z0, z1, mat=None):
    """Бокс по границам. Нормали наружу."""
    mesh = bpy.data.meshes.new(name)
    verts = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
             (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    faces = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
             (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    if mat:
        mesh.materials.append(mat)
    return link(bpy.data.objects.new(name, mesh))


def make_prism(name, section_yz, x0, x1, mat=None):
    """Призма: контур задан в плоскости YZ, вытянут вдоль X.

    Так делается арочный проём: полукруг поверх прямоугольника — это один
    контур, и никакой булевой операции для самой формы не нужно. Булева
    остаётся только на вычитание готовой призмы из стены.
    """
    n = len(section_yz)
    verts = [(x0, y, z) for y, z in section_yz] + [(x1, y, z) for y, z in section_yz]
    faces = [tuple(range(n - 1, -1, -1)), tuple(range(n, 2 * n))]
    faces += [(i, (i + 1) % n, (i + 1) % n + n, i + n) for i in range(n)]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    if mat:
        mesh.materials.append(mat)
    return link(bpy.data.objects.new(name, mesh))


def arch_section(y_c, half_w, z_bottom, z_spring, segments=20):
    """Контур арочного проёма: прямоугольник, сверху полукруг."""
    pts = [(y_c - half_w, z_bottom), (y_c + half_w, z_bottom), (y_c + half_w, z_spring)]
    for i in range(1, segments):
        t = math.pi * i / segments
        pts.append((y_c + half_w * math.cos(t), z_spring + half_w * math.sin(t)))
    pts.append((y_c - half_w, z_spring))
    return pts


def cut(target, cutter):
    """Вычесть cutter из target и УБЕДИТЬСЯ, что вычлось.

    Модификатор применяется оператором, а оператор Blender возвращает
    FINISHED и тогда, когда ничего не сделал. Единственная надёжная проверка -
    изменение числа граней.
    """
    before = len(target.data.polygons)
    mod = target.modifiers.new(name="cut", type="BOOLEAN")
    mod.object = cutter
    mod.operation = "DIFFERENCE"
    mod.solver = "EXACT"

    bpy.context.view_layer.objects.active = target
    for o in bpy.context.selected_objects:
        o.select_set(False)
    target.select_set(True)
    bpy.ops.object.modifier_apply(modifier=mod.name)

    after = len(target.data.polygons)
    if after == before:
        raise SystemExit(f"CORRIDOR_ERROR булева не сработала на {target.name}: "
                         f"граней как было {before}")
    bpy.data.objects.remove(cutter, do_unlink=True)
    return after - before


# --------------------------------------------------------------------------- #
# Материалы. Всё процедурное: никаких внешних карт, сцена самодостаточна.
# Координаты берутся Object - см. пояснение в шапке модуля.
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
    """Шум с необязательным растягиванием по осям (для вертикальных потёков)."""
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



# --------------------------------------------------------------------------- #
# Фотосканные материалы
# --------------------------------------------------------------------------- #

TEX_DIR = Path("/mnt/d/Develop/photo3d/data/textures")


def box_uv(obj, tile_m):
    """Развёртка проекцией по осям, в МИРОВЫХ координатах.

    Мировые, а не локальные - иначе стык двух объектов с одним материалом
    показывает разрыв рисунка: у каждого своя нулевая точка. В коридоре стена
    собрана из нескольких кусков, и шов был бы виден насквозь.

    Считается руками, а не оператором uv.cube_project: операторам нужен
    контекст окна, которого в фоновом Blender нет, и они падают или молча
    ничего не делают - ровно тот случай, о котором предупреждает CLAUDE.md.
    """
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
    """Материал из фотоскана: цвет, нормаль, шероховатость картинками.

    Такой материал НЕ запекается (bake_scene узнаёт его и пропускает) и уезжает
    в glTF со своим тайлингом. Отсюда и выигрыш: разрешение перестаёт упираться
    в размер атласа на всю поверхность.

    ТОНИРОВАТЬ ЗДЕСЬ НЕЛЬЗЯ, и параметр tint оставлен только затем, чтобы
    сказать об этом вслух. Множитель между текстурой и входом Base Color
    экспортёр glTF выбрасывает целиком: в файле не появляется ни baseColorFactor,
    ни следа правки, а картинка уезжает исходного цвета. Проверено на файле -
    baseColorFactor отсутствует. Та же семья, что и процедурные материалы:
    формат знает Principled с картинками и константами, всё остальное молча
    заменяет умолчанием.

    Тон сцены сводится СВЕТОМ - цветом солнца и рассеянного света в .tscn,
    где его видно и где он не теряется при экспорте.
    """
    if tint is not None:
        raise SystemExit(
            "CORRIDOR_ERROR tint в mat_scanned не работает: множитель между "
            "текстурой и Base Color экспортёр glTF выбрасывает. Сводите тон "
            "светом в сцене либо подберите скан нужного цвета")
    mat, nt, bsdf, coord = _mat(name)
    mat["tile_m"] = tile_m
    d = TEX_DIR / asset
    if not d.is_dir():
        raise SystemExit(f"CORRIDOR_ERROR нет текстур {d}. "
                         f"Прогони scripts/fetch_textures.py")

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
            rng = nt.nodes.new("ShaderNodeMapRange")
            rng.location = (-450, 0)
            rng.inputs["To Min"].default_value = rough_range[0]
            rng.inputs["To Max"].default_value = rough_range[1]
            nt.links.new(rng.inputs["Value"], rough.outputs["Color"])
            nt.links.new(bsdf.inputs["Roughness"], rng.outputs["Result"])
        else:
            nt.links.new(bsdf.inputs["Roughness"], rough.outputs["Color"])

    nor = _tex(nt, d, "nor", "Non-Color", (-800, -300))
    if nor is not None:
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nm.location = (-450, -300)
        nt.links.new(nm.inputs["Color"], nor.outputs["Color"])
        nt.links.new(bsdf.inputs["Normal"], nm.outputs["Normal"])
    return mat


def mat_floor():
    """Доски вдоль коридора, разнотон между досками, продольная свиль."""
    mat, nt, bsdf, coord = _mat("floor_wood")

    # Кирпичная текстура как раскладка досок: ряд - доска. Поворот на 90°
    # вокруг Z ставит длинную сторону вдоль коридора.
    mapping = nt.nodes.new("ShaderNodeMapping")
    mapping.location = (-1200, 0)
    mapping.inputs["Rotation"].default_value = (0, 0, math.radians(90))
    nt.links.new(mapping.inputs["Vector"], coord.outputs["Object"])

    brick = nt.nodes.new("ShaderNodeTexBrick")
    brick.location = (-950, 0)
    brick.offset = 0.37
    brick.offset_frequency = 2
    brick.squash = 1.0
    brick.inputs["Scale"].default_value = 1.0
    brick.inputs["Mortar Size"].default_value = 0.006
    brick.inputs["Brick Width"].default_value = 2.4     # длина доски
    brick.inputs["Row Height"].default_value = 0.155    # ширина доски
    brick.inputs["Bias"].default_value = 0.0
    # Разброс между досками намеренно заметный: на первом прогоне пол вышел
    # ровным коричневым полем, и раскладка читалась только по швам.
    brick.inputs["Color1"].default_value = (0.300, 0.180, 0.095, 1)
    brick.inputs["Color2"].default_value = (0.430, 0.270, 0.150, 1)
    brick.inputs["Mortar"].default_value = (0.030, 0.016, 0.009, 1)
    nt.links.new(brick.inputs["Vector"], mapping.outputs["Vector"])

    # Свиль: шум, сплющенный поперёк доски - получаются продольные волокна.
    grain = _noise(nt, coord, 18.0, 8.0, (-950, -320), stretch=(1.0, 0.06, 1.0))
    grain_mix = nt.nodes.new("ShaderNodeMixRGB")
    grain_mix.location = (-620, 0)
    grain_mix.blend_type = "MULTIPLY"
    grain_mix.inputs["Fac"].default_value = 0.35
    nt.links.new(grain_mix.inputs["Color1"], brick.outputs["Color"])
    nt.links.new(grain_mix.inputs["Color2"], grain.outputs["Fac"])

    # Крупные пятна затёртости — пол старый и мытый неровно.
    wear = _noise(nt, coord, 0.9, 4.0, (-950, -620))
    wear_mix = nt.nodes.new("ShaderNodeMixRGB")
    wear_mix.location = (-400, 0)
    wear_mix.blend_type = "MULTIPLY"
    wear_mix.inputs["Fac"].default_value = 0.30
    nt.links.new(wear_mix.inputs["Color1"], grain_mix.outputs["Color"])
    nt.links.new(wear_mix.inputs["Color2"], wear.outputs["Fac"])

    # Вытоптанная дорожка посередине. Это главное отличие живого пола от
    # ровно зашумлённого: у поверхности должна быть ПАМЯТЬ о том, что по ней
    # ходили, а шум её не даёт - он не знает, где середина коридора.
    #
    # Считается по координате поперёк прохода: |x| мало - середина. Дорожка
    # темнее (грязь втоптана) и ГЛАДЧЕ (лак отполирован подошвами), поэтому
    # она же входит в шероховатость ниже.
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    sep.location = (-1200, -900)
    nt.links.new(sep.inputs["Vector"], coord.outputs["Object"])
    across = nt.nodes.new("ShaderNodeMath")
    across.location = (-1030, -900)
    across.operation = "ABSOLUTE"
    nt.links.new(across.inputs[0], sep.outputs["X"])
    path = nt.nodes.new("ShaderNodeMapRange")
    path.location = (-870, -900)
    path.inputs["From Min"].default_value = 0.35   # ядро дорожки
    path.inputs["From Max"].default_value = 1.25   # край, дальше чистый пол
    path.inputs["To Min"].default_value = 0.0      # 0 - вытоптано
    path.inputs["To Max"].default_value = 1.0
    path.clamp = True
    nt.links.new(path.inputs["Value"], across.outputs["Value"])
    # Край дорожки не по линейке: подмешиваем крупный шум, иначе выйдет
    # нарисованная полоса, а не след ходьбы.
    path_noise = _noise(nt, coord, 1.6, 3.0, (-1030, -1150))
    path_mix = nt.nodes.new("ShaderNodeMixRGB")
    path_mix.location = (-700, -900)
    path_mix.blend_type = "MIX"
    path_mix.inputs["Fac"].default_value = 0.35
    nt.links.new(path_mix.inputs["Color1"], path.outputs["Result"])
    nt.links.new(path_mix.inputs["Color2"], path_noise.outputs["Fac"])

    walk_dark = nt.nodes.new("ShaderNodeMixRGB")
    walk_dark.location = (-230, 0)
    walk_dark.blend_type = "MULTIPLY"
    walk_dark.inputs["Fac"].default_value = 0.45
    nt.links.new(walk_dark.inputs["Color1"], wear_mix.outputs["Color"])
    nt.links.new(walk_dark.inputs["Color2"], path_mix.outputs["Color"])
    nt.links.new(bsdf.inputs["Base Color"], walk_dark.outputs["Color"])

    # Лак вытерт пятнами: блеск неоднородный, иначе пол читается пластиком.
    rough = nt.nodes.new("ShaderNodeMapRange")
    rough.location = (-400, -400)
    rough.inputs["To Min"].default_value = 0.28
    rough.inputs["To Max"].default_value = 0.62
    nt.links.new(rough.inputs["Value"], wear.outputs["Fac"])
    # Дорожка глаже остального пола: подошвы полируют. Берём минимум из двух -
    # где вытоптано, там блеск, независимо от пятен лака.
    rough_path = nt.nodes.new("ShaderNodeMapRange")
    rough_path.location = (-400, -640)
    rough_path.inputs["To Min"].default_value = 0.16
    rough_path.inputs["To Max"].default_value = 0.70
    nt.links.new(rough_path.inputs["Value"], path_mix.outputs["Color"])
    rough_min = nt.nodes.new("ShaderNodeMath")
    rough_min.location = (-230, -500)
    rough_min.operation = "MINIMUM"
    nt.links.new(rough_min.inputs[0], rough.outputs["Result"])
    nt.links.new(rough_min.inputs[1], rough_path.outputs["Result"])
    nt.links.new(bsdf.inputs["Roughness"], rough_min.outputs["Value"])

    bump = nt.nodes.new("ShaderNodeBump")
    bump.location = (-200, -600)
    bump.inputs["Strength"].default_value = 0.4
    nt.links.new(bump.inputs["Height"], brick.outputs["Fac"])
    nt.links.new(bsdf.inputs["Normal"], bump.outputs["Normal"])
    return mat


def mat_plaster(name, color, streaks=0.35):
    """Штукатурка с вертикальными потёками и разводами."""
    mat, nt, bsdf, coord = _mat(name)

    base = nt.nodes.new("ShaderNodeRGB")
    base.location = (-700, 200)
    base.outputs[0].default_value = (*color, 1)

    dirt = nt.nodes.new("ShaderNodeRGB")
    dirt.location = (-700, 0)
    dirt.outputs[0].default_value = (color[0] * 0.55, color[1] * 0.55,
                                     color[2] * 0.58, 1)

    # Потёки: шум, растянутый по вертикали в пятнадцать раз.
    streak = _noise(nt, coord, 3.0, 8.0, (-950, -250), stretch=(1.0, 1.0, 0.07))
    stains = _noise(nt, coord, 0.55, 4.0, (-950, -550))

    fac = nt.nodes.new("ShaderNodeMixRGB")
    fac.location = (-620, -400)
    fac.blend_type = "MULTIPLY"
    fac.inputs["Fac"].default_value = 1.0
    nt.links.new(fac.inputs["Color1"], streak.outputs["Fac"])
    nt.links.new(fac.inputs["Color2"], stains.outputs["Fac"])

    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.location = (-420, -400)
    ramp.color_ramp.elements[0].position = 0.30
    ramp.color_ramp.elements[1].position = 0.75
    nt.links.new(ramp.inputs["Fac"], fac.outputs["Color"])

    mix = nt.nodes.new("ShaderNodeMixRGB")
    mix.location = (-200, 100)
    mix.inputs["Fac"].default_value = streaks
    nt.links.new(mix.inputs["Fac"], ramp.outputs["Color"])
    nt.links.new(mix.inputs["Color1"], dirt.outputs[0])
    nt.links.new(mix.inputs["Color2"], base.outputs[0])

    # Затёртость у пола. Стену пачкают снизу - обувью, швабрами, спинами
    # сидящих; на референсе низ стены заметно грязнее верха, и без этого
    # штукатурка читается свежепокрашенной. Высота берётся из координаты Z,
    # а край размывается шумом, иначе выйдет ровная полоса по линейке.
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    sep.location = (-950, -900)
    nt.links.new(sep.inputs["Vector"], coord.outputs["Object"])
    low = nt.nodes.new("ShaderNodeMapRange")
    low.location = (-780, -900)
    low.inputs["From Min"].default_value = 0.05    # у самого пола - грязнее всего
    low.inputs["From Max"].default_value = 1.15    # выше пояса уже чисто
    low.inputs["To Min"].default_value = 0.0
    low.inputs["To Max"].default_value = 1.0
    low.clamp = True
    nt.links.new(low.inputs["Value"], sep.outputs["Z"])
    low_noise = _noise(nt, coord, 2.2, 4.0, (-780, -1150))
    low_mix = nt.nodes.new("ShaderNodeMixRGB")
    low_mix.location = (-560, -900)
    low_mix.blend_type = "MIX"
    low_mix.inputs["Fac"].default_value = 0.4
    nt.links.new(low_mix.inputs["Color1"], low.outputs["Result"])
    nt.links.new(low_mix.inputs["Color2"], low_noise.outputs["Fac"])

    grime = nt.nodes.new("ShaderNodeMixRGB")
    grime.location = (-40, 100)
    grime.blend_type = "MULTIPLY"
    grime.inputs["Fac"].default_value = 0.55
    nt.links.new(grime.inputs["Color1"], mix.outputs["Color"])
    nt.links.new(grime.inputs["Color2"], low_mix.outputs["Color"])
    nt.links.new(bsdf.inputs["Base Color"], grime.outputs["Color"])

    bsdf.inputs["Roughness"].default_value = 0.92
    fine = _noise(nt, coord, 60.0, 2.0, (-420, -800))
    bump = nt.nodes.new("ShaderNodeBump")
    bump.location = (-200, -700)
    bump.inputs["Strength"].default_value = 0.2
    nt.links.new(bump.inputs["Height"], fine.outputs["Fac"])
    nt.links.new(bsdf.inputs["Normal"], bump.outputs["Normal"])
    return mat


def mat_metal(name, color, rough=0.42, metallic=0.65):
    mat, nt, bsdf, coord = _mat(name)
    n = _noise(nt, coord, 22.0, 3.0, (-900, -200))
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.location = (-650, -200)
    ramp.color_ramp.elements[0].position = 0.35
    ramp.color_ramp.elements[1].position = 0.72
    ramp.color_ramp.elements[0].color = (color[0] * 0.75, color[1] * 0.75,
                                         color[2] * 0.75, 1)
    ramp.color_ramp.elements[1].color = (*color, 1)
    nt.links.new(ramp.inputs["Fac"], n.outputs["Fac"])
    nt.links.new(bsdf.inputs["Base Color"], ramp.outputs["Color"])
    bsdf.inputs["Metallic"].default_value = metallic
    rr = nt.nodes.new("ShaderNodeMapRange")
    rr.location = (-650, -500)
    rr.inputs["To Min"].default_value = rough - 0.10
    rr.inputs["To Max"].default_value = rough + 0.14
    nt.links.new(rr.inputs["Value"], n.outputs["Fac"])
    nt.links.new(bsdf.inputs["Roughness"], rr.outputs["Result"])
    return mat


def mat_wood(name, color, rough=0.48):
    mat, nt, bsdf, coord = _mat(name)
    grain = _noise(nt, coord, 26.0, 8.0, (-900, -200), stretch=(1.0, 1.0, 0.10))
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.location = (-650, -200)
    ramp.color_ramp.elements[0].color = (color[0] * 0.62, color[1] * 0.62,
                                         color[2] * 0.62, 1)
    ramp.color_ramp.elements[1].color = (*color, 1)
    nt.links.new(ramp.inputs["Fac"], grain.outputs["Fac"])
    nt.links.new(bsdf.inputs["Base Color"], ramp.outputs["Color"])
    bsdf.inputs["Roughness"].default_value = rough
    return mat


def mat_flat(name, color, rough=0.55, metallic=0.0):
    mat, nt, bsdf, _ = _mat(name)
    bsdf.inputs["Base Color"].default_value = (*color, 1)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metallic
    return mat


def mat_glass():
    """Стекло намеренно почти без преломления: IOR 1.02.

    Настоящее стекло с IOR 1.45 ломает солнечный прямоугольник на полу в
    размытое пятно и добавляет каустику, которую Cycles на таких выборках
    только зашумит. Здесь стекло нужно как лёгкий блик на плоскости, а
    рисунок переплёта на полу должен остаться чётким.
    """
    mat, nt, bsdf, _ = _mat("glass")
    bsdf.inputs["Base Color"].default_value = (0.85, 0.90, 0.95, 1)
    bsdf.inputs["Roughness"].default_value = 0.03
    bsdf.inputs["IOR"].default_value = 1.02
    for socket in ("Transmission Weight", "Transmission"):
        if socket in bsdf.inputs:
            bsdf.inputs[socket].default_value = 1.0
            break
    return mat


# --------------------------------------------------------------------------- #
# Геометрия
# --------------------------------------------------------------------------- #

def build_shell(m):
    """Коробка: пол, потолок, четыре стены. Ближняя стена за камерой -
    без неё свет вытекает наружу и коридор перестаёт быть замкнутым."""
    x0, x1 = -WIDTH / 2, WIDTH / 2
    make_box("floor", x0 - WALL_T, x1 + WALL_T, -WALL_T, LENGTH + WALL_T,
             -0.25, 0.0, m["floor"])
    make_box("ceiling", x0 - WALL_T, x1 + WALL_T, -WALL_T, LENGTH + WALL_T,
             HEIGHT, HEIGHT + 0.25, m["ceil"])
    make_box("wall_left", x0 - WALL_T, x0, -WALL_T, LENGTH + WALL_T, 0, HEIGHT,
             m["wall"])
    make_box("wall_far", x0, x1, LENGTH, LENGTH + WALL_T, 0, HEIGHT, m["wall"])
    make_box("wall_near", x0, x1, -WALL_T, 0.0, 0, HEIGHT, m["wall"])
    right = make_box("wall_right", x1, x1 + WALL_T, -WALL_T, LENGTH + WALL_T,
                     0, HEIGHT, m["wall"])

    # Плинтус по обеим стенам — стык стены с полом на референсе выражен.
    make_box("skirt_left", x0, x0 + 0.03, 0, LENGTH, 0, 0.12, m["trim"])
    make_box("skirt_right", x1 - 0.03, x1, 0, LENGTH, 0, 0.12, m["trim"])
    return right


def build_windows(right_wall, m):
    """Проёмы в правой стене, откосы, переплёты, стёкла, подоконники."""
    x1 = WIDTH / 2
    glass_objs = []
    for i, y in enumerate(WIN_Y):
        section = arch_section(y, WIN_R, WIN_SILL, WIN_SPRING)
        cutter = make_prism(f"cut{i}", section, x1 - 0.05, x1 + WALL_T + 0.05)
        cut(right_wall, cutter)

        # Стекло на всю форму проёма, ближе к улице.
        glass = make_prism(f"glass{i}", arch_section(y, WIN_R - 0.04, WIN_SILL,
                                                     WIN_SPRING),
                           x1 + WALL_T - 0.10, x1 + WALL_T - 0.07, m["glass"])
        glass_objs.append(glass)

        # Рама по краю проёма: четыре бруска прямоугольной части.
        fx0, fx1 = x1 + WALL_T - 0.14, x1 + WALL_T - 0.06
        for name, y0, y1, z0, z1 in (
            ("l", y - WIN_R, y - WIN_R + 0.05, WIN_SILL, WIN_SPRING),
            ("r", y + WIN_R - 0.05, y + WIN_R, WIN_SILL, WIN_SPRING),
            ("b", y - WIN_R, y + WIN_R, WIN_SILL, WIN_SILL + 0.05),
        ):
            make_box(f"frame{i}{name}", fx0, fx1, y0, y1, z0, z1, m["frame"])

        # Переплёт: два столбика и две перекладины - на референсе окно
        # разбито примерно на 2x3 стекла.
        make_box(f"mull{i}", fx0, fx1, y - 0.02, y + 0.02, WIN_SILL, WIN_SPRING,
                 m["frame"])
        span = WIN_SPRING - WIN_SILL
        for k in (1, 2):
            z = WIN_SILL + span * k / 3
            make_box(f"trans{i}{k}", fx0, fx1, y - WIN_R, y + WIN_R,
                     z - 0.02, z + 0.02, m["frame"])

        # Подоконник внутрь коридора.
        make_box(f"sill{i}", x1 - 0.09, x1 + WALL_T - 0.05,
                 y - WIN_R - 0.10, y + WIN_R + 0.10,
                 WIN_SILL - 0.06, WIN_SILL, m["trim"])

        # Пилястра между окнами: на референсе простенки с выступом.
        if i:
            y_mid = (WIN_Y[i - 1] + y) / 2
            # Узкая и того же тона, что стена: широкая деревянная пилястра
            # читалась в кадре бежевой колонной и спорила с окнами.
            make_box(f"pil{i}", x1 - 0.045, x1, y_mid - 0.13, y_mid + 0.13,
                     0.12, HEIGHT, m["wall"])
    return glass_objs


def build_lockers(m):
    """Ряды шкафчиков вдоль левой стены: корпус, дверцы, жалюзи, ручки."""
    x0 = -WIDTH / 2
    n_doors = 0
    for run_i, (y_start, y_end) in enumerate(LOCKER_RUNS):
        make_box(f"lockbody{run_i}", x0, x0 + LOCKER_D, y_start, y_end,
                 0, LOCKER_H, m["locker"])
        y = y_start
        while y + LOCKER_W <= y_end + 1e-6:
            d0, d1 = y + 0.012, y + LOCKER_W - 0.012
            xd = x0 + LOCKER_D
            make_box(f"lockdoor{run_i}_{n_doors}", xd - 0.015, xd + 0.012,
                     d0, d1, 0.06, LOCKER_H - 0.05, m["locker"])
            # Жалюзи вверху дверцы
            for k in range(4):
                z = LOCKER_H - 0.20 - k * 0.055
                make_box(f"vent{run_i}_{n_doors}_{k}", xd + 0.012, xd + 0.020,
                         d0 + 0.05, d1 - 0.05, z, z + 0.022, m["locker"])
            make_box(f"handle{run_i}_{n_doors}", xd + 0.012, xd + 0.035,
                     d1 - 0.10, d1 - 0.04, 1.05, 1.20, m["handle"])
            y += LOCKER_W
            n_doors += 1
    return n_doors


def build_doors(m):
    """Двери левой стены и одна в торце — с наличниками."""
    x0 = -WIDTH / 2
    for i, y in enumerate(DOOR_Y):
        make_box(f"door{i}", x0, x0 + 0.05, y - DOOR_W / 2, y + DOOR_W / 2,
                 0, DOOR_H, m["door"])
        # Филёнки: две утопленные панели
        for k, (z0, z1) in enumerate(((0.25, 0.95), (1.15, 1.95))):
            make_box(f"panel{i}{k}", x0 + 0.05, x0 + 0.062,
                     y - DOOR_W / 2 + 0.11, y + DOOR_W / 2 - 0.11, z0, z1,
                     m["door"])
        for name, y0, y1, z0, z1 in (
            ("l", y - DOOR_W / 2 - 0.08, y - DOOR_W / 2, 0, DOOR_H + 0.08),
            ("r", y + DOOR_W / 2, y + DOOR_W / 2 + 0.08, 0, DOOR_H + 0.08),
            ("t", y - DOOR_W / 2 - 0.08, y + DOOR_W / 2 + 0.08, DOOR_H, DOOR_H + 0.08),
        ):
            make_box(f"arch{i}{name}", x0, x0 + 0.075, y0, y1, z0, z1, m["trim"])
        make_box(f"knob{i}", x0 + 0.05, x0 + 0.09, y + DOOR_W / 2 - 0.16,
                 y + DOOR_W / 2 - 0.10, 1.02, 1.08, m["handle"])

    # Дверь в торце — точка схода кадра, она должна быть по центру.
    make_box("door_far", -DOOR_W / 2, DOOR_W / 2, LENGTH - 0.05, LENGTH,
             0, DOOR_H, m["door"])
    for k, (z0, z1) in enumerate(((0.25, 0.95), (1.15, 1.95))):
        make_box(f"farpanel{k}", -DOOR_W / 2 + 0.11, DOOR_W / 2 - 0.11,
                 LENGTH - 0.062, LENGTH - 0.05, z0, z1, m["door"])
    for name, x_a, x_b in (("l", -DOOR_W / 2 - 0.08, -DOOR_W / 2),
                           ("r", DOOR_W / 2, DOOR_W / 2 + 0.08)):
        make_box(f"fararch{name}", x_a, x_b, LENGTH - 0.075, LENGTH,
                 0, DOOR_H + 0.08, m["trim"])
    make_box("fararch_t", -DOOR_W / 2 - 0.08, DOOR_W / 2 + 0.08,
             LENGTH - 0.075, LENGTH, DOOR_H, DOOR_H + 0.08, m["trim"])


def build_props(m):
    """Потолочные светильники и мусор на полу.

    Лампы намеренно ВЫКЛЮЧЕНЫ: на референсе они тёмные, и весь смысл кадра в
    том, что коридор освещён только улицей. Включить их - потерять картинку.
    """
    for i, y in enumerate((4.5, 8.5, 12.5)):
        make_box(f"lamp{i}", -0.62, 0.62, y - 0.09, y + 0.09,
                 HEIGHT - 0.10, HEIGHT, m["lamp"])

    # Пара отвалившихся половиц — на референсе они лежат в световых пятнах.
    plank = make_box("debris0", -0.95, -0.25, 3.10, 3.24, 0.0, 0.028, m["floor"])
    plank.rotation_euler = (0, 0, math.radians(-9))
    plank = make_box("debris1", 0.35, 1.05, 5.55, 5.70, 0.0, 0.028, m["floor"])
    plank.rotation_euler = (0, 0, math.radians(6))


# --------------------------------------------------------------------------- #
# Свет, камера, рендер
# --------------------------------------------------------------------------- #

def sun_direction(elev_deg, azim_deg):
    """Куда ЛЕТИТ свет. Азимут отсчитывается от оси коридора.

    Знаки заданы жёстко и в этом весь смысл: -X значит «внутрь коридора от
    правой стены», то есть солнце снаружи той стены, где окна. -Y значит «от
    дальнего конца к камере» - именно поэтому оконные пятна вытягиваются по
    полу к зрителю, а не уходят в глубину.
    """
    e, a = math.radians(elev_deg), math.radians(azim_deg)
    horiz = math.cos(e)
    return Vector((-math.sin(a) * horiz, -math.cos(a) * horiz, -math.sin(e)))


def setup_light(scene, args, glass_objs):
    d = sun_direction(args.sun_elev, args.sun_azim)

    data = bpy.data.lights.new("sun", type="SUN")
    data.energy = args.sun_energy
    data.color = (1.0, 0.87, 0.70)      # низкое солнце, тёплое
    data.angle = math.radians(1.2)      # края пятен чуть мягкие, но читаемые
    sun = link(bpy.data.objects.new("sun", data))
    sun.location = Vector((WIDTH, LENGTH * 0.7, HEIGHT * 2)) - d * 10
    sun.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()

    # Стекло не должно ловить теневой луч: физически прозрачная поверхность
    # в Cycles всё равно перекрывает прямой свет, и вместо солнечных
    # прямоугольников на полу получается ровный сумрак.
    for g in glass_objs:
        g.visible_shadow = False

    world = bpy.data.worlds.new("sky")
    world.use_nodes = True
    nt = world.node_tree
    bg = nt.nodes["Background"]
    bg.inputs[0].default_value = (0.55, 0.68, 0.92, 1)
    bg.inputs[1].default_value = args.sky
    scene.world = world

    if args.haze > 0:
        build_haze(scene, args.haze)
    return d


def build_haze(scene, density):
    """Пыль в воздухе — ограниченным объёмом внутри коридора, не объёмом мира.

    Первая попытка вешала Volume Scatter на мир, и кадр выходил ЧЁРНЫМ
    целиком. Причина не в плотности: объём мира бесконечен, солнце светит
    из бесконечности, и на пути к сцене луч проходит бесконечную толщу
    среды - ослабление exp(-d*L) при L=∞ обнуляет прямой свет при любой
    сколь угодно малой плотности. Коробка даёт конечную толщу, и солнце
    доходит.
    """
    box = make_box("haze", -WIDTH / 2, WIDTH / 2, 0.0, LENGTH, 0.0, HEIGHT)
    mat = bpy.data.materials.new("haze")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.remove(nt.nodes["Principled BSDF"])   # только объём, без поверхности
    scatter = nt.nodes.new("ShaderNodeVolumeScatter")
    scatter.inputs["Density"].default_value = density
    scatter.inputs["Anisotropy"].default_value = 0.45   # рассеяние вперёд, лучи видны
    nt.links.new(nt.nodes["Material Output"].inputs["Volume"],
                 scatter.outputs["Volume"])
    box.data.materials.append(mat)
    # Без отскоков внутри среды рассеянный луч просто гибнет, и дымка
    # работает как поглотитель: картинка темнеет, а лучей не появляется.
    scene.cycles.volume_bounces = 2


def setup_camera(scene, args):
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
    return cam


def setup_cycles(scene, samples):
    scene.render.engine = "CYCLES"
    scene.cycles.samples = samples
    scene.cycles.use_denoising = True
    scene.cycles.max_bounces = 10
    # Замкнутая коробка живёт переотражениями: почти всё, что видно вне
    # солнечных пятен, - это второй и третий диффузный отскок. На дефолтных
    # четырёх дальний конец коридора проваливается в чёрное.
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
    return device


def main():
    global WIDTH, HEIGHT
    args = parse_args()
    WIDTH = args.width
    HEIGHT = args.height
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene

    m = {
        # Пол и стены - фотосканы, а не шум. Это две поверхности, занимающие
        # почти весь кадр, и на них разница видна сразу: у скана есть история
        # (сучки, стыки, потёртости в конкретных местах), а шум даёт лишь
        # равномерную рябь. Тайлинг два и три метра, тон подогнан множителем.
        "floor": mat_scanned("floor_wood", "brown_planks_09", 1.6,
                             rough_range=(0.30, 0.70)),
        # Палитра сведена по референсу. Главная правка - стены: были насыщенно
        # синие, отчего коридор читался ночным. На референсе штукатурка светлая
        # и почти серая, а холод в кадр приносит НЕ краска, а свет в тени;
        # насыщенная стена спорит с этим и съедает тёплые пятна солнца.
        # Скан бежевый. Тонировать его в шейдере бесполезно - множитель не
        # переживает экспорт (см. mat_scanned), а холод в кадр всё равно
        # приносит свет, а не краска.
        "wall": mat_scanned("wall_plaster", "beige_wall_001", 3.0,
                            rough_range=(0.75, 0.95)),
        "ceil": mat_plaster("ceiling_plaster", (0.30, 0.32, 0.37), streaks=0.25),
        "locker": mat_metal("locker_metal", (0.38, 0.40, 0.37)),
        "handle": mat_metal("handle_metal", (0.62, 0.63, 0.60), 0.30, 0.9),
        "door": mat_wood("door_wood", (0.28, 0.155, 0.09)),
        "trim": mat_wood("trim_wood", (0.52, 0.44, 0.35), 0.55),
        "frame": mat_flat("frame_paint", (0.72, 0.70, 0.66), 0.60),
        "lamp": mat_flat("lamp_plastic", (0.78, 0.79, 0.80), 0.45),
        "glass": mat_glass(),
    }

    right = build_shell(m)
    glass = build_windows(right, m)
    doors = build_lockers(m)
    build_doors(m)
    build_props(m)

    # Развёртка под фотосканы. Делается ПОСЛЕ всей геометрии: булевы вырезы
    # окон и дверей меняют сетку, и развёртка, построенная до них, на новых
    # гранях просто отсутствовала бы.
    scanned = 0
    for obj in scene.objects:
        if obj.type != "MESH":
            continue
        tiles = [sl.material["tile_m"] for sl in obj.material_slots
                 if sl.material is not None and "tile_m" in sl.material]
        if tiles:
            box_uv(obj, tiles[0])
            scanned += 1
    print(f"CORRIDOR_UV объектов с фотосканной развёрткой: {scanned}")

    d = setup_light(scene, args, glass)
    cam = setup_camera(scene, args)
    device = setup_cycles(scene, args.samples)

    if args.plan:
        bpy.data.objects["ceiling"].hide_render = True
        cam.data.type = "ORTHO"
        cam.data.ortho_scale = LENGTH + 1.0
        cam.location = (0.0, LENGTH / 2, 12.0)
        cam.rotation_euler = (0.0, 0.0, 0.0)

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

    if args.walk:
        # Именно проход, а не панорама с одной точки. Панораму я снял первой:
        # коридор шириной три метра, и при повороте вокруг себя половина
        # кадров - стена шкафчиков в полутора метрах от объектива. Локация
        # вытянута вдоль, поэтому показывать её надо движением вдоль.
        cam = scene.camera
        y0, y1 = (float(v) for v in args.walk_span.split(","))
        for i in range(args.walk):
            y = y0 + (y1 - y0) * i / max(args.walk - 1, 1)
            cam.location = Vector((0.0, y, args.walk_z))
            target = Vector((0.05, LENGTH, args.walk_z - 0.45))
            cam.rotation_euler = (target - cam.location).to_track_quat(
                "-Z", "Y").to_euler()
            scene.render.filepath = f"{out}/{i:03d}"
            bpy.ops.render.render(write_still=True)
            print(f"CORRIDOR_VIEW_OK {i:03d}")
    else:
        scene.render.filepath = f"{out}/corridor"
        bpy.ops.render.render(write_still=True)
        print("CORRIDOR_VIEW_OK corridor")

    if args.extra_views:
        cam = scene.camera
        for name, loc, look in (
            ("mid", (0.60, 6.0, 1.55), (-0.4, 0.5, 1.1)),      # взгляд назад
            ("high", (-0.9, 2.2, 2.60), (0.9, 9.0, 0.6)),      # сверху вдоль
        ):
            cam.location = Vector(loc)
            cam.rotation_euler = (Vector(look) - Vector(loc)).to_track_quat(
                "-Z", "Y").to_euler()
            scene.render.filepath = f"{out}/{name}"
            bpy.ops.render.render(write_still=True)
            print(f"CORRIDOR_VIEW_OK {name}")

    if args.blend:
        bpy.ops.wm.save_as_mainfile(filepath=args.blend)

    faces = sum(len(o.data.polygons) for o in scene.objects if o.type == "MESH")
    stats = {
        "объектов": len([o for o in scene.objects if o.type == "MESH"]),
        "граней": faces,
        "дверец_шкафчиков": doors,
        "окон": len(WIN_Y),
        "устройство": device,
        "солнце_летит": [round(v, 3) for v in d],
        "габариты_м": [WIDTH, LENGTH, HEIGHT],
    }
    print("CORRIDOR_STATS " + json.dumps(stats, ensure_ascii=False))
    print("CORRIDOR_DONE")


if __name__ == "__main__":
    main()
