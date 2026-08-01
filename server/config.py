"""Пути и константы. Всё переопределяется через переменные окружения,
чтобы тот же код работал и на хосте, и внутри GPU-контейнера."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(os.environ.get("PHOTO3D_ROOT", "/mnt/d/Develop/photo3d"))

DATA = ROOT / "data"
INPUT_DIR = DATA / "input"
OUTPUT_DIR = DATA / "output"
CACHE_DIR = DATA / "cache"
WEIGHTS_DIR = DATA / "weights"

BLENDER = Path(os.environ.get("PHOTO3D_BLENDER", "/opt/blender/blender"))
BLENDER_SCRIPTS = ROOT / "pipeline" / "blender"

# Движок генерации: stub - заглушка без GPU, trellis - настоящий (появится позже)
ENGINE = os.environ.get("PHOTO3D_ENGINE", "stub")

# Превью для Claude. 512 - компромисс: деталей хватает, контекст не раздувается.
PREVIEW_RES = int(os.environ.get("PHOTO3D_PREVIEW_RES", "512"))
DEFAULT_VIEWS = 4

# Кадров полного оборота, которые пишутся на диск. Веб-интерфейс крутит по ним
# модель перетаскиванием - это работает без WebGL и не зависит от того, ожил ли
# 3D-вьюер. В контекст агента при этом уходит лишь несколько кадров: смотреть
# два десятка почти одинаковых картинок бессмысленно, а место они занимают.
# Рендерятся все за один запуск Blender, поэтому 24 вместо 4 стоят секунд пять.
SPIN_FRAMES = int(os.environ.get("PHOTO3D_SPIN_FRAMES", "24"))

# Потолок времени на рендер, чтобы зависший Blender не вешал MCP-вызов
RENDER_TIMEOUT_SEC = int(os.environ.get("PHOTO3D_RENDER_TIMEOUT", "300"))


def ensure_dirs() -> None:
    for d in (INPUT_DIR, OUTPUT_DIR, CACHE_DIR, WEIGHTS_DIR):
        d.mkdir(parents=True, exist_ok=True)
