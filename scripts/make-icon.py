"""Иконка photo3d: изометрический куб в палитре интерфейса.

Лежит скриптом, а не готовой картинкой в репозитории, по той же причине, что и
make-shortcut.ps1: цвета берутся из web/static/style.css, и когда палитра
интерфейса поменяется, иконку надо будет пересобрать, а не перерисовывать.

Форма выбрана под 16 пикселей, а не под 512. В трее и в панели задач иконка
живёт крошечной, поэтому здесь нет ни фотографии, ни камеры, ни текста -
только силуэт, который читается тремя гранями разной яркости. Проверять её
надо уменьшенной: в 512 красиво почти всё.

Сглаживания у полигонов в Pillow нет, поэтому всё рисуется вчетверо крупнее
и ужимается LANCZOS - края получаются мягкими без ручного антиалиасинга.

    python scripts/make-icon.py
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "static" / "icons"

# Палитра — из style.css. Дублируется числами, а не читается разбором CSS:
# зависимость от формата чужого файла ради трёх цветов дороже, чем сверка
# глазами раз в год.
BG_TOP = (28, 32, 41)       # чуть светлее --panel: сверху падает свет
BG_BOTTOM = (14, 15, 18)    # --bg
ACCENT = (110, 168, 254)    # --accent

# Грани куба. Верхняя почти белая, боковые темнеют - так объём читается даже
# в 16 пикселях, где никакие блики уже не видны.
FACE_TOP = (173, 205, 255)
FACE_LEFT = (79, 134, 214)
FACE_RIGHT = (43, 82, 143)

SS = 4  # множитель суперсэмплинга


def _rounded_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1),
                                           radius=radius, fill=255)
    return mask


def _vertical_gradient(size: int, top: tuple, bottom: tuple) -> Image.Image:
    grad = Image.new("RGB", (1, size))
    px = grad.load()
    for y in range(size):
        t = y / (size - 1)
        px[0, y] = tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
    return grad.resize((size, size), Image.Resampling.BILINEAR)


def draw_icon(size: int) -> Image.Image:
    s = size * SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))

    # Подложка: скруглённый квадрат с градиентом. Радиус 22% - пропорция,
    # принятая и в Windows 11, и в macOS; на глаз подобранный радиус в мелком
    # размере выглядит либо квадратом, либо кругом.
    plate = _vertical_gradient(s, BG_TOP, BG_BOTTOM).convert("RGBA")
    plate.putalpha(_rounded_mask(s, int(s * 0.22)))
    img.alpha_composite(plate)

    # Свечение под кубом: без него куб висит на плоском фоне отдельной
    # наклейкой. Рисуется на своём слое и размывается - краёв быть не должно.
    glow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    r = s * 0.30
    gd.ellipse((s / 2 - r, s / 2 - r * 0.8, s / 2 + r, s / 2 + r * 0.8),
               fill=ACCENT + (70,))
    glow = glow.filter(ImageFilter.GaussianBlur(s * 0.09))
    glow.putalpha(glow.getchannel("A").point(lambda a: a))
    img.alpha_composite(Image.composite(glow, Image.new("RGBA", (s, s), (0, 0, 0, 0)),
                                        _rounded_mask(s, int(s * 0.22))))

    # Изометрический куб. cos(30°) = 0.866 по горизонтали, половина по
    # вертикали - стандартная изометрия, при которой три грани равны.
    cx, cy = s / 2, s / 2
    a = s * 0.29
    w = a * math.cos(math.radians(30))
    h = a * 0.5

    top = (cx, cy - a)
    right = (cx + w, cy - h)
    lower_right = (cx + w, cy + h)
    bottom = (cx, cy + a)
    lower_left = (cx - w, cy + h)
    left = (cx - w, cy - h)
    mid = (cx, cy)

    d = ImageDraw.Draw(img)
    d.polygon([top, right, mid, left], fill=FACE_TOP)
    d.polygon([left, mid, bottom, lower_left], fill=FACE_LEFT)
    d.polygon([mid, right, lower_right, bottom], fill=FACE_RIGHT)

    # Светлое ребро по верхней грани: подчёркивает силуэт на тёмном фоне,
    # иначе левая грань сливается с подложкой на мелких размерах.
    d.line([left, top, right], fill=(226, 238, 255), width=max(1, int(s * 0.008)))

    return img.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    # PNG для PWA. 192 и 512 - размеры, которых Chrome и Edge требуют, чтобы
    # предложить установку; без любого из них кнопки «Установить» не будет.
    for px in (192, 512):
        p = OUT / f"icon-{px}.png"
        draw_icon(px).save(p)
        print(f"{p.relative_to(ROOT)}")

    # Maskable: та же картинка, ужатая до 60% поля. Android и Windows режут
    # иконку под свою форму, и без запаса по краям куб теряет углы.
    safe = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    inner = draw_icon(512).resize((307, 307), Image.Resampling.LANCZOS)
    plate = _vertical_gradient(512, BG_TOP, BG_BOTTOM).convert("RGBA")
    safe.alpha_composite(plate)
    safe.alpha_composite(inner, (102, 102))
    p = OUT / "icon-maskable-512.png"
    safe.save(p)
    print(f"{p.relative_to(ROOT)}")

    # ICO для ярлыка Windows. Размеры все сразу: система берёт подходящий сама,
    # а масштабирование одного большого даёт мыло в панели задач.
    sizes = (16, 24, 32, 48, 64, 128, 256)
    ico = OUT / "photo3d.ico"
    draw_icon(256).save(ico, format="ICO",
                       sizes=[(n, n) for n in sizes])
    print(f"{ico.relative_to(ROOT)} ({', '.join(str(n) for n in sizes)})")


if __name__ == "__main__":
    main()
