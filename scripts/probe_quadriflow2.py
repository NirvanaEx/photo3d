"""Два эксперимента разом.

1. Не мешает ли QuadriFlow фоновый режим Blender: пробуем через
   context.temp_override и на триангулированном входе.
2. Сколько граней даёт воксельная перестройка при разной плотности -
   это запасной путь к базовой сетке для лепки, если QuadriFlow недоступен.

    blender -b --factory-startup -noaudio -P probe_quadriflow2.py -- --in mesh.ply
"""
import argparse
import sys

import bpy


def args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="src", required=True)
    return p.parse_args(argv)


def fresh(src, divisions):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.wm.ply_import(filepath=src)
    obj = [o for o in bpy.context.scene.objects if o.type == "MESH"][0]
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    obj.data.remesh_voxel_size = max(max(obj.dimensions) / divisions, 1e-5)
    obj.data.remesh_voxel_adaptivity = 0.0
    bpy.ops.object.voxel_remesh()
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.remove_doubles(threshold=1e-5)
    bpy.ops.mesh.delete_loose()
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode="OBJECT")
    return obj


a = args()

print("=== эксперимент 1: обходные пути для QuadriFlow ===")
obj = fresh(a.src, 128)
before = len(obj.data.polygons)

# 1a. с явным переопределением контекста
try:
    with bpy.context.temp_override(
        active_object=obj, object=obj, selected_objects=[obj],
        selected_editable_objects=[obj],
    ):
        bpy.ops.object.quadriflow_remesh(target_faces=5000, mode="FACES",
                                         use_mesh_symmetry=False)
    print(f"temp_override: {'СРАБОТАЛО' if len(obj.data.polygons) != before else 'отказ'}")
except Exception as exc:
    print("temp_override: исключение", type(exc).__name__, exc)

# 1b. на триангулированном меше
obj = fresh(a.src, 128)
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.mesh.quads_convert_to_tris(quad_method="BEAUTY", ngon_method="BEAUTY")
bpy.ops.object.mode_set(mode="OBJECT")
before = len(obj.data.polygons)
try:
    bpy.ops.object.quadriflow_remesh(target_faces=5000, mode="FACES",
                                     use_mesh_symmetry=False)
    print(f"на треугольниках: {'СРАБОТАЛО' if len(obj.data.polygons) != before else 'отказ'} "
          f"({before} -> {len(obj.data.polygons)})")
except Exception as exc:
    print("на треугольниках: исключение", type(exc).__name__, exc)

print("\n=== эксперимент 2: плотность воксельной сетки ===")
for div in (32, 48, 64, 96, 128):
    o = fresh(a.src, div)
    m = o.data
    quads = sum(1 for p in m.polygons if len(p.vertices) == 4)
    print(f"  divisions={div:3d}: {len(m.polygons):7d} граней, квадов {quads:7d}, "
          f"вершин {len(m.vertices):7d}")

print("PROBE_DONE")
