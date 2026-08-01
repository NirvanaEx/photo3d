"""Какие сглаживающие фильтры доступны в установленном pymeshlab.

    /opt/photo3d/venv/bin/python /mnt/d/Develop/photo3d/scripts/probe_smooth.py
"""
import inspect
import sys
from pathlib import Path

ROOT = Path("/mnt/d/Develop/photo3d")
sys.path.insert(0, str(ROOT))

import pymeshlab  # noqa: E402

ms = pymeshlab.MeshSet()
names = sorted(n for n in dir(ms) if not n.startswith("_")
               and any(k in n for k in ("smooth", "laplacian", "taubin", "normal", "subdiv")))
for n in names:
    print(" ", n)

print("\n=== параметры ключевых фильтров ===")
for n in ("apply_coord_taubin_smoothing", "apply_coord_laplacian_smoothing",
          "apply_coord_hc_laplacian_smoothing", "meshing_surface_subdivision_loop"):
    if hasattr(ms, n):
        try:
            print(f"{n}: {inspect.signature(getattr(ms, n))}")
        except (ValueError, TypeError):
            doc = (getattr(ms, n).__doc__ or "").strip().splitlines()
            print(f"{n}: {doc[0] if doc else 'без сигнатуры'}")
    else:
        print(f"{n}: НЕТ")
