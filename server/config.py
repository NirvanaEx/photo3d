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

# --------------------------------------------------------------------------- #
# Godot
# --------------------------------------------------------------------------- #

# Движок запускается с ВИНДОВОЙ стороны, а не из WSL, и это не вкусовщина:
# внутри WSL графика достаётся только программным контекстом - тем самым, из-за
# которого EEVEE проигрывает Cycles в шесть раз. С Windows Godot видит RTX 3060
# напрямую. WSL исполняет .exe через interop, нужен лишь перевод путей.
#
# Консольная сборка, а не обычная: обычная отвязывается от консоли и не отдаёт
# ни строчки вывода, а весь разбор результата построен на её печати.
GODOT = Path(os.environ.get(
    "PHOTO3D_GODOT",
    "/mnt/c/Tools/Godot/Godot_v4.7.1-stable_win64_console.exe"))

GAME_DIR = Path(os.environ.get("PHOTO3D_GAME", str(ROOT / "game")))
GAME_ASSETS = GAME_DIR / "assets" / "models"

# Импорт трёх моделей на 63 МБ занял 25.9 с, дальше пересобирается только
# изменившееся. Потолок с запасом на пачку тяжёлых ассетов.
GODOT_TIMEOUT_SEC = int(os.environ.get("PHOTO3D_GODOT_TIMEOUT", "600"))

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

# Эти два значения связаны, и связь неочевидная: развёртка строится
# автоматически по сетке из marching cubes, поэтому каждый треугольник
# получает свой лоскут, а между лоскутами остаётся незаполненный фон. Чем
# больше граней на ту же карту, тем мельче лоскуты - и тем сильнее чёрный
# фон затекает в них при сглаживании текстуры.
#
# Замер: 300 000 граней на карту 2048 дают ~14 пикселей на треугольник, и
# модель выглядит испачканной, особенно на гладких местах вроде лица.
# 80 000 граней на 4096 дают ~210 пикселей - грязь уходит полностью, время
# генерации то же. Подробностей формы при этом хватает с запасом.
TRELLIS_TEXTURE_SIZE = int(os.environ.get("PHOTO3D_TRELLIS_TEXTURE", "4096"))
TRELLIS_DECIMATION = int(os.environ.get("PHOTO3D_TRELLIS_DECIMATION", "80000"))

# Генерация вместе с загрузкой весов с диска идёт минуты, а не секунды.
TRELLIS_TIMEOUT_SEC = int(os.environ.get("PHOTO3D_TRELLIS_TIMEOUT", "1800"))

# Модель для снятия фона. isnet-general-use даёт заметно более чистый силуэт
# на предметах, чем u2net по умолчанию.
REMBG_MODEL = os.environ.get("PHOTO3D_REMBG_MODEL", "isnet-general-use")

# Превью для Claude. 512 - компромисс: деталей хватает, контекст не раздувается.
PREVIEW_RES = int(os.environ.get("PHOTO3D_PREVIEW_RES", "512"))
DEFAULT_VIEWS = 4

# Стиль превью по умолчанию. Была глина - и это стало вредно, как только
# появился настоящий генератор: TRELLIS отдаёт модели с PBR-материалами, а
# глина закрашивает их однородно серым. Агент смотрит на превью, чтобы судить
# о результате, и серая болванка вместо цветной модели - это потеря главного.
# Постановочный кадр на Cycles стоит секунд двадцать сверх быстрого, что на
# фоне шестиминутной генерации несущественно.
PREVIEW_STYLE = os.environ.get("PHOTO3D_PREVIEW_STYLE", "beauty")

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
