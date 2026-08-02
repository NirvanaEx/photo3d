"""Подготовка модели к игре: запуск Blender.

Зачем это отдельный шаг, а не настройка экспорта: в игре у модели две разные
жизни. Видимая сетка может позволить себе десятки тысяч треугольников -
видеокарта их не замечает. Оболочка столкновений не может: цена там растёт
нелинейно, и 300 тысяч треугольников вешают физику намертво (замер в вебе -
296 000 треугольников, октодерево строится минутами).

Поэтому на выходе один GLB с двумя мешами, и второй назван так, что импортёр
Godot сам делает из него тело столкновений. Подробности - в
pipeline/blender/gameready.py.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from server import config
from server.errors import PipelineError

SCRIPT = config.BLENDER_SCRIPTS / "gameready.py"


def prepare(src: Path, out: Path, faces: int = 20000, collider: int = 1500,
            collider_mode: str = "colonly") -> dict[str, Any]:
    if not config.BLENDER.exists():
        raise PipelineError("gameready", f"Blender не найден: {config.BLENDER}",
                            hint="прогони scripts/setup-host.sh из-под root")
    if not src.exists():
        raise PipelineError("gameready", f"нет исходного GLB: {src}",
                            hint="проверь list_models() и id модели")

    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(config.BLENDER), "-b", "--factory-startup", "-noaudio",
        "-P", str(SCRIPT), "--",
        "--src", str(src), "--out", str(out),
        "--faces", str(faces), "--collider", str(collider),
        "--collider-mode", collider_mode,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          timeout=config.RENDER_TIMEOUT_SEC)
    text = (proc.stdout or "") + (proc.stderr or "")

    stats: dict[str, Any] = {}
    for line in text.splitlines():
        if line.startswith("GAMEREADY_STATS "):
            stats = json.loads(line[len("GAMEREADY_STATS "):])

    if not stats or not out.exists():
        detail = next((l for l in text.splitlines()
                       if l.startswith("GAMEREADY_ERROR")), "")
        raise PipelineError(
            "gameready", detail or "подготовка не удалась",
            hint=("хвост вывода Blender:\n"
                  + "\n".join(text.strip().splitlines()[-10:])))

    # Проверка по счётчику, а не по коду возврата: Decimate применяется молча
    # и на вырожденном входе может не изменить ничего.
    if (stats["tris_before"] > faces
            and stats["tris_after"] >= stats["tris_before"]):
        raise PipelineError(
            "gameready",
            f"децимация ничего не дала: было {stats['tris_before']}, "
            f"стало {stats['tris_after']}",
            hint=("похоже, меш вырожден - у Decimate нет рёбер, которые можно "
                  "схлопнуть. Прогони prepare_for_sculpting: он чинит "
                  "неманифолдность и перестраивает оболочку"))
    if stats["collider_mode"] != "none" and stats["collider_tris"] == 0:
        raise PipelineError(
            "gameready", "оболочка столкновений вышла пустой",
            hint="без неё игрок провалится сквозь модель; проверь исходный GLB")

    stats["log"] = text
    return stats
