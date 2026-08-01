"""Забрать примеры изображений из репозитория TRELLIS.2 и показать их разом.

Сердце и звезда, на которых всё отлаживалось, - синтетика: плоская заливка,
идеальный контур, фон белее белого. Настоящее испытание конвейера - снимки
реальных предметов со светом, тенями и неоднородным фоном.

Примеры авторов подходят лучше случайных картинок из сети: они заведомо
входят в область, на которой модель обучалась, поэтому неудача укажет на
нашу сборку, а не на трудный вход.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

from PIL import Image

DST = Path("/mnt/d/Develop/photo3d/data/input/examples")
API = ("https://api.github.com/repos/microsoft/TRELLIS.2/contents/"
       "assets/example_image")
HOW_MANY = 12


def main() -> int:
    DST.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(API, timeout=30) as r:
        items = json.load(r)

    picked = [e for e in items if e["name"].endswith((".webp", ".png", ".jpg"))]
    picked = picked[:HOW_MANY]
    print(f"беру {len(picked)} из {len(items)}")

    saved: list[Path] = []
    for i, e in enumerate(picked):
        # имена в репозитории - хеши; для работы нужны короткие и читаемые
        out = DST / f"ex{i:02d}.png"
        if not out.exists():
            with urllib.request.urlopen(e["download_url"], timeout=60) as r:
                raw = r.read()
            tmp = DST / f".tmp_{i}"
            tmp.write_bytes(raw)
            Image.open(tmp).convert("RGBA").save(out)
            tmp.unlink()
        saved.append(out)
        print(f"  {out.name}  {Image.open(out).size}")

    cols = 4
    rows = (len(saved) + cols - 1) // cols
    th = 260
    sheet = Image.new("RGB", (cols * th, rows * (th + 22)), (24, 24, 26))
    from PIL import ImageDraw, ImageFont
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
    except OSError:
        font = ImageFont.load_default()
    draw = ImageDraw.Draw(sheet)
    for i, p in enumerate(saved):
        im = Image.open(p).convert("RGB")
        im.thumbnail((th, th), Image.LANCZOS)
        x = (i % cols) * th + (th - im.width) // 2
        y = (i // cols) * (th + 22)
        sheet.paste(im, (x, y))
        draw.text(((i % cols) * th + 6, y + th + 2), p.stem,
                  fill=(210, 210, 210), font=font)

    out = DST / "примеры.jpg"
    sheet.save(out, quality=90)
    print(f"\nсмотреть: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
