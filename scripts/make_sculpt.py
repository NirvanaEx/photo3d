"""Сделать из готовой модели чистую версию под лепку - через вызов MCP.

    python make_sculpt.py m_495350 [граней]

Полный путь инструмента prepare_for_sculpting: ремонт сетки, воксельная
перестройка в квады, перенос внешнего вида запеканием, рендер оборота.
Результат ложится в базу отдельной моделью, исходная остаётся нетронутой.
"""
from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, "/mnt/d/Develop/photo3d")

from server.main import mcp  # noqa: E402


async def main() -> int:
    mid = sys.argv[1] if len(sys.argv) > 1 else "last"
    faces = int(sys.argv[2]) if len(sys.argv) > 2 else 20_000

    res = await mcp.call_tool("prepare_for_sculpting",
                              {"model_id": mid, "target_faces": faces,
                               "keep_texture": True})
    for c in res.content:
        if type(c).__name__ == "TextContent":
            print(c.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
