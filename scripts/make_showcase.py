"""Сделать пару моделей через настоящий вызов MCP - для витрины и проверки.

    python make_showcase.py [файл ...]

Отличие от test_examples.py существенное: там движок дёргается напрямую, а
здесь идёт полный путь через инструмент photo_to_3d - со складыванием в базу,
записью метаданных и рендером полного оборота. Значит модели появятся в
веб-интерфейсе, а в сводке будут настоящие числа, а не прочерки.

Заодно это проверка: сводку читают из тех же ключей, что отдаёт движок, и
расхождение в именах однажды уже давало вопросительные знаки вместо чисел.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, "/mnt/d/Develop/photo3d")

from server import config  # noqa: E402
from server.main import mcp  # noqa: E402

DEFAULT = ["examples/ex00.png", "examples/ex05.png"]


async def one(image: str) -> None:
    print(f"\n=== {image}")
    res = await mcp.call_tool("photo_to_3d", {"image": image,
                                              "mode": "quality",
                                              "views": 4})
    blocks: dict[str, int] = {}
    for c in res.content:
        blocks[type(c).__name__] = blocks.get(type(c).__name__, 0) + 1
    print(f"блоков: {blocks}")
    for c in res.content:
        if type(c).__name__ == "TextContent":
            print(c.text)


async def main() -> int:
    names = sys.argv[1:] or DEFAULT
    for n in names:
        p = config.INPUT_DIR / n
        if not p.exists():
            print(f"нет файла {p}")
            return 1
        await one(n)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
