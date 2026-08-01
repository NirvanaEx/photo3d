"""Проверка сглаживания через MCP-инструмент.

    /opt/photo3d/venv/bin/python .../test_smooth.py [model_id] [сила] [проходов] [подразделений] [стиль]
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path("/mnt/d/Develop/photo3d")
sys.path.insert(0, str(ROOT))


async def main() -> int:
    from server.main import mcp
    from server.store import ModelStore

    a = sys.argv[1:]
    args = {
        "model_id": a[0] if len(a) > 0 else ModelStore().resolve("last"),
        "strength": float(a[1]) if len(a) > 1 else 0.7,
        "iterations": int(a[2]) if len(a) > 2 else 15,
        "subdivide": int(a[3]) if len(a) > 3 else 0,
        "style": a[4] if len(a) > 4 else "",
    }
    print("параметры:", args, "\n")

    res = await mcp.call_tool("smooth_model", args)
    blocks = getattr(res, "content", res)
    kinds: dict[str, int] = {}
    for b in blocks:
        kinds[type(b).__name__] = kinds.get(type(b).__name__, 0) + 1
        if type(b).__name__ == "TextContent":
            print(b.text)
    print("\nблоков:", kinds)
    return 0 if kinds.get("ImageContent", 0) == 4 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
