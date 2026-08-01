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
        cmd += ["--from-photo", str(photo)]
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
