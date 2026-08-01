"""Проверка снятия фона. Смотреть глазами, а не только на цифры.

Метрики вроде «доля кадра» показывают, что маска непустая, но не показывают,
не отрезало ли половину объекта и не прилипли ли к нему куски фона. Поэтому
скрипт кладёт рядом картинку: слева исходник, посередине маска, справа
вырезанный объект на шахматке.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, "/mnt/d/Develop/photo3d")

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from pipeline import preprocess  # noqa: E402
from server import config  # noqa: E402


def checker(size: tuple[int, int], step: int = 16) -> Image.Image:
    w, h = size
    ys, xs = np.mgrid[0:h, 0:w]
    tile = ((xs // step + ys // step) % 2).astype(np.uint8)
    grey = 90 + tile * 40
    return Image.fromarray(np.dstack([grey] * 3).astype(np.uint8), "RGB")


def main() -> int:
    out_dir = config.ROOT / "data" / "cache" / "preprocess_test"
    out_dir.mkdir(parents=True, exist_ok=True)

    photos = sorted((config.ROOT / "data" / "input").glob("*.png"))
    if not photos:
        print("нет входных фото в data/input")
        return 1

    panels = []
    for src in photos:
        dst = out_dir / f"{src.stem}_rgba.png"
        try:
            info = preprocess.cutout(src, dst)
        except Exception as exc:  # noqa: BLE001
            print(f"{src.name}: ОТКАЗ - {exc}")
            continue
        print(f"{src.name}: доля кадра {info['доля_кадра']:.1%}, "
              f"силуэт {info['габарит_силуэта']} из {info['кадр']}")

        orig = Image.open(src).convert("RGB")
        rgba = Image.open(dst).convert("RGBA")
        mask = Image.fromarray(np.asarray(rgba)[:, :, 3]).convert("RGB")
        onchk = checker(rgba.size)
        onchk.paste(rgba, (0, 0), rgba)

        h = 340
        row = [im.resize((int(im.width * h / im.height), h), Image.LANCZOS)
               for im in (orig, mask, onchk)]
        strip = Image.new("RGB", (sum(i.width for i in row), h), (20, 20, 22))
        x = 0
        for im in row:
            strip.paste(im, (x, 0))
            x += im.width
        panels.append(strip)

    if not panels:
        return 1
    w = max(p.width for p in panels)
    sheet = Image.new("RGB", (w, sum(p.height for p in panels)), (20, 20, 22))
    y = 0
    for p in panels:
        sheet.paste(p, (0, y))
        y += p.height
    result = out_dir / "проверка.jpg"
    sheet.save(result, quality=90)
    print(f"\nсмотреть: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
