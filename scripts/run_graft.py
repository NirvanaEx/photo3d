"""Собрать тело с подробной головой и положить результат в базу.

    python run_graft.py m_750ef9 m_cee258

Берёт преобразование, посчитанное scripts/graft_head.py, зовёт Blender,
кладёт готовую модель отдельной записью и рендерит оборот - чтобы её было
видно в веб-интерфейсе наравне с остальными.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "/mnt/d/Develop/photo3d")

from pipeline import graft, render  # noqa: E402
from server import config  # noqa: E402
from server.store import ModelStore  # noqa: E402


def main() -> int:
    body_id, head_id = sys.argv[1], sys.argv[2]
    tag = f"{body_id}_{head_id}".replace(":", "-").replace(".glb", "")
    plan = config.CACHE_DIR / f"graft_{tag}.json"
    if not plan.exists():
        print(f"нет плана {plan} - сначала scripts/graft_head.py")
        return 1
    spec = json.loads(plan.read_text(encoding="utf-8"))

    store = ModelStore()
    new_id, mdir = store.create()
    out = mdir / "model.glb"
    started = time.time()

    print(f"{new_id}: тело {body_id} + голова {head_id}")
    stats = graft.merge(Path(spec["body"]), Path(spec["head"]), plan, out)
    log = stats.pop("log", "")
    print(json.dumps(stats, ensure_ascii=False, indent=2))

    frames, rengine, rlog = render.render_turntable(
        out, mdir / "views", views=config.SPIN_FRAMES, res=config.PREVIEW_RES)
    store.log(new_id, log + "\n" + rlog)
    store.write_meta(new_id, {
        "source": f"{body_id} + {head_id}",
        "stats": {
            "engine": "graft",
            "mode": f"голова из {head_id}",
            "seed": 0,
            "vertices": None,
            "faces": stats.get("граней_итого"),
            "watertight": False,
            "подробности": stats,
        },
        "elapsed_sec": time.time() - started,
        "render_engine": rengine,
        "views": len(frames),
    })
    print(f"\nготово: {new_id}, кадров {len(frames)}, {time.time() - started:.1f} с")
    print(f"GLB: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
