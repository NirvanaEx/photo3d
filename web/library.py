"""Библиотека моделей: то, чем распоряжается веб, а не генератор.

Здесь главное - **разделение владения файлами**. `meta.json` пишет пайплайн,
и веб его не трогает вообще: генерация идёт в соседнем процессе и вполне
может писать туда прямо сейчас. Всё, что добавляет человек через интерфейс -
имя, заметка, звёздочка - лежит рядом в `ui.json`, у которого один-единственный
автор. Так два процесса пишут в одну папку модели и не наступают друг другу
на руки. Правило простое: пайплайну - `meta.json`, вебу - `ui.json`.

Удаление - перекладывание в `data/trash`, ровно как в `scripts/cleanup.py`,
и по той же причине: место на диске есть, а вернуть передумав дешевле, чем
восстанавливать. Окончательное стирание - отдельное действие отдельной
кнопкой, случайно на него не попадёшь.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any

from server import config

# Идентификатор модели приходит из URL и подставляется в путь, поэтому
# проверяется не «начинается с m_», а полным совпадением с шаблоном.
# Так внутрь заведомо не попадут ни '..', ни косые черты, ни NUL - и это
# не зависит от того, не забыли ли ниже сделать resolve() и сравнить корни.
# Одной такой проверки мало (в model_file защита остаётся своя), но она
# отсекает целый класс ошибок в самом начале.
MODEL_ID = re.compile(r"m_[0-9a-z]{2,32}\Z")

# Ссылки на другие модели внутри строк meta: 'm_0ef45f + m_cee258:model_fine.glb'
MODEL_REF = re.compile(r"\bm_[0-9a-z]{2,32}\b")

TRASH_DIR = config.DATA / "trash"


def valid_id(model_id: str) -> bool:
    return bool(model_id) and MODEL_ID.match(model_id) is not None


def model_dir(model_id: str, trashed: bool = False) -> Path:
    """Папка модели. Вызывать только после valid_id - иначе это дыра."""
    return (TRASH_DIR if trashed else config.OUTPUT_DIR) / model_id


# --------------------------------------------------------------------- размер

# Пересчёт размера - полсотни stat через drvfs на каждую модель, а зовётся он
# на каждое изменение папки. Кэш по mtime снимает почти все повторы.
_size_cache: dict[str, tuple[float, int]] = {}


def folder_size(d: Path) -> int:
    """Сколько занимает модель на диске.

    Кэшируется по mtime папки. Дописывание в log.txt mtime папки не меняет,
    поэтому число может отставать на несколько килобайт - для строки «53 МБ»
    это несущественно, а полный обход drvfs на каждый опрос SSE - нет.
    """
    try:
        stamp = d.stat().st_mtime
    except OSError:
        return 0
    key = str(d)
    hit = _size_cache.get(key)
    if hit and hit[0] == stamp:
        return hit[1]
    total = 0
    for f in d.rglob("*"):
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError:
            continue          # файл могли удалить прямо под обходом
    _size_cache[key] = (stamp, total)
    return total


# ------------------------------------------------------------------- ui.json


def read_ui(d: Path) -> dict[str, Any]:
    f = d / "ui.json"
    if not f.exists():
        return {}
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}            # битый ui.json не должен ронять весь список
    return data if isinstance(data, dict) else {}


# Что человек вправе править через интерфейс. Список закрытый: обработчик
# принимает JSON из браузера, и без него в ui.json приехало бы что угодно.
UI_FIELDS = {"title", "note", "star", "deleted_at", "scale"}


def patch_ui(d: Path, patch: dict[str, Any]) -> dict[str, Any]:
    """Дописать поля в ui.json, не теряя остальные."""
    data = read_ui(d)
    for k, v in patch.items():
        if k not in UI_FIELDS:
            continue
        if v is None:
            data.pop(k, None)
        else:
            data[k] = v
    # Через временный файл: обрыв записи не должен оставить огрызок JSON
    # вместо имени модели.
    tmp = d / "ui.json.tmp"
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, d / "ui.json")
    return data


# ---------------------------------------------------------------- родословная


def parents_of(meta: dict[str, Any], known: set[str] | None = None) -> list[str]:
    """Из каких моделей сделана эта.

    Родителей может быть больше одного: пересадка головы берёт тело из одной
    модели, голову из другой, и в `source` лежит строка вида
    'm_0ef45f + m_cee258:model_fine.glb'. Поэтому здесь не разбор пути, как
    в cleanup.py, а поиск всех ссылок разом - иначе второй родитель теряется,
    и в интерфейсе цепочка обрывается на полпути.

    known отсеивает совпадения, за которыми нет настоящей модели: имя входного
    файла тоже может начинаться на m_.
    """
    out: list[str] = []
    ref = meta.get("derived_from")
    if isinstance(ref, str) and MODEL_ID.match(ref):
        out.append(ref)
    for hit in MODEL_REF.findall(str(meta.get("source", ""))):
        if hit not in out:
            out.append(hit)
    if known is not None:
        out = [p for p in out if p in known]
    return out


# ------------------------------------------------------------------- корзина


def list_ids(root: Path) -> list[str]:
    """Модели в папке, свежие сверху."""
    if not root.is_dir():
        return []
    dirs = [p for p in root.iterdir() if p.is_dir() and valid_id(p.name)]
    dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [p.name for p in dirs]


def to_trash(model_id: str) -> None:
    """Убрать модель из библиотеки, не удаляя."""
    src = model_dir(model_id)
    TRASH_DIR.mkdir(parents=True, exist_ok=True)
    dst = TRASH_DIR / model_id

    # Занятого имени тут быть не может: пока модель лежит в корзине, в
    # output её нет, а id не переиспользуются. Если всё же есть - это
    # чужая папка, и молча стирать её нельзя.
    if dst.exists():
        raise FileExistsError(model_id)

    # Отметку о времени удаления ставим ДО переноса: после него папка уже
    # не наша, а сам перенос mtime не меняет, и «удалена когда» иначе
    # неоткуда взять - в корзине лежали бы даты последней генерации.
    try:
        patch_ui(src, {"deleted_at": time.time()})
    except OSError:
        pass                 # не смогли пометить - переносить всё равно надо

    shutil.move(str(src), str(dst))
    _size_cache.pop(str(src), None)


def from_trash(model_id: str) -> None:
    """Вернуть модель в библиотеку."""
    src = TRASH_DIR / model_id
    dst = model_dir(model_id)
    if dst.exists():
        raise FileExistsError(model_id)
    shutil.move(str(src), str(dst))
    _size_cache.pop(str(src), None)
    try:
        patch_ui(dst, {"deleted_at": None})
    except OSError:
        pass


def purge(model_id: str) -> None:
    """Стереть окончательно. Обратного пути нет."""
    d = TRASH_DIR / model_id
    if not d.is_dir():
        return
    shutil.rmtree(d)
    _size_cache.pop(str(d), None)


def purge_all() -> int:
    """Опустошить корзину. Возвращает, сколько моделей стёрто."""
    n = 0
    for mid in list_ids(TRASH_DIR):
        purge(mid)
        n += 1
    return n


# --------------------------------------------------------------- «в работе»

# Столько же, сколько в scripts/cleanup.py, и по той же причине: мы уже
# чуть не снесли идущую генерацию, приняв недописанную папку за мусор.
# Здесь это не запрет, а предупреждение - кнопку нажимает человек, и он
# может знать лучше. Но знать он должен.
FRESH_SEC = 15 * 60


def is_fresh(d: Path) -> bool:
    try:
        return (time.time() - d.stat().st_mtime) < FRESH_SEC
    except OSError:
        return False
