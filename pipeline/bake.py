"""Перенос внешнего вида на перестроенную модель: запуск Blender."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from server import config
from server.errors import PipelineError

SCRIPT = config.BLENDER_SCRIPTS / "bake.py"


def transfer(source: Path, target: Path, out: Path,
             resolution: int = 2048) -> dict[str, Any]:
    """Переносит материал с source на target, результат кладёт в out.

    Сам выбирает путь: однородный материал копируется, текстурный запекается.
    """
    if not config.BLENDER.exists():
        raise PipelineError("bake", f"Blender не найден: {config.BLENDER}",
                            hint="прогони scripts/setup-host.sh из-под root")

    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(config.BLENDER), "-b", "--factory-startup", "-noaudio",
        "-P", str(SCRIPT), "--",
        "--source", str(source), "--target", str(target),
        "--out", str(out), "--resolution", str(resolution),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          timeout=config.RENDER_TIMEOUT_SEC)
    text = (proc.stdout or "") + (proc.stderr or "")

    stats: dict[str, Any] = {}
    for line in text.splitlines():
        if line.startswith("BAKE_STATS "):
            stats = json.loads(line[len("BAKE_STATS "):])
    if proc.returncode != 0 or not stats or not out.exists():
        detail = next((l for l in text.splitlines() if l.startswith("BAKE_ERROR")), "")
        raise PipelineError("bake", detail or "перенос материала не удался",
                            hint="полный вывод в log.txt папки модели")
    stats["log"] = text
    return stats
