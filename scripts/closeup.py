"""Крупный план верхней части модели - посмотреть на лицо.

    python closeup.py m_0ef45f [доля_высоты] [разрешение]

Превью в 512 пикселей показывает фигуру целиком, и голова на нём занимает
десятков шесть точек - по такой картинке о лице судить нельзя. Здесь модель
снимается в высоком разрешении, и от кадра берётся только верх.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, "/mnt/d/Develop/photo3d")

from PIL import Image  # noqa: E402

from pipeline import render  # noqa: E402
from server import config  # noqa: E402


def skin_share(im: Image.Image, share: float) -> float:
    """Доля пикселей телесного оттенка в верхней части кадра.

    Нужно, чтобы выбрать ракурс автоматически: модели встают в объёме
    по-разному, и у одной нулевой кадр смотрит лицом, у другой затылком.
    Перебирать номера руками - потерянное время, а признак простой: там, где
    видно лицо, кожи заметно больше, чем там, где виден затылок под волосами.
    """
    import numpy as np

    top = im.crop((0, 0, im.width, int(im.height * share)))
    a = np.asarray(top.convert("RGB")).astype(np.int16)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    skin = (r > 120) & (r > g + 8) & (g >= b) & (r - b < 120)
    return float(skin.mean())


def face_of(glb: Path, tag: str, share: float, res: int,
            frame: int | None = None) -> Image.Image | None:
    out = glb.parent / f"closeup_{tag}"
    frames, engine, log = render.render_turntable(
        glb, out, views=8, res=res, style="beauty")
    if not frames:
        print(f"  рендер не удался:\n{log[-1200:]}")
        return None

    if frame is None:
        scores = [(skin_share(Image.open(p), share), i) for i, p in enumerate(frames)]
        best = max(scores)[1]
        print(f"    выбран кадр {best} (кожи {max(scores)[0]:.1%})")
    else:
        best = frame % len(frames)
    im = Image.open(frames[best]).convert("RGB")
    # верхняя доля кадра по высоте, по ширине - центр
    h = int(im.height * share)
    w = int(im.width * share * 1.0)
    x0 = (im.width - w) // 2
    return im.crop((x0, 0, x0 + w, h))


def main() -> int:
    ids = sys.argv[1:] or ["last"]
    share = 0.42
    res = 1536

    parts = []
    for spec in ids:
        # вид m_xxx[:файл.glb][@номер_кадра]
        spec, _, fr = spec.partition("@")
        frame = int(fr) if fr else None      # None - выбрать самому
        mid, _, fname = spec.partition(":")
        glb = config.OUTPUT_DIR / mid / (fname or "model.glb")
        if not glb.exists():
            print(f"нет {glb}")
            return 1
        print(f"снимаю {mid} ({glb.name}), кадр {frame}, в {res}px...")
        im = face_of(glb, mid, share, res, frame)
        if im is None:
            return 1
        parts.append((mid, im))

    height = min(p[1].height for p in parts)
    scaled = [p[1].resize((int(p[1].width * height / p[1].height), height),
                          Image.LANCZOS) for p in parts]
    sheet = Image.new("RGB", (sum(i.width for i in scaled), height), (18, 18, 20))
    x = 0
    for im in scaled:
        sheet.paste(im, (x, 0))
        x += im.width

    dst = config.OUTPUT_DIR / parts[0][0] / "лица.jpg"
    sheet.save(dst, quality=93)
    print(f"смотреть: {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
