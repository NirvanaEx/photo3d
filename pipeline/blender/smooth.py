"""Сглаживание модели. Исполняется внутри Blender.

    blender -b --factory-startup -noaudio -P smooth.py -- \
        --in model.glb --out model.glb --strength 0.6 --iterations 12

Делается в Blender, а не в pymeshlab, сознательно: тот пишет PLY и потерял бы
материал с текстурой. Здесь материалы, UV и покраска доезжают до GLB целыми.

Два метода:
  preserve — Corrective Smooth: сглаживает, заметно меньше «сдувая» объём.
             Подходит, когда важно сохранить силуэт
  simple   — обычный Smooth: сильнее, но модель немного усыхает

Подразделение (--subdivide) добавляет геометрии перед сглаживанием: силуэт
становится по-настоящему круглым, а не многоугольным, ценой вчетверо
большего числа граней на каждый уровень.
"""
import argparse
import json
import math
import sys

import bpy


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="src", required=True)
    p.add_argument("--out", dest="dst", required=True)
    p.add_argument("--strength", type=float, default=0.6)
    p.add_argument("--iterations", type=int, default=12)
    p.add_argument("--subdivide", type=int, default=0)
    p.add_argument("--method", default="preserve", choices=["preserve", "simple"])
    p.add_argument("--shade-angle", type=float, default=50.0)
    return p.parse_args(argv)


def topology(obj):
    m = obj.data
    return {"vertices": len(m.vertices), "faces": len(m.polygons)}


def bbox_size(obj):
    d = obj.dimensions
    return [round(d.x, 4), round(d.y, 4), round(d.z, 4)]


def main():
    a = parse_args()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=a.src)
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not meshes:
        print("SMOOTH_ERROR: после импорта нет мешей")
        sys.exit(1)

    stats = {"objects": len(meshes), "method": a.method,
             "strength": a.strength, "iterations": a.iterations,
             "subdivide": a.subdivide}
    obj = meshes[0]
    stats["before"] = topology(obj)
    stats["size_before"] = bbox_size(obj)

    for o in meshes:
        bpy.ops.object.select_all(action="DESELECT")
        o.select_set(True)
        bpy.context.view_layer.objects.active = o

        if a.subdivide > 0:
            sub = o.modifiers.new("subdiv", type="SUBSURF")
            sub.subdivision_type = "CATMULL_CLARK"
            sub.levels = sub.render_levels = min(a.subdivide, 3)
            bpy.ops.object.modifier_apply(modifier=sub.name)

        if a.strength > 0 and a.iterations > 0:
            if a.method == "preserve":
                m = o.modifiers.new("smooth", type="CORRECTIVE_SMOOTH")
                m.factor = a.strength
                m.iterations = a.iterations
                m.smooth_type = "LENGTH_WEIGHTED"
                m.use_only_smooth = True
            else:
                m = o.modifiers.new("smooth", type="SMOOTH")
                m.factor = a.strength
                m.iterations = a.iterations
            bpy.ops.object.modifier_apply(modifier=m.name)

        # Нормали: без этого модель выглядит гранёной даже после сглаживания
        # геометрии — свет ломается на каждой грани.
        try:
            bpy.ops.object.shade_smooth_by_angle(angle=math.radians(a.shade_angle))
        except (AttributeError, RuntimeError):
            bpy.ops.object.shade_smooth()

    stats["after"] = topology(obj)
    stats["size_after"] = bbox_size(obj)
    # Усадку считаем честно: сглаживание всегда немного стягивает объём,
    # и это надо показывать, а не прятать.
    sb, sa = stats["size_before"], stats["size_after"]
    stats["shrink_percent"] = [round((1 - sa[i] / sb[i]) * 100, 1) if sb[i] else 0
                               for i in range(3)]

    bpy.ops.export_scene.gltf(filepath=a.dst, export_format="GLB")
    print("SMOOTH_STATS " + json.dumps(stats, ensure_ascii=False))
    print("SMOOTH_DONE")


if __name__ == "__main__":
    main()
