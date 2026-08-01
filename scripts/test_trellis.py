"""Первый прогон настоящего движка: фото -> 3D.

Проверяется весь хостовый путь целиком, а не только контейнер: снятие фона,
сборка команды docker, монтирование томов, разбор ответа. Именно здесь
выяснится, укладывается ли 512 в наши 12 ГБ видеопамяти - официально
заявлено 24.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "/mnt/d/Develop/photo3d")

from pipeline.engines import get_engine  # noqa: E402
from server import config  # noqa: E402


def main() -> int:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else \
        config.ROOT / "data" / "input" / "demo_heart.png"
    if not src.exists():
        print(f"нет файла {src}")
        return 1

    out_dir = config.ROOT / "data" / "cache" / "trellis_test"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "model.glb"

    engine = get_engine("trellis")
    print(f"движок: {engine.name}, фото: {src.name}")
    print("пошла генерация, первый запуск дольше - веса читаются с диска\n")

    t = time.time()
    try:
        report = engine.generate(src, out, seed=42, mode="quality")
    except Exception as exc:  # noqa: BLE001
        print(f"ОТКАЗ: {exc}")
        return 1

    log = report.pop("log", "")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\nвсего по часам: {time.time() - t:.1f} с")
    print(f"результат: {out} ({out.stat().st_size / 1e6:.1f} МБ)")

    (out_dir / "log.txt").write_text(log, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
