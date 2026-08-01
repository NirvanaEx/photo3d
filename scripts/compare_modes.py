"""Сравнить две модели одинаковым рендером, бок о бок.

    python compare_modes.py a.glb "подпись A" b.glb "подпись B"

Числа вроде числа граней не отвечают на вопрос «стало лучше?». Отвечает
только взгляд на одинаково снятые кадры.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, "/mnt/d/Develop/photo3d")

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from pipeline import render  # noqa: E402
from server import config  # noqa: E402

# Встроенный шрифт PIL - латиница в растре, кириллица рисуется квадратиками.
# DejaVu входит в базовый набор Ubuntu и покрывает нужное.
FONT_PATH = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")


def label_font(size: int = 20):
    try:
        return ImageFont.truetype(str(FONT_PATH), size)
    except OSError:
        return ImageFont.load_default()


def strip(glb: Path, tag: str, views: int) -> Image.Image | None:
    out = glb.parent / f"cmp_{glb.stem}"
    frames, engine, log = render.render_turntable(
        glb, out, views=views, res=config.PREVIEW_RES, style="beauty")
    if not frames:
        print(f"  рендер {tag} не удался:\n{log[-1200:]}")
        return None
    picked = frames[:views]
    ims = [Image.open(p).convert("RGB") for p in picked]
    w, h = ims[0].size
    row = Image.new("RGB", (w * len(ims), h + 34), (18, 18, 20))
    for i, im in enumerate(ims):
        row.paste(im, (i * w, 34))
    ImageDraw.Draw(row).text((10, 7), tag, fill=(235, 235, 235), font=label_font())
    print(f"  {tag}: {len(frames)} кадров, {engine}")
    return row


def main() -> int:
    if len(sys.argv) < 5:
        print(__doc__)
        return 1
    pairs = [(Path(sys.argv[1]), sys.argv[2]), (Path(sys.argv[3]), sys.argv[4])]
    rows = []
    for path, tag in pairs:
        if not path.exists():
            print(f"нет файла {path}")
            return 1
        r = strip(path, tag, views=4)
        if r is None:
            return 1
        rows.append(r)

    sheet = Image.new("RGB", (rows[0].width, sum(r.height for r in rows)),
                      (18, 18, 20))
    y = 0
    for r in rows:
        sheet.paste(r, (0, y))
        y += r.height
    dst = pairs[0][0].parent / "сравнение_режимов.jpg"
    sheet.save(dst, quality=92)
    print(f"\nсмотреть: {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
