"""Подготовка кадра перед генерацией: снятие фона.

Зачем это здесь, а не внутри TRELLIS. У пайплайна есть своя модель для фона
(BiRefNet), но она весит 5.4 ГБ, требует согласия с некоммерческой лицензией
и грузится через trust_remote_code=True. При этом preprocess_image в
trellis2_image_to_3d.py устроен так, что при наличии альфа-канала он её
не трогает вовсе - ветка `if has_alpha`. Поэтому фон снимается здесь, своим
rembg, а внутрь контейнера уходит уже готовый RGBA.

Побочная выгода: силуэт от rembg нужен и заглушке, и проекции фотографии
на модель, так что путь один для всех.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from server import config
from server.errors import PipelineError


@lru_cache(maxsize=2)
def _session(model: str):
    """Сессия onnxruntime переиспользуется: её создание - это чтение модели
    с диска, секунды. На каждый кадр заново было бы расточительно."""
    from rembg import new_session

    return new_session(model)


def cutout(src: Path, dst: Path, model: str = "") -> dict[str, Any]:
    """Снять фон и записать RGBA. Возвращает замеры, а не только путь.

    Замеры нужны не для красоты: если объект занял три пикселя или, наоборот,
    залил весь кадр, генерация выдаст мусор, и лучше сказать об этом сразу,
    чем через несколько минут работы GPU.
    """
    from rembg import remove

    model = model or config.REMBG_MODEL
    img = Image.open(src).convert("RGB")
    out = remove(img, session=_session(model))
    if out.mode != "RGBA":
        out = out.convert("RGBA")

    alpha = np.asarray(out)[:, :, 3]
    solid = alpha > 200
    covered = float(solid.mean())

    if covered < 0.005:
        raise PipelineError(
            "preprocess", f"после снятия фона от объекта осталось {covered:.1%} кадра",
            hint="объект слишком мелкий или сливается с фоном; "
                 "сними ближе или на контрастном фоне",
        )
    if covered > 0.98:
        raise PipelineError(
            "preprocess", "фон снять не удалось: непрозрачен почти весь кадр",
            hint="нужен снимок одного предмета на отличимом фоне, а не сцена",
        )

    ys, xs = np.nonzero(solid)
    dst.parent.mkdir(parents=True, exist_ok=True)
    out.save(dst)

    return {
        "модель": model,
        "доля_кадра": round(covered, 4),
        "габарит_силуэта": [int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)],
        "кадр": list(img.size),
        "файл": str(dst),
    }
