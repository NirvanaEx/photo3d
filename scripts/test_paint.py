"""Проверка покраски и постановочного рендера.

    /opt/photo3d/venv/bin/python /mnt/d/Develop/photo3d/scripts/test_paint.py [model_id] [цвет]
"""
import asyncio
import sys
import time
from pathlib import Path

ROOT = Path("/mnt/d/Develop/photo3d")
sys.path.insert(0, str(ROOT))


async def main() -> int:
    from server.main import mcp
    from server.store import ModelStore

    store = ModelStore()
    # resolve, а не сырой аргумент: "last" понимает только он, и без этого
    # скрипт падал на store.meta("last") уже ПОСЛЕ успешной покраски
    mid = store.resolve(sys.argv[1] if len(sys.argv) > 1 else "last")
    color = sys.argv[2] if len(sys.argv) > 2 else "терракота"
    print(f"модель {mid}, цвет {color}\n")

    t = time.time()
    # «фото» вместо цвета — проверить путь с настоящей картинкой в материале
    args = {"model_id": mid, "metallic": 0.0, "roughness": 0.45, "style": "beauty"}
    if color == "фото":
        args["from_photo"] = True
    else:
        args["color"] = color
    res = await mcp.call_tool("paint_model", args)
    blocks = getattr(res, "content", res)
    kinds: dict[str, int] = {}
    for b in blocks:
        kinds[type(b).__name__] = kinds.get(type(b).__name__, 0) + 1
        if type(b).__name__ == "TextContent":
            print(b.text)
    print(f"\nвсего {time.time()-t:.1f} c, блоков: {kinds}")

    meta = store.meta(mid)
    print("движок рендера:", meta.get("render_engine"))
    print("стиль:", meta.get("style"))
    print("покраска:", meta.get("paint"))

    ok = kinds.get("ImageContent", 0) == 4 and meta.get("style") == "beauty"
    print("ИТОГ:", "готово" if ok else "ПРОБЛЕМА")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
