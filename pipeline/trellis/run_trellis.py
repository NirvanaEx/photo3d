"""Генерация 3D из фото. Исполняется ВНУТРИ контейнера photo3d/trellis.

    python run_trellis.py --in /work/input.png --out /work/model.glb

Скрипт монтируется в контейнер с хоста, а не копируется в образ: править его
можно без пересборки, а пересборка тут - десятки минут.

Три отступления от официального example.py, каждое вынужденное:

1. BiRefNet подменяется заглушкой. В конфиге он нужен (from_pretrained падает
   без ключа rembg_model), но его конструктор качает 5.4 ГБ и выполняет
   trust_remote_code=True. Вызывается он только когда у входной картинки нет
   альфа-канала - а мы всегда подаём RGBA, фон снят нашим rembg на хосте.
   Если заглушка всё-таки сработает, значит альфы не было: падаем внятно.

2. pipeline_type="512" задаётся явно. По умолчанию в конфиге стоит каскад
   1024, а его весов у нас нет и на 12 ГБ они не нужны.

3. Рендер превью выброшен. В example.py он через nvdiffrast и HDRI, а у нас
   для этого есть Blender - и лишняя нагрузка на видеопамять ни к чему.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

import numpy as np  # noqa: E402
import torch  # noqa: E402
from PIL import Image  # noqa: E402


class _NoRembg:
    """Заглушка вместо BiRefNet: ничего не грузит и ничего не умеет.

    Интерфейс повторяет настоящий (to/cuda/cpu вызываются в low_vram-режиме
    безусловно), но вызов на картинке - ошибка, а не тихая работа: если сюда
    дошло, значит альфа-канала не было и фон снять нечем.
    """

    def __init__(self, *a, **kw) -> None:
        pass

    def to(self, device):  # noqa: ANN001
        return self

    def cuda(self):
        return self

    def cpu(self):
        return self

    def __call__(self, image):  # noqa: ANN001
        raise RuntimeError(
            "у входной картинки нет альфа-канала, а модель удаления фона "
            "намеренно не установлена. Фон должен сниматься на хосте (rembg) "
            "до вызова контейнера"
        )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="src", required=True)
    p.add_argument("--out", dest="dst", required=True)
    p.add_argument("--weights", default="/weights/TRELLIS.2-4B")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--pipeline-type", dest="ptype", default="512")
    # 4096 как в примере авторов - это под 24 ГБ. Начинаем скромнее.
    p.add_argument("--texture-size", dest="texture", type=int, default=2048)
    p.add_argument("--decimation-target", dest="decimation", type=int, default=300_000)
    p.add_argument("--max-tokens", dest="max_tokens", type=int, default=49152)
    return p.parse_args()


def vram() -> dict[str, float]:
    if not torch.cuda.is_available():
        return {}
    free, total = torch.cuda.mem_get_info()
    return {
        "пик_выделено_ГБ": round(torch.cuda.max_memory_allocated() / 2**30, 2),
        "пик_зарезервировано_ГБ": round(torch.cuda.max_memory_reserved() / 2**30, 2),
        "свободно_ГБ": round(free / 2**30, 2),
        "всего_ГБ": round(total / 2**30, 2),
    }


def main() -> int:
    a = parse_args()
    stages: dict[str, float] = {}
    t0 = time.time()

    img = Image.open(a.src)
    if img.mode != "RGBA":
        print(json.dumps({"ошибка": f"нужен RGBA, получено {img.mode}"},
                         ensure_ascii=False))
        return 1
    alpha = np.array(img)[:, :, 3]
    if np.all(alpha == 255):
        print(json.dumps({"ошибка": "альфа-канал полностью непрозрачный, "
                                    "фон не снят"}, ensure_ascii=False))
        return 1

    # Подмена ДО from_pretrained: конструктор настоящего BiRefNet вызывается
    # прямо там (trellis2_image_to_3d.py, строка 105).
    from trellis2.pipelines import rembg as rembg_mod

    rembg_mod.BiRefNet = _NoRembg

    from trellis2.pipelines import Trellis2ImageTo3DPipeline

    stages["импорт_с"] = round(time.time() - t0, 1)

    t = time.time()
    pipeline = Trellis2ImageTo3DPipeline.from_pretrained(a.weights)
    pipeline.cuda()   # при low_vram только запоминает устройство
    stages["загрузка_с"] = round(time.time() - t, 1)
    print(f"low_vram={pipeline.low_vram}  режим={a.ptype}", file=sys.stderr, flush=True)

    torch.cuda.reset_peak_memory_stats()
    t = time.time()
    outputs = pipeline.run(
        img,
        seed=a.seed,
        pipeline_type=a.ptype,
        max_num_tokens=a.max_tokens,
    )
    stages["генерация_с"] = round(time.time() - t, 1)
    peak_gen = vram()

    mesh = outputs[0]
    mesh.simplify(16_777_216)   # предел nvdiffrast

    t = time.time()
    import o_voxel

    glb = o_voxel.postprocess.to_glb(
        vertices=mesh.vertices,
        faces=mesh.faces,
        attr_volume=mesh.attrs,
        coords=mesh.coords,
        attr_layout=mesh.layout,
        voxel_size=mesh.voxel_size,
        aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
        decimation_target=a.decimation,
        texture_size=a.texture,
        remesh=True,
        remesh_band=1,
        remesh_project=0,
        verbose=False,
    )
    # extension_webp=False намеренно: наш Blender-конвейер (запекание,
    # рендер) читает GLB через стандартный импортёр, а webp-текстуры он
    # понимает не во всех сборках. Размер тут вторичен.
    glb.export(a.dst, extension_webp=False)
    stages["экспорт_с"] = round(time.time() - t, 1)

    report = {
        "движок": "trellis2",
        "режим": a.ptype,
        "seed": a.seed,
        "вершин": int(len(glb.vertices)) if hasattr(glb, "vertices") else None,
        "граней": int(len(glb.faces)) if hasattr(glb, "faces") else None,
        "текстура": a.texture,
        "время": stages,
        "всего_с": round(time.time() - t0, 1),
        "видеопамять": peak_gen,
    }
    print("TRELLIS_RESULT " + json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
