"""Сглаживание модели: запуск Blender и разбор ответа."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from server import config
from server.errors import PipelineError

SCRIPT = config.BLENDER_SCRIPTS / "smooth.py"


def smooth(src: Path, dst: Path, strength: float = 0.6, iterations: int = 12,
           subdivide: int = 0, method: str = "preserve") -> dict[str, Any]:
    if not config.BLENDER.exists():
        raise PipelineError("smooth", f"Blender не найден: {config.BLENDER}",
                            hint="прогони scripts/setup-host.sh из-под root")
    if method not in ("preserve", "simple"):
        raise PipelineError("smooth", f"метод {method!r} неизвестен",
                            hint="доступны: preserve (бережный), simple (сильнее)")

    cmd = [
        str(config.BLENDER), "-b", "--factory-startup", "-noaudio",
        "-P", str(SCRIPT), "--",
        "--in", str(src), "--out", str(dst),
        "--strength", str(max(0.0, min(strength, 1.0))),
        "--iterations", str(max(0, min(iterations, 60))),
        "--subdivide", str(max(0, min(subdivide, 3))),
        "--method", method,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          timeout=config.RENDER_TIMEOUT_SEC)
    out = (proc.stdout or "") + (proc.stderr or "")

    stats: dict[str, Any] = {}
    for line in out.splitlines():
        if line.startswith("SMOOTH_STATS "):
            stats = json.loads(line[len("SMOOTH_STATS "):])
    if proc.returncode != 0 or not stats:
        detail = next((l for l in out.splitlines() if l.startswith("SMOOTH_ERROR")), "")
        raise PipelineError("smooth", detail or "Blender не смог сгладить модель",
                            hint="полный вывод в log.txt папки модели")
    stats["log"] = out
    return stats
