"""Собрать pipeline.json по тому, что реально лежит на диске.

    python sync_config.py [512|1024|1024_cascade|1536_cascade]

Конфиг не правится по месту, а каждый раз пересобирается из сохранённого
оригинала pipeline.orig.json. Причина простая: правки накапливаются
(режим, локальные пути, набор моделей), и править поверх правок - верный
способ однажды получить конфиг, про который никто не помнит, откуда он взялся.

Ключи моделей включаются ТОЛЬКО если файл есть на диске. Это не
предосторожность, а необходимость: from_pretrained в base.py перебирает все
ключи из args["models"] и падает на первом отсутствующем файле. Поэтому
состав конфига обязан отвечать составу папки.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

WEIGHTS = Path("/opt/photo3d/weights")
MAIN = WEIGHTS / "TRELLIS.2-4B"
SS_DEC = "ckpts/ss_dec_conv3d_16l8_fp16"
DINO_IN_CONTAINER = "/weights/dinov3-vitl16"

# Что нужно каждому режиму - переписано из проверок в
# trellis2/pipelines/trellis2_image_to_3d.py
NEEDS = {
    "512": ("shape_slat_flow_model_512", "tex_slat_flow_model_512"),
    "1024": ("shape_slat_flow_model_1024", "tex_slat_flow_model_1024"),
    "1024_cascade": ("shape_slat_flow_model_512", "shape_slat_flow_model_1024",
                     "tex_slat_flow_model_1024"),
    "1536_cascade": ("shape_slat_flow_model_512", "shape_slat_flow_model_1024",
                     "tex_slat_flow_model_1024"),
}


def build(mode: str) -> int:
    orig = MAIN / "pipeline.orig.json"
    if not orig.exists():
        print(f"нет {orig} - сначала прогоняется fetch_trellis.py")
        return 1

    cfg = json.loads(orig.read_text(encoding="utf-8"))
    args = cfg["args"]

    # Декодер структуры лежит рядом со своими, а не в чужом репозитории:
    # иначе загрузчик уходит в сеть при каждом старте
    args["models"]["sparse_structure_decoder"] = SS_DEC

    # Ключи с суффиксом разрешения берутся только те, что нужны режиму:
    # from_pretrained грузит всё перечисленное, а лишний DiT - это 2.58 ГБ
    # чтения с диска и место в памяти без всякой пользы.
    wanted = set(NEEDS.get(mode, ()))
    kept, dropped = {}, []
    for key, rel in args["models"].items():
        resolution_specific = key.endswith(("_512", "_1024"))
        if resolution_specific and key not in wanted:
            dropped.append(f"{key} (не нужен режиму)")
            continue
        if (MAIN / f"{rel}.safetensors").exists():
            kept[key] = rel
        else:
            dropped.append(f"{key} (нет файла)")
    args["models"] = kept

    missing = [k for k in NEEDS.get(mode, ()) if k not in kept]
    if missing:
        print(f"режим {mode} требует {missing}, а этих весов нет")
        print(f"на диске: {sorted(kept)}")
        return 1

    args["default_pipeline_type"] = mode
    args["low_vram"] = True
    args["image_cond_model"]["args"]["model_name"] = DINO_IN_CONTAINER

    (MAIN / "pipeline.json").write_text(
        json.dumps(cfg, indent=4, ensure_ascii=False), encoding="utf-8")

    print(f"режим: {mode}")
    print(f"моделей в конфиге: {len(kept)}")
    for k in sorted(kept):
        print(f"   {k}")
    if dropped:
        print(f"пропущено (нет файла): {dropped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(build(sys.argv[1] if len(sys.argv) > 1 else "512"))
