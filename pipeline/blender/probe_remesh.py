"""Разведка: тянет ли встроенный Blender связку Voxel Remesh -> QuadriFlow.

Это стандартная подготовка меша под скульптинг. Voxel Remesh делает оболочку
замкнутой и равномерной, QuadriFlow перекладывает её в квады с ровными петлями -
такую сетку уже можно подразделять и лепить, в отличие от треугольного супа
после marching cubes.

    blender -b --factory-startup -noaudio -P probe_remesh.py -- --glb model.glb
"""
import argparse
import sys
import time

import bpy


def args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--glb", required=True)
    p.add_argument("--target-faces", type=int, default=4000)
    p.add_argument("--out", default="")
    return p.parse_args(argv)


def stats(obj):
    m = obj.data
    quads = sum(1 for p in m.polygons if len(p.vertices) == 4)
    tris = sum(1 for p in m.polygons if len(p.vertices) == 3)
    ngons = len(m.polygons) - quads - tris
    return f"{len(m.vertices)} верш / {len(m.polygons)} граней (квадов {quads}, треуг {tris}, n-гонов {ngons})"


def main():
    a = args()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=a.glb)

    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not meshes:
        print("PROBE_FAIL: нет мешей"); return
    obj = meshes[0]

    # QuadriFlow работает с одним активным объектом
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    print("ИСХОДНЫЙ:", stats(obj))

    # --- шаг 1: воксельная перестройка, закрывает дыры -------------------
    dims = obj.dimensions
    voxel = max(max(dims) / 128.0, 1e-4)
    obj.data.remesh_voxel_size = voxel
    obj.data.remesh_voxel_adaptivity = 0.0
    t = time.time()
    try:
        bpy.ops.object.voxel_remesh()
        print(f"VOXEL_OK размер вокселя {voxel:.5f} за {time.time()-t:.1f} c")
        print("ПОСЛЕ VOXEL:", stats(obj))
    except Exception as exc:
        print("VOXEL_FAIL:", exc)

    # --- шаг 1.5: привести меш в вид, который QuadriFlow примет ----------
    # Он молча отказывается работать с неманифолдной геометрией и
    # разнонаправленными нормалями, возвращая при этом FINISHED.
    import bmesh
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.remove_doubles(threshold=1e-5)
    bpy.ops.mesh.delete_loose()
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bm = bmesh.from_edit_mesh(obj.data)
    bad = sum(1 for e in bm.edges if not e.is_manifold)
    print(f"ПОДГОТОВКА: неманифолдных рёбер {bad}")
    bpy.ops.object.mode_set(mode="OBJECT")
    print("ПОСЛЕ ПОДГОТОВКИ:", stats(obj))

    # --- шаг 2: ретопология в квады --------------------------------------
    before = len(obj.data.polygons)
    t = time.time()
    try:
        bpy.ops.object.quadriflow_remesh(
            target_faces=a.target_faces,
            use_mesh_symmetry=False,
            use_preserve_sharp=False,
            use_preserve_boundary=False,
            mode="FACES",
        )
        # Оператор возвращает FINISHED даже когда ничего не сделал,
        # поэтому судим по числу граней, а не по коду возврата.
        after = len(obj.data.polygons)
        if after == before:
            print(f"QUADRIFLOW_NOOP: граней как было ({before}), оператор отказался")
        else:
            print(f"QUADRIFLOW_OK за {time.time()-t:.1f} c")
        print("ПОСЛЕ QUADRIFLOW:", stats(obj))
    except Exception as exc:
        print("QUADRIFLOW_FAIL:", exc)

    # --- что ещё есть под рукой ------------------------------------------
    have = {
        "quadriflow_remesh": hasattr(bpy.ops.object, "quadriflow_remesh"),
        "voxel_remesh": hasattr(bpy.ops.object, "voxel_remesh"),
        "shade_smooth_by_angle": hasattr(bpy.ops.object, "shade_smooth_by_angle"),
        "modifier_MULTIRES": "MULTIRES" in [i.identifier for i in
            bpy.types.Modifier.bl_rna.properties["type"].enum_items],
        "modifier_DECIMATE": "DECIMATE" in [i.identifier for i in
            bpy.types.Modifier.bl_rna.properties["type"].enum_items],
    }
    print("ВОЗМОЖНОСТИ:", have)

    # аддон проверки печатной пригодности - находит non-manifold и тонкие стенки
    try:
        import addon_utils
        mods = [m.__name__ for m in addon_utils.modules()]
        print("3D-Print Toolbox доступен:", any("print3d" in m or "3d_print" in m for m in mods))
    except Exception as exc:
        print("аддоны не перечислить:", exc)

    if a.out:
        bpy.ops.export_scene.gltf(filepath=a.out, export_format="GLB")
        print("СОХРАНЁН:", a.out)
    print("PROBE_DONE")


if __name__ == "__main__":
    main()
