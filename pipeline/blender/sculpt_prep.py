"""Перестройка меша в базовую сетку для скульптинга. Исполняется в Blender.

    blender -b --factory-startup -noaudio -P sculpt_prep.py -- \
        --in repaired.ply --out sculpt.glb --target-faces 5000

Основной инструмент здесь - Voxel Remesh, и это не компромисс: именно им
скульпторы перестраивают сетку по ходу лепки. Он даёт замкнутую оболочку
равномерной плотности, целиком из квадов.

QuadriFlow (ровные петли, более аккуратный поток рёбер) в фоновом режиме
Blender НЕ РАБОТАЕТ. Проверено на заведомо чистом меше - ноль неманифолдных
рёбер и вершин, ноль граничных, один остров - оператор всё равно отвечает
"needs to be manifold and have consistent normals" и возвращает FINISHED,
не изменив ни одной грани. Воспроизводится в режимах FACES и RATIO, через
context.temp_override и на триангулированном входе. Попытка оставлена на
случай, если в будущих версиях починят, но рассчитывать на неё нельзя.

Плотность задаётся числом граней, а не размером вокселя: у любого объекта
грани ≈ 4.1 × divisions², откуда берётся начальная оценка. Форма влияет на
коэффициент, поэтому после первого прохода делается одна корректировка.
"""
import argparse
import json
import math
import sys
import time

import bmesh
import bpy

FACES_PER_DIV2 = 4.1   # эмпирический коэффициент, см. scripts/probe_quadriflow2.py
MIN_DIV, MAX_DIV = 12, 400


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="src", required=True)
    p.add_argument("--out", dest="dst", required=True)
    p.add_argument("--target-faces", type=int, default=5000)
    p.add_argument("--try-quadriflow", action="store_true")
    return p.parse_args(argv)


def topology(obj):
    m = obj.data
    quads = sum(1 for p in m.polygons if len(p.vertices) == 4)
    tris = sum(1 for p in m.polygons if len(p.vertices) == 3)
    return {
        "vertices": len(m.vertices),
        "faces": len(m.polygons),
        "quads": quads,
        "tris": tris,
        "ngons": len(m.polygons) - quads - tris,
    }


def load(path):
    low = path.lower()
    if low.endswith(".ply"):
        # Оси задаются явно, и это не педантизм. glTF хранит Y вверх, и его
        # импортёр разворачивает сцену в Z-вверх по умолчанию. PLY же читается
        # как есть, поэтому цепочка GLB -> pymeshlab -> PLY -> Blender давала
        # модель, повёрнутую на 90°: турнтейбл снимал объект в профиль, и
        # результат выглядел бесформенным комком при совершенно целой геометрии.
        bpy.ops.wm.ply_import(filepath=path, forward_axis="NEGATIVE_Z", up_axis="Y")
    elif low.endswith((".glb", ".gltf")):
        bpy.ops.import_scene.gltf(filepath=path)
    elif low.endswith(".obj"):
        bpy.ops.wm.obj_import(filepath=path)
    elif low.endswith(".stl"):
        bpy.ops.wm.stl_import(filepath=path)
    else:
        raise SystemExit(f"SCULPT_ERROR: неизвестный формат {path}")


def activate(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def cleanup(obj):
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.remove_doubles(threshold=1e-5)
    bpy.ops.mesh.delete_loose()
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode="OBJECT")


def health(obj):
    bpy.ops.object.mode_set(mode="EDIT")
    bm = bmesh.from_edit_mesh(obj.data)
    out = {
        "non_manifold_edges": sum(1 for e in bm.edges if not e.is_manifold),
        "non_manifold_verts": sum(1 for v in bm.verts if not v.is_manifold),
        "boundary_edges": sum(1 for e in bm.edges if e.is_boundary),
    }
    bpy.ops.object.mode_set(mode="OBJECT")
    out["watertight"] = out["boundary_edges"] == 0 and out["non_manifold_edges"] == 0
    return out


def voxel_pass(obj, divisions):
    obj.data.remesh_voxel_size = max(max(obj.dimensions) / divisions, 1e-5)
    obj.data.remesh_voxel_adaptivity = 0.0
    bpy.ops.object.voxel_remesh()
    cleanup(obj)
    return len(obj.data.polygons)


def main():
    a = parse_args()
    stats = {"target_faces": a.target_faces}

    bpy.ops.wm.read_factory_settings(use_empty=True)
    load(a.src)
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not meshes:
        print("SCULPT_ERROR: после импорта нет мешей")
        sys.exit(1)
    obj = meshes[0]
    activate(obj)
    stats["source"] = topology(obj)

    t = time.time()
    div = int(min(max(math.sqrt(a.target_faces / FACES_PER_DIV2), MIN_DIV), MAX_DIV))
    faces = voxel_pass(obj, div)
    passes = [{"divisions": div, "faces": faces}]

    # Коэффициент зависит от отношения площади поверхности к габариту,
    # поэтому одну поправку по факту делаем всегда, если промах заметный.
    if faces and abs(faces - a.target_faces) / a.target_faces > 0.35:
        corrected = int(min(max(div * math.sqrt(a.target_faces / faces),
                                MIN_DIV), MAX_DIV))
        if corrected != div:
            bpy.ops.wm.read_factory_settings(use_empty=True)
            load(a.src)
            obj = [o for o in bpy.context.scene.objects if o.type == "MESH"][0]
            activate(obj)
            faces = voxel_pass(obj, corrected)
            passes.append({"divisions": corrected, "faces": faces})

    stats["voxel"] = {"passes": passes, "sec": round(time.time() - t, 2)}
    stats["health"] = health(obj)

    stats["quadriflow"] = {"attempted": bool(a.try_quadriflow), "applied": False}
    if a.try_quadriflow:
        before = len(obj.data.polygons)
        try:
            bpy.ops.object.quadriflow_remesh(target_faces=a.target_faces,
                                             mode="FACES", use_mesh_symmetry=False)
            stats["quadriflow"]["applied"] = len(obj.data.polygons) != before
        except Exception as exc:  # noqa: BLE001
            stats["quadriflow"]["error"] = f"{type(exc).__name__}: {exc}"
        if not stats["quadriflow"]["applied"]:
            stats["quadriflow"]["note"] = "не работает в фоновом режиме Blender"

    stats["final"] = topology(obj)
    bpy.ops.object.shade_smooth()
    bpy.ops.export_scene.gltf(filepath=a.dst, export_format="GLB")

    print("SCULPT_STATS " + json.dumps(stats, ensure_ascii=False))
    print("SCULPT_DONE")


if __name__ == "__main__":
    main()
