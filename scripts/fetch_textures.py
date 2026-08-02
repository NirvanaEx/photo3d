"""Скачать фотосканные материалы с Poly Haven.

    python scripts/fetch_textures.py
    python scripts/fetch_textures.py --res 4k brown_planks_09

Зачем готовые, а не свои процедурные: шум даёт «статистически грязно», а нужно
«грязно вот здесь, потому что здесь ходят». У фотоскана история поверхности
уже есть - её сняли с настоящей стены, а не сгенерировали.

Лицензия CC0, то есть без условий вовсе. Файлы кладутся в data/textures и в git
не уезжают: они воспроизводятся этой командой, а весят десятки мегабайт - то же
правило, что у весов моделей и у vendor-библиотек.

Берётся три карты: цвет, нормаль (OpenGL), шероховатость. Displacement и AO не
нужны - геометрию мы не подразделяем, а затенение в порах Godot считает сам.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, "/mnt/d/Develop/photo3d")

from server import config  # noqa: E402
from server.errors import PipelineError  # noqa: E402

API = "https://api.polyhaven.com/files/{}"

# Без User-Agent CDN отвечает 403. Не каприз сервера, а обычная защита от
# ботов: urllib по умолчанию представляется "Python-urllib", и такие запросы
# отсекаются. Представляемся честно - с именем проекта и ссылкой.
UA = {"User-Agent": "photo3d/0.1 (+https://github.com/; asset fetcher)"}


def _open(url: str, timeout: int = 120):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                  timeout=timeout)
TEX_DIR = config.DATA / "textures"

# Что качаем по умолчанию. Пол и стены - две поверхности, которые занимают
# почти весь кадр; на них разница между сканом и шумом видна сразу.
DEFAULT = ("brown_planks_09", "beige_wall_001")

# Ключ в ответе API -> имя, под которым карта ложится на диск.
WANTED = {"Diffuse": "diff", "nor_gl": "nor", "Rough": "rough"}


def fetch(asset: str, res: str = "2k") -> dict[str, Path]:
    with _open(API.format(asset), 60) as r:
        files = json.load(r)

    out = TEX_DIR / asset
    out.mkdir(parents=True, exist_ok=True)
    got: dict[str, Path] = {}
    for key, short in WANTED.items():
        entry = files.get(key, {}).get(res, {}).get("jpg")
        if entry is None:
            # Вслух, а не молча: материал без нормали работать будет, но
            # рельефа у него не окажется, и искать причину пришлось бы в игре.
            print(f"  {asset}: карты {key} в {res}/jpg нет", file=sys.stderr)
            continue
        dst = out / f"{short}.jpg"
        if dst.exists() and dst.stat().st_size == entry["size"]:
            got[short] = dst
            print(f"  {short}: уже на месте ({entry['size'] / 1e6:.1f} МБ)")
            continue
        with _open(entry["url"]) as r, dst.open("wb") as f:
            shutil.copyfileobj(r, f)
        if dst.stat().st_size != entry["size"]:
            raise PipelineError(
                "textures",
                f"{asset}/{short}: скачалось {dst.stat().st_size} байт "
                f"вместо {entry['size']}",
                hint="повтори команду - файл докачается заново")
        got[short] = dst
        print(f"  {short}: {entry['size'] / 1e6:.1f} МБ")
    if "diff" not in got:
        raise PipelineError("textures", f"{asset}: не скачался даже цвет",
                            hint=f"проверь имя набора на polyhaven.com/a/{asset}")
    return got


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("assets", nargs="*", default=list(DEFAULT))
    p.add_argument("--res", default="2k", choices=["1k", "2k", "4k", "8k"])
    a = p.parse_args()
    for asset in (a.assets or DEFAULT):
        print(f"{asset} ({a.res}):")
        fetch(asset, a.res)
    print(f"готово: {TEX_DIR}")


if __name__ == "__main__":
    main()
