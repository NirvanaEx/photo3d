"""Запуск Blender из основного процесса.

Blender живёт отдельным процессом со своим Python, поэтому общение через
subprocess и файлы. Если Workbench не поднимет графический контекст в headless
WSL, автоматически переключаемся на Cycles CPU — медленнее, но работает всегда.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from server import config
from server.errors import BlenderFailed

SCRIPT = config.BLENDER_SCRIPTS / "turntable.py"

# Какими движками пробовать рисовать каждый стиль, по порядку.
#
# У постановочного стиля первым идёт Cycles, а не EEVEE, и это измерено:
# Cycles на CUDA даёт ~1.7 с на кадр, тогда как EEVEE в WSL получает лишь
# программный GL-контекст и тратит 14.3 с. То есть «быстрый» растеризатор
# здесь в шесть раз медленнее трассировщика на видеокарте.
STYLE_ENGINES = {
    "clay": ("workbench", "cycles"),
    "color": ("workbench", "cycles"),
    "beauty": ("cycles", "eevee"),
}


def render_turntable(
    glb: Path,
    out_dir: Path,
    views: int = config.DEFAULT_VIEWS,
    res: int = config.PREVIEW_RES,
    style: str = "",
) -> tuple[list[Path], str, str]:
    """Возвращает (кадры, использованный движок, лог).

    Пустой style означает «взять из конфига», а не «глина». Раньше здесь
    стояла глина, и после подключения TRELLIS это стало вредно: модели с
    PBR-материалами возвращались однородно серыми.
    """
    style = style or config.PREVIEW_STYLE
    out_dir.mkdir(parents=True, exist_ok=True)
    if not config.BLENDER.exists():
        raise BlenderFailed(
            f"Blender не найден по пути {config.BLENDER}",
            log_tail="",
        )

    log_parts: list[str] = []
    for engine in STYLE_ENGINES.get(style, ("workbench", "cycles")):
        for old in out_dir.glob("*.png"):
            old.unlink()

        cmd = [
            str(config.BLENDER), "-b", "--factory-startup", "-noaudio",
            "-P", str(SCRIPT), "--",
            "--glb", str(glb),
            "--out", str(out_dir),
            "--views", str(views),
            "--res", str(res),
            "--style", style,
            "--engine", engine,
        ]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=config.RENDER_TIMEOUT_SEC,
            )
        except subprocess.TimeoutExpired:
            log_parts.append(f"--- {engine}: таймаут {config.RENDER_TIMEOUT_SEC}s ---")
            continue

        out = (proc.stdout or "") + (proc.stderr or "")
        log_parts.append(f"--- {engine} (rc={proc.returncode}) ---\n{out}")

        frames = sorted(out_dir.glob("*.png"))
        if proc.returncode == 0 and len(frames) == views:
            return frames, engine, "\n".join(log_parts)

    tail = "\n".join(log_parts)
    tried = " и ".join(STYLE_ENGINES.get(style, ()))
    raise BlenderFailed(
        f"не удалось отрендерить стиль {style!r} ни одним движком ({tried})",
        log_tail=tail[-2000:],
    )
