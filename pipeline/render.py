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


def _attempt(glb: Path, out_dir: Path, style: str, res: int, extra: list[str],
             collect, expected: int) -> tuple[list[Path], str, str]:
    """Общий перебор движков: рисуем, пока какой-нибудь не отдаст нужные файлы.

    collect() возвращает готовые кадры, expected - сколько их должно быть.
    Проверять именно файлы, а не код возврата: Blender охотно завершается
    успехом, ничего не нарисовав.
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
        for old in collect():
            old.unlink()

        cmd = [
            str(config.BLENDER), "-b", "--factory-startup", "-noaudio",
            "-P", str(SCRIPT), "--",
            "--glb", str(glb),
            "--out", str(out_dir),
            "--res", str(res),
            "--style", style,
            "--engine", engine,
            *extra,
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

        frames = collect()
        if proc.returncode == 0 and len(frames) == expected:
            return frames, engine, "\n".join(log_parts)

    tail = "\n".join(log_parts)
    tried = " и ".join(STYLE_ENGINES.get(style, ()))
    raise BlenderFailed(
        f"не удалось отрендерить стиль {style!r} ни одним движком ({tried})",
        log_tail=tail[-2000:],
    )


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
    return _attempt(
        glb, out_dir, style, res,
        extra=["--views", str(views)],
        collect=lambda: sorted(out_dir.glob("*.png")),
        expected=views,
    )


def render_view(
    glb: Path,
    out_png: Path,
    azimuth: float = 0.0,
    elevation: float | None = None,
    zoom: float = 1.0,
    focus: float | None = None,
    res: int = 768,
    style: str = "",
) -> tuple[Path, str, str]:
    """Один кадр с заданного ракурса. Возвращает (файл, движок, лог).

    Пишется отдельным файлом, а НЕ в папку views: там лежит оборот, по
    которому крутится модель в веб-интерфейсе, и подмешивать туда крупные
    планы значило бы ломать вращение.
    """
    extra = ["--azimuth", str(azimuth), "--zoom", str(zoom),
             "--name", out_png.stem]
    if elevation is not None:
        extra += ["--elevation", str(elevation)]
    if focus is not None:
        extra += ["--focus", str(focus)]

    frames, engine, log = _attempt(
        glb, out_png.parent, style, res, extra,
        collect=lambda: [out_png] if out_png.exists() else [],
        expected=1,
    )
    return frames[0], engine, log
