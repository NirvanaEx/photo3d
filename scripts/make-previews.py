"""Превью сцен для лаунчера: по кадру с каждой сцены в assets/previews.

    wsl -e /opt/photo3d/venv/bin/python /mnt/d/Develop/photo3d/scripts/make-previews.py
    wsl -e /opt/photo3d/venv/bin/python .../make-previews.py islands walk

Без аргументов снимаются все сцены из game/scenes, кроме самого лаунчера.

Кадр снимает тот же bridge.shot_scene, что и инструмент агента: движок
запускается с окном (в --headless кадров не рисуется вовсе, см. docs/PITFALLS.md),
берётся камера самой сцены - та, что поставил автор, - и первый кадр кладётся
в game/assets/previews/<имя сцены>.png.

Скрипт отдельный, а не часть лаунчера: снимать сцену изнутри игры значило бы
грузить все пять сцен разом при каждом запуске. Превью меняются редко -
пересобирать их вручную дешевле, чем платить за них каждым стартом.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, "/mnt/d/Develop/photo3d")

from bridge import shot_scene as shot  # noqa: E402
from server import config  # noqa: E402

SCENES = config.GAME_DIR / "scenes"
OUT = config.GAME_DIR / "assets" / "previews"
SKIP = {"launcher"}

# 640x360 - карточка в лаунчере шириной чуть больше трёхсот точек, на экране
# с двойным масштабом это 640. Больше снимать незачем: превью не рассматривают.
WIDTH = 640


def scene_ids(argv: list[str]) -> list[str]:
    if argv:
        return [a.removesuffix(".tscn") for a in argv]
    return sorted(p.stem for p in SCENES.glob("*.tscn") if p.stem not in SKIP)


def _import() -> str:
    """Разобрать новые картинки движком. Тот же вызов, что в bridge/import_asset.py."""
    proc = subprocess.run(
        [str(config.GODOT), "--headless", "--path", shot.win_path(config.GAME_DIR),
         "--import"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=config.GODOT_TIMEOUT_SEC)
    return "готово" if proc.returncode == 0 else f"движок вернул {proc.returncode}"


def main() -> int:
    ids = scene_ids(sys.argv[1:])
    if not ids:
        print(f"в {SCENES} нет сцен")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)

    failed = []
    for sid in ids:
        print(f"снимаю {sid} ... ", end="", flush=True)
        try:
            res = shot.shot_scene(scene=sid, views=1, res=WIDTH)
        except Exception as exc:                       # noqa: BLE001
            print(f"не вышло: {exc}")
            failed.append(sid)
            continue
        shots = res.get("shots") or []
        if not shots:
            print("движок не вернул кадров")
            failed.append(sid)
            continue
        src = Path(shots[0]["path"])
        dst = OUT / f"{sid}.png"
        shutil.copyfile(src, dst)
        print(f"{dst.name}")

    # Импорт обязателен, и это не перестраховка: новая картинка в assets/ для
    # запущенной игры не существует, пока движок не разобрал её в .godot/imported.
    # Без этого шага лаунчер честно показывает «превью нет» на только что
    # снятых кадрах.
    print("импортирую ... ", end="", flush=True)
    print(_import())

    if failed:
        # Ошибка несёт, что делать дальше (CLAUDE.md).
        print()
        print("не снялись: " + ", ".join(failed))
        print("посмотреть причину целиком: запусти движок руками на этой сцене")
        print(f"  {config.GODOT} --path <game> res://scenes/<имя>.tscn")
        return 1

    print()
    print(f"готово: {len(ids)} превью в {OUT}")
    print("Godot подхватит их при следующем запуске - импорт идёт сам")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
