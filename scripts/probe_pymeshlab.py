"""Разведка pymeshlab: какие фильтры ремонта доступны в этой версии,
понимает ли он GLB и что показывает по топологии нашего меша.

    /opt/photo3d/venv/bin/python /mnt/d/Develop/photo3d/scripts/probe_pymeshlab.py
"""
import sys
from pathlib import Path

ROOT = Path("/mnt/d/Develop/photo3d")
sys.path.insert(0, str(ROOT))

import pymeshlab  # noqa: E402

GLB = ROOT / "data" / "output" / "m_e8659c" / "model.glb"


def head(t):
    print("\n" + "=" * 8, t)


head("версия")
print(getattr(pymeshlab, "__version__", "неизвестна"))

head("доступные фильтры ремонта")
ms = pymeshlab.MeshSet()
keys = ("manifold", "hole", "duplicate", "unreferenced", "null", "orient",
        "remesh", "isolated", "degenerate")
found = sorted(n for n in dir(ms) if not n.startswith("_")
               and any(k in n for k in keys))
for n in found:
    print("  ", n)

head("загрузка GLB")
loaded = False
try:
    ms.load_new_mesh(str(GLB))
    loaded = True
    print("GLB прочитан напрямую")
except Exception as exc:
    print("напрямую не вышло:", type(exc).__name__, exc)
    import trimesh
    tmp = ROOT / "data" / "cache" / "probe_in.ply"
    trimesh.load(GLB, force="mesh").export(tmp)
    ms.load_new_mesh(str(tmp))
    loaded = True
    print("прочитан через конвертацию в PLY:", tmp)

if not loaded:
    sys.exit(1)


def measures(tag):
    m = ms.current_mesh()
    try:
        t = ms.get_topological_measures()
    except Exception as exc:
        t = {"ошибка": str(exc)}
    interesting = {k: v for k, v in t.items() if any(
        s in k for s in ("manifold", "hole", "boundary", "connected", "genus"))}
    print(f"{tag}: {m.vertex_number()} верш / {m.face_number()} граней")
    print("   ", interesting)


head("до ремонта")
measures("исходный")

head("ремонт")
seq = [
    ("meshing_remove_duplicate_vertices", {}),
    ("meshing_remove_duplicate_faces", {}),
    ("meshing_remove_null_faces", {}),
    ("meshing_remove_unreferenced_vertices", {}),
    ("meshing_repair_non_manifold_edges", {}),
    ("meshing_repair_non_manifold_vertices", {}),
    ("meshing_close_holes", {"maxholesize": 300}),
    ("meshing_re_orient_faces_coherentely", {}),
]
for name, kw in seq:
    if not hasattr(ms, name):
        print(f"  ПРОПУСК {name} - нет в этой версии")
        continue
    try:
        getattr(ms, name)(**kw)
        print(f"  ok {name}")
    except Exception as exc:
        print(f"  СБОЙ {name}: {type(exc).__name__} {exc}")

head("после ремонта")
measures("починенный")

out = ROOT / "data" / "cache" / "repaired.ply"
ms.save_current_mesh(str(out))
print("сохранено:", out)
