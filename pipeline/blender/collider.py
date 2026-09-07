"""Оболочка столкновений отдельным файлом — исполняется внутри Blender.

    blender -b --factory-startup -noaudio -P collider.py -- \
        --src model.glb --out collider.glb [--faces 8000]

Зачем отдельно от gameready.py, который умеет то же самое: тот собирает ассет
ДЛЯ ИГРЫ — видимый меш с текстурами плюс оболочку в одном файле. Прогулке в
вебе видимый меш из этого файла не нужен: она показывает исходную модель во
всей плотности, а от оболочки ей нужна только геометрия. Прогнав gameready,
пришлось бы тащить в браузер лишние мегабайты текстур ради полутора тысяч
треугольников пола.

Здесь на выходе один меш без материалов, UV и нормалей — только вершины и
грани. Для m_258aeb это 19 МБ против 0.2 МБ.

Имя меша кончается на `-colonly`: то же соглашение, что у импортёра Godot
(см. gameready.py). Одно правило на оба потребителя — на движок и на веб.
"""
from __future__ import annotations

import argparse
import json
import sys

import bpy


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--src", required=True)
    p.add_argument("--out", required=True)
    # 8000, а не 12000 (порог октодерева в web/static/walk.js): запас нужен,
    # потому что порог измерен на РОВНЫХ сетках, а децимированный скан остаётся
    # неравномерным — треугольники у стен крупные, у мебели мелкие.
    p.add_argument("--faces", type=int, default=8000)
    return p.parse_args(argv)


def tris(obj) -> int:
    return sum(len(p.vertices) - 2 for p in obj.data.polygons)


def main() -> None:
    a = parse_args()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=a.src)

    sources = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not sources:
        raise SystemExit("COLLIDER_ERROR в GLB нет ни одного меша")
    before = sum(tris(o) for o in sources)

    # Свет и камеры выбрасываем сразу: в файле столкновений им делать нечего,
    # а солнце с яркостью в люксах ещё и приехало бы в браузер вторым
    # источником поверх настоящего.
    for o in list(bpy.context.scene.objects):
        if o.type in {"LIGHT", "CAMERA"}:
            bpy.data.objects.remove(o, do_unlink=True)

    # Одна оболочка на всю модель, а не по копии на меш: сотня мелких тел
    # дороже одного крупного, и разбиение на объекты столкновений не касается.
    bpy.ops.object.select_all(action="DESELECT")
    for o in sources:
        o.select_set(True)
    bpy.context.view_layer.objects.active = sources[0]
    if len(sources) > 1:
        bpy.ops.object.join()
    col = bpy.context.view_layer.objects.active

    col.data.materials.clear()
    while col.data.uv_layers:
        col.data.uv_layers.remove(col.data.uv_layers[0])

    if before > a.faces:
        mod = col.modifiers.new(name="collider", type="DECIMATE")
        mod.decimate_type = "COLLAPSE"
        mod.ratio = max(a.faces / before, 0.0001)
        # Без этого на квадах остаются n-угольники, и счётчик, по которому мы
        # судим об успехе, врёт в меньшую сторону.
        mod.use_collapse_triangulate = True
        bpy.context.view_layer.objects.active = col
        bpy.ops.object.modifier_apply(modifier=mod.name)

    after = tris(col)
    # Проверка по счётчику, а не по коду возврата: Decimate отрабатывает молча
    # и на вырожденном входе может не изменить ничего (CLAUDE.md).
    if before > a.faces and after >= before:
        raise SystemExit(
            f"COLLIDER_ERROR децимация ничего не дала: было {before}, стало {after}")

    # Имя обязано КОНЧАТЬСЯ суффиксом: и импортёр Godot, и прогулка смотрят
    # именно на конец строки. Blender дописывает .001 к неуникальным именам,
    # поэтому проверяем результат, а не полагаемся на присваивание.
    col.name = "collision-colonly"
    if not col.name.endswith("-colonly"):
        raise SystemExit(f"COLLIDER_ERROR имя оболочки испорчено: {col.name}")

    bpy.ops.export_scene.gltf(filepath=a.out, export_format="GLB",
                              export_apply=True,
                              export_materials="NONE",
                              export_normals=False)

    print("COLLIDER_STATS " + json.dumps({
        "tris_before": before,
        "tris_after": after,
        "meshes_joined": len(sources),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
