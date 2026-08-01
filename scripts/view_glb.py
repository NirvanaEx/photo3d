"""Отрендерить GLB и собрать контактный лист - посмотреть результат глазами.

    python view_glb.py путь.glb [стиль]

Цифры в отчёте генерации говорят, что модель непустая, но не говорят, на что
она похожа. Здесь она снимается с четырёх сторон и складывается в одну
картинку.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, "/mnt/d/Develop/photo3d")

from PIL import Image  # noqa: E402

from pipeline import render  # noqa: E402
from server import config  # noqa: E402


def main() -> int:
    src = Path(sys.argv[1])
    style = sys.argv[2] if len(sys.argv) > 2 else "beauty"
    if not src.exists():
        print(f"нет файла {src}")
        return 1

    out_dir = src.parent / f"views_{style}"
    out_dir.mkdir(parents=True, exist_ok=True)

    frames, engine, log = render.render_turntable(
        src, out_dir, views=8, res=config.PREVIEW_RES, style=style
    )
    print(f"движок рендера: {engine}, кадров: {len(frames)}")
    if not frames:
        print(log[-2000:])
        return 1

    picked = [frames[i] for i in range(0, len(frames), max(len(frames) // 4, 1))][:4]
    ims = [Image.open(p).convert("RGB") for p in picked]
    w, h = ims[0].size
    sheet = Image.new("RGB", (w * len(ims), h), (18, 18, 20))
    for i, im in enumerate(ims):
        sheet.paste(im, (i * w, 0))
    dst = src.parent / f"contact_{style}.jpg"
    sheet.save(dst, quality=90)
    print(f"смотреть: {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
