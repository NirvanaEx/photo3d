"""Подготовка модели к игре — исполняется внутри Blender, не в venv.

    blender -b --factory-startup -noaudio -P gameready.py -- \
        --src model.glb --out model_game.glb [--faces 20000] [--collider 1500]

Сгенерированная модель в игру не ставится как есть: TRELLIS отдаёт около
120 тысяч треугольников на предмет, и это цена не столько отрисовки, сколько
СТОЛКНОВЕНИЙ. Замер в вебе на том же классе моделей: 16 000 треугольников -
дерево столкновений строится 199 мс, 40 000 - уже 3.9 с, 296 000 вешают
вкладку на минуты. Цена нелинейна, потому что на плотной сетке треугольник
попадает сразу во много узлов.

Поэтому на выходе ДВА меша в одном файле:

* видимый - децимированный до разумного числа граней, с UV и материалами;
* столкновения - грубая оболочка, названная с суффиксом `-colonly`.

Суффикс не наша выдумка, а соглашение импортёра Godot: узел, чьё имя кончается
на `-colonly`, превращается в StaticBody3D с телом столкновения, а сам меш из
сцены убирается. Так столкновения не надо ни писать, ни настраивать - они
приезжают вместе с ассетом. Своё писать было бы ровно тем случаем, о котором
предупреждает CLAUDE.md.

Результат проверяется по счётчикам треугольников до и после: модификатор
Decimate применяется молча и на плохом входе может не изменить ничего.
"""
from __future__ import annotations

import argparse
import json
import sys

import bpy
from mathutils import Vector


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--src", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--faces", type=int, default=20000,
                   help="целевое число треугольников видимого меша")
    p.add_argument("--collider", type=int, default=1500,
                   help="целевое число треугольников оболочки столкновений")
    p.add_argument("--collider-mode", default="colonly",
                   choices=["colonly", "convcolonly", "none"])
    return p.parse_args(argv)


def tris(obj) -> int:
    """Треугольников в меше. Не len(polygons): у квада их два, у n-угольника n-2."""
    return sum(len(p.vertices) - 2 for p in obj.data.polygons)


def scene_tris(objs) -> int:
    return sum(tris(o) for o in objs)


def meshes() -> list:
    return [o for o in bpy.context.scene.objects if o.type == "MESH"]


def clear_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def decimate(obj, target: int) -> int:
    """Собрать меш до target треугольников. Возвращает, сколько получилось.

    Модификатор применяется, а не оставляется висеть: экспорт glTF вычисляет
    меш сам, но следующий шаг (сборка оболочки столкновений) работает с
    геометрией напрямую, и невыполненный модификатор он бы не увидел.
    """
    have = tris(obj)
    if have <= target or have == 0:
        return have
    mod = obj.modifiers.new(name="gameready", type="DECIMATE")
    mod.decimate_type = "COLLAPSE"
    mod.ratio = max(target / have, 0.0001)
    # use_collapse_triangulate: иначе на сетке из квадов Decimate оставляет
    # n-угольники, и счётчик треугольников после применения врёт в меньшую
    # сторону - а по нему мы и судим об успехе.
    mod.use_collapse_triangulate = True
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=mod.name)
    return tris(obj)


def build_collider(sources: list, target: int, mode: str):
    """Одна грубая оболочка на всю модель.

    Именно одна, а не по копии на каждый меш: столкновения не должны повторять
    разбиение на объекты, а сотня мелких тел дороже одного крупного. У коридора
    мешей 172 - столько отдельных тел строить незачем.
    """
    bpy.ops.object.select_all(action="DESELECT")
    copies = []
    for src in sources:
        dup = src.copy()
        dup.data = src.data.copy()
        bpy.context.collection.objects.link(dup)
        copies.append(dup)
    for c in copies:
        c.select_set(True)
    bpy.context.view_layer.objects.active = copies[0]
    if len(copies) > 1:
        bpy.ops.object.join()
    col = bpy.context.view_layer.objects.active

    # Материалы и развёртка оболочке не нужны и только утяжеляют файл:
    # Godot всё равно выбросит сам меш, оставив одно тело столкновений.
    col.data.materials.clear()
    while col.data.uv_layers:
        col.data.uv_layers.remove(col.data.uv_layers[0])

    got = decimate(col, target)
    # Имя обязано КОНЧАТЬСЯ суффиксом - импортёр смотрит именно на конец.
    # Отсюда и проверка ниже: Blender дописывает .001 к неуникальным именам,
    # и тогда суффикс перестаёт быть последним, а столкновения молча пропадают.
    col.name = f"collision-{mode}"
    if not col.name.endswith(f"-{mode}"):
        raise SystemExit(f"GAMEREADY_ERROR имя оболочки испорчено: {col.name}")
    return col, got


def strip_lights_and_cameras() -> tuple[list, int]:
    """Выбросить свет и камеры: в игре они принадлежат СЦЕНЕ, а не ассету.

    Не косметика. Солнце коридора приезжает внутри GLB с яркостью 28 686
    (Blender пишет люксы, Godot читает их как множитель) - и в тексте сцены
    этого источника не видно вовсе, править его приходится вслепую через
    editable-инстанс. Свет - это художественное решение уровня, и жить он
    должен там, где его видно и где его меняют.

    Число выброшенного возвращается наружу и печатается: молча пропавший свет
    выглядел бы как «сцена почему-то тёмная».
    """
    lights = [o for o in bpy.context.scene.objects if o.type == "LIGHT"]
    cams = [o for o in bpy.context.scene.objects if o.type == "CAMERA"]

    # Параметры выброшенного записываются, а не теряются. Направление солнца -
    # это результат работы над локацией, и восстановить его в сцене на глаз
    # нельзя: пятна света либо ложатся на пол, либо уезжают на стену под
    # потолок. Отдаём в осях Godot (Y вверх), чтобы число можно было положить
    # в .tscn без пересчёта.
    described = []
    for ob in lights:
        d = ob.matrix_world.to_3x3() @ Vector((0.0, 0.0, -1.0))
        d.normalize()
        described.append({
            "name": ob.name,
            "type": ob.data.type,
            "energy_blender": round(ob.data.energy, 2),
            "color": [round(c, 3) for c in ob.data.color],
            # Blender: Z вверх; Godot и glTF: Y вверх, Z на зрителя.
            "dir_godot": [round(d.x, 3), round(d.z, 3), round(-d.y, 3)],
        })

    for ob in lights + cams:
        bpy.data.objects.remove(ob, do_unlink=True)
    return described, len(cams)


def main() -> None:
    a = parse_args()
    clear_scene()
    bpy.ops.import_scene.gltf(filepath=a.src)
    dropped_lights, dropped_cams = strip_lights_and_cameras()

    visual = meshes()
    if not visual:
        print("GAMEREADY_ERROR в файле нет мешей")
        raise SystemExit(1)

    before = scene_tris(visual)
    if before <= a.faces:
        # Модель уже в бюджете - не трогаем вовсе. Коридор весит 2756
        # треугольников на 172 меша, и подушное деление бюджета (по 116 на
        # объект) резало бы его до 2472 без всякой пользы: экономии нет,
        # а форма портится. Децимация - плата за превышение, а не обряд.
        after = before
    else:
        # Бюджет делится между мешами поровну, а не выдаётся каждому целиком:
        # «каждому по 20 тысяч» на локации дало бы четыре миллиона.
        per_obj = max(a.faces // max(len(visual), 1), 24)
        after = 0
        for obj in visual:
            after += decimate(obj, per_obj)

    collider_tris = 0
    if a.collider_mode != "none":
        _, collider_tris = build_collider(visual, a.collider, a.collider_mode)

    bpy.ops.export_scene.gltf(filepath=a.out, export_format="GLB",
                              export_apply=True)

    print("GAMEREADY_STATS " + json.dumps({
        "tris_before": before,
        "tris_after": after,
        "collider_tris": collider_tris,
        "collider_mode": a.collider_mode,
        "meshes": len(visual),
        "lights_dropped": dropped_lights,
        "cameras_dropped": dropped_cams,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
