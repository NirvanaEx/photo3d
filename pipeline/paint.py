"""Покраска модели: запуск Blender и разбор его ответа."""
from __future__ import annotations

import subprocess
from pathlib import Path

from server import config
from server.errors import PipelineError

SCRIPT = config.BLENDER_SCRIPTS / "paint.py"

# Палитра задана привычными sRGB-кодами, а не линейными долями: линейные
# числа приходится подбирать на глаз, и первая попытка дала «терракоту»,
# которая рендерилась блёклым лососевым. Преобразование в линейное
# пространство делает parse_color - оно же используется для #rrggbb от
# пользователя, так что путь один и тот же.
NAMED_COLORS: dict[str, str] = {
    "красный": "#B0342A",
    "оранжевый": "#C75B18",
    "жёлтый": "#D3A319",
    "зелёный": "#2E7D32",
    "бирюзовый": "#18827B",
    "синий": "#2D4C9E",
    "фиолетовый": "#6B3FA0",
    "розовый": "#C56A82",
    "белый": "#E8E6E1",
    "серый": "#8A8A8C",
    "чёрный": "#1E1E20",
    "золото": "#C9A227",
    "бронза": "#8C6239",
    "медь": "#A85C32",
    "терракота": "#9E4A2E",
}


def srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def parse_color(value: str) -> tuple[float, float, float]:
    """Принимает название, #rrggbb или 'r,g,b' (последнее — уже линейное)."""
    v = value.strip().lower()
    if v in NAMED_COLORS:
        v = NAMED_COLORS[v]

    if v.startswith("#"):
        h = v[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        if len(h) != 6:
            raise PipelineError("paint", f"не разобрать цвет {value!r}",
                                hint="используй #rrggbb, 'r,g,b' или название: "
                                     + ", ".join(sorted(NAMED_COLORS)))
        # sRGB -> линейное: Blender считает в линейном, и без преобразования
        # цвет выходит заметно светлее заданного
        return tuple(srgb_to_linear(int(h[i:i + 2], 16) / 255) for i in (0, 2, 4))

    parts = v.replace(";", ",").split(",")
    if len(parts) == 3:
        try:
            return tuple(min(max(float(p), 0.0), 1.0) for p in parts)
        except ValueError:
            pass
    raise PipelineError(
        "paint", f"не разобрать цвет {value!r}",
        hint="используй #rrggbb, 'r,g,b' в 0..1 или название: "
             + ", ".join(sorted(NAMED_COLORS)),
    )


def photo_foreground_rect(path: Path) -> tuple[float, float, float, float]:
    """Границы силуэта на кадре в координатах UV (u0, v0, u1, v1).

    Модель строится по силуэту, поэтому её габарит соответствует именно ему,
    а не всему кадру. Без этой поправки поля вокруг объекта ложились бы на
    края модели, и она получалась бы по краям цвета фона.

    V считается от низа: в Blender начало координат текстуры внизу слева,
    а нулевая строка изображения - вверху.
    """
    import numpy as np
    from PIL import Image

    from pipeline.engines import _foreground_mask

    rgba = np.asarray(Image.open(path).convert("RGBA")).astype(np.float32) / 255.0
    mask = _foreground_mask(rgba)
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return (0.0, 0.0, 1.0, 1.0)
    h, w = mask.shape
    return (
        float(xs.min()) / max(w - 1, 1),
        1.0 - float(ys.max()) / max(h - 1, 1),
        float(xs.max()) / max(w - 1, 1),
        1.0 - float(ys.min()) / max(h - 1, 1),
    )


def paint(src: Path, dst: Path, color: str = "", photo: Path | None = None,
          metallic: float = 0.0, roughness: float = 0.5) -> str:
    if not color and not photo:
        raise PipelineError("paint", "нечем красить",
                            hint="задай color или from_photo=True")

    cmd = [
        str(config.BLENDER), "-b", "--factory-startup", "-noaudio",
        "-P", str(SCRIPT), "--",
        "--in", str(src), "--out", str(dst),
        "--metallic", str(metallic), "--roughness", str(roughness),
    ]
    if photo:
        rect = photo_foreground_rect(photo)
        cmd += ["--from-photo", str(photo),
                "--photo-rect", ",".join(f"{c:.6f}" for c in rect)]
    if color:
        r, g, b = parse_color(color)
        cmd += ["--color", f"{r},{g},{b}"]

    proc = subprocess.run(cmd, capture_output=True, text=True,
                          timeout=config.RENDER_TIMEOUT_SEC)
    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0 or "PAINT_DONE" not in out:
        detail = ""
        for line in out.splitlines():
            if line.startswith("PAINT_ERROR"):
                detail = line
        raise PipelineError("paint", detail or "Blender не смог покрасить модель",
                            hint="полный вывод в log.txt папки модели")
    return out
