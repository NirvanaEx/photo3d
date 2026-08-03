"""Что из библиотеки уехало в игру.

Связь читается **только в одну сторону**: веб смотрит в `game/` и не пишет
туда ничего. Владение файлами там чужое — ассеты кладёт
`bridge/import_asset.py`, сцены правит человек в редакторе Godot, — и второй
пишущий сломал бы ровно то же, что развели `meta.json` и `ui.json`.

Отвечает на вопрос, на который сама библиотека ответить не может: **«эта
модель уже в игре или нет»**. Когда моделей полтора десятка и половина из них
попытки, вопрос возникает каждый раз, а ответа взять негде. Лаунчер сцен на
него тоже не отвечает: там видны сцены, а не то, из чего они собраны.

Три источника, все дешёвые:

| источник | что даёт |
|----------|----------|
| `game/assets.json` | что импортировано: файл, треугольники, габариты, когда |
| `game/scenes/*.tscn` | где используется: `ext_resource` на `assets/models` |
| `game/scenes/games.json` | как сцена называется по-человечески |

Разбор кэшируется по отпечатку из `stat`, как размеры папок в `library.py`
и как карточки в `app.py`: список приходит целиком на каждое изменение, и
перечитывать шесть сцен по восемьсот миллисекунд незачем.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from server import config

SCENES = config.GAME_DIR / "scenes"
ASSETS_JSON = config.GAME_DIR / "assets.json"
GAMES_JSON = SCENES / "games.json"

# Ссылка на ассет в сцене. Матчится именно объявление ресурса, а не любое
# упоминание пути: в corridor.tscn строка `assets/models` встречается ещё и в
# комментарии сверху, и по наивному поиску подстроки сцена засчитывала бы
# модель, которой в ней нет.
ASSET_REF = re.compile(r'path="res://assets/models/([^"/]+)\.glb"')

# Облегчённый вариант ассета. Суффикс ровно один и ставится в одном месте -
# `bridge/import_asset.py`, `name = f"{mid}_game"`. Поэтому здесь не догадка
# по шаблону, а тот же суффикс.
GAMEREADY_SUFFIX = "_game"


def _model_of(asset: str) -> str:
    """Из имени ассета — id модели. `m_corridor_game` → `m_corridor`."""
    return asset[: -len(GAMEREADY_SUFFIX)] if asset.endswith(GAMEREADY_SUFFIX) else asset


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}            # нет игры или битый файл - не повод ронять библиотеку
    return data if isinstance(data, dict) else {}


def stamp() -> str:
    """Дешёвый отпечаток игровой части. Только `stat`, ничего не читается.

    Сцены считаются поимённо, а не одним `stat` по папке: правка сцены на
    месте (а именно так в неё и добавляют модель) mtime самой папки не меняет,
    и связь «модель в сцене» обновлялась бы только при создании файлов.
    Шесть лишних `stat` на опрос против шестнадцати моделей по четыре - шум.
    """
    parts = []
    for p in (ASSETS_JSON, GAMES_JSON):
        try:
            parts.append(f"{p.name}:{p.stat().st_mtime_ns}")
        except OSError:
            parts.append(f"{p.name}:0")
    try:
        for p in sorted(SCENES.glob("*.tscn")):
            parts.append(f"{p.stem}:{p.stat().st_mtime_ns}")
    except OSError:
        pass
    return "game[" + "|".join(parts) + "]"


_cache: tuple[str, dict[str, dict]] | None = None


def state() -> dict[str, dict]:
    """id модели → чем она стала в игре. Моделей вне игры в словаре нет."""
    global _cache
    key = stamp()
    if _cache and _cache[0] == key:
        return _cache[1]
    out = _build()
    _cache = (key, out)
    return out


def _scene_titles() -> dict[str, str]:
    """id сцены → человеческое название. Нет записи — останется id файла:
    молча потерянная сцена хуже некрасивой подписи (там же, в games.json)."""
    titles = {}
    for sid, rec in _read_json(GAMES_JSON).items():
        if sid.startswith("_") or not isinstance(rec, dict):
            continue          # "_" - это блок пояснений в самом файле
        if rec.get("hide"):
            continue          # лаунчер сам себя не показывает, и здесь тоже
        titles[sid] = str(rec.get("title") or sid)
    return titles


def _build() -> dict[str, dict]:
    imported = _read_json(ASSETS_JSON)
    if not imported:
        return {}

    titles = _scene_titles()

    # Где какой ассет лежит. Ключ - имя ассета, а не модели: в сцене может
    # стоять как исходный вариант, так и облегчённый, и знать надо какой.
    used: dict[str, list[str]] = {}
    try:
        scene_files = sorted(SCENES.glob("*.tscn"))
    except OSError:
        scene_files = []
    for path in scene_files:
        if path.stem == "launcher":
            continue          # лаунчер ассетов не держит, он только список
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for asset in set(ASSET_REF.findall(text)):
            used.setdefault(asset, []).append(path.stem)

    out: dict[str, dict] = {}
    for asset, rec in imported.items():
        if not isinstance(rec, dict) or not rec.get("ok", True):
            continue
        mid = _model_of(asset)
        cur = out.setdefault(mid, {
            "scenes": [], "gameready": False,
            "triangles": 0, "size": None, "at": 0.0,
        })

        ready = bool(rec.get("gameready"))
        cur["gameready"] = cur["gameready"] or ready

        # Числа берём у того варианта, который реально стоит в сцене, а при
        # равных - у облегчённого: именно он попадает в игру, и именно его
        # треугольники решают, потянет ли сцена. У исходного их бывает в
        # шесть раз больше, и цифра вводила бы в заблуждение.
        prefer = ready or cur["size"] is None
        if prefer:
            cur["triangles"] = int(rec.get("triangles") or 0)
            size = rec.get("size")
            cur["size"] = [round(float(v), 2) for v in size] if isinstance(size, list) else None

        cur["at"] = max(cur["at"], float(rec.get("imported_at") or 0))

        for sid in used.get(asset, []):
            if any(s["id"] == sid for s in cur["scenes"]):
                continue
            cur["scenes"].append({"id": sid, "title": titles.get(sid, sid)})

    for rec in out.values():
        rec["scenes"].sort(key=lambda s: s["title"])
    return out
