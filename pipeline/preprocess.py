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


def _rgba(src: Path, model: str) -> tuple[Image.Image, Image.Image, str]:
    """Исходник, он же со снятым фоном, и откуда взялась маска.

    Вынесено из cutout, потому что тем же путём ходит проверка кадра: она
    обязана смотреть ровно на ту маску, с которой потом пойдёт генерация,
    иначе её вывод не про то.
    """
    from rembg import remove

    img = Image.open(src)

    # Если фон уже снят, второй раз не режем. Готовая альфа почти всегда
    # точнее нашей: её либо нарисовали, либо получили в графическом
    # редакторе. Прежняя версия делала convert("RGB") первым же действием и
    # молча выбрасывала эту информацию - на примерах из репозитория TRELLIS,
    # которые все идут с прозрачным фоном, это была чистая порча.
    source = "rembg"
    if img.mode == "RGBA":
        alpha = np.asarray(img)[:, :, 3]
        if alpha.min() < 250:          # альфа осмысленная, а не сплошная
            out = img
            source = "готовая альфа"
        else:
            out = remove(img.convert("RGB"), session=_session(model))
    else:
        out = remove(img.convert("RGB"), session=_session(model))

    if out.mode != "RGBA":
        out = out.convert("RGBA")
    return img, out, source


def cutout(src: Path, dst: Path, model: str = "") -> dict[str, Any]:
    """Снять фон и записать RGBA. Возвращает замеры, а не только путь.

    Замеры нужны не для красоты: если объект занял три пикселя или, наоборот,
    залил весь кадр, генерация выдаст мусор, и лучше сказать об этом сразу,
    чем через несколько минут работы GPU.
    """
    model = model or config.REMBG_MODEL
    img, out, source = _rgba(src, model)

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
        "источник_маски": source,
        "модель": model if source == "rembg" else None,
        "доля_кадра": round(covered, 4),
        "габарит_силуэта": [int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)],
        "кадр": list(img.size),
        "файл": str(dst),
    }


# --------------------------------------------------------------------------- #
# Проверка кадра до генерации
# --------------------------------------------------------------------------- #

# Резкость считается на силуэте, приведённом к одному размеру: у большого
# снимка дисперсия лапласиана выше просто из-за числа точек, и без нормировки
# порог означал бы разное для разных кадров.
SHARP_SIDE = 512


def _components(solid: np.ndarray) -> list[float]:
    """Доли площади связных кусков силуэта, крупные сверху.

    Считается на уменьшенной маске: нужен не точный список, а ответ
    «предмет один или их несколько», и на нём мелкие крапины только мешают.
    """
    small = np.asarray(
        Image.fromarray((solid * 255).astype(np.uint8)).resize(
            (256, 256), Image.NEAREST)
    ) > 127
    total = int(small.sum())
    if total == 0:
        return []
    try:
        from scipy import ndimage
    except ImportError:
        return []
    lab, n = ndimage.label(small)
    if n == 0:
        return []
    sizes = ndimage.sum_labels(small, lab, index=range(1, n + 1))
    return sorted((float(s) / total for s in sizes), reverse=True)


def _texture(rgb: np.ndarray, solid: np.ndarray) -> float:
    """Дисперсия лапласиана внутри силуэта: сколько в предмете мелкой фактуры.

    Задумывалось как детектор размытия, но им НЕ является, и это выяснилось
    на замерах: demo_heart.png даёт 27 при совершенно резком контуре - просто
    он залит ровным цветом. Порог на такой величине браковал бы чистые
    студийные снимки, которые как раз выходят лучше всего.

    Поэтому число остаётся справочным и предупреждения не рождает. Польза у
    него сравнительная: из двух снимков одного предмета брать тот, где
    фактуры больше. Замеренный разброс на примерах TRELLIS - от 384 до 7251.

    Считается внутри силуэта: размытый фон - обычное дело и о предмете
    ничего не говорит.
    """
    ys, xs = np.nonzero(solid)
    if len(ys) < 64:
        return 0.0
    box = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
    side = max(box[2] - box[0], box[3] - box[1])
    if side < 8:
        return 0.0
    k = SHARP_SIDE / side

    def _fit(a: np.ndarray, mode: str) -> np.ndarray:
        im = Image.fromarray(a).crop(box)
        w = max(int(im.width * k), 4)
        h = max(int(im.height * k), 4)
        return np.asarray(im.resize((w, h),
                                    Image.LANCZOS if mode == "L" else Image.NEAREST))

    grey = _fit(rgb.mean(axis=2).astype(np.uint8), "L").astype(np.float32)
    mask = _fit((solid * 255).astype(np.uint8), "M") > 127
    lap = (grey[:-2, 1:-1] + grey[2:, 1:-1] + grey[1:-1, :-2] + grey[1:-1, 2:]
           - 4.0 * grey[1:-1, 1:-1])
    inner = mask[1:-1, 1:-1]
    if inner.sum() < 64:
        return 0.0
    return float(lap[inner].var())


def measure(src: Path, model: str = "") -> dict[str, Any]:
    """Замеры кадра и предупреждения о том, чем обычно кончается такой кадр.

    Стоит секунду процессорного времени против семи минут видеокарты, и в
    этом весь смысл: половина неудачных прогонов видна прямо здесь - предмет
    в четверть кадра, обрезанный краем, два предмета вместо одного.

    Возвращает и картинку силуэта: числа не показывают, что именно вырезалось,
    а маска, съевшая половину предмета, объясняет будущий результат сразу.
    """
    model = model or config.REMBG_MODEL
    img, out, source = _rgba(src, model)

    arr = np.asarray(out)
    rgb, alpha = arr[:, :, :3], arr[:, :, 3]
    solid = alpha > 200
    h, w = solid.shape
    covered = float(solid.mean())

    if not solid.any():
        raise PipelineError(
            "check", "после снятия фона не осталось ничего",
            hint="объект сливается с фоном; сними на контрастном фоне "
                 "или подай PNG с готовой прозрачностью",
        )

    ys, xs = np.nonzero(solid)
    bw, bh = int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)
    fill = covered * (w * h) / max(bw * bh, 1)      # заполнение своей рамки

    # Касание края: доля точек рамки кадра, попавших в силуэт. Одна-две точки
    # бывают от шума маски, поэтому смотрим долю, а не факт.
    border = np.concatenate([solid[0], solid[-1], solid[:, 0], solid[:, -1]])
    touch = float(border.mean())

    # Мелкие обрывки не в счёт: у ажурных предметов маска честно распадается
    # на сотни кусочков (у примера с завитками - 349), и это не дефект.
    # Признаком «предметов несколько» служит только крупный второй кусок.
    parts = _components(solid)
    extra = [p for p in parts[1:] if p > 0.05]

    return {
        "источник_маски": source,
        "кадр": [w, h],
        "доля_кадра": round(covered, 4),
        "габарит_силуэта": [bw, bh],
        "заполнение_рамки": round(float(fill), 3),
        "касание_края": round(touch, 4),
        "лишние_куски": [round(p, 3) for p in extra],
        "фактура": round(_texture(rgb, solid), 1),
        "_rgba": out,
    }


def preview(rgba: Image.Image, dst: Path, side: int = 512) -> Path:
    """Картинка того, что уйдёт в генератор: вырезанный предмет на шахматке.

    Шахматка, а не сплошной фон: на однотонном не видно, где кончился предмет
    и началась дырка в маске. Числа этого не показывают вовсе, а маска,
    отъевшая предмету половину, объясняет будущий результат сразу.
    """
    im = rgba.copy()
    im.thumbnail((side, side), Image.LANCZOS)
    a = np.asarray(im).astype(np.float32) / 255.0
    h, w = a.shape[:2]

    cell = max(side // 32, 4)
    yy, xx = np.mgrid[0:h, 0:w]
    board = np.where(((yy // cell) + (xx // cell)) % 2 == 0, 0.62, 0.48)
    board = np.repeat(board[:, :, None], 3, axis=2).astype(np.float32)

    alpha = a[:, :, 3:4]
    out = a[:, :, :3] * alpha + board * (1.0 - alpha)

    dst.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray((out * 255).astype(np.uint8)).save(dst)
    return dst


def verdict(m: dict[str, Any]) -> list[str]:
    """Предупреждения строками «что не так и что делать».

    Пороги стоят по замерам на двенадцати примерах репозитория TRELLIS и на
    своих снимках, а не назначены из общих соображений. Правил всего три,
    и это не лень: остальные проверялись и были отброшены, потому что на
    известных кадрах не разделяли годные и негодные - см. docs/PITFALLS.md.
    """
    out: list[str] = []
    bw, bh = m["габарит_силуэта"]

    if m["доля_кадра"] < 0.06:
        out.append(
            f"предмет занимает {m['доля_кадра']:.1%} кадра — обрежь кадр по "
            "предмету. Объём считается сеткой 512³ на весь снимок, и мелкому "
            "предмету достанется несколько десятков ячеек вместо пятисот"
        )
    if min(bw, bh) < 320:
        out.append(
            f"силуэт {bw}×{bh} точек — для подробностей мало. На примерах, "
            "которые вышли хорошо, силуэт был от 400 точек по меньшей стороне"
        )
    if m["касание_края"] > 0.02:
        out.append(
            f"силуэт выходит за край кадра ({m['касание_края']:.1%} рамки) — "
            "то, что за кадром, генератор достроит по своему разумению. "
            "Для намеренно обрезанного портрета это нормально, для предмета "
            "целиком — оставь поля вокруг"
        )
    if m["лишние_куски"]:
        доли = ", ".join(f"{p:.0%}" for p in m["лишние_куски"])
        out.append(
            f"в кадре не один предмет: кроме основного ещё {доли} площади. "
            "TRELLIS делает ОДИН предмет — лишнее либо слипнется с ним, либо "
            "даст мусор. Убери лишнее или обрежь кадр"
        )
    return out
