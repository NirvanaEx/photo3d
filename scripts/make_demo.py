"""Генерирует модель из синтетического кадра — для проверки живого обновления.

Форма отличается от звезды в selftest, чтобы новую карточку в интерфейсе
нельзя было спутать со старой.

    /opt/photo3d/venv/bin/python /mnt/d/Develop/photo3d/scripts/make_demo.py
"""
import asyncio
import math
import sys
from pathlib import Path

ROOT = Path("/mnt/d/Develop/photo3d")
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw  # noqa: E402


def draw_heart(path: Path, size: int = 640) -> Path:
    img = Image.new("RGB", (size, size), (245, 245, 243))
    d = ImageDraw.Draw(img)
    pts = []
    for i in range(720):
        t = i * math.pi / 360
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        pts.append((size / 2 + x * size / 42, size / 2 - y * size / 42))
    d.polygon(pts, fill=(198, 62, 76))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return path


async def main() -> None:
    photo = draw_heart(ROOT / "data" / "input" / "demo_heart.png")
    print("кадр:", photo)
    from server.main import mcp
    res = await mcp.call_tool("photo_to_3d", {
        "image": "demo_heart.png", "mode": "quality", "seed": 42, "views": 4,
    })
    blocks = getattr(res, "content", res)
    for b in blocks:
        if type(b).__name__ == "TextContent":
            print(b.text)
    imgs = sum(1 for b in blocks if type(b).__name__ == "ImageContent")
    print(f"картинок в ответе: {imgs}")


if __name__ == "__main__":
    asyncio.run(main())
