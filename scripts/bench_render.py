"""Замер скорости стилей рендера и того, на чём считает Cycles.

    /opt/photo3d/venv/bin/python /mnt/d/Develop/photo3d/scripts/bench_render.py [model_id] [кадров]
"""
import sys
import time
from pathlib import Path

ROOT = Path("/mnt/d/Develop/photo3d")
sys.path.insert(0, str(ROOT))

from pipeline import render  # noqa: E402
from server.store import ModelStore  # noqa: E402

store = ModelStore()
mid = sys.argv[1] if len(sys.argv) > 1 else store.resolve("last")
views = int(sys.argv[2]) if len(sys.argv) > 2 else 4
glb = store.glb(mid)
print(f"модель {mid}, кадров {views}\n")

for style in ("clay", "color", "beauty"):
    out = ROOT / "data" / "cache" / f"bench_{style}"
    t = time.time()
    try:
        frames, engine, log = render.render_turntable(glb, out, views=views,
                                                      res=512, style=style)
        dt = time.time() - t
        device = next((ln.split(" ", 1)[1] for ln in log.splitlines()
                       if ln.startswith("CYCLES_DEVICE")), "")
        egl = sum(1 for ln in log.splitlines() if "libEGL" in ln or "EGL Error" in ln)
        print(f"{style:7s} {engine:10s} {dt:7.1f} c  "
              f"({dt/max(views,1):.1f} c/кадр)  {device}"
              + (f"  [EGL-ошибок: {egl}]" if egl else ""))
    except Exception as exc:  # noqa: BLE001
        print(f"{style:7s} ПРОВАЛ за {time.time()-t:.1f} c: "
              f"{str(exc).splitlines()[0]}")
