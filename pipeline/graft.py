"""Посадка подробной головы на тело: запуск Blender и разбор ответа."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from server import config
from server.errors import PipelineError

SCRIPT = config.BLENDER_SCRIPTS / "graft.py"


def merge(body: Path, head: Path, plan: Path, out: Path,
          overlap: float = 0.03) -> dict[str, Any]:
    """Срезать голову у тела, поставить на её место подробную, слить в один GLB.

    plan - JSON от scripts/graft_head.py с матрицей и уровнем среза.
    """
    for p in (body, head, plan):
        if not p.exists():
            raise PipelineError("graft", f"нет файла {p}",
                                hint="сначала прогони scripts/graft_head.py")

    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(config.BLENDER), "-b", "--factory-startup", "-noaudio",
        "-P", str(SCRIPT), "--",
        "--body", str(body), "--head", str(head),
        "--plan", str(plan), "--out", str(out),
        "--overlap", str(overlap),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          timeout=config.RENDER_TIMEOUT_SEC)
    out_text = (proc.stdout or "") + (proc.stderr or "")

    stats: dict[str, Any] = {}
    for line in out_text.splitlines():
        if line.startswith("GRAFT_STATS "):
            stats = json.loads(line[len("GRAFT_STATS "):])

    if proc.returncode != 0 or "GRAFT_DONE" not in out_text or not out.exists():
        detail = ""
        for line in out_text.splitlines():
            if line.startswith("GRAFT_ERROR"):
                detail = line
        raise PipelineError("graft", detail or "Blender не собрал модель",
                            hint="полный вывод в log.txt рядом с результатом")

    stats["log"] = out_text
    return stats
