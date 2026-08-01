"""Почему QuadriFlow отказывается работать с уже починенным мешем.

Проверяем то, что оператор мог бы счесть препятствием: неманифолдные вершины
(а не только рёбра), число островов, согласованность нормалей. Плюс пробуем
разные режимы вызова.

    blender -b --factory-startup -noaudio -P probe_quadriflow.py -- --in mesh.ply
"""
import argparse
import sys

import bmesh
import bpy


def args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="src", required=True)
    return p.parse_args(argv)


def diagnose(obj, tag):
    bpy.ops.object.mode_set(mode="EDIT")
    bm = bmesh.from_edit_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    nm_edges = sum(1 for e in bm.edges if not e.is_manifold)
    nm_verts = sum(1 for v in bm.verts if not v.is_manifold)
    wire = sum(1 for e in bm.edges if e.is_wire)
    boundary = sum(1 for e in bm.edges if e.is_boundary)

    # острова обходом по связности
    seen, islands = set(), 0
    for v in bm.verts:
        if v in seen:
            continue
        islands += 1
        stack = [v]
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            for e in cur.link_edges:
                other = e.other_vert(cur)
                if other not in seen:
                    stack.append(other)
    bpy.ops.object.mode_set(mode="OBJECT")
    print(f"{tag}: рёбер-неманифолд {nm_edges}, вершин-неманифолд {nm_verts}, "
          f"wire {wire}, граничных {boundary}, островов {islands}, "
          f"граней {len(obj.data.polygons)}")
    return islands


def main():
    a = args()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.wm.ply_import(filepath=a.src)
    obj = [o for o in bpy.context.scene.objects if o.type == "MESH"][0]
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    size = max(max(obj.dimensions) / 128.0, 1e-5)
    obj.data.remesh_voxel_size = size
    obj.data.remesh_voxel_adaptivity = 0.0
    bpy.ops.object.voxel_remesh()

    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.remove_doubles(threshold=1e-5)
    bpy.ops.mesh.delete_loose()
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode="OBJECT")

    islands = diagnose(obj, "после воксельной перестройки")

    # Если островов больше одного - оставляем самый крупный.
    if islands > 1:
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="DESELECT")
        bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.mesh.separate(type="LOOSE") if False else None
        print("островов больше одного — это и может быть причиной")

    for kw in (
        {"target_faces": 5000, "mode": "FACES"},
        {"target_ratio": 0.1, "mode": "RATIO"},
        {"target_faces": 5000, "mode": "FACES", "use_preserve_boundary": True},
    ):
        before = len(obj.data.polygons)
        try:
            bpy.ops.object.quadriflow_remesh(use_mesh_symmetry=False, **kw)
            after = len(obj.data.polygons)
            print(f"попытка {kw}: {'СРАБОТАЛО' if after != before else 'отказ'} "
                  f"({before} -> {after})")
            if after != before:
                break
        except Exception as exc:
            print(f"попытка {kw}: исключение {type(exc).__name__}: {exc}")

    print("PROBE_DONE")


if __name__ == "__main__":
    main()
