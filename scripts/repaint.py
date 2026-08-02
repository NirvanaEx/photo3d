"""Скопировать модель и перекрасить копию проекцией исходного кадра.

    python repaint.py m_cee258

Зачем копия. paint_model меняет модель на месте - это сделано намеренно,
чтобы открытый веб-интерфейс сразу показал изменение. Но при сравнении
«было/стало» терять исходную раскраску нельзя, поэтому красим дубликат.

Смысл затеи. Геометрию TRELLIS лепит хорошо - проверено рендером глиной:
нос, губы, надбровья, пряди волос на месте. Портит вид ТЕКСТУРА: раскраска
лица ложится мимо. А исходный рисунок у нас есть, и персонаж на нём смотрит
прямо - значит фронтальная проекция должна положить глаза на глазницы, а губы
на губы.

Честное ограничение остаётся прежним: бока и затылок получат растянутый цвет,
одного ракурса на всю поверхность не хватает.
"""
from __future__ import annotations

import asyncio
import shutil
import sys

sys.path.insert(0, "/mnt/d/Develop/photo3d")

from server import config  # noqa: E402
from server.main import mcp, store  # noqa: E402


async def main() -> int:
    src_id = sys.argv[1]
    src_dir = config.OUTPUT_DIR / src_id
    if not (src_dir / "model.glb").exists():
        print(f"нет модели {src_id}")
        return 1

    new_id, new_dir = store.create()
    for name in ("model.glb", "meta.json"):
        if (src_dir / name).exists():
            shutil.copy2(src_dir / name, new_dir / name)
    for photo in src_dir.glob("input.*"):
        shutil.copy2(photo, new_dir / photo.name)
    print(f"копия {src_id} -> {new_id}")

    res = await mcp.call_tool("paint_model", {
        "model_id": new_id,
        "from_photo": True,
        "roughness": 0.65,
    })
    for c in res.content:
        if type(c).__name__ == "TextContent":
            print(c.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
