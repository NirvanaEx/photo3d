"""Полная цепочка на настоящем выводе TRELLIS: ремонт, ретопология, запекание.

    python test_fullchain.py [путь.glb]

Обвязка отлаживалась на заглушке, а та давала семь тысяч граней аккуратной
сетки. TRELLIS отдаёт под триста тысяч после marching cubes - другой порядок
и другое качество входа. Здесь проверяется, что цепочка это переваривает, а
внешний вид переживает перестройку сетки.

Результат сравнивается ГЛАЗАМИ: исходник и ретопологизированная модель
рендерятся одинаково и кладутся рядом. Совпадение чисел ничего не доказывает -
именно так однажды была пропущена модель, повёрнутая на 90 градусов.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "/mnt/d/Develop/photo3d")

from PIL import Image  # noqa: E402

from pipeline import bake, render, sculpt  # noqa: E402
from server import config  # noqa: E402

TARGET_FACES = 20_000


def strip(glb: Path, out_dir: Path, tag: str, views: int = 4) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    frames, engine, log = render.render_turntable(
        glb, out_dir, views=views, res=config.PREVIEW_RES, style="beauty")
    if not frames:
        print(f"  рендер {tag} не удался:\n{log[-1500:]}")
    return frames


def main() -> int:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else \
        config.ROOT / "data" / "cache" / "trellis_test" / "model.glb"
    if not src.exists():
        print(f"нет файла {src}")
        return 1

    work = src.parent / "fullchain"
    work.mkdir(parents=True, exist_ok=True)
    print(f"вход: {src} ({src.stat().st_size / 1e6:.1f} МБ)\n")

    t = time.time()
    print("=== ремонт и ретопология")
    retopo, stats = sculpt.prepare(src, work, target_faces=TARGET_FACES)
    log = stats.pop("log", "")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    print(f"    {time.time() - t:.1f} с\n")

    t = time.time()
    print("=== перенос внешнего вида")
    baked = work / "baked.glb"
    try:
        info = bake.transfer(src, retopo, baked)
        print(f"    {info}")
    except Exception as exc:  # noqa: BLE001
        print(f"    ОТКАЗ: {exc}")
        (work / "bake_error.txt").write_text(str(exc), encoding="utf-8")
        return 1
    print(f"    {time.time() - t:.1f} с\n")

    print("=== рендер для сравнения")
    rows = []
    for tag, path in (("исходник TRELLIS", src), ("после ретопологии", baked)):
        frames = strip(path, work / f"views_{tag.split()[0]}", tag)
        if not frames:
            return 1
        ims = [Image.open(p).convert("RGB") for p in frames[:4]]
        w, h = ims[0].size
        row = Image.new("RGB", (w * len(ims), h), (18, 18, 20))
        for i, im in enumerate(ims):
            row.paste(im, (i * w, 0))
        rows.append(row)
        print(f"    {tag}: {len(frames)} кадров")

    sheet = Image.new("RGB", (rows[0].width, sum(r.height for r in rows)),
                      (18, 18, 20))
    y = 0
    for r in rows:
        sheet.paste(r, (0, y))
        y += r.height
    dst = work / "сравнение.jpg"
    sheet.save(dst, quality=90)
    print(f"\nсверху исходник, снизу после перестройки сетки:\n{dst}")
    (work / "log.txt").write_text(log, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
