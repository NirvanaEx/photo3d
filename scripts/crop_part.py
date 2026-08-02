"""Вырезать часть фигуры по маске силуэта - под отдельную генерацию.

    python crop_part.py girl.png head 0.0 0.38

Зачем. Объём считается сеткой 512x512x512, и в неё помещается ВСЯ фигура.
На голову приходится примерно восьмая часть высоты - около шестидесяти
ячеек, а на глаз две-три. Отсюда каша вместо лица.

Если подать в ту же сетку только голову, она займёт её целиком, и
подробностей станет примерно втрое больше по каждой оси. Это не хитрость,
а прямое следствие того, что разрешение тратится на то, что видно.

Границы задаются долями ВЫСОТЫ СИЛУЭТА, а не кадра: кадр может быть каким
угодно, а силуэт - это и есть объект.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, "/mnt/d/Develop/photo3d")

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from pipeline import preprocess  # noqa: E402
from server import config  # noqa: E402

# Запас вокруг выреза: генератору нужен воздух по краям, впритык обрезанный
# объект он достраивает хуже.
PAD = 0.06

# Кодировщик работает с картинкой 512x512. Вырез из фигуры получается мелким
# (голова с исходника вышла 281 пиксель), и после его растяжения деталей не
# прибавляется, но и терять их на ровном месте незачем: подаём заранее в
# нужном размере, увеличивая мягкой интерполяцией.
MIN_SIDE = 512


def main() -> int:
    src_name = sys.argv[1]
    tag = sys.argv[2] if len(sys.argv) > 2 else "part"
    top = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0
    bottom = float(sys.argv[4]) if len(sys.argv) > 4 else 0.38

    src = config.INPUT_DIR / src_name
    if not src.exists():
        print(f"нет файла {src}")
        return 1

    cut = config.CACHE_DIR / f"{src.stem}_rgba.png"
    info = preprocess.cutout(src, cut)
    print(f"силуэт: {info['габарит_силуэта']} из {info['кадр']}")

    rgba = Image.open(cut).convert("RGBA")
    alpha = np.asarray(rgba)[:, :, 3]
    ys, xs = np.nonzero(alpha > 200)
    y0, y1 = int(ys.min()), int(ys.max())
    x0, x1 = int(xs.min()), int(xs.max())
    h = y1 - y0 + 1

    # полоса по вертикали
    cy0 = y0 + int(h * top)
    cy1 = y0 + int(h * bottom)

    # по горизонтали берём ширину силуэта ИМЕННО В ЭТОЙ ПОЛОСЕ: у фигуры
    # плечи шире головы, и брать общую ширину значило бы тащить пустоту
    band = alpha[cy0:cy1 + 1] > 200
    bxs = np.nonzero(band.any(axis=0))[0]
    if len(bxs) == 0:
        print("в этой полосе силуэта нет")
        return 1
    bx0, bx1 = int(bxs.min()), int(bxs.max())

    pad_y = int((cy1 - cy0) * PAD)
    pad_x = int((bx1 - bx0) * PAD)
    box = (max(bx0 - pad_x, 0), max(cy0 - pad_y, 0),
           min(bx1 + pad_x + 1, rgba.width), min(cy1 + pad_y + 1, rgba.height))

    part = rgba.crop(box)
    was = part.size
    short = min(part.size)
    if short < MIN_SIDE:
        k = MIN_SIDE / short
        part = part.resize((round(part.width * k), round(part.height * k)),
                           Image.LANCZOS)

    dst = config.INPUT_DIR / f"{src.stem}_{tag}.png"
    part.save(dst)

    print(f"вырезано {was} из полосы {top:.0%}..{bottom:.0%} высоты силуэта")
    if part.size != was:
        print(f"увеличено до {part.size}")
    print(f"файл: {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
