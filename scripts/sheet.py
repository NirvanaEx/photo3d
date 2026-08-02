"""Контактный лист из уже отрендеренных ракурсов модели.

    python sheet.py m_495350 [сколько]

От view_glb.py отличается тем, что ничего не рендерит заново: берёт кадры,
которые photo_to_3d уже положил на диск. Посмотреть на готовую модель стоит
секунды, а не минуты работы Cycles.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, "/mnt/d/Develop/photo3d")

from PIL import Image  # noqa: E402

from server import config  # noqa: E402


def main() -> int:
    mid = sys.argv[1]
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 4

    views = sorted((config.OUTPUT_DIR / mid / "views").glob("*.png"))
    if not views:
        print(f"нет ракурсов у {mid}")
        return 1

    step = max(len(views) // count, 1)
    picked = [views[i] for i in range(0, len(views), step)][:count]
    ims = [Image.open(p).convert("RGB") for p in picked]

    w, h = ims[0].size
    sheet = Image.new("RGB", (w * len(ims), h), (18, 18, 20))
    for i, im in enumerate(ims):
        sheet.paste(im, (i * w, 0))

    dst = config.OUTPUT_DIR / mid / "contact.jpg"
    sheet.save(dst, quality=90)
    print(f"{mid}: {len(views)} ракурсов, взято {len(picked)}")
    print(f"смотреть: {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
