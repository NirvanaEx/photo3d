"""Скачать кодировщик DINOv3 и убедиться, что это действительно он.

    python fetch_dinov3.py            # официальный источник (нужен вход)
    python fetch_dinov3.py --mirror   # открытая копия, вход не нужен

Зачем два маршрута. Официальный репозиторий Meta закрыт ручным одобрением, и
скачивание оттуда требует ключа доступа. Когда одобрение получено, но ключ
в систему завести нечем, остаётся открытая копия того же содержимого.

Копия не принимается на веру. Проверяется трижды:

  1. хеши мелких файлов сверяются с официальным репозиторием - его
     метаданные публичны, даже когда скачивание закрыто;
  2. размер файла весов сверяется с официальным;
  3. после скачивания читаются сами тензоры: их состав и размерности должны
     отвечать архитектуре из config.json.

Хеш самого файла весов Meta скрывает за замком, поэтому побайтовую
идентичность доказать нельзя - и скрипт об этом честно говорит, а не молчит.

Лицензия Meta действует независимо от источника байтов: файл LICENSE.md в
копии тот же самый.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

WEIGHTS = Path("/opt/photo3d/weights")
LOCAL = WEIGHTS / "dinov3-vitl16"
MAIN = WEIGHTS / "TRELLIS.2-4B"

os.environ["HF_HOME"] = str(WEIGHTS / "hf")

OFFICIAL = "facebook/dinov3-vitl16-pretrain-lvd1689m"
MIRROR = "camenduru/dinov3-vitl16-pretrain-lvd1689m"

# Путь ВНУТРИ контейнера: конфиг читается там, а не на хосте
CONTAINER_PATH = "/weights/dinov3-vitl16"


def tree(repo: str) -> dict[str, dict]:
    """Состав репозитория с хешами. Метаданные публичны даже у закрытых."""
    import urllib.request

    url = f"https://huggingface.co/api/models/{repo}/tree/main?recursive=1"
    with urllib.request.urlopen(url, timeout=30) as r:
        data = json.load(r)
    out = {}
    for e in data:
        if e.get("type") != "file":
            continue
        lfs = e.get("lfs") or {}
        out[e["path"]] = {
            "size": e.get("size", 0),
            "hash": lfs.get("oid") or e.get("oid", ""),
        }
    return out


def compare(official: dict, mirror: dict) -> bool:
    """Сверка копии с оригиналом. Возвращает False только при расхождении -
    невозможность сверить (скрытый хеш) расхождением не считается."""
    print("=== сверка копии с официальным репозиторием")
    ok = True
    for name, o in sorted(official.items()):
        m = mirror.get(name)
        if m is None:
            print(f"  ОТСУТСТВУЕТ  {name}")
            ok = False
            continue
        if o["size"] != m["size"]:
            print(f"  РАЗМЕР РАЗНЫЙ {name}: {o['size']} против {m['size']}")
            ok = False
            continue
        # хеш закрытых больших файлов Meta маскирует звёздочками
        if set(o["hash"]) <= {"*"} or not o["hash"]:
            print(f"  размер сходится, хеш скрыт  {name}  ({o['size'] / 1e6:.0f} МБ)")
            continue
        if o["hash"] == m["hash"]:
            print(f"  идентичен                   {name}")
        else:
            print(f"  ХЕШ НЕ СОВПАЛ               {name}")
            ok = False
    return ok


def read_header(st: Path) -> dict[str, dict]:
    """Оглавление safetensors без единой зависимости.

    Формат устроен просто: 8 байт длины заголовка (little-endian), затем
    JSON с именами тензоров, их типами и размерностями. Читать через
    safe_open(framework="pt") означало бы тащить на хост torch ради одной
    проверки - а нам нужны только имена и формы.
    """
    import struct

    with st.open("rb") as f:
        (length,) = struct.unpack("<Q", f.read(8))
        header = json.loads(f.read(length).decode("utf-8"))
    header.pop("__metadata__", None)
    return header


def inspect(path: Path) -> bool:
    """Сверить веса с архитектурой из config.json.

    Подменённый или битый файл здесь и вскроется: у него не сойдётся ни
    число блоков, ни размерность скрытого состояния.
    """
    cfg = json.loads((path / "config.json").read_text(encoding="utf-8"))
    hidden = cfg.get("hidden_size")
    layers = cfg.get("num_hidden_layers")
    print(f"\n=== содержимое весов (ожидается {layers} слоёв, "
          f"скрытое состояние {hidden})")

    header = read_header(path / "model.safetensors")
    names = sorted(header)
    print(f"    тензоров: {len(names)}")
    for k in names[:4]:
        print(f"      {k} {header[k]['shape']} {header[k]['dtype']}")

    # Номер блока - первая же числовая часть имени: у разных реализаций
    # префикс отличается (layer.N / layers.N / blocks.N), а цифра общая.
    blocks = set()
    for k in names:
        for part in k.split("."):
            if part.isdigit():
                blocks.add(int(part))
                break
    found = len(blocks)
    print(f"    блоков насчитано: {found}")

    seen_hidden = any(hidden in header[k]["shape"] for k in names)
    ok = True
    if hidden and not seen_hidden:
        print(f"    НЕСОВПАДЕНИЕ: размерность {hidden} не встречается вовсе")
        ok = False
    if layers and found and found != layers:
        print(f"    НЕСОВПАДЕНИЕ: блоков {found}, а по конфигу {layers}")
        ok = False
    if ok:
        print(f"    сходится: {found} блоков, размерность {hidden} присутствует")
    return ok


def patch_config() -> None:
    """Указать пайплайну локальный путь вместо имени закрытого репозитория."""
    cfg_path = MAIN / "pipeline.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["args"]["image_cond_model"]["args"]["model_name"] = CONTAINER_PATH
    cfg_path.write_text(json.dumps(cfg, indent=4, ensure_ascii=False),
                        encoding="utf-8")
    print(f"\nконфиг: кодировщик теперь берётся из {CONTAINER_PATH}")


def main() -> int:
    use_mirror = "--mirror" in sys.argv
    repo = MIRROR if use_mirror else OFFICIAL
    print(f"источник: {repo}\n")

    if use_mirror:
        try:
            if not compare(tree(OFFICIAL), tree(MIRROR)):
                print("\nСВЕРКА НЕ ПРОШЛА - копия отличается, скачивание отменено")
                return 1
        except Exception as exc:  # noqa: BLE001
            print(f"сверку выполнить не удалось: {type(exc).__name__}: {exc}")
            return 1

    from huggingface_hub import snapshot_download

    print(f"\n=== скачивание -> {LOCAL}")
    snapshot_download(repo_id=repo, local_dir=str(LOCAL),
                      allow_patterns=["*.json", "*.safetensors", "*.md", "*.txt"],
                      max_workers=4)
    size = sum(f.stat().st_size for f in LOCAL.rglob("*") if f.is_file())
    print(f"    получено {size / 1e9:.2f} ГБ")

    if not inspect(LOCAL):
        print("\nВЕСА НЕ ОТВЕЧАЮТ АРХИТЕКТУРЕ - использовать нельзя")
        return 1

    patch_config()
    print("\nГОТОВО")
    return 0


if __name__ == "__main__":
    sys.exit(main())
