"""Выгрузка открытой сцены в GLB — исполняется внутри Blender, не в venv.

    blender -b СЦЕНА.blend --factory-startup -noaudio \
        -P export_glb.py -- --out путь/model.glb

Нужен для локаций: `corridor.py` оставляет после себя .blend и кадры Cycles,
а чтобы по коридору можно было ХОДИТЬ в вебе, нужен GLB. Отдельным файлом,
а не строчкой в corridor.py, потому что выгрузка нужна любой сцене, а не
только этой, и потому что пересобирать локацию ради одного экспорта незачем.

Честное ограничение: **процедурные материалы в glTF не переносятся**.
Формат знает только Principled BSDF с картинками и константами, а доски пола
и штукатурка в коридоре нарисованы шумами прямо в шейдере. В GLB они уедут
БЕЛЫМИ — экспортёр не сворачивает узлы в цвет, а выбрасывает вход целиком, и
`baseColorFactor` в файле просто не появляется. Чтобы вид совпал с рендером,
материалы надо сперва запечь в текстуры: `pipeline/blender/bake_scene.py`.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy


def has_surface(mat) -> bool:
    """Есть ли у материала поверхность, а не только объём."""
    if mat is None or not mat.use_nodes:
        return True                     # без узлов это обычный диффуз
    out = next((n for n in mat.node_tree.nodes if n.type == "OUTPUT_MATERIAL"), None)
    return bool(out and out.inputs["Surface"].is_linked)


def drop_volume_only() -> list[str]:
    """Убрать из выгрузки объекты, у которых материал только объёмный.

    Дымка коридора — это КОРОБКА во всю длину прохода с Volume Scatter и без
    поверхности. Cycles сквозь неё смотрит, а glTF объёмов не знает вовсе:
    коробка уезжает обычным мешем с белым материалом по умолчанию и
    `doubleSided`, то есть в прогулке человек стоит внутри белого ящика и не
    видит ни пола, ни стен. Симптом «модель не раскрашена» — на самом деле он.
    """
    doomed = [o for o in bpy.context.scene.objects
              if o.type == "MESH" and o.data.materials
              and not any(has_surface(m) for m in o.data.materials)]
    names = [o.name for o in doomed]    # имена берутся ДО удаления: после
    for ob in doomed:                   # обращение к объекту падает
        bpy.data.objects.remove(ob, do_unlink=True)
    return names


def main() -> None:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--keep-cameras", action="store_true")
    a = ap.parse_args(argv)

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    dropped = drop_volume_only()

    tris = 0
    for ob in bpy.context.scene.objects:
        if ob.type == "MESH":
            ob.data.calc_loop_triangles()
            tris += len(ob.data.loop_triangles)

    # export_lights: без него сцена приедет без солнца, и коридор, у которого
    # весь свет идёт снаружи через окна, окажется чёрным. three.js читает эти
    # источники штатно, через расширение KHR_lights_punctual.
    # export_apply: модификаторы применяются, иначе массивы шкафчиков и фаски
    # в GLB просто не попадут.
    bpy.ops.export_scene.gltf(
        filepath=str(out),
        export_format="GLB",
        export_apply=True,
        export_lights=True,
        export_cameras=a.keep_cameras,
        export_yup=True,            # glTF хранит Y вверх, Blender - Z
        export_materials="EXPORT",
    )

    size = out.stat().st_size if out.exists() else 0
    print(f"GLB: {out} | {size/1048576:.1f} МБ | треугольников {tris} | "
          f"объектов {len(bpy.context.scene.objects)}")
    if dropped:
        print("не выгружены (только объём, поверхности нет): " + ", ".join(dropped))
    if size == 0:
        raise SystemExit("экспорт не создал файл")


if __name__ == "__main__":
    main()
