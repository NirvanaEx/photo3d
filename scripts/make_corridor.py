"""Собрать локацию «школьный коридор» и снять её.

    python scripts/make_corridor.py
    python scripts/make_corridor.py --sun-elev 45 --preview

Локация процедурная: геометрия и материалы строятся кодом в Blender, внешних
карт и ассетов нет вовсе. Поэтому пересборка с другими параметрами - это одна
команда, а не переделка сцены руками.

Результат кладётся в data/output/loc_corridor, а НЕ отдельной моделью в базу:
ModelStore подбирает каталоги по префиксу m_, и локация в списке моделей
выглядела бы неудачно рядом с предметами - у неё нет ни оборота, ни габарита,
по которым этот список устроен.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, "/mnt/d/Develop/photo3d")

from server import config  # noqa: E402
from server.errors import PipelineError  # noqa: E402
from server.store import ModelStore  # noqa: E402

SCRIPT = config.BLENDER_SCRIPTS / "corridor.py"
OUT_DIR = config.OUTPUT_DIR / "loc_corridor"

# Проброс насквозь в блендер-скрипт: список ровно тот, что имеет смысл крутить
# снаружи. Всё остальное - константы сцены, их место в коде.
PASS_THROUGH = ("sun_elev", "sun_azim", "sun_energy", "sky", "haze",
                "lens", "cam", "look", "width", "height", "exposure", "view_transform",
                "walk_span", "walk_z")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=str(OUT_DIR))
    p.add_argument("--res", default="1366x768")
    p.add_argument("--samples", type=int, default=128)
    p.add_argument("--preview", action="store_true",
                   help="быстрый черновик: половина стороны, мало выборок")
    p.add_argument("--plan", action="store_true",
                   help="ортоплан сверху со снятым потолком - смотреть, куда "
                        "на самом деле ложится свет")
    p.add_argument("--extra-views", action="store_true")
    p.add_argument("--no-blend", action="store_true")
    p.add_argument("--publish", action="store_true",
                   help="показать локацию в библиотеке: снять проход по "
                        "коридору и завести запись m_corridor")
    p.add_argument("--walk", type=int, default=24,
                   help="кадров прохода при --publish")
    for name in PASS_THROUGH:
        p.add_argument(f"--{name.replace('_', '-')}", default=None)
    args = p.parse_args()

    out = Path(args.out)
    mdir = None
    if args.publish:
        # Реестр подбирает каталоги по шаблону m_<буквы-цифры>, поэтому имя
        # записи фиксированное: пересъёмка обзора должна обновлять ту же
        # карточку, а не плодить новые.
        mdir = config.OUTPUT_DIR / "m_corridor"
        out = mdir / "views"
    out.mkdir(parents=True, exist_ok=True)

    res, samples = args.res, args.samples
    if args.preview:
        w, h = (int(v) for v in res.lower().split("x"))
        res, samples = f"{w // 2}x{h // 2}", 32

    cmd = [str(config.BLENDER), "-b", "--factory-startup", "-noaudio",
           "-P", str(SCRIPT), "--",
           "--out", str(out), "--res", res, "--samples", str(samples)]
    for name in PASS_THROUGH:
        val = getattr(args, name)
        if val is not None:
            cmd += [f"--{name.replace('_', '-')}", str(val)]
    if args.plan:
        cmd.append("--plan")
    if args.extra_views:
        cmd.append("--extra-views")
    if args.publish:
        cmd += ["--walk", str(args.walk)]
    if not args.no_blend and not args.plan and not args.publish:
        cmd += ["--blend", str(out / "corridor.blend")]

    started = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          timeout=config.TRELLIS_TIMEOUT_SEC)
    text = (proc.stdout or "") + (proc.stderr or "")
    (out / "log.txt").write_text(text, encoding="utf-8")

    stats = {}
    for line in text.splitlines():
        if line.startswith("CORRIDOR_STATS "):
            stats = json.loads(line[len("CORRIDOR_STATS "):])

    if proc.returncode != 0 or "CORRIDOR_DONE" not in text:
        tail = "\n".join(text.strip().splitlines()[-15:])
        raise PipelineError("corridor", "Blender не собрал сцену",
                            hint=f"полный вывод в {out / 'log.txt'}\n{tail}")

    stats["время_с"] = round(time.time() - started, 1)
    frames = sorted(f.name for f in out.glob("*.png"))
    stats["кадры"] = len(frames) if args.publish else frames

    if mdir is not None:
        # GLB не кладём намеренно. Материалы процедурные, в glTF они без
        # запекания не переходят, и «открыть» показало бы серую коробку
        # изнутри - хуже, чем честное отсутствие 3D у записи.
        ModelStore().write_meta("m_corridor", {
            "source": "процедурная сцена pipeline/blender/corridor.py",
            "stats": {
                "engine": "corridor",
                "mode": "локация, проход по коридору",
                "seed": 0,
                "vertices": None,
                "faces": stats.get("граней"),
                "watertight": True,
                "подробности": stats,
            },
            "elapsed_sec": stats["время_с"],
            "render_engine": "cycles",
            "views": len(frames),
        })
        print(f"запись в библиотеке: m_corridor, кадров {len(frames)}")

    print(json.dumps(stats, ensure_ascii=False, indent=2))
    print(f"\nготово: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
