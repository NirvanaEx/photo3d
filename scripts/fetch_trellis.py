"""Скачать веса TRELLIS.2 под наши 12 ГБ VRAM и починить конфиг под них.

Качается не весь репозиторий. Три сознательных отличия от инструкции авторов,
каждое проверено по исходникам, а не по документации:

1. Файлы 1024 пропускаются. Режим pipeline_type="512" их не требует, а весят
   они 5.2 ГБ. НО from_pretrained в base.py перебирает ВСЕ ключи из
   args["models"] и падает на отсутствующем файле - поэтому лишние ключи
   вычищаются из локального pipeline.json, иначе пропуск не сработает.

2. sparse_structure_decoder в исходном конфиге указан как
   "microsoft/TRELLIS-image-large/ckpts/..." - путь в чужой репозиторий.
   Локально он не разрешается, и загрузчик уходит в интернет при каждом
   старте. Кладём файл рядом со своими и переписываем путь на относительный.

3. rembg_model остаётся в конфиге (без ключа падает строка 105
   trellis2_image_to_3d.py), но качать BiRefNet не нужно: подменяется
   заглушкой в pipeline/trellis.py. Он вызывается только когда у входной
   картинки нет альфа-канала (строка 141), а мы всегда подаём RGBA.
   Заодно не тянем 5.4 ГБ и не выполняем trust_remote_code=True.

DINOv3 закрыт ручным одобрением Meta. Скрипт пробует его скачать и, если
доступа нет, честно об этом сообщает, не роняя остальное.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

WEIGHTS = Path("/opt/photo3d/weights")
MAIN = WEIGHTS / "TRELLIS.2-4B"

os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "1")
# DINOv3 грузится не по пути, а по имени репозитория:
# DINOv3ViTModel.from_pretrained("facebook/dinov3-...") в
# trellis2/modules/image_feature_extractor.py. Значит класть его отдельной
# папкой бесполезно - transformers его там не найдёт. Нужен кэш HF, и тот же
# HF_HOME монтируется в контейнер, чтобы внутри работать без сети.
os.environ["HF_HOME"] = str(WEIGHTS / "hf")

REPO = "microsoft/TRELLIS.2-4B"
SS_DEC_REPO = "microsoft/TRELLIS-image-large"
SS_DEC_NAME = "ss_dec_conv3d_16l8_fp16"
DINO = "facebook/dinov3-vitl16-pretrain-lvd1689m"


def human(n: int) -> str:
    return f"{n / 1e9:.2f} ГБ" if n >= 1e9 else f"{n / 1e6:.0f} МБ"


def dir_size(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def fetch(repo: str, local: Path, **kw) -> None:
    from huggingface_hub import snapshot_download

    print(f"\n=== {repo} -> {local}", flush=True)
    snapshot_download(repo_id=repo, local_dir=str(local), max_workers=4, **kw)
    print(f"    получено: {human(dir_size(local))}", flush=True)


def patch_config() -> None:
    """Переписать pipeline.json под режим 512 и локальные пути."""
    cfg_path = MAIN / "pipeline.json"
    orig = MAIN / "pipeline.orig.json"
    if not orig.exists():
        shutil.copy2(cfg_path, orig)

    cfg = json.loads(orig.read_text(encoding="utf-8"))
    args = cfg["args"]
    models = args["models"]

    dropped = [k for k in list(models) if "1024" in k]
    for k in dropped:
        del models[k]

    models["sparse_structure_decoder"] = f"ckpts/{SS_DEC_NAME}"
    args["default_pipeline_type"] = "512"
    args["low_vram"] = True

    cfg_path.write_text(json.dumps(cfg, indent=4, ensure_ascii=False), encoding="utf-8")
    print(f"\nконфиг починен: выброшено {dropped}, "
          f"режим {args['default_pipeline_type']}, low_vram={args['low_vram']}",
          flush=True)


def check() -> bool:
    """Проверить, что на месте ровно то, что нужно режиму 512."""
    cfg = json.loads((MAIN / "pipeline.json").read_text(encoding="utf-8"))
    ok = True
    print("\n=== проверка ===", flush=True)
    for key, rel in cfg["args"]["models"].items():
        f = MAIN / f"{rel}.safetensors"
        if f.exists():
            print(f"  есть   {human(f.stat().st_size):>10}  {key}", flush=True)
        else:
            print(f"  НЕТ FILE                {key} -> {f}", flush=True)
            ok = False
    for stray in MAIN.rglob("*1024*"):
        print(f"  лишний файл 1024: {stray.name}", flush=True)
    return ok


def main() -> int:
    MAIN.mkdir(parents=True, exist_ok=True)

    # 1024 не качаем - 5.2 ГБ, которые на 12 ГБ VRAM всё равно не пригодятся
    fetch(REPO, MAIN, ignore_patterns=["*_1024_*"])

    # один файл из репозитория первой версии, кладём прямо в ckpts рядом
    # со своими, чтобы путь в конфиге стал относительным
    fetch(SS_DEC_REPO, MAIN, allow_patterns=[f"ckpts/{SS_DEC_NAME}*"])

    patch_config()
    ok = check()

    print("\n=== DINOv3 (закрыт ручным одобрением) ===", flush=True)
    try:
        # без local_dir - кладётся в кэш HF_HOME, откуда transformers найдёт
        # его по имени репозитория
        from huggingface_hub import snapshot_download

        snapshot_download(repo_id=DINO, max_workers=4)
        print(f"  доступ есть, кэш: {human(dir_size(WEIGHTS / 'hf'))}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"  пока нет доступа: {type(exc).__name__}: {str(exc)[:200]}", flush=True)
        print(f"  запросить: https://huggingface.co/{DINO}", flush=True)
        print("  затем `hf auth login` и перезапустить этот скрипт", flush=True)
        ok = False

    print(f"\nИТОГО на диске: {human(dir_size(WEIGHTS))}", flush=True)
    print("ГОТОВО" if ok else "НЕ ХВАТАЕТ DINOv3", flush=True)
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
