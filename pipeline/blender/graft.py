"""Посадить подробную голову на тело. Исполняется внутри Blender.

    blender -b --factory-startup -noaudio -P graft.py -- \
        --body body.glb --head head.glb --plan graft.json --out merged.glb

Сюда приходит уже готовое преобразование, посчитанное в scripts/graft_head.py.
Здесь только применение и сборка - зато с материалами, которых у trimesh нет.

ГЛАВНАЯ ЛОВУШКА - оси. Матрица считалась над моделью, загруженной trimesh,
а импортёр glTF в Blender разворачивает сцену из Y-вверх в Z-вверх. Матрицу
нельзя переносить как есть: её надо сопрячь тем же поворотом,
M_blender = R * M_gltf * R^-1. Признак, нужно ли это, - какая ось оказалась
вертикальной при расчёте: Y (индекс 1) означает, что trimesh соглашение glTF
сохранил, и сопряжение необходимо.

Мы на этом уже обжигались: модель, повёрнутая на 90 градусов, проходит все
проверки по числам и выглядит бессмыслицей.
"""
import argparse
import json
import sys

import bmesh
import bpy
from mathutils import Matrix, Vector

# glTF: Y вверх. Blender: Z вверх. Импортёр отображает (x, y, z) -> (x, -z, y),
# то есть поворот на +90 градусов вокруг X.
GLTF_TO_BLENDER = Matrix.Rotation(1.5707963267948966, 4, "X")


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--body", required=True)
    p.add_argument("--head", required=True)
    p.add_argument("--plan", required=True)
    p.add_argument("--out", required=True)
    # Насколько ВЫШЕ плоскости стыка оставить тело. Знак тут решает всё:
    # cut_above убирает всё над уровнем, поэтому срез НИЖЕ плоскости удаляет
    # лишнее и оставляет щель, а не нахлёст. Первая версия ошиблась именно
    # здесь, и на стыке зияла чёрная полоса.
    p.add_argument("--overlap", type=float, default=0.06)
    return p.parse_args(argv)


def import_glb(path):
    before = set(bpy.context.scene.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    added = [o for o in bpy.context.scene.objects
             if o not in before and o.type == "MESH"]
    if not added:
        raise SystemExit(f"GRAFT_ERROR: после импорта {path} нет мешей")
    return added


def join(objs, name):
    """Слить список объектов в один. Материалы сохраняются: у объединённого
    меша их становится несколько, и glTF это переваривает."""
    if len(objs) == 1:
        objs[0].name = name
        return objs[0]
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.join()
    obj = bpy.context.view_layer.objects.active
    obj.name = name
    return obj


def cut_plane(obj, axis, level, keep):
    """Отрезать половину меша по плоскости. keep - 'below' или 'above'.

    Оператор bisect в фоновом режиме капризен, поэтому работаем через bmesh:
    он от контекста не зависит.
    """
    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)

    normal = [0.0, 0.0, 0.0]
    normal[axis] = 1.0
    origin = [0.0, 0.0, 0.0]
    origin[axis] = level

    before = len(bm.faces)
    bmesh.ops.bisect_plane(
        bm, geom=list(bm.verts) + list(bm.edges) + list(bm.faces),
        plane_co=Vector(origin), plane_no=Vector(normal),
        clear_outer=(keep == "below"), clear_inner=(keep == "above"),
    )
    after = len(bm.faces)
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return before, after


def main():
    a = parse_args()
    with open(a.plan, encoding="utf-8") as f:
        plan = json.load(f)

    matrix = Matrix([list(row) for row in plan["matrix"]])
    up = int(plan["up_axis"])
    cut = float(plan["cut"])

    if up == 1:
        # trimesh сохранил соглашение glTF - сопрягаем матрицу поворотом,
        # который применил импортёр
        matrix = GLTF_TO_BLENDER @ matrix @ GLTF_TO_BLENDER.inverted()
        cut_axis = 2                       # вертикаль в Blender - Z
        cut_level = cut                    # Y_gltf -> Z_blender, знак не меняется
        note = "оси сопряжены (trimesh был в Y-вверх)"
    elif up == 2:
        cut_axis = 2
        cut_level = cut
        note = "оси совпадают (trimesh уже был в Z-вверх)"
    else:
        raise SystemExit(f"GRAFT_ERROR: неожиданная вертикаль {up}")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    body = join(import_glb(a.body), "body")
    head = join(import_glb(a.head), "head")

    head.matrix_world = matrix @ head.matrix_world

    # Преобразования впечатываются в сами меши. Без этого резка врёт:
    # bmesh работает с данными меша, то есть в ЛОКАЛЬНЫХ координатах объекта,
    # а уровень плоскости посчитан в мировых. У тела они совпадали случайно,
    # а голове мы только что задали матрицу со сдвигом, поворотом и масштабом
    # 0.54 - и плоскость среза уезжала, отрезая пол-лица вместо шеи.
    for obj in (body, head):
        obj.data.transform(obj.matrix_world)
        obj.matrix_world = Matrix.Identity(4)

    # Режем ОБА, по одной плоскости шеи. От головы берётся верх, от тела низ.
    # Плечи и куртка остаются телу - так снимается и вопрос с разным тоном
    # у двух независимо сгенерированных моделей.
    #
    # Телу оставляем немного выше плоскости, чтобы его шея заходила внутрь
    # головы внахлёст. Знак важен: cut_plane(keep="below") убирает всё над
    # уровнем, поэтому уровень НИЖЕ плоскости оставил бы щель.
    span = body.dimensions[cut_axis]
    body_before, body_after = cut_plane(
        body, cut_axis, cut_level + span * a.overlap, keep="below")
    head_before, head_after = cut_plane(
        head, cut_axis, cut_level - span * a.overlap, keep="above")

    merged = join([body, head], "merged")

    bpy.ops.export_scene.gltf(filepath=a.out, export_format="GLB")

    stats = {
        "оси": note,
        "срез_по": "XYZ"[cut_axis],
        "уровень": round(cut_level, 4),
        "тело": f"{body_before} -> {body_after} граней (низ)",
        "голова": f"{head_before} -> {head_after} граней (верх)",
        "граней_итого": len(merged.data.polygons),
        "материалов": len(merged.data.materials),
    }
    print("GRAFT_STATS " + json.dumps(stats, ensure_ascii=False))
    print("GRAFT_DONE")


if __name__ == "__main__":
    main()
