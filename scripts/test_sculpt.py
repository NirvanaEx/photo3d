"""Проверка подготовки под скульптинг — через MCP-инструмент, как это
будет вызываться в работе.

    /opt/photo3d/venv/bin/python /mnt/d/Develop/photo3d/scripts/test_sculpt.py [model_id]
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path("/mnt/d/Develop/photo3d")
sys.path.insert(0, str(ROOT))


async def main() -> int:
    from server.main import mcp
    from server.store import ModelStore

    src = sys.argv[1] if len(sys.argv) > 1 else ModelStore().resolve("last")
    target = int(sys.argv[2]) if len(sys.argv) > 2 else 40000
    print(f"исходная модель: {src}, целевых граней: {target}\n")

    res = await mcp.call_tool("prepare_for_sculpting", {
        "model_id": src, "target_faces": target,
    })
    blocks = getattr(res, "content", res)
    kinds: dict[str, int] = {}
    for b in blocks:
        kinds[type(b).__name__] = kinds.get(type(b).__name__, 0) + 1
        if type(b).__name__ == "TextContent":
            print(b.text)
    print("\nблоков в ответе:", kinds)

    ok = kinds.get("ImageContent", 0) == 4
    print("ИТОГ:", "готово" if ok else "ПРОБЛЕМА: превью не вернулись")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
