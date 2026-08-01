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

# Движок генерации. По умолчанию настоящий; stub остаётся для отладки
# обвязки без видеокарты и контейнера - он на порядок быстрее и не требует
# ничего, кроме numpy.
ENGINE = os.environ.get("PHOTO3D_ENGINE", "trellis")

# --------------------------------------------------------------------------- #
# TRELLIS.2
# --------------------------------------------------------------------------- #

# Веса лежат НЕ в data/weights на диске D, а на нативной ext4, и это
# принципиально. safetensors читаются через mmap: страницы идут из кэша ядра
# и вытесняются под нагрузкой, поэтому 11 ГБ весов уживаются с 10 ГБ ОЗУ.
# Через drvfs (/mnt/d) mmap так не работает, и всё упирается в память.
TRELLIS_WEIGHTS = Path(os.environ.get("PHOTO3D_TRELLIS_WEIGHTS",
                                      "/opt/photo3d/weights"))
TRELLIS_IMAGE = os.environ.get("PHOTO3D_TRELLIS_IMAGE", "photo3d/trellis:1")
TRELLIS_SCRIPTS = ROOT / "pipeline" / "trellis"

# Разрешение объёма. 1024 и каскады требуют весов, которые мы не качали:
# на 12 ГБ они всё равно не идут.
TRELLIS_PIPELINE_TYPE = os.environ.get("PHOTO3D_TRELLIS_TYPE", "512")

# У авторов в примере 4096, но это под 24 ГБ видеопамяти.
TRELLIS_TEXTURE_SIZE = int(os.environ.get("PHOTO3D_TRELLIS_TEXTURE", "2048"))
TRELLIS_DECIMATION = int(os.environ.get("PHOTO3D_TRELLIS_DECIMATION", "300000"))

# Генерация вместе с загрузкой весов с диска идёт минуты, а не секунды.
TRELLIS_TIMEOUT_SEC = int(os.environ.get("PHOTO3D_TRELLIS_TIMEOUT", "1800"))

# Модель для снятия фона. isnet-general-use даёт заметно более чистый силуэт
# на предметах, чем u2net по умолчанию.
REMBG_MODEL = os.environ.get("PHOTO3D_REMBG_MODEL", "isnet-general-use")

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
