"""Собрать оболочку столкновений для модели: data/output/<id>/collider.glb.

    python scripts/make_collider.py m_258aeb [--faces 8000]
    python scripts/make_collider.py --all

Зачем нужна. Прогулка в вебе считает столкновения по самой геометрии только
до 12 000 треугольников: дальше октодерево строится нелинейно долго, на
296 000 вкладка висит минутами (замеры в web/static/walk.js). Выше порога
человек ходил по плоскому полу и проходил сквозь стены. Отдельная грубая
оболочка возвращает стены обратно, стоя браузеру полтора процента веса
исходного файла.

Почему отдельным скриптом, а не кнопкой в интерфейсе: веб намеренно не
запускает пайплайн - он отдельный процесс, который можно ронять и
перезапускать, и генерация этого не замечает (README, «Веб-интерфейс»).
Интерфейс лишь подхватывает collider.glb, если тот появился рядом.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server import config          # noqa: E402
from server.errors import PipelineError  # noqa: E402

SCRIPT = config.BLENDER_SCRIPTS / "collider.py"


def build(model_id: str, faces: int = 8000) -> dict:
    d = config.OUTPUT_DIR / model_id
    src = d / "model.glb"
    out = d / "collider.glb"
    if not src.exists():
        raise PipelineError("collider", f"нет модели: {src}",
                            hint="проверь id: python scripts/make_collider.py --all")

    cmd = [
        str(config.BLENDER), "-b", "--factory-startup", "-noaudio",
        "-P", str(SCRIPT), "--",
        "--src", str(src), "--out", str(out), "--faces", str(faces),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          timeout=config.RENDER_TIMEOUT_SEC)
    text = (proc.stdout or "") + (proc.stderr or "")

    stats = {}
    for line in text.splitlines():
        if line.startswith("COLLIDER_STATS "):
            stats = json.loads(line[len("COLLIDER_STATS "):])

    if not stats or not out.exists():
        detail = next((l for l in text.splitlines()
                       if l.startswith("COLLIDER_ERROR")), "")
        raise PipelineError(
            "collider", detail or "оболочка не собралась",
            hint=("хвост вывода Blender:\n"
                  + "\n".join(text.strip().splitlines()[-10:])))

    stats["mb"] = round(out.stat().st_size / 1e6, 2)
    stats["path"] = str(out)
    return stats


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("model_id", nargs="?", help="id модели; без него нужен --all")
    p.add_argument("--faces", type=int, default=8000)
    p.add_argument("--all", action="store_true",
                   help="для всех моделей, у которых оболочки ещё нет")
    a = p.parse_args()

    if a.all:
        ids = [d.name for d in sorted(config.OUTPUT_DIR.iterdir())
               if (d / "model.glb").exists() and not (d / "collider.glb").exists()]
    elif a.model_id:
        ids = [a.model_id]
    else:
        p.error("укажи id модели или --all")

    if not ids:
        print("нечего собирать: у всех моделей оболочка уже есть")
        return

    for i, mid in enumerate(ids, 1):
        print(f"[{i}/{len(ids)}] {mid} … ", end="", flush=True)
        try:
            s = build(mid, a.faces)
        except PipelineError as e:
            print(f"ОШИБКА\n{e}")
            continue
        print(f"{s['tris_before']} → {s['tris_after']} тр, {s['mb']} МБ")


if __name__ == "__main__":
    main()
