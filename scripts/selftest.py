"""Сквозная проверка: генерация -> Blender -> MCP-слой.

Тестовый кадр рисуется звездой намеренно: форма ни на что не похожа, поэтому
на турнтейбле сразу видно, построен ли меш по входному файлу или отрендерилось
что-то постороннее.

    /opt/photo3d/venv/bin/python /mnt/d/Develop/photo3d/scripts/selftest.py
"""
import asyncio
import math
import sys
import time
import traceback
from pathlib import Path

ROOT = Path("/mnt/d/Develop/photo3d")
sys.path.insert(0, str(ROOT))

from PIL import Image as PILImage, ImageDraw  # noqa: E402

FAILURES: list[str] = []


def phase(title: str):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def make_test_photo(path: Path, size: int = 640) -> Path:
    img = PILImage.new("RGB", (size, size), (246, 246, 244))
    d = ImageDraw.Draw(img)
    cx = cy = size / 2
    r_out, r_in, n = size * 0.38, size * 0.16, 5
    pts = []
    for i in range(2 * n):
        r = r_out if i % 2 == 0 else r_in
        a = -math.pi / 2 + i * math.pi / n
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    d.polygon(pts, fill=(212, 96, 54))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return path


def main() -> int:
    phase("1. тестовое фото")
    photo = make_test_photo(ROOT / "data" / "input" / "selftest_star.png")
    print("создано:", photo)

    phase("2. движок генерации")
    from pipeline.engines import get_engine
    glb = ROOT / "data" / "cache" / "selftest.glb"
    t = time.time()
    stats = get_engine("stub").generate(photo, glb, seed=1, mode="fast")
    print("stats:", stats)
    print(f"GLB: {glb} ({glb.stat().st_size} байт) за {time.time()-t:.2f} c")
    if not glb.exists() or glb.stat().st_size < 1000:
        FAILURES.append("GLB не создан или подозрительно мал")

    phase("3. Blender: рендер турнтейбла")
    from pipeline import render
    t = time.time()
    try:
        frames, engine, log = render.render_turntable(
            glb, ROOT / "data" / "cache" / "selftest_views", views=4, res=384
        )
        print(f"движок рендера: {engine}, кадров: {len(frames)}, за {time.time()-t:.1f} c")
        for f in frames:
            print(f"   {f.name}  {f.stat().st_size} байт")
        if len(frames) != 4:
            FAILURES.append(f"ожидал 4 кадра, получил {len(frames)}")
    except Exception as exc:  # noqa: BLE001
        FAILURES.append(f"рендер упал: {exc}")
        traceback.print_exc()

    phase("4. MCP-слой")
    try:
        from server.main import mcp
        tools = asyncio.run(mcp.list_tools())
        print("инструментов зарегистрировано:", len(tools))
        for t_ in tools:
            # в SDK 2.0 поле snake_case, в 1.x было inputSchema - берём любое
            schema = getattr(t_, "input_schema", None) or getattr(t_, "inputSchema", None) or {}
            print(f"   {t_.name}({', '.join(schema.get('properties', {}))})")
    except Exception as exc:  # noqa: BLE001
        FAILURES.append(f"список инструментов не собрался: {exc}")
        traceback.print_exc()

    phase("5. вызов photo_to_3d через MCP")
    try:
        from server.main import mcp
        res = asyncio.run(mcp.call_tool("photo_to_3d", {
            "image": "selftest_star.png", "mode": "fast", "seed": 7, "views": 4,
        }))
        print("тип результата:", type(res).__name__)
        blocks = getattr(res, "content", res)
        kinds: dict[str, int] = {}
        for b in blocks:
            kinds[type(b).__name__] = kinds.get(type(b).__name__, 0) + 1
        print("блоков в ответе:", kinds)
        for b in blocks:
            if type(b).__name__ == "TextContent":
                print("--- текст ---")
                print(b.text)
            else:
                data = getattr(b, "data", b"")
                print(f"--- {type(b).__name__}: {getattr(b, 'mime_type', '?')}, "
                      f"{len(data)} симв. base64 ---")
        # Ради этого всё и затевалось: картинки должны дойти до агента
        if kinds.get("ImageContent", 0) != 4:
            FAILURES.append(
                f"ожидал 4 ImageContent в ответе, получил {kinds.get('ImageContent', 0)}"
            )
    except Exception as exc:  # noqa: BLE001
        FAILURES.append(f"вызов инструмента упал: {exc}")
        traceback.print_exc()

    phase("ИТОГ")
    if FAILURES:
        for f in FAILURES:
            print("ПРОВАЛ:", f)
        return 1
    print("всё зелено")
    return 0


if __name__ == "__main__":
    sys.exit(main())
