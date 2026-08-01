"""Проверка всего, что можно проверить без DINOv3. Идёт внутри контейнера.

    docker run --rm --gpus all -v /opt/photo3d/weights:/weights \
        -v .../pipeline/trellis:/app:ro photo3d/trellis:1 python /app/smoke.py

Смысл в том, чтобы к моменту получения доступа к кодировщику не осталось
неизвестных: смонтированы ли веса, верен ли переписанный конфиг, читаются ли
модели, и главное - переживает ли 10 ГБ ОЗУ загрузку 11 ГБ весов.

Последнее - ставка на mmap: safetensors отображаются в память, страницы идут
из кэша ядра и вытесняются под давлением. Если ставка неверна, здесь будет
не туманное замедление, а честный OOM, и лучше узнать это сейчас.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

WEIGHTS = Path(os.environ.get("TRELLIS_WEIGHTS", "/weights/TRELLIS.2-4B"))


def ram() -> dict[str, float]:
    """Память процесса и системы в ГБ. RSS у mmap-нутых весов показателен:
    если он вырос на все 11 ГБ, значит отображение не работает как задумано."""
    out: dict[str, float] = {}
    with open("/proc/self/status") as f:
        for line in f:
            if line.startswith("VmRSS:"):
                out["процесс_RSS_ГБ"] = round(int(line.split()[1]) / 2**20, 2)
    with open("/proc/meminfo") as f:
        info = {p[0].rstrip(":"): int(p[1]) for p in
                (ln.split() for ln in f) if len(p) >= 2}
    out["система_доступно_ГБ"] = round(info.get("MemAvailable", 0) / 2**20, 2)
    out["система_всего_ГБ"] = round(info.get("MemTotal", 0) / 2**20, 2)
    return out


def main() -> int:
    print(f"=== веса: {WEIGHTS}")
    cfg_path = WEIGHTS / "pipeline.json"
    if not cfg_path.exists():
        print(f"НЕТ КОНФИГА {cfg_path} - проверь монтирование тома")
        return 1

    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    args = cfg["args"]
    print(f"    режим по умолчанию: {args.get('default_pipeline_type')}")
    print(f"    low_vram: {args.get('low_vram')}")
    print(f"    моделей в конфиге: {len(args['models'])}")

    print(f"\n=== память до загрузки: {ram()}")

    import torch

    print(f"    видеокарта: {torch.cuda.get_device_name(0)}, "
          f"{torch.cuda.mem_get_info()[1] / 2**30:.1f} ГБ")

    # Модели грузятся тем же кодом, что и в бою, но по одной - чтобы видеть,
    # на какой именно всё сломается, если сломается.
    from trellis2 import models as t2models

    total = time.time()
    for key, rel in args["models"].items():
        t = time.time()
        try:
            t2models.from_pretrained(str(WEIGHTS / rel))
        except Exception as exc:  # noqa: BLE001
            print(f"    СБОЙ {key}: {type(exc).__name__}: {str(exc)[:160]}")
            return 1
        m = ram()
        print(f"    ok {key:28} {time.time() - t:5.1f} с   "
              f"RSS {m['процесс_RSS_ГБ']:5.2f} ГБ   "
              f"свободно {m['система_доступно_ГБ']:5.2f} ГБ")
    print(f"    все модели загружены за {time.time() - total:.1f} с")

    print(f"\n=== память после: {ram()}")

    # А теперь то, чего пока не хватает
    print("\n=== DINOv3")
    try:
        from transformers.models.dinov3_vit import DINOv3ViTModel

        name = args["image_cond_model"]["args"]["model_name"]
        DINOv3ViTModel.from_pretrained(name)
        print("    ok, кодировщик на месте - можно запускать генерацию")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"    пока недоступен: {type(exc).__name__}: {str(exc)[:200]}")
        print("    это ожидаемо: остальное проверено и готово")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
