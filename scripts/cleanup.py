"""Убрать из базы отработанное. Не удаляя, а перекладывая в корзину.

    python cleanup.py          # показать план, ничего не трогая
    python cleanup.py --do     # выполнить

Почему корзина, а не удаление. Место на диске есть, а вернуть передумав
дешевле, чем восстанавливать. Опустошить корзину можно в любой момент руками.

Что считается отработанным:
  * записи без model.glb - оборвавшиеся запуски;
  * модели движка-заглушки и всё, что из них сделано, - они были нужны, пока
    настоящего генератора не было;
  * поимённо заданные неудачные опыты.

Свежие записи не трогаются вовсе: работа могла идти прямо сейчас, и уборка
не должна сносить её на ходу. Мы уже чуть не удалили идущую генерацию,
приняв пустую папку за мусор.
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, "/mnt/d/Develop/photo3d")

from server import config  # noqa: E402

# Всё, что менялось за последние четверть часа, считается работой в процессе
FRESH_SEC = 15 * 60

# Неудачные опыты, которые нет смысла хранить
FAILED = {
    "m_3022cd": "голова без плеч вышла плоской карточкой",
    "m_a5d5da": "перекраска проекцией размазалась по бокам",
}


def classify(d: Path) -> tuple[bool, str]:
    """(убирать ли, причина)"""
    age = time.time() - d.stat().st_mtime
    if age < FRESH_SEC:
        return False, "свежая, возможно в работе"

    if d.name in FAILED:
        return True, FAILED[d.name]

    if not (d / "model.glb").exists():
        return True, "нет model.glb, запуск оборвался"

    meta = d / "meta.json"
    if not meta.exists():
        return True, "нет метаданных"

    try:
        j = json.loads(meta.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return True, "метаданные не читаются"

    stats = j.get("stats") or {}
    engine = stats.get("engine")

    if engine == "stub":
        return True, "модель заглушки"
    return False, f"движок {engine}"


def parent_of(d: Path) -> str | None:
    """Из какой модели сделана эта. Производные (ретопология, пересадка)
    без родителя смысла не имеют, и решать их судьбу надо вслед за ним."""
    meta = d / "meta.json"
    if not meta.exists():
        return None
    try:
        j = json.loads(meta.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None

    ref = j.get("derived_from")
    if isinstance(ref, str) and ref.startswith("m_"):
        return ref

    # запасной путь: в source лежит полный путь к GLB родителя
    for part in Path(str(j.get("source", ""))).parts:
        if part.startswith("m_"):
            return part
    return None


def size_of(d: Path) -> int:
    return sum(f.stat().st_size for f in d.rglob("*") if f.is_file())


def main() -> int:
    do_it = "--do" in sys.argv
    trash = config.DATA / "trash"

    dirs = sorted(p for p in config.OUTPUT_DIR.iterdir()
                  if p.is_dir() and p.name.startswith("m_"))

    doomed: dict[str, str] = {}
    for d in dirs:
        drop, why = classify(d)
        if drop:
            doomed[d.name] = why

    # Производные уходят вслед за родителем. Повторяем, пока список растёт:
    # цепочка бывает длиннее одного звена (заглушка -> ретопология -> ещё что-то).
    fresh = {d.name for d in dirs if time.time() - d.stat().st_mtime < FRESH_SEC}
    changed = True
    while changed:
        changed = False
        for d in dirs:
            if d.name in doomed or d.name in fresh:
                continue
            parent = parent_of(d)
            if parent and parent in doomed:
                doomed[d.name] = f"сделана из {parent}, а та уходит"
                changed = True

    keep = [d for d in dirs if d.name not in doomed]
    freed = sum(size_of(config.OUTPUT_DIR / n) for n in doomed)

    print(f"остаётся: {len(keep)}")
    for d in keep:
        _, why = classify(d)
        print(f"   {d.name}  ({why})")
    print(f"\nв корзину: {len(doomed)}, освободится {freed / 1e6:.0f} МБ")
    for name, why in sorted(doomed.items()):
        print(f"   {name}  — {why}")

    if not do_it:
        print("\nэто только план. Выполнить: cleanup.py --do")
        return 0

    trash.mkdir(parents=True, exist_ok=True)
    for name in doomed:
        dst = trash / name
        if dst.exists():
            shutil.rmtree(dst)
        shutil.move(str(config.OUTPUT_DIR / name), str(dst))
    print(f"\nперенесено в {trash}")
    print("окончательно удалить: rm -rf " + str(trash))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
