"""Прогнать примеры из репозитория TRELLIS.2 через нашу сборку.

    python test_examples.py [сколько] [режим]

Для каждого примера: снятие фона -> генерация -> постановочный рендер.
Итог складывается в одну картинку - слева исходный снимок, справа четыре
ракурса готовой модели. Так видно не «отработало без ошибок», а совпадает ли
результат с тем, что просили.

Скрипт можно прерывать и запускать снова: готовое пропускается. Каждая модель
идёт минут шесть-семь, и терять их из-за случайного сбоя на шестой из восьми
было бы обидно.
"""
from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, "/mnt/d/Develop/photo3d")

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from pipeline import render  # noqa: E402
from pipeline.engines import get_engine  # noqa: E402
from server import config  # noqa: E402

SRC_DIR = config.ROOT / "data" / "input" / "examples"
OUT_DIR = config.ROOT / "data" / "cache" / "examples"
TILE = 300


def font(size: int = 16):
    try:
        return ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default()


def one(src: Path, mode: str) -> dict | None:
    work = OUT_DIR / src.stem
    work.mkdir(parents=True, exist_ok=True)
    glb = work / "model.glb"
    report_path = work / "report.json"

    if report_path.exists() and glb.exists():
        print(f"  {src.stem}: уже готово, пропускаю")
        return json.loads(report_path.read_text(encoding="utf-8"))

    engine = get_engine("trellis")
    t = time.time()
    try:
        rep = engine.generate(src, glb, seed=42, mode=mode)
    except Exception as exc:  # noqa: BLE001
        print(f"  {src.stem}: ОТКАЗ {exc}")
        (work / "error.txt").write_text(
            f"{exc}\n\n{traceback.format_exc()}", encoding="utf-8")
        return None
    rep.pop("log", None)

    frames, rengine, rlog = render.render_turntable(
        glb, work / "views", views=8, res=config.PREVIEW_RES, style="beauty")
    if not frames:
        print(f"  {src.stem}: рендер не удался")
        (work / "render_error.txt").write_text(rlog[-4000:], encoding="utf-8")
        return None

    rep["рендер_движок"] = rengine
    rep["кадров"] = len(frames)
    rep["по_часам_с"] = round(time.time() - t, 1)
    report_path.write_text(json.dumps(rep, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    print(f"  {src.stem}: {rep['по_часам_с']} с, "
          f"граней {rep.get('граней')}, "
          f"видеопамять {rep.get('видеопамять', {}).get('пик_выделено_ГБ')} ГБ")
    return rep


def row(src: Path, rep: dict) -> Image.Image:
    """Слева исходник, справа четыре ракурса."""
    views = sorted((OUT_DIR / src.stem / "views").glob("*.png"))
    picked = [views[i] for i in range(0, len(views), max(len(views) // 4, 1))][:4]

    cells = []
    orig = Image.open(src).convert("RGBA")
    flat = Image.new("RGB", orig.size, (26, 26, 28))
    flat.paste(orig, (0, 0), orig)
    cells.append(flat)
    cells += [Image.open(p).convert("RGB") for p in picked]

    strip = Image.new("RGB", (TILE * len(cells), TILE + 20), (26, 26, 28))
    for i, im in enumerate(cells):
        im = im.copy()
        im.thumbnail((TILE, TILE), Image.LANCZOS)
        strip.paste(im, (i * TILE + (TILE - im.width) // 2,
                         (TILE - im.height) // 2))
    vram = rep.get("видеопамять", {}).get("пик_выделено_ГБ", "?")
    ImageDraw.Draw(strip).text(
        (6, TILE + 2),
        f"{src.stem}   {rep.get('граней', '?')} граней   "
        f"{rep.get('по_часам_с', '?')} с   видеопамять {vram} ГБ",
        fill=(205, 205, 205), font=font())
    return strip


def main() -> int:
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    mode = sys.argv[2] if len(sys.argv) > 2 else "quality"

    photos = sorted(SRC_DIR.glob("ex*.png"))[:count]
    if not photos:
        print(f"нет примеров в {SRC_DIR} - прогони fetch_examples.py")
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"примеров: {len(photos)}, режим {mode}\n")

    rows = []
    for src in photos:
        rep = one(src, mode)
        if rep:
            rows.append(row(src, rep))

    if not rows:
        print("ни один пример не прошёл")
        return 1

    sheet = Image.new("RGB", (rows[0].width, sum(r.height for r in rows)),
                      (26, 26, 28))
    y = 0
    for r in rows:
        sheet.paste(r, (0, y))
        y += r.height
    dst = OUT_DIR / "итог.jpg"
    sheet.save(dst, quality=90)
    print(f"\nготово {len(rows)} из {len(photos)}\nсмотреть: {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
